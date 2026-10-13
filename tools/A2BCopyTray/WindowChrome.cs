using System.Runtime.InteropServices;

namespace A2BCopyTray;

/// <summary>
/// 窗口外观（Windows 11）：圆角 + 标题栏配色。
/// Win10 及更早版本上 DWM 不认识这些属性，调用会被忽略 —— 不会出错，只是没效果。
/// </summary>
internal static class WindowChrome
{
    private const int DwmwaWindowCornerPreference = 33;
    private const int DwmwaCaptionColor = 35;
    private const int DwmwaTextColor = 36;
    private const int DwmwcpRound = 2;

    [DllImport("dwmapi.dll", PreserveSig = true)]
    private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int value, int size);

    /// <summary>
    /// 让系统标题栏与应用内的深色 header 连成一体，并启用圆角。
    /// 只在 Win11（build 22000+）生效。
    /// </summary>
    public static void Apply(Form form, Color caption, Color captionText)
    {
        if (!OperatingSystem.IsWindowsVersionAtLeast(10, 0, 22000)) return;
        try
        {
            var hwnd = form.Handle;
            if (hwnd == IntPtr.Zero) return;
            Set(hwnd, DwmwaWindowCornerPreference, DwmwcpRound);
            Set(hwnd, DwmwaCaptionColor, ToColorRef(caption));
            Set(hwnd, DwmwaTextColor, ToColorRef(captionText));
        }
        catch { /* 外观失败不影响功能 */ }
    }

    /// <summary>COLORREF 是 0x00BBGGRR，与 Color 的 RGB 顺序相反。</summary>
    private static int ToColorRef(Color c) => c.R | (c.G << 8) | (c.B << 16);

    private static void Set(IntPtr hwnd, int attr, int value) =>
        _ = DwmSetWindowAttribute(hwnd, attr, ref value, sizeof(int));
}
