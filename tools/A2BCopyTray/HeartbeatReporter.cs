using System.Net.Http;
using System.Reflection;
using System.Text;
using System.Text.Json;

namespace A2BCopyTray;

/// <summary>
/// 站点心跳上报。独立线程，按 HeartbeatSeconds 周期 POST JSON 到 HeartbeatUrl，
/// 不占用同步线程；只在「失败 / 恢复」状态翻转时写日志，避免刷屏。
///
/// 地址容错：未写协议时补 http://；只给了主机或根路径时自动补 /api/heartbeat
/// （与旧版行为一致）。
/// </summary>
public sealed class HeartbeatReporter : IDisposable
{
    private static readonly HttpClient Http = new()
    {
        Timeout = TimeSpan.FromSeconds(10)
    };

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        DefaultIgnoreCondition = System.Text.Json.Serialization.JsonIgnoreCondition.WhenWritingNull
    };

    private static readonly string ClientVersion =
        Assembly.GetExecutingAssembly().GetName().Version?.ToString(3) ?? "0.0.0";

    private readonly object _gate = new();
    private readonly CancellationTokenSource _cts = new();
    private readonly ManualResetEventSlim _wake = new(false);
    private readonly Thread _thread;

    private AppConfig _cfg;
    private Func<SyncSnapshot> _snapshot = static () => new SyncSnapshot();
    private bool? _lastResult;
    private volatile bool _stopping;
    private bool _disposed;

    public HeartbeatReporter(AppConfig cfg)
    {
        _cfg = ConfigStore.Normalize(cfg);
        _thread = new Thread(Loop) { IsBackground = true, Name = "Heartbeat" };
    }

    public void SetSnapshotProvider(Func<SyncSnapshot> provider)
    {
        _snapshot = provider ?? (static () => new SyncSnapshot());
    }

    public void Start()
    {
        _thread.Start();
        if (string.IsNullOrWhiteSpace(_cfg.HeartbeatUrl))
            AppLogger.Info("未配置心跳地址，心跳上报已跳过");
    }

    public void UpdateConfig(AppConfig cfg)
    {
        lock (_gate) _cfg = ConfigStore.Normalize(cfg);
        _lastResult = null;      // 换地址后重新建立状态
        _wake.Set();
    }

    public void Stop()
    {
        _stopping = true;
        try { _cts.Cancel(); } catch (ObjectDisposedException) { /* ignore */ }
        try { _wake.Set(); } catch (ObjectDisposedException) { /* ignore */ }
        if (_thread.IsAlive)
            _thread.Join(TimeSpan.FromSeconds(12));
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        Stop();
        if (!_thread.IsAlive)
        {
            _cts.Dispose();
            _wake.Dispose();
        }
    }

    private void Loop()
    {
        // 启动后先报一次，让服务端尽快看到这台机器
        SendOnce();

        while (!_stopping)
        {
            AppConfig cfg;
            lock (_gate) cfg = _cfg;
            var interval = Math.Max(10, cfg.HeartbeatSeconds);

            try
            {
                // 同时等取消 与 UpdateConfig 的唤醒，换地址后不必干等整个心跳间隔
                var idx = WaitHandle.WaitAny(
                    [_cts.Token.WaitHandle, _wake.WaitHandle],
                    TimeSpan.FromSeconds(interval));
                if (idx == 0) return;          // CTS 取消
                if (idx == 1) _wake.Reset();   // 配置更新唤醒
            }
            catch (ObjectDisposedException)
            {
                return;
            }

            if (_stopping) return;
            SendOnce();
        }
    }

    private void SendOnce()
    {
        AppConfig cfg;
        lock (_gate) cfg = _cfg;

        var url = NormalizeUrl(cfg.HeartbeatUrl);
        if (url is null) return;

        var snap = SafeSnapshot();
        var payload = BuildPayload(cfg, snap);

        try
        {
            using var content = new StringContent(payload, Encoding.UTF8, "application/json");
            using var resp = Http.PostAsync(url, content).GetAwaiter().GetResult();
            var code = (int)resp.StatusCode;
            Record(resp.IsSuccessStatusCode,
                resp.IsSuccessStatusCode ? $"HTTP {code}" : $"HTTP {code} {resp.ReasonPhrase}");
        }
        catch (Exception ex)
        {
            Record(false, ex.InnerException?.Message ?? ex.Message);
        }
    }

    /// <summary>只在成功/失败状态翻转时落日志。</summary>
    private void Record(bool ok, string detail)
    {
        if (_lastResult == ok) return;
        if (ok)
            AppLogger.Info(_lastResult is null ? $"心跳已连通: {detail}" : "心跳上报已恢复");
        else
            AppLogger.Warn($"心跳上报失败: {detail}");
        _lastResult = ok;
    }

    private SyncSnapshot SafeSnapshot()
    {
        try { return _snapshot(); }
        catch { return new SyncSnapshot(); }
    }

    /// <summary>
    /// 归一化心跳地址：补协议、补 /api/heartbeat。返回 null 表示未配置或格式非法。
    /// </summary>
    public static string? NormalizeUrl(string? raw)
    {
        var u = (raw ?? "").Trim();
        if (u.Length == 0) return null;
        if (!u.StartsWith("http://", StringComparison.OrdinalIgnoreCase) &&
            !u.StartsWith("https://", StringComparison.OrdinalIgnoreCase))
            u = "http://" + u;

        if (!Uri.TryCreate(u, UriKind.Absolute, out var uri)) return null;
        if (uri.Host.Length == 0) return null;

        if (string.IsNullOrEmpty(uri.AbsolutePath) || uri.AbsolutePath == "/")
            u = u.TrimEnd('/') + "/api/heartbeat";
        return u;
    }

    private static string BuildPayload(AppConfig cfg, SyncSnapshot snap)
    {
        // 设备别名由配置按模式自动派生（注塑机=机台号 / 外观机=项目-机台-工站），
        // 未填任何标识时 AppConfig 内部已退回本机主机名。
        var alias = cfg.DeviceAlias;
        var body = new Dictionary<string, object?>
        {
            ["clientId"] = alias,
            ["deviceAlias"] = alias,
            ["hostName"] = Environment.MachineName,
            ["clientVersion"] = ClientVersion,
            ["mode"] = cfg.Mode,
            ["modeLabel"] = cfg.ModeLabel,
            ["machine"] = cfg.Machine,
            ["project"] = cfg.Project,
            ["station"] = cfg.Station,
            ["clientStatus"] = cfg.Paused ? SyncStatus.Paused : snap.Status,
            ["paused"] = cfg.Paused,
            ["source"] = cfg.SourceDir,
            ["target"] = cfg.EffectiveTarget(),
            ["okCount"] = snap.OkCount,
            ["failCount"] = snap.FailCount,
            ["totalRuns"] = snap.TotalRuns,
            ["lastSync"] = snap.LastSync,
            ["timestamp"] = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss")
        };
        return JsonSerializer.Serialize(body, JsonOptions);
    }

    /// <summary>设置页「测试」用：同步发一次并返回结果说明。</summary>
    public static (bool ok, string message) Test(AppConfig cfg)
    {
        var url = NormalizeUrl(cfg.HeartbeatUrl);
        if (url is null)
            return (false, "心跳地址为空或格式非法。\n示例：http://10.18.97.189:5000");

        string payload;
        try
        {
            payload = BuildPayload(cfg, new SyncSnapshot());
        }
        catch (Exception ex)
        {
            return (false, $"构造心跳报文失败：{ex.Message}");
        }

        try
        {
            using var content = new StringContent(payload, Encoding.UTF8, "application/json");
            using var resp = Http.PostAsync(url, content).GetAwaiter().GetResult();
            var code = (int)resp.StatusCode;
            var text = "";
            try { text = resp.Content.ReadAsStringAsync().GetAwaiter().GetResult(); } catch { }
            if (text.Length > 300) text = text[..300] + "…";
            var body = string.IsNullOrWhiteSpace(text) ? "" : $"\n\n响应：{text}";
            return (resp.IsSuccessStatusCode,
                (resp.IsSuccessStatusCode ? "心跳上报成功" : "心跳上报失败") +
                $"（HTTP {code} {resp.ReasonPhrase}）\n地址：{url}{body}");
        }
        catch (Exception ex)
        {
            return (false, $"心跳上报异常：\n{ex.InnerException?.Message ?? ex.Message}\n\n地址：{url}");
        }
    }
}
