using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.RegularExpressions;

namespace A2BCopyTray;

/// <summary>
/// 增量同步引擎。性能与正确性要点：
/// 1) 主循环零阻塞：文件"是否写完"用「两轮观察一致 + 文件年龄 ≥ 释放等待」推算，不做 sleep；
/// 2) 已同步的文件在任何耗时判断之前就被跳过，已同步目录的扫描成本≈纯枚举；
/// 3) 所有等待都可取消，进程退出时线程毫秒级收敛；
/// 4) 目标不可达走冷却退避，不会每轮卡在 SMB 超时上；
/// 5) 跟随时标不可靠时改用「目标不旧于源」判重，避免每轮全量重传。
/// </summary>
public sealed class SyncEngine : IDisposable
{
    public const string TempSuffix = ".a2btmp";

    /// <summary>时间戳比较容差。目标文件系统粒度可能是 2 秒（exFAT/SMB 网关）。</summary>
    private const double MtimeToleranceSeconds = 3;

    /// <summary>目标不可达后的冷却秒数：冷却期内不再做任何阻塞式探测。</summary>
    private const int TargetCooldownSeconds = 45;

    private const int TempSweepMinutes = 30;
    private const int TempStaleMinutes = 10;

    /// <summary>同一文件连续多少轮"被占用/暂时不可用"后，才升级成真正的失败告警。</summary>
    private const int TransientStrikeLimit = 10;

    /// <summary>进度/当前文件的 UI 刷新节流：200ms 一次。</summary>
    private static readonly long PublishIntervalTicks = Stopwatch.Frequency / 5;

    private readonly object _gate = new();
    private readonly CancellationTokenSource _cts = new();
    private readonly AutoResetEvent _wake = new(false);
    private readonly Thread _thread;

    /// <summary>上一轮观察到的 (大小, 修改时间UTC)，用于非阻塞的稳定性判定。</summary>
    private readonly Dictionary<string, (long Size, DateTime Mtime)> _probe = new(StringComparer.OrdinalIgnoreCase);
    /// <summary>本轮访问过的文件（用于收敛 _probe / _transientStrikes）。</summary>
    private readonly HashSet<string> _probeSeen = new(StringComparer.OrdinalIgnoreCase);
    /// <summary>连续"被占用"轮次计数。</summary>
    private readonly Dictionary<string, int> _transientStrikes = new(StringComparer.OrdinalIgnoreCase);

    private enum CopyOutcome { Success, Transient, Failed, Aborted }

    private AppConfig _cfg;
    private SyncSnapshot _snap = new();
    /// <summary>暂停态。volatile：同步线程在文件循环里无锁读取，点「停止同步」才能立刻中止本轮。</summary>
    private volatile bool _paused;
    /// <summary>
    /// 仅在「运行 → 暂停」边沿置位，用来打断正在进行的本轮。
    /// 不能把「当前已暂停」本身当成 abort —— 否则暂停下的手动同步会在 EnsureDir 里被误杀。
    /// </summary>
    private volatile bool _abortRound;
    private bool _manual;
    private bool _envLogged;
    private volatile bool _stopping;
    private bool _disposed;
    /// <summary>上一轮留下的「待稳定」文件数；&gt;0 时下一轮提早醒来，保证新图及时同步。</summary>
    private volatile int _pendingHint;

    private DateTime _targetDownUntil = DateTime.MinValue;
    private string _targetDownPath = "";
    private DateTime _lastTempSweep = DateTime.MinValue;
    private int _mtimeWarnings;
    private long _lastPublishTick;

    public event Action<SyncSnapshot>? SnapshotChanged;

    public SyncEngine(AppConfig cfg)
    {
        _cfg = ConfigStore.Normalize(cfg);
        // 启动初始态由「启动后暂停」决定（AppConfig.StartPaused，默认 true）：
        // 程序起来先停着，等人在界面上点「开始监控」才动。
        // 同时把运行态写回 _cfg.Paused，保证界面/托盘的切换按钮读数一致
        // （否则首次点「开始监控」会因为读到 false 反而又进入暂停）。
        _cfg.Paused = _cfg.StartPaused;
        _paused = _cfg.Paused;
        _thread = new Thread(Loop) { IsBackground = true, Name = "SyncEngine" };
    }

    /// <summary>当前是否暂停（供界面/测试查询，避免去读配置文件里的运行态字段）。</summary>
    public bool IsPaused
    {
        get { lock (_gate) return _paused; }
    }

    public void Start()
    {
        Publish();
        _thread.Start();
        if (_paused)
        {
            AppLogger.Info($"监控待启动（{_cfg.ModeLabel} {_cfg.DeviceAlias}）—— 请在界面点「开始监控」");
            if (_cfg.AutoStart)
                AppLogger.Warn("已开启「开机自启」且「启动后暂停」生效：开机后不会自动复制，需人工点「开始监控」");
        }
        else
        {
            AppLogger.Info($"监控已启动（{_cfg.ModeLabel} {_cfg.DeviceAlias}）");
        }
    }

