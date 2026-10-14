using System.Drawing.Drawing2D;
using System.Drawing.Text;

namespace A2BCopyTray;

/// <summary>
/// 按钮 / 菜单用的矢量图标字形。
/// 用系统自带的图标字体（Win11 是 Segoe Fluent Icons，Win10 是 Segoe MDL2 Assets），
/// 不引入任何图片资源；字体不存在时 <see cref="Available"/> 为 false，调用方自动退回纯文字。
/// </summary>
internal static class UiGlyphs
{
    private static readonly string? FamilyName = Pick(
        "Segoe Fluent Icons", "Segoe MDL2 Assets", "Segoe UI Symbol");

    public static bool Available => FamilyName is not null;

    public static Font Font(float size) =>
        new(FamilyName ?? "Segoe UI", size, FontStyle.Regular, GraphicsUnit.Point);

    /// <summary>按像素指定字号 —— 画按钮图标时比 pt 更好控制视觉高度。</summary>
    public static Font FontPx(float px) =>
        new(FamilyName ?? "Segoe UI", px, FontStyle.Regular, GraphicsUnit.Pixel);

    // —— 字形码位（Fluent Icons 与 MDL2 在这些码位上保持一致）——
    public const string Sync = "\uE895";
    public const string Settings = "\uE713";
    public const string Play = "\uE768";
    public const string Pause = "\uE769";
    public const string Download = "\uE896";
    public const string Save = "\uE74E";
    public const string Folder = "\uE8B7";
    public const string Copy = "\uE8C8";
    public const string Delete = "\uE74D";
    public const string Check = "\uE73E";
    public const string Refresh = "\uE72C";
    public const string Info = "\uE946";
    public const string Clear = "\uE894";
    public const string Monitor = "\uE7F4";
    public const string OpenInNewWindow = "\uE8A7";
    public const string Power = "\uE7E8";

    /// <summary>把字形画成位图（托盘菜单项、MessageBox 之类需要 Image 的地方用）。</summary>
    public static Bitmap? Bitmap(string glyph, int size, Color color)
    {
        if (!Available) return null;
        var bmp = new Bitmap(size, size, System.Drawing.Imaging.PixelFormat.Format32bppArgb);
        using var g = Graphics.FromImage(bmp);
        g.SmoothingMode = SmoothingMode.AntiAlias;
        g.TextRenderingHint = TextRenderingHint.AntiAliasGridFit;
        g.Clear(Color.Transparent);

        // 图标字体是等宽方框设计，字号取边长的 0.72 倍视觉上刚好填满
        using var font = Font(size * 0.72f);
        using var brush = new SolidBrush(color);
        using var fmt = new StringFormat
        {
            Alignment = StringAlignment.Center,
            LineAlignment = StringAlignment.Center,
            FormatFlags = StringFormatFlags.NoClip
        };
        // 略下移 0.5px，抵消 GDI+ 图标字体常见的光学偏上
        g.DrawString(glyph, font, brush, new RectangleF(0, 0.5f, size, size), fmt);
        return bmp;
    }

    private static string? Pick(params string[] candidates)
    {
        try
        {
            using var installed = new InstalledFontCollection();
            var names = installed.Families
                .Select(f => f.Name)
                .ToHashSet(StringComparer.OrdinalIgnoreCase);
            foreach (var c in candidates)
                if (names.Contains(c)) return c;
        }
        catch { /* ignore */ }
        return null;
    }
}
