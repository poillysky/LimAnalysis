using System.Drawing;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace A2BCopyTray;

/// <summary>
/// 界面状态：窗口位置/大小、是否已提示过最小化等。
/// 与业务配置分开存放（ui.json），因为它是「这台机器」的属性，
/// 现场拷贝 config.json 到另一台机时不该把窗口坐标也带过去。
/// </summary>
internal sealed class UiState
{
    /// <summary>未保存过位置时的哨兵值。</summary>
    public const int Unset = int.MinValue;

    public int MainX { get; set; } = Unset;
    public int MainY { get; set; } = Unset;
    public int MainW { get; set; }
    public int MainH { get; set; }
    public bool Maximized { get; set; }
    /// <summary>是否已经弹过「已最小化到托盘」的气泡（只弹一次，避免每次烦人）。</summary>
    public bool MinimizeTipShown { get; set; }

    [JsonIgnore]
    public bool HasBounds => MainX != Unset && MainY != Unset && MainW > 0 && MainH > 0;

    /// <summary>
    /// 把保存的窗口矩形夹回某块屏幕的可见区域内。
    /// 换显示器 / 改分辨率 / 拔掉扩展屏后，旧坐标可能整个落在屏幕外，
    /// 不夹一下就会「程序在跑但窗口找不到」。
    /// </summary>
    public static Rectangle Fit(Rectangle saved, Size minimum, Rectangle workArea)
    {
        var w = Math.Clamp(saved.Width, minimum.Width, Math.Max(minimum.Width, workArea.Width));
        var h = Math.Clamp(saved.Height, minimum.Height, Math.Max(minimum.Height, workArea.Height));

        // 至少留 80px 在屏幕内，保证窗口能被鼠标抓住
        const int keep = 80;
        var minX = workArea.Left - w + keep;
        var maxX = workArea.Right - keep;
        var minY = workArea.Top;
        var maxY = workArea.Bottom - keep;

        var x = Math.Clamp(saved.X, minX, Math.Max(minX, maxX));
        var y = Math.Clamp(saved.Y, minY, Math.Max(minY, maxY));
        return new Rectangle(x, y, w, h);
    }
}

/// <summary>ui.json 的读写。任何失败都静默降级为默认值，绝不影响主流程。</summary>
internal static class UiStateStore
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        PropertyNameCaseInsensitive = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
        AllowTrailingCommas = true
    };

    private static UiState? _cache;

    public static string FilePath => Path.Combine(AppPaths.ConfigDir, "ui.json");

    public static UiState Current => _cache ??= Load();

    public static UiState Load(string? path = null)
    {
        var file = path ?? FilePath;
        try
        {
            if (!File.Exists(file)) return new UiState();
            var json = File.ReadAllText(file);
            return JsonSerializer.Deserialize<UiState>(json, JsonOptions) ?? new UiState();
        }
        catch
        {
            // 界面状态坏了不值得打扰用户，也用不着备份，直接回默认
            return new UiState();
        }
    }

    /// <summary>写回界面状态。path 仅供测试注入，正常路径留空。</summary>
    public static bool Save(UiState? state = null, string? path = null)
    {
        var data = state ?? _cache;
        if (data is null) return false;
        if (path is null) _cache = data;

        try
        {
            var json = JsonSerializer.Serialize(data, JsonOptions);
            File.WriteAllText(path ?? FilePath, json + Environment.NewLine);
            return true;
        }
        catch
        {
            return false;
        }
    }
}
