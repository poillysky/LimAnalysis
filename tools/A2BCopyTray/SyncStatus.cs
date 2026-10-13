namespace A2BCopyTray;

/// <summary>
/// 运行状态常量。引擎、主界面、托盘三处都用它比较状态，
/// 避免散落的魔法字符串（改一次文案就崩掉图标/按钮逻辑）。
/// </summary>
public static class SyncStatus
{
    /// <summary>运行中（两次轮询之间、当前没有文件要复制的常态）。
    /// 刻意不再叫「正常待机」：待机容易被读成「没在干活」，与「已暂停」混淆。</summary>
    public const string Idle = "监控中";
    public const string Syncing = "同步中";
    public const string Paused = "已暂停";
    public const string Error = "异常";
}