    public void Stop()
    {
        _stopping = true;
        try { _cts.Cancel(); } catch (ObjectDisposedException) { /* ignore */ }
        try { _wake.Set(); } catch (ObjectDisposedException) { /* ignore */ }
        if (_thread.IsAlive)
            _thread.Join(TimeSpan.FromSeconds(15));
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        Stop();
        // 只有线程确实退出了才释放底层原语；否则让它随进程回收，
        // 免得引擎线程醒来后读到已释放的 CTS/Event 抛 ObjectDisposedException。
        if (!_thread.IsAlive)
        {
            _cts.Dispose();
            _wake.Dispose();
        }
    }

    public void UpdateConfig(AppConfig cfg)
    {
        lock (_gate)
        {
            // 运行态暂停只由 SetPaused 控制；配置保存绝不能把它覆盖掉
            // （设置页打开期间若从托盘点了暂停/开始，Draft 里的 Paused 可能是过期值）
            var keepPaused = _paused;
            _cfg = ConfigStore.Normalize(cfg);
            _cfg.Paused = keepPaused;
            _paused = keepPaused;
        }
        _envLogged = false;          // 目标/源可能变了，重新做一次环境诊断
        _targetDownUntil = DateTime.MinValue;
        Publish(message: "配置已更新");
        _wake.Set();
    }

    public void SetPaused(bool paused)
    {
        lock (_gate)
        {
            // 只有运行中被按下暂停，才打断本轮；已暂停时再点无效边沿
            if (paused && !_paused) _abortRound = true;
            if (!paused) _abortRound = false;
            _paused = paused;
            _cfg.Paused = paused;
        }
        if (paused)
        {
            // 立刻唤醒：打断轮询等待 / Sleep（限速·重试），本轮文件循环见 ShouldAbort 后退出
            AppLogger.Info("监控已暂停（当前同步任务将中止）");
            Publish(status: SyncStatus.Paused, currentFile: "-", message: "已停止同步");
        }
        else
        {
            // 开启监控 → 马上跑一轮同步，完成后才进入持续轮询
            _pendingHint = 0;
            AppLogger.Info("监控已启动，立即开始同步");
            Publish(status: SyncStatus.Syncing, currentFile: "-", message: "开始同步…");
        }
        _wake.Set();
    }

    public void RequestManualSync()
    {
        lock (_gate) _manual = true;
        AppLogger.Info("收到手动同步请求");
        _wake.Set();
    }

    public SyncSnapshot Snapshot()
    {
        lock (_gate) return _snap.Clone();
    }

    // ───────────────────────── 主循环 ─────────────────────────

    private void Loop()
    {
        while (!_stopping)
        {
            AppConfig cfg;
            bool manual;
            bool paused;
            lock (_gate)
            {
                cfg = _cfg;
                manual = _manual;
                _manual = false;
                paused = _paused;
            }

            if (paused && !manual)
            {
                Publish(status: SyncStatus.Paused);
            }
            else
            {
                try { Execute(cfg, manual); }
                catch (Exception ex)
                {
                    AppLogger.Error($"同步周期发生未预期异常: {ex.Message}");
                    Publish(status: SyncStatus.Error, message: ex.Message);
                }
            }

            if (_stopping) break;
            // 暂停态睡满轮询间隔即可；运行中若有待稳定文件，最多 2 秒再扫一轮，避免新图干等
            var waitSec = Math.Max(1, cfg.PollSeconds);
            if (!paused && _pendingHint > 0)
                waitSec = Math.Min(waitSec, 2);
            _wake.WaitOne(TimeSpan.FromSeconds(waitSec));
        }
    }

    /// <summary>进程退出，或「运行→暂停」边沿要求打断本轮时返回 true。</summary>
    private bool ShouldAbort() => _stopping || _abortRound;

    /// <summary>可取消等待。返回 true=可以继续，false=已要求停止/暂停。</summary>
    private bool Sleep(double seconds)
    {
        if (ShouldAbort()) return false;
        if (seconds <= 0) return true;

        // 切成 ≤200ms 的片，点「停止同步」时限速/重试等待也能马上醒
        var end = Stopwatch.GetTimestamp() + (long)(seconds * Stopwatch.Frequency);
        while (!ShouldAbort())
        {
            var remainMs = (end - Stopwatch.GetTimestamp()) * 1000.0 / Stopwatch.Frequency;
            if (remainMs <= 0) return true;
            var slice = (int)Math.Clamp(remainMs, 1, 200);
            try
            {
                if (_cts.Token.WaitHandle.WaitOne(slice))
                    return false;
            }
            catch (ObjectDisposedException)
            {
                return false;
            }
        }
        return false;
    }

    private void Execute(AppConfig cfg, bool manual)
    {
        // 暂停下的手动同步必须能完整跑完：清掉可能残留的 abort 边沿
        if (manual) _abortRound = false;
        _probeSeen.Clear();
        try
        {
            ExecuteCore(cfg, manual);
        }
        finally
        {
            PruneProbe();
        }
    }

