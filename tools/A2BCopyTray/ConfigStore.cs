using System.Text.Json;
using System.Text.Json.Serialization;

namespace A2BCopyTray;

public static class ConfigStore
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        PropertyNameCaseInsensitive = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
        AllowTrailingCommas = true
    };

    public static AppConfig Load()
    {
        if (!File.Exists(AppPaths.ConfigFile))
        {
            var fresh = AppConfig.CreateDefault();
            Save(fresh);
            return fresh;
        }

        try
        {
            var json = File.ReadAllText(AppPaths.ConfigFile);
            var cfg = JsonSerializer.Deserialize<AppConfig>(json, JsonOptions);
            var normalized = Normalize(cfg);
            // 落盘一次，把旧字段（excludeDirs / excludePath）就地迁移成 excludePaths
            TrySave(normalized);
            return normalized;
        }
        catch (Exception ex)
        {
            // 不能静默回默认值：现场会以为"配置自己变了"。备份损坏文件并明确告知。
            var backup = BackupBroken();
            AppLogger.Error(
                $"配置文件无法解析，已使用默认配置启动" +
                (backup is null ? $"（备份失败）| {ex.Message}" : $"（原文件已备份到 {backup}）| {ex.Message}"));
            var fallback = AppConfig.CreateDefault();
            TrySave(fallback);
            return fallback;
        }
    }

    public static void Save(AppConfig cfg)
    {
        var normalized = Normalize(cfg);
        var json = JsonSerializer.Serialize(normalized, JsonOptions);
        File.WriteAllText(AppPaths.ConfigFile, json + Environment.NewLine);
    }

    /// <summary>保存但不抛异常，用于启动阶段/自动落盘。</summary>
    public static bool TrySave(AppConfig cfg)
    {
        try
        {
            Save(cfg);
            return true;
        }
        catch (Exception ex)
        {
            AppLogger.Warn($"配置保存失败（{AppPaths.ConfigFile} 可能不可写）: {ex.Message}");
            return false;
        }
    }

    private static string? BackupBroken()
    {
        try
        {
            var stamp = DateTime.Now.ToString("yyyyMMdd_HHmmss");
            var target = Path.Combine(AppPaths.ConfigDir, $"config.broken_{stamp}.json");
            File.Copy(AppPaths.ConfigFile, target, overwrite: true);
            return target;
        }
        catch
        {
            return null;
        }
    }

    public static AppConfig Normalize(AppConfig? raw)
    {
        var cfg = raw ?? AppConfig.CreateDefault();
        var mode = (cfg.Mode ?? "mold").Trim().ToLowerInvariant();
        if (mode is not ("mold" or "appearance")) mode = "mold";
        cfg.Mode = mode;
        cfg.Machine = (cfg.Machine ?? "").Trim();
        cfg.Project = (cfg.Project ?? "").Trim();
        cfg.Station = (cfg.Station ?? "").Trim();
        cfg.SourceDir = string.IsNullOrWhiteSpace(cfg.SourceDir)
            ? AppConfig.CreateDefault().SourceDir
            : cfg.SourceDir.Trim();
        cfg.TargetRoot = string.IsNullOrWhiteSpace(cfg.TargetRoot)
            ? AppConfig.CreateDefault().TargetRoot
            : cfg.TargetRoot.Trim();
        cfg.HeartbeatUrl = (cfg.HeartbeatUrl ?? "").Trim();
        cfg.PollSeconds = Math.Max(1, cfg.PollSeconds);
        cfg.FileSettleSeconds = Math.Max(0, cfg.FileSettleSeconds);
        cfg.RetryCount = Math.Max(1, cfg.RetryCount);
        cfg.RetryInterval = Math.Max(0.5, cfg.RetryInterval);
        cfg.SpeedLimitKbps = Math.Max(0, cfg.SpeedLimitKbps);
        cfg.LogKeepDays = Math.Max(1, cfg.LogKeepDays);
        cfg.HeartbeatSeconds = Math.Max(10, cfg.HeartbeatSeconds);
        var compare = (cfg.CompareMode ?? "fast").Trim().ToLowerInvariant();
        cfg.CompareMode = compare is "md5" ? "md5" : "fast";
        cfg.Whitelist ??= new();
        cfg.Blacklist ??= new();
        cfg.Whitelist = Clean(cfg.Whitelist);
        cfg.Blacklist = Clean(cfg.Blacklist);

        // 排除清单合并：内置默认项（永远保留、排最前）+ 当前字段 + 旧单值 + 旧相对名列表
        var merged = new List<string>();
        void AddEx(string? v)
        {
            var s = (v ?? "").Trim();
            if (s.Length == 0) return;
            if (!merged.Contains(s, StringComparer.OrdinalIgnoreCase)) merged.Add(s);
        }
        foreach (var d in AppConfig.DefaultExcludePaths) AddEx(d);
        foreach (var x in cfg.ExcludePaths ?? new List<string>()) AddEx(x);
        AddEx(cfg.ExcludePath);
        if (cfg.ExcludeDirs is { Count: > 0 })
            foreach (var x in cfg.ExcludeDirs) AddEx(x);

        cfg.ExcludePaths = merged;
        cfg.ExcludePath = null;   // 旧字段不再写出
        cfg.ExcludeDirs = null;
        return cfg;
    }

    private static List<string> Clean(List<string> src) =>
        src.Where(x => !string.IsNullOrWhiteSpace(x)).Select(x => x.Trim()).ToList();
}
