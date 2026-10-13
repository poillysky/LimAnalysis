using System.Text.Json.Serialization;

namespace A2BCopyTray;

/// <summary>
/// 站点复制配置。注塑机 / 外观机模式字段不同，存储仍是一份 config.json。
/// 目标路径对齐 LimAnalysis 注塑机图片 / 自动外观图片识别结构。
/// </summary>
public sealed class AppConfig
{
    public const string AppearanceSeg0 = "GVIMAGES";
    public const string AppearanceSeg1 = "LIM外观检测";

    /// <summary>mold = 注塑机；appearance = 外观机</summary>
    public string Mode { get; set; } = "mold";
    public string Machine { get; set; } = "";
    public string Project { get; set; } = "";
    /// <summary>外观机工站信息（仅外观模式使用，不参与目标路径拼装）。</summary>
    public string Station { get; set; } = "";
    public string SourceDir { get; set; } = @"C:\A2B\Source";
    public string TargetRoot { get; set; } = @"\\SERVER\Share\A2B";
    public string HeartbeatUrl { get; set; } = "";
    public int PollSeconds { get; set; } = 5;
    public double FileSettleSeconds { get; set; } = 10;
    public int RetryCount { get; set; } = 3;
    public double RetryInterval { get; set; } = 5;
    public int SpeedLimitKbps { get; set; } = 0;
    public int LogKeepDays { get; set; } = 15;
    public int HeartbeatSeconds { get; set; } = 30;
    /// <summary>fast | md5</summary>
    public string CompareMode { get; set; } = "fast";
    public bool AutoStart { get; set; }
    public bool CrashRestart { get; set; } = true;

    /// <summary>
    /// **当前**是否处于暂停态。只对本次运行有效，**不写进 config.json**（见 [JsonIgnore]）。
    /// 启动时的初始值来自 <see cref="StartPaused"/>；运行中由主界面/托盘的「开始监控 · 暂停监控」切换。
    /// 老配置里遗留的 <c>"paused": true</c> 会被直接忽略（它不是启动偏好）。
    /// </summary>
    [JsonIgnore]
    public bool Paused { get; set; }

    /// <summary>
    /// **启动后停在暂停态、等人工点「开始监控」**（默认 true）。这一项**会持久化**。
    /// 与 <see cref="Paused"/> 的区别：Paused 是"此刻的运行状态"，StartPaused 是"启动策略"。
    /// 现场要求：程序起来不能自己就开始复制 —— 必须有人确认过设备/源目录/目标共享都就绪，
    /// 再手动点开始。否则一旦源目录里混进无关文件，会被自动搬进分析流水线。
    /// 注意：与「开机自启」同时勾选时，开机后同样停在暂停态、需人工开始（启动日志会打印提醒）。
    /// </summary>
    public bool StartPaused { get; set; } = true;
    public List<string> Whitelist { get; set; } = new();
    /// <summary>默认黑名单：临时文件 + Windows 缩略图/目录配置文件（不该进分析流水线）。</summary>
    public List<string> Blacklist { get; set; } = new()
    {
        "*.tmp", "*.temp", "*.part", "Thumbs.db", "desktop.ini"
    };

    /// <summary>
    /// 排除清单。**实际生效 = 内置默认项 + 这里的自定义项**（去重，默认在前）。
    /// 每行一条，两种写法都支持：
    /// ① 相对目录名 / 文件名（如 cache、Thumbs.db），按当天目录树里的路径段匹配；
    /// ② 绝对路径或 UNC（如 \\NAS\Share\tmp），按目标前缀排除。
    /// </summary>
    public List<string> ExcludePaths { get; set; } = new(DefaultExcludePaths);

    /// <summary>
    /// 内置默认排除项：**始终生效、界面上只读、不可删除**。
    /// 这几项是所有站点通吃的垃圾目录/文件，交给代码兜底比让现场手填可靠。
    /// </summary>
    public static readonly IReadOnlyList<string> DefaultExcludePaths = ["temp", "cache", "Thumbs"];

    public static bool IsDefaultExclude(string? s) =>
        !string.IsNullOrWhiteSpace(s) &&
        DefaultExcludePaths.Contains(s.Trim(), StringComparer.OrdinalIgnoreCase);

    /// <summary>
    /// 实际生效的排除清单 = 内置默认 + 自定义（去重、忽略大小写，默认项在前）。
    /// 同步引擎按这个来过滤，因此默认项在任何配置下都不会失效。
    /// </summary>
    [JsonIgnore]
    public List<string> EffectiveExcludePaths
    {
        get
        {
            var list = new List<string>();
            Add(DefaultExcludePaths);
            Add(ExcludePaths);

            void Add(IEnumerable<string>? src)
            {
                if (src is null) return;
                foreach (var raw in src)
                {
                    var s = (raw ?? "").Trim();
                    if (s.Length == 0) continue;
                    if (!list.Contains(s, StringComparer.OrdinalIgnoreCase)) list.Add(s);
                }
            }
            return list;
        }
    }