    private void ExecuteCore(AppConfig cfg, bool manual)
    {
        var err = cfg.Validate();
        if (err is not null)
        {
            Publish(status: SyncStatus.Error, message: err);
            if (manual) AppLogger.Warn(err);
            return;
        }

        AppLogger.Cleanup(cfg.LogKeepDays);

        var source = cfg.SourceDir;
        var target = cfg.EffectiveTarget();
        var (ymd, dateLabel) = TodayKeys(cfg.IsAppearance);
        Publish(
            status: SyncStatus.Syncing,
            source: source,
            target: target,
            watchDate: dateLabel,
            currentFile: "-",
            progressDone: 0,
            progressTotal: 0,
            message: "");

        if (!_envLogged)
        {
            _envLogged = true;
            LogEnvironment(target);
        }

        if (!Directory.Exists(source))
        {
            if (FinishIfAborted()) return;
            var msg = $"源目录不存在: {source}";
            if (manual) AppLogger.Warn(msg);
            Publish(status: MonitorStatus(), message: manual ? msg : "");
            return;
        }

        if (!EnsureDir(target, allowPowerShellFallback: true))
        {
            // 暂停/退出会让 EnsureDir 提前返回 false，绝不能误报成「目标不可用」
            if (FinishIfAborted()) return;
            Publish(status: SyncStatus.Error, message: $"目标路径不可用，请检查网络连接: {target}");
            return;
        }

        var srcDay = FindSourceDayDir(source, cfg.IsAppearance, ymd, dateLabel);
        if (srcDay is null)
        {
            if (FinishIfAborted()) return;
            if (manual) AppLogger.Info("手动同步结束：当天目录不存在，保持静默等待");
            BumpRun(ok: true);
            Publish(status: MonitorStatus(), lastSync: Now(), message: "当天目录不存在");
            return;
        }

        var dstDay = Path.Combine(target, dateLabel);
        if (!EnsureDir(dstDay))
        {
            if (FinishIfAborted()) return;
            Publish(status: SyncStatus.Error, message: $"无法创建目标日期目录: {dstDay}");
            return;
        }

        SweepTempFiles(dstDay);

        var files = ListFiles(srcDay, cfg);
        var total = files.Count;
        var ok = 0;
        var fail = 0;
        var pending = 0;
        var index = 0;
        var aborted = false;

        foreach (var srcFile in files)
        {
            if (ShouldAbort()) { aborted = true; break; }
            index++;

            var rel = Path.GetRelativePath(srcDay, srcFile);
            var dstFile = Path.Combine(dstDay, rel);
            _probeSeen.Add(srcFile);

            // 1) 已经同步过 → 立刻跳过，不付出任何额外成本
            if (SameFile(srcFile, dstFile, cfg.CompareMode)) continue;

            // 2) 还没写完的文件不阻塞等待，记下来下轮再看
            if (!IsSettled(srcFile, cfg.FileSettleSeconds))
            {
                pending++;
                PublishThrottled(rel.Replace('\\', '/'), index, total);
                continue;
            }

            PublishThrottled(rel.Replace('\\', '/'), index, total);

            switch (CopyWithRetry(srcFile, dstFile, cfg))
            {
                case CopyOutcome.Success:
                    _transientStrikes.Remove(srcFile);
                    ok++;
                    AppLogger.Sync($"已同步: {rel}");
                    break;

                case CopyOutcome.Aborted:
                    aborted = true;
                    break;

                case CopyOutcome.Transient:
                    var strikes = _transientStrikes.TryGetValue(srcFile, out var v) ? v + 1 : 1;
                    if (strikes >= TransientStrikeLimit)
                    {
                        _transientStrikes.Remove(srcFile);
                        AppLogger.Error($"复制失败（连续 {strikes} 轮未能完成）: {rel}");
                        fail++;
                    }
                    else
                    {
                        _transientStrikes[srcFile] = strikes;
                        pending++;
                    }
                    break;

                default:
                    fail++;
                    break;
            }

            if (aborted) break;
        }

        // 用户点了「停止同步」：记上本轮已完成的计数，状态回到「已暂停」，不再进入监控中
        if (aborted)
        {
            var didWork = ok > 0 || fail > 0;
            if (didWork)
                BumpRun(ok: fail == 0, okDelta: ok, failDelta: fail);
            if (FinishIfAborted(
                    didWork ? $"同步已中止 成功={ok} 失败={fail}，监控已停止" : null,
                    touchLastSync: didWork))
                return;
            // 中止窗口里又点了「开始监控」：本轮计数已记过，按当前态收尾，避免再次 BumpRun
            if (_stopping) return;
            _pendingHint = pending;
            Publish(
                status: MonitorStatus(),
                lastSync: didWork ? Now() : null,
                currentFile: "-",
                progressDone: 0,
                progressTotal: 0,
                message: didWork ? $"已中止后恢复 成功 {ok} / 失败 {fail}" : "已停止同步");
            return;
        }

        if (_stopping) return;

        BumpRun(ok: fail == 0, okDelta: ok, failDelta: fail);
        _pendingHint = pending;

        // 稳态下不打日志，避免每天上万行空转记录
        if (ok > 0 || fail > 0 || pending > 0 || manual)
            AppLogger.Sync(
                $"本轮同步完成 成功={ok} 失败={fail} 待稳定={pending} 扫描={total}");

        // 同步跑完 → 持续监控；若本轮是「暂停态下的手动同步」，仍回到已暂停
        Publish(
            status: fail == 0 ? MonitorStatus() : SyncStatus.Error,
            lastSync: Now(),
            currentFile: "-",
            progressDone: total,
            progressTotal: total,
            message: $"成功 {ok} / 失败 {fail}" + (pending > 0 ? $" / 待稳定 {pending}" : ""));
    }

