namespace A2BCopyTray;

public static class AppPaths
{
    private static string? _logsDir;

    public static string AppDir
    {
        get
        {
            var baseDir = AppContext.BaseDirectory.TrimEnd('\\', '/');
            // single-file publish: BaseDirectory is extract dir; prefer exe folder
            try
            {
                var exe = Environment.ProcessPath;
                if (!string.IsNullOrWhiteSpace(exe))
                    return Path.GetDirectoryName(exe) ?? baseDir;
            }
            catch { /* ignore */ }
            return baseDir;
        }
    }

    public static string ConfigDir => AppDir;

    public static string ConfigFile => Path.Combine(AppDir, "config.json");

    /// <summary>日志目录。目录创建只做一次（原先每写一行日志都要 CreateDirectory）。</summary>
    public static string LogsDir
    {
        get
        {
            if (_logsDir is not null) return _logsDir;
            var dir = Path.Combine(AppDir, "logs");
            try { Directory.CreateDirectory(dir); } catch { /* ignore */ }
            _logsDir = dir;
            return dir;
        }
    }
}
