namespace A2BCopyTray;

public static class AppLogger
{
    private static readonly object Gate = new();
    private static readonly List<string> Recent = new();
    private const int RecentCap = 500;

    private static string? _todayPath;
    private static DateTime _todayDate = DateTime.MinValue;
    private static DateTime _lastCleanupDay = DateTime.MinValue;

    public static event Action<string>? LineWritten;

    public static void Info(string message) => Write("信息", message);
    public static void Sync(string message) => Write("同步", message);
    public static void Warn(string message) => Write("警告", message);
    public static void Error(string message) => Write("错误", message);

    public static void Write(string level, string message)
    {
        var now = DateTime.Now;
        var line = $"{now:yyyy-MM-dd HH:mm:ss} [{level}] {message}";
        lock (Gate)
        {
            try
            {
                File.AppendAllText(TodayPathCore(now), line + Environment.NewLine);
            }
            catch { /* ignore */ }

            Recent.Add(line);
            if (Recent.Count > RecentCap)
                Recent.RemoveRange(0, Recent.Count - RecentCap);
        }
        try { Console.WriteLine(line); } catch { /* ignore */ }
        try { LineWritten?.Invoke(line); } catch { /* ignore */ }
    }

    private static string TodayPathCore(DateTime now)
    {
        if (_todayPath is null || _todayDate.Date != now.Date)
        {
            _todayDate = now;
            _todayPath = Path.Combine(AppPaths.LogsDir, $"{now:yyyyMMdd}.log");
        }
        return _todayPath;
    }

    public static string[] SnapshotRecent()
    {
        lock (Gate) return Recent.ToArray();
    }

    /// <summary>按保留天数清理日志。内部按天节流，每轮同步调用也只是空转。</summary>
    public static void Cleanup(int keepDays)
    {
        lock (Gate)
        {
            var today = DateTime.Now.Date;
            if (_lastCleanupDay == today) return;
            _lastCleanupDay = today;

            try
            {
                var cutoff = today.AddDays(-Math.Max(1, keepDays));
                foreach (var file in Directory.EnumerateFiles(AppPaths.LogsDir, "*.log"))
                {
                    var name = Path.GetFileNameWithoutExtension(file);
                    if (name.Length == 8 &&
                        DateTime.TryParseExact(name, "yyyyMMdd", null,
                            System.Globalization.DateTimeStyles.None, out var day) &&
                        day < cutoff)
                    {
                        File.Delete(file);
                    }
                }
            }
            catch
            {
                Warn("清理日志失败");
            }
        }
    }

    public static string TodayLogPath =>
        Path.Combine(AppPaths.LogsDir, $"{DateTime.Now:yyyyMMdd}.log");
}