    /// <summary>本轮被「停止同步」打断时的收尾。返回 true 表示调用方应立刻 return。</summary>
    private bool FinishIfAborted(string? log = null, bool touchLastSync = false)
    {
        if (_stopping) return true;
        if (!_abortRound) return false; // 真失败（如目标不可达）不能当成暂停中止
        _abortRound = false; // 本轮已收束，后续手动同步不再被误伤
        _pendingHint = 0;
        AppLogger.Info(log ?? "同步已中止，监控已停止");
        Publish(
            status: _paused ? SyncStatus.Paused : SyncStatus.Idle,
            lastSync: touchLastSync ? Now() : null,
            currentFile: "-",
            progressDone: 0,
            progressTotal: 0,
            message: "已停止同步");
        return true;
    }

    /// <summary>正常结束时的状态：仍暂停 → 已暂停；否则 → 监控中。</summary>
    private string MonitorStatus() => _paused ? SyncStatus.Paused : SyncStatus.Idle;

    private static (string ymd, string label) TodayKeys(bool appearance)
    {
        var now = DateTime.Now;
        var ymd = now.ToString("yyyyMMdd");
        return appearance ? (ymd, now.ToString("yyyy.MM.dd")) : (ymd, ymd);
    }

    private static string? FindSourceDayDir(string source, bool appearance, string ymd, string dotted)
    {
        var candidates = new[] { ymd, dotted, $"{ymd[..4]}-{ymd[4..6]}-{ymd[6..]}" };
        var name = Path.GetFileName(source.TrimEnd('\\', '/'));
        if (candidates.Contains(name, StringComparer.OrdinalIgnoreCase) && Directory.Exists(source))
            return source;
        foreach (var c in candidates)
        {
            var path = Path.Combine(source, c);
            if (Directory.Exists(path)) return path;
        }
        return null;
    }

    // ───────────────────────── 稳定性判定（非阻塞） ─────────────────────────

    /// <summary>
    /// 判断源文件是否已经写完。
    /// 不再 sleep，而是要求：① 本轮与上一轮观察到的 (大小, 修改时间) 完全一致；
    /// ② 文件修改时间距今已超过 FileSettleSeconds。
    /// 未通过时只记录本轮采样，下一轮再判，因此单轮扫描成本与文件数成正比但不含等待。
    /// </summary>
    private bool IsSettled(string path, double settleSeconds)
    {
        if (settleSeconds <= 0) return true;

        FileInfo info;
        try
        {
            info = new FileInfo(path);
            if (!info.Exists) return false;
        }
        catch
        {
            return false;
        }

        long size;
        DateTime mtime;
        try
        {
            size = info.Length;
            mtime = info.LastWriteTimeUtc;
        }
        catch
        {
            return false;
        }

        var hadPrev = _probe.TryGetValue(path, out var prev);
        _probe[path] = (size, mtime);

        if (!hadPrev || prev.Size != size || prev.Mtime != mtime)
            return false;

        var age = (DateTime.UtcNow - mtime).TotalSeconds;
        return age >= settleSeconds;
    }

    private void PruneProbe()
    {
        if (_probeSeen.Count == 0)
        {
            _probe.Clear();
            _transientStrikes.Clear();
            return;
        }

        if (_probe.Count > 0)
        {
            var stale = new List<string>();
            foreach (var key in _probe.Keys)
                if (!_probeSeen.Contains(key)) stale.Add(key);
            foreach (var key in stale) _probe.Remove(key);
        }

        if (_transientStrikes.Count > 0)
        {
            var stale = new List<string>();
            foreach (var key in _transientStrikes.Keys)
                if (!_probeSeen.Contains(key)) stale.Add(key);
            foreach (var key in stale) _transientStrikes.Remove(key);
        }
    }

    // ───────────────────────── 文件枚举与过滤 ─────────────────────────