    /// <summary>用户自定义排除项（不含内置默认），供设置页编辑框显示。</summary>
    [JsonIgnore]
    public List<string> CustomExcludePaths =>
        EffectiveExcludePaths.Where(x => !IsDefaultExclude(x)).ToList();

    /// <summary>旧版单值排除路径，仅用于读入迁移，保存时清空。</summary>
    public string? ExcludePath { get; set; }

    /// <summary>旧版多相对名列表，仅用于读入迁移，保存时清空。</summary>
    public List<string>? ExcludeDirs { get; set; }

    [JsonIgnore]
    public bool IsAppearance =>
        string.Equals(Mode, "appearance", StringComparison.OrdinalIgnoreCase);

    [JsonIgnore]
    public string ModeLabel => IsAppearance ? "外观机" : "注塑机";

    /// <summary>
    /// 设备别名 —— 由运行模式**自动派生**，不手工填写：
    /// 注塑机 → 机台号；外观机 → 项目-机台-工站（空段自动跳过）。
    /// 一个都没填时退回本机主机名，保证日志与心跳始终有可识别的标识。
    /// 这是「这台设备是谁」的唯一来源：日志、主界面、心跳报文全部取这里。
    /// </summary>
    [JsonIgnore]
    public string DeviceAlias
    {
        get
        {
            var text = IsAppearance
                ? string.Join("-", new[] { Project, Machine, Station }
                    .Select(x => (x ?? "").Trim())
                    .Where(x => x.Length > 0))
                : (Machine ?? "").Trim();
            return text.Length > 0 ? text : Environment.MachineName;
        }
    }

    public string? Validate()
    {
        if (!string.Equals(Mode, "mold", StringComparison.OrdinalIgnoreCase) &&
            !string.Equals(Mode, "appearance", StringComparison.OrdinalIgnoreCase))
            return "模式必须是注塑机或外观机";
        if (string.IsNullOrWhiteSpace(SourceDir))
            return "源目录和目标目录不能为空。";
        if (string.IsNullOrWhiteSpace(TargetRoot))
            return "源目录和目标目录不能为空。";
        if (string.IsNullOrWhiteSpace(Machine))
            return IsAppearance ? "外观机号不能为空" : "机台号不能为空";
        if (IsAppearance && string.IsNullOrWhiteSpace(Project))
            return "外观机模式需要填写项目名（与目标上项目文件夹一致）";

        var src = TrimTrailingSeparators(SourceDir);
        var dst = TrimTrailingSeparators(TargetRoot);
        if (src.Length >= 2 && dst.Length >= 2)
        {
            if (string.Equals(src, dst, StringComparison.OrdinalIgnoreCase))
                return "源目录与目标目录不能相同。";
            if (IsUnderPath(dst, src))
                return "目标共享目录不能位于源目录内部（会造成复制出来的文件被再次复制，无限增长）。";
        }
        return null;
    }

    public string EffectiveTarget()
    {
        var root = TrimTrailingSeparators(TargetRoot);
        var machine = Machine.Trim();
        if (IsAppearance)
        {
            var project = Project.Trim();
            return Path.Combine(root, project, machine, AppearanceSeg0, AppearanceSeg1);
        }
        return Path.Combine(root, machine);
    }

    public string EffectiveExclude()
    {
        var items = EffectiveExcludePaths;
        return items.Count == 0 ? "-" : string.Join(" ; ", items);
    }

    /// <summary>
    /// 去掉结尾分隔符，但保留文件系统根（`D:\`、`\\NAS\Share\` 不能被削成 `D:`、`\\NAS\Share`，
    /// 后者是非法或被重新解释的路径）。
    /// </summary>
    public static string TrimTrailingSeparators(string? path)
    {
        var p = (path ?? "").Trim();
        if (p.Length == 0) return p;

        var root = Path.GetPathRoot(p);
        var trimmed = p.TrimEnd('\\', '/');
        if (!string.IsNullOrEmpty(root) &&
            string.Equals(trimmed, root.TrimEnd('\\', '/'), StringComparison.OrdinalIgnoreCase))
            return root;
        return trimmed;
    }

    private static bool IsUnderPath(string child, string parent)
    {
        if (parent.Length == 0 || child.Length == 0) return false;
        var prefix = parent.TrimEnd('\\', '/') + Path.DirectorySeparatorChar;
        return child.StartsWith(prefix, StringComparison.OrdinalIgnoreCase);
    }

    public static AppConfig CreateDefault() => new();
}
