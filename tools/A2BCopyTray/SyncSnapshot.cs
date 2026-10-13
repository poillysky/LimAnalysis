namespace A2BCopyTray;

public sealed class SyncSnapshot
{
    public string Status { get; set; } = SyncStatus.Idle;
    public string ModeLabel { get; set; } = "";
    /// <summary>设备别名（自动派生，见 AppConfig.DeviceAlias）。</summary>
    public string DeviceAlias { get; set; } = "";
    public string Source { get; set; } = "";
    public string Target { get; set; } = "";
    public string WatchDate { get; set; } = "";
    public string LastSync { get; set; } = "-";
    public string CurrentFile { get; set; } = "-";
    public int OkCount { get; set; }
    public int FailCount { get; set; }
    public int TotalRuns { get; set; }
    public int ProgressDone { get; set; }
    public int ProgressTotal { get; set; }
    public string Message { get; set; } = "";

    public SyncSnapshot Clone() => (SyncSnapshot)MemberwiseClone();
}