    private List<string> ListFiles(string root, AppConfig cfg)
    {
        var absExcludes = new List<string>();
        var nameExcludes = new List<string>();
        // 用「实际生效」清单：内置默认项在此并入，任何配置下都不会漏
        foreach (var raw in cfg.EffectiveExcludePaths)
        {
            var e = (raw ?? "").Trim().TrimEnd('\\', '/');
            if (e.Length == 0) continue;
            if (IsAbsolutePath(e)) absExcludes.Add(e);
            else nameExcludes.Add(e);
        }

        var outList = new List<string>();
        foreach (var file in SafeEnumerateFiles(root))
        {
            if (ShouldAbort()) break;
            var rel = Path.GetRelativePath(root, file).Replace('\\', '/');
            var fileName = Path.GetFileName(file);

            if (IsUnderAnyExcludeRoot(file, absExcludes)) continue;
            if (MatchesAnyNameExclude(rel, fileName, nameExcludes)) continue;
            if (cfg.Blacklist.Any(pat => MatchWildcard(rel, pat) || MatchWildcard(fileName, pat)))
                continue;
            if (cfg.Whitelist.Count > 0 &&
                !cfg.Whitelist.Any(pat => MatchWildcard(rel, pat) || MatchWildcard(fileName, pat)))
                continue;

            outList.Add(file);
        }
        return outList;
    }

    /// <summary>
    /// 逐目录递归枚举，任何一层出错（无权限、路径过长、IO）只跳过该层，不影响其余文件。
    /// 不跟随重解析点（联接/符号链接），避免目录环。
    /// </summary>
    private List<string> SafeEnumerateFiles(string root)
    {
        var result = new List<string>();
        var stack = new Stack<string>();
        stack.Push(root);

        while (stack.Count > 0)
        {
            if (ShouldAbort()) break;
            var dir = stack.Pop();

            try
            {
                foreach (var f in Directory.EnumerateFiles(dir, "*", SearchOption.TopDirectoryOnly))
                    result.Add(f);
            }
            catch (Exception ex)
            {
                AppLogger.Warn($"枚举文件失败，跳过该目录: {dir} | {ex.Message}");
            }

            try
            {
                foreach (var d in Directory.EnumerateDirectories(dir, "*", SearchOption.TopDirectoryOnly))
                {
                    if (ShouldAbort()) break;
                    try
                    {
                        if ((File.GetAttributes(d) & FileAttributes.ReparsePoint) != 0) continue;
                    }
                    catch
                    {
                        continue;
                    }
                    stack.Push(d);
                }
            }
            catch (Exception ex)
            {
                AppLogger.Warn($"枚举子目录失败，跳过该目录: {dir} | {ex.Message}");
            }
        }
        return result;
    }

    private static bool IsAbsolutePath(string p) =>
        p.StartsWith(@"\\", StringComparison.Ordinal) ||
        p.StartsWith("//", StringComparison.Ordinal) ||
        (p.Length >= 2 && p[1] == ':');

    private static bool IsUnderAnyExcludeRoot(string file, List<string> roots)
    {
        foreach (var root in roots)
        {
            if (IsUnderExclude(file, root)) return true;
        }
        return false;
    }

    private static bool IsUnderExclude(string file, string excludeRoot)
    {
        if (string.IsNullOrEmpty(excludeRoot)) return false;
        try
        {
            var full = Path.GetFullPath(file);
            string ex;
            try { ex = Path.GetFullPath(excludeRoot); }
            catch { ex = excludeRoot; }
            ex = ex.TrimEnd('\\', '/');
            return full.Equals(ex, StringComparison.OrdinalIgnoreCase) ||
                   full.StartsWith(ex + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase) ||
                   full.StartsWith(ex + Path.AltDirectorySeparatorChar, StringComparison.OrdinalIgnoreCase);
        }
        catch
        {
            return false;
        }
    }

    /// <summary>相对名排除：匹配任意路径段（目录名）或文件名，支持 * ? 通配。</summary>
    private static bool MatchesAnyNameExclude(string rel, string fileName, List<string> names)
    {
        if (names.Count == 0) return false;
        var segments = rel.Split('/');
        foreach (var name in names)
        {
            if (MatchWildcard(fileName, name)) return true;
            foreach (var seg in segments)
            {
                if (MatchWildcard(seg, name)) return true;
            }
            // 允许写 "a/b" 这类多段相对路径
            if (name.Contains('/') && MatchWildcard(rel, name)) return true;
        }
        return false;
    }

    private static readonly Dictionary<string, Regex> WildcardCache = new(StringComparer.OrdinalIgnoreCase);
    private static readonly object WildcardGate = new();

    private static bool MatchWildcard(string text, string pattern)
    {
        if (string.IsNullOrEmpty(pattern)) return false;
        // 统一分隔符，用户写 sub\*.jpg 也能命中
        var key = pattern.Replace('\\', '/');

        Regex rx;
        lock (WildcardGate)
        {
            if (!WildcardCache.TryGetValue(key, out rx!))
            {
                var expr = "^" + Regex.Escape(key).Replace("\\*", ".*").Replace("\\?", ".") + "$";
                rx = new Regex(
                    expr,
                    RegexOptions.IgnoreCase | RegexOptions.CultureInvariant,
                    TimeSpan.FromMilliseconds(250));
                if (WildcardCache.Count > 500) WildcardCache.Clear();
                WildcardCache[key] = rx;
            }
        }

        try { return rx.IsMatch(text); }
        catch (RegexMatchTimeoutException) { return false; }
    }

