using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;

namespace A2BCopyTray;

/// <summary>托盘图标要表达的三种状态。</summary>
internal enum TrayState
{
    Ok,
    Paused,
    Error
}

/// <summary>
/// 托盘状态图标：纯几何绘制（圆底 + 对勾 / 暂停条 / 叉）。
///
/// 早先版本用 Arial 画 "✓ ⏸ ✕" 文本，但 Arial 并不含 ⏸（U+23F8），
/// 实际靠字体回退凑出来，16px 下笔画糊且有时整个变方框。改成矢量绘制后
/// 各尺寸都清晰，也不再依赖本机装了哪些字体。
/// </summary>
internal static class StatusIcons
{
    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool DestroyIcon(IntPtr hIcon);

    public static readonly Color OkColor = Color.FromArgb(46, 125, 50);
    public static readonly Color PausedColor = Color.FromArgb(230, 126, 34);
    public static readonly Color ErrorColor = Color.FromArgb(198, 40, 40);

    public static Color ColorOf(TrayState state) => state switch
    {
        TrayState.Paused => PausedColor,
        TrayState.Error => ErrorColor,
        _ => OkColor
    };

    /// <summary>生成托盘图标。调用方负责 Dispose。</summary>
    public static Icon Create(TrayState state, int size = 32) => BitmapToIcon(Render(state, size));

    /// <summary>渲染成位图（也用于预览 / 菜单项图标）。</summary>
    public static Bitmap Render(TrayState state, int size = 32)
    {
        var bmp = new Bitmap(size, size, PixelFormat.Format32bppArgb);
        using var g = Graphics.FromImage(bmp);
        g.SmoothingMode = SmoothingMode.AntiAlias;
        g.Clear(Color.Transparent);

        // 圆底留 1px 余量，避免抗锯齿被裁掉
        var pad = Math.Max(1f, size * 0.04f);
        using (var brush = new SolidBrush(ColorOf(state)))
            g.FillEllipse(brush, pad, pad, size - pad * 2 - 1, size - pad * 2 - 1);

        var stroke = Math.Max(1.6f, size * 0.13f);
        using var pen = new Pen(Color.White, stroke)
        {
            StartCap = LineCap.Round,
            EndCap = LineCap.Round,
            LineJoin = LineJoin.Round
        };

        float P(float t) => size * t;   // 归一化坐标 → 像素

        switch (state)
        {
            case TrayState.Paused:
                // 两条竖杠
                var barW = Math.Max(1.6f, size * 0.11f);
                var barH = size * 0.40f;
                var top = (size - barH) / 2f;
                using (var bar = new SolidBrush(Color.White))
                {
                    g.FillRectangle(bar, P(0.345f) - barW / 2, top, barW, barH);
                    g.FillRectangle(bar, P(0.655f) - barW / 2, top, barW, barH);
                }
                break;

            case TrayState.Error:
                g.DrawLine(pen, P(0.34f), P(0.34f), P(0.66f), P(0.66f));
                g.DrawLine(pen, P(0.66f), P(0.34f), P(0.34f), P(0.66f));
                break;

            default:
                g.DrawLines(pen,
                [
                    new PointF(P(0.29f), P(0.52f)),
                    new PointF(P(0.44f), P(0.67f)),
                    new PointF(P(0.72f), P(0.35f))
                ]);
                break;
        }

        return bmp;
    }

    private static Icon BitmapToIcon(Bitmap bmp)
    {
        var hIcon = bmp.GetHicon();
        try
        {
            using var tmp = Icon.FromHandle(hIcon);
            return (Icon)tmp.Clone();
        }
        finally
        {
            // Icon.FromHandle 不接管句柄所有权，不销毁就会每次泄漏一个 GDI 图标句柄
            _ = DestroyIcon(hIcon);
        }
    }
}