    // ───────────────────────── 判重 ─────────────────────────

    private bool SameFile(string src, string dst, string mode)
    {
        FileInfo a;
        FileInfo b;
        try
        {
            a = new FileInfo(src);
            if (!a.Exists) return false;
            b = new FileInfo(dst);
            if (!b.Exists) return false;
            if (a.Length != b.Length) return false;
        }
        catch
        {
            return false;
        }

        if (a.Length == 0) return true;

        if (string.Equals(mode, "md5", StringComparison.OrdinalIgnoreCase))
        {
            try { return Md5(src) == Md5(dst); }
            catch { return false; }
        }

        try
        {
            var delta = (a.LastWriteTimeUtc - b.LastWriteTimeUtc).TotalSeconds;
            // 时间戳一致（正常路径）
            if (Math.Abs(delta) <= MtimeToleranceSeconds) return true;
            // 目标比源新：源文件写入时间戳失败时的正常情形，判定为已同步，
            // 否则会出现"每轮全量重传"。源文件被覆盖后 mtime 变晚 → delta>0 → 重新同步。
            if (delta < 0) return true;
            return false;
        }
        catch
        {
            return false;
        }
    }

    private static string Md5(string path)
    {
        using var fs = File.Open(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
        var hash = MD5.HashData(fs);
        return Convert.ToHexString(hash);
    }

    // ───────────────────────── 复制 ─────────────────────────

    /// <summary>
    /// 带重试的复制。区分三种结果：
    /// Success=已同步；Transient=文件被占用/暂时不可用（不阻塞，交给下轮）；Failed=真的失败。
    /// </summary>
    private CopyOutcome CopyWithRetry(string src, string dst, AppConfig cfg)
    {
        var attempts = Math.Max(1, cfg.RetryCount);
        var last = "";

        for (var attempt = 1; attempt <= attempts; attempt++)
        {
            if (ShouldAbort()) return CopyOutcome.Aborted;
            try
            {
                var dir = Path.GetDirectoryName(dst);
                if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir))
                    Directory.CreateDirectory(dir);

                CopyFile(src, dst, cfg.SpeedLimitKbps);
                PreserveTimestamp(src, dst);
                return CopyOutcome.Success;
            }
            catch (OperationCanceledException)
            {
                return ShouldAbort() ? CopyOutcome.Aborted : CopyOutcome.Failed;
            }
            catch (DestinationBusyException ex)
            {
                // 目录可写、目标文件被下游占用：不在这里 sleep 重试（会卡住整轮），交给下轮
                AppLogger.Sync($"目标文件被占用，等待下轮同步: {Path.GetFileName(dst)} | {ex.Message}");
                return CopyOutcome.Transient;
            }
            catch (IOException ex) when (IsTransientIo(ex))
            {
                // 相机程序还没放开源文件句柄：同样不阻塞，下轮再看
                AppLogger.Sync($"文件被占用，等待下轮同步: {Path.GetFileName(src)}");
                return CopyOutcome.Transient;
            }
            catch (UnauthorizedAccessException ex) { last = $"访问被拒绝: {ex.Message}"; }
            catch (IOException ex) { last = $"IO错误: {ex.Message}"; }
            catch (Exception ex) { last = ex.Message; }

            AppLogger.Warn($"同步重试 {attempt}/{attempts}: {last}");
            if (attempt < attempts && !Sleep(cfg.RetryInterval)) return CopyOutcome.Failed;
        }

        AppLogger.Error($"复制失败: {Path.GetFileName(src)} | {last}");
        return CopyOutcome.Failed;
    }

    /// <summary>ERROR_SHARING_VIOLATION(32) / ERROR_LOCK_VIOLATION(33)：属于"等一会就好"，不算失败。</summary>
    private static bool IsTransientIo(IOException ex)
    {
        var code = ex.HResult & 0xFFFF;
        return code is 32 or 33;
    }

    /// <summary>
    /// 先写同目录临时文件再原子改名（目标上不会出现半截图）。
    /// 临时文件方式不被目标支持时（部分 SMB/网关对 Move-overwrite 不友好）降级为直接覆盖复制。
    /// 若临时文件已写入成功、只是最后一步替换失败，说明目录可写而目标文件被占用，
    /// 抛 <see cref="DestinationBusyException"/> 让上层按"等下轮"处理，而不是误报失败。
    /// </summary>
    private void CopyFile(string src, string dst, int limitKbps)
    {
        var tmp = dst + TempSuffix;
        var tmpWritten = false;

        try
        {
            try
            {
                using (var rf = File.Open(src, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                using (var wf = File.Create(tmp))
                {
                    ThrottledCopy(rf, wf, limitKbps);
                    wf.Flush(flushToDisk: true);
                }
                tmpWritten = true;

                try
                {
                    File.Move(tmp, dst, overwrite: true);
                    return;
                }
                catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
                {
                    AppLogger.Warn($"临时文件方式复制失败，降级为直接复制: {ex.Message}");
                }
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                AppLogger.Warn($"写临时文件失败，降级为直接复制: {ex.Message}");
            }

            try
            {
                File.Copy(src, dst, overwrite: true);
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                if (tmpWritten)
                    throw new DestinationBusyException($"目标文件无法替换: {ex.Message}", ex);
                throw;
            }
        }
        finally
        {
            TryDelete(tmp);
        }
    }

    /// <summary>目录可写、只有目标文件本身被占用（下游正在读）时抛出。</summary>
    private sealed class DestinationBusyException : Exception
    {
        public DestinationBusyException(string message, Exception inner) : base(message, inner) { }
    }

    /// <summary>按块复制并按剩余时间补偿限速，实际速率贴近设定值。</summary>
    private void ThrottledCopy(FileStream rf, FileStream wf, int limitKbps)
    {
        const int chunk = 256 * 1024;
        var limit = Math.Max(0, limitKbps) * 1024.0;
        var buf = new byte[chunk];

        int n;
        while ((n = rf.Read(buf, 0, buf.Length)) > 0)
        {
            var started = Stopwatch.GetTimestamp();
            wf.Write(buf, 0, n);

            if (limit > 0)
            {
                var budget = n / limit;
                var elapsed = (Stopwatch.GetTimestamp() - started) / (double)Stopwatch.Frequency;
                var remain = budget - elapsed;
                if (remain > 0 && !Sleep(remain))
                    throw new OperationCanceledException();
            }

            if (ShouldAbort()) throw new OperationCanceledException();
        }
    }

    private void PreserveTimestamp(string src, string dst)
    {
        try
        {
            File.SetLastWriteTimeUtc(dst, File.GetLastWriteTimeUtc(src));
        }
        catch (Exception ex)
        {
            // 目标不支持改时间戳：判重会自动退化为「目标不旧于源」，但必须让人知道
            if (++_mtimeWarnings <= 3)
                AppLogger.Warn($"无法保留目标文件时间戳（判重将退化为「目标不旧于源」）: {ex.Message}");
        }
    }

    private static void TryDelete(string path)
    {
        try { if (File.Exists(path)) File.Delete(path); } catch { /* ignore */ }
    }

    /// <summary>清理目标当天目录里残留的历史临时文件（崩溃/断电遗留）。</summary>
    private void SweepTempFiles(string dstDay)
    {
        if (DateTime.UtcNow - _lastTempSweep < TimeSpan.FromMinutes(TempSweepMinutes)) return;
        _lastTempSweep = DateTime.UtcNow;
        try
        {
            var cutoff = DateTime.UtcNow.AddMinutes(-TempStaleMinutes);
            var removed = 0;
            foreach (var f in Directory.EnumerateFiles(dstDay, "*" + TempSuffix, SearchOption.AllDirectories))
            {
                if (ShouldAbort()) break;
                try
                {
                    if (File.GetLastWriteTimeUtc(f) < cutoff)
                    {
                        File.Delete(f);
                        removed++;
                    }
                }
                catch { /* ignore */ }
            }
            if (removed > 0) AppLogger.Info($"清理残留临时文件 {removed} 个: {dstDay}");
        }
        catch (Exception ex)
        {
            AppLogger.Warn($"清理残留临时文件失败: {ex.Message}");
        }
    }

    // ───────────────────────── 目录 ─────────────────────────

    /// <summary>
    /// 建目录。失败后的 <see cref="TargetCooldownSeconds"/> 秒内直接快速失败，
    /// 不再做「3 次重试 + PowerShell 兜底」那种会卡住整个同步线程的探测。
    /// </summary>
    private bool EnsureDir(string path, bool allowPowerShellFallback = false)
    {
        if (Directory.Exists(path)) return true;

        if (_targetDownUntil > DateTime.UtcNow &&
            string.Equals(path, _targetDownPath, StringComparison.OrdinalIgnoreCase))
            return false;

        for (var attempt = 1; attempt <= 2; attempt++)
        {
            if (ShouldAbort()) return false;
            try
            {
                Directory.CreateDirectory(path);
                if (Directory.Exists(path))
                {
                    _targetDownUntil = DateTime.MinValue;
                    return true;
                }
            }
            catch (UnauthorizedAccessException ex)
            {
                AppLogger.Warn($"创建目录权限被拒绝 ({attempt}/2): {path} | {ex.Message}");
            }
            catch (IOException ex)
            {
                AppLogger.Warn($"创建目录IO错误 ({attempt}/2): {path} | {ex.Message}");
            }
            catch (Exception ex)
            {
                AppLogger.Warn($"创建目录异常 ({attempt}/2): {path} | {ex.Message}");
            }

            if (attempt < 2 && !Sleep(1)) return false;
        }

        if (allowPowerShellFallback && IsNetworkPath(path) && TryCreateDirectoryWithPowerShell(path))
        {
            _targetDownUntil = DateTime.MinValue;
            return true;
        }

        _targetDownPath = path;
        _targetDownUntil = DateTime.UtcNow.AddSeconds(TargetCooldownSeconds);
        AppLogger.Warn($"目标路径暂不可用，{TargetCooldownSeconds}s 内不再重试: {path}");
        return false;
    }

    private bool TryCreateDirectoryWithPowerShell(string path)
    {
        try
        {
            var quoted = path.Replace("'", "''");
            var psi = new ProcessStartInfo
            {
                FileName = "powershell.exe",
                Arguments = $"-NoProfile -NonInteractive -Command \"New-Item -ItemType Directory -Path '{quoted}' -Force | Out-Null\"",
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true
            };

            using var proc = Process.Start(psi);
            if (proc is null) return false;

            var deadline = DateTime.UtcNow.AddSeconds(15);
            while (!proc.WaitForExit(250))
            {
                if (ShouldAbort() || DateTime.UtcNow > deadline)
                {
                    try { proc.Kill(true); } catch { /* ignore */ }
                    AppLogger.Warn(ShouldAbort() ? "PowerShell 创建目录已取消" : "PowerShell 创建目录超时");
                    return false;
                }
            }

            if (proc.ExitCode == 0 && Directory.Exists(path))
            {
                AppLogger.Info($"PowerShell 兜底创建目录成功: {path}");
                return true;
            }
            AppLogger.Warn($"PowerShell 兜底创建目录失败: {path}");
        }
        catch (Exception ex)
        {
            AppLogger.Warn($"调用 PowerShell 创建目录异常 | {ex.Message}");
        }
        return false;
    }

    private static bool IsNetworkPath(string path) =>
        path.StartsWith(@"\\", StringComparison.Ordinal) ||
        path.StartsWith("//", StringComparison.Ordinal);

    private void LogEnvironment(string target)
    {
        try
        {
            var user = $"{Environment.UserDomainName}\\{Environment.UserName}";
            AppLogger.Info(
                $"运行环境诊断: 用户={user}；认证=NTLM；进程ID={Environment.ProcessId}；" +
                $"目标路径={target}；目标路径长度={target.Length}；是否网络路径={IsNetworkPath(target)}；" +
                $"当前目录={Environment.CurrentDirectory}");
        }
        catch (Exception ex)
        {
            AppLogger.Warn($"记录运行环境诊断失败: {ex.Message}");
        }
    }

    // ───────────────────────── 状态发布 ─────────────────────────

    private void BumpRun(bool ok, int okDelta = 0, int failDelta = 0)
    {
        lock (_gate)
        {
            _snap.TotalRuns++;
            _snap.OkCount += okDelta;
            _snap.FailCount += failDelta;
            if (!ok && failDelta == 0) _snap.FailCount++;
        }
    }

    /// <summary>进度刷新节流：最多 5 次/秒，避免大目录把 UI 消息队列刷爆。</summary>
    private void PublishThrottled(string currentFile, int done, int total)
    {
        var now = Stopwatch.GetTimestamp();
        var due = done >= total || _lastPublishTick == 0 ||
                  now - _lastPublishTick >= PublishIntervalTicks;
        if (!due) return;
        _lastPublishTick = now;
        Publish(currentFile: currentFile, progressDone: done, progressTotal: total);
    }

    private void Publish(
        string? status = null,
        string? source = null,
        string? target = null,
        string? watchDate = null,
        string? lastSync = null,
        string? currentFile = null,
        string? message = null,
        int? progressDone = null,
        int? progressTotal = null)
    {
        SyncSnapshot snap;
        lock (_gate)
        {
            _snap.ModeLabel = _cfg.ModeLabel;
            _snap.DeviceAlias = _cfg.DeviceAlias;
            _snap.Source = _cfg.SourceDir;
            _snap.Target = _cfg.EffectiveTarget();
            if (_paused && status is null) _snap.Status = SyncStatus.Paused;
            if (status is not null) _snap.Status = status;
            if (source is not null) _snap.Source = source;
            if (target is not null) _snap.Target = target;
            if (watchDate is not null) _snap.WatchDate = watchDate;
            if (lastSync is not null) _snap.LastSync = lastSync;
            if (currentFile is not null) _snap.CurrentFile = currentFile;
            if (message is not null) _snap.Message = message;
            if (progressDone is not null) _snap.ProgressDone = progressDone.Value;
            if (progressTotal is not null) _snap.ProgressTotal = progressTotal.Value;
            snap = _snap.Clone();
        }
        try { SnapshotChanged?.Invoke(snap); } catch { /* ignore */ }
    }

    private static string Now() => DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss");
}
