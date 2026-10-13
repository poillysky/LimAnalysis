using System.Drawing.Drawing2D;

namespace A2BCopyTray;

/// <summary>白底圆角 + 1px 描边的卡面。子控件请显式给白底。</summary>
internal sealed class CardSurface : Panel
{
    public CardSurface()
    {
        SetStyle(ControlStyles.AllPaintingInWmPaint
               | ControlStyles.OptimizedDoubleBuffer
               | ControlStyles.UserPaint
               | ControlStyles.ResizeRedraw, true);
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        var g = e.Graphics;
        g.SmoothingMode = SmoothingMode.AntiAlias;
        var r = new Rectangle(0, 0, Width - 1, Height - 1);
        if (r.Width <= 0 || r.Height <= 0) return;

        // 极轻的投影：比描边再淡一档，卡片才像"浮"在灰底上而不是贴上去的
        using (var shadow = UiTheme.RoundedRect(new Rectangle(r.X, r.Y + 1, r.Width, r.Height), UiTheme.CardRadius))
        using (var sb = new SolidBrush(UiTheme.CardShadow))
            g.FillPath(sb, shadow);

        using var path = UiTheme.RoundedRect(r, UiTheme.CardRadius);
        using (var fill = new SolidBrush(UiTheme.PanelBg))
            g.FillPath(fill, path);
        using (var pen = new Pen(UiTheme.Border, 1f))
            g.DrawPath(pen, path);
    }
}

/// <summary>
/// 扁平圆角按钮（保留 Button 的点击 / 键盘 / DialogResult 行为）。
/// 支持左侧矢量图标字形（<see cref="Glyph"/>），字体不存在时自动只画文字。
/// </summary>
internal sealed class FlatButton : Button
{
    public Color Bg = UiTheme.PanelBg;
    public Color HoverBg = UiTheme.NeutralHover;
    public Color DownBg = UiTheme.NeutralDown;
    public Color BorderColor = UiTheme.Border;
    public bool ShowBorder;

    /// <summary>图标字形（取 <see cref="UiGlyphs"/> 常量），空串表示无图标。</summary>
    public string Glyph = "";

    /// <summary>字形像素高度。</summary>
    public float GlyphPx = 15f;

    /// <summary>图标与文字之间的间距。</summary>
    public int Gap = 7;

    private bool _hover;
    private bool _down;

    public FlatButton()
    {
        SetStyle(ControlStyles.UserPaint
               | ControlStyles.AllPaintingInWmPaint
               | ControlStyles.OptimizedDoubleBuffer
               | ControlStyles.ResizeRedraw, true);

        FlatStyle = FlatStyle.Flat;
        FlatAppearance.BorderSize = 0;
        UseVisualStyleBackColor = false;
        Cursor = Cursors.Hand;
        Font = UiTheme.UiFont();
        Size = new Size(UiTheme.BtnWidth, UiTheme.BtnHeight);
        Margin = new Padding(0);
        TabStop = true;
    }

    protected override void OnMouseEnter(EventArgs e) { _hover = true; Invalidate(); base.OnMouseEnter(e); }
    protected override void OnMouseLeave(EventArgs e) { _hover = false; _down = false; Invalidate(); base.OnMouseLeave(e); }
    protected override void OnMouseDown(MouseEventArgs mevent) { _down = true; Invalidate(); base.OnMouseDown(mevent); }
    protected override void OnMouseUp(MouseEventArgs mevent) { _down = false; Invalidate(); base.OnMouseUp(mevent); }
    protected override void OnEnabledChanged(EventArgs e) { Invalidate(); base.OnEnabledChanged(e); }
    protected override void OnGotFocus(EventArgs e) { Invalidate(); base.OnGotFocus(e); }
    protected override void OnLostFocus(EventArgs e) { Invalidate(); base.OnLostFocus(e); }
    protected override void OnTextChanged(EventArgs e) { Invalidate(); base.OnTextChanged(e); }

    protected override void OnPaint(PaintEventArgs pevent)
    {
        var g = pevent.Graphics;
        g.SmoothingMode = SmoothingMode.AntiAlias;
        g.Clear(Parent?.BackColor ?? UiTheme.WindowBg);

        var r = new Rectangle(0, 0, Width - 1, Height - 1);
        if (r.Width <= 0 || r.Height <= 0) return;

        var bg = !Enabled ? UiTheme.NeutralDown
               : _down ? DownBg
               : _hover ? HoverBg
               : Bg;

        using (var path = UiTheme.RoundedRect(r, UiTheme.BtnRadius))
        {
            using (var b = new SolidBrush(bg))
                g.FillPath(b, path);
            if (ShowBorder)
            {
                using var pen = new Pen(BorderColor, 1f);
                g.DrawPath(pen, path);
            }
        }

        var fg = Enabled ? ForeColor : UiTheme.TextMuted;
        DrawContent(g, fg);

        if (Focused && ShowFocusCues)
        {
            var inner = Rectangle.Inflate(r, -4, -4);
            using var fp = UiTheme.RoundedRect(inner, Math.Max(2, UiTheme.BtnRadius - 3));
            using var fpen = new Pen(Color.FromArgb(120, ForeColor), 1f) { DashStyle = DashStyle.Dot };
            g.DrawPath(fpen, fp);
        }
    }

    /// <summary>图标 + 文字整体居中。文字为自动省略，避免窄按钮被撑破。</summary>
    private void DrawContent(Graphics g, Color fg)
    {
        const TextFormatFlags baseFlags =
            TextFormatFlags.NoPadding | TextFormatFlags.SingleLine | TextFormatFlags.VerticalCenter;

        var useGlyph = !string.IsNullOrEmpty(Glyph) && UiGlyphs.Available;
        var textW = Text.Length == 0
            ? 0
            : TextRenderer.MeasureText(Text, Font, new Size(int.MaxValue, int.MaxValue),
                baseFlags | TextFormatFlags.Left).Width;
        var glyphW = useGlyph ? (int)Math.Ceiling(GlyphPx) + 2 : 0;
        var gap = useGlyph && textW > 0 ? Gap : 0;

        var total = glyphW + gap + textW;
        var x = Math.Max(1, (Width - total) / 2);

        if (useGlyph)
        {
            using var gf = UiGlyphs.FontPx(GlyphPx);
            TextRenderer.DrawText(g, Glyph, gf, new Rectangle(x, 0, glyphW, Height), fg,
                baseFlags | TextFormatFlags.HorizontalCenter);
            x += glyphW + gap;
        }

        if (textW > 0)
        {
            TextRenderer.DrawText(g, Text, Font,
                new Rectangle(x, 0, Math.Max(1, Width - x - 1), Height),
                fg, baseFlags | TextFormatFlags.Left | TextFormatFlags.EndEllipsis);
        }
    }

    /// <summary>图标 + 文字的期望宽度（给自动宽度布局用）。</summary>
    public int PreferredContentWidth()
    {
        var useGlyph = !string.IsNullOrEmpty(Glyph) && UiGlyphs.Available;
        var textW = TextRenderer.MeasureText(Text, Font, new Size(int.MaxValue, int.MaxValue),
            TextFormatFlags.NoPadding | TextFormatFlags.SingleLine).Width;
        var glyphW = useGlyph ? (int)Math.Ceiling(GlyphPx) + 2 : 0;
        var gap = useGlyph && textW > 0 ? Gap : 0;
        return glyphW + gap + textW + 32;   // 左右各留 16px
    }
}

/// <summary>
/// 胶囊状态徽标（自绘圆角底 + 左侧状态圆点 + 居中文字）。
/// <see cref="Pulse"/> 打开时圆点呼吸，用来表达"正在运行"。
/// </summary>
internal sealed class PillLabel : Control
{
    private Color _fill = UiTheme.Success;
    private bool _pulse;
    private float _phase;
    private readonly System.Windows.Forms.Timer _timer;

    public Color Fill
    {
        get => _fill;
        set { _fill = value; Invalidate(); }
    }

    /// <summary>是否显示左侧状态圆点。</summary>
    public bool Indicator { get; set; } = true;

    /// <summary>圆点是否呼吸（同步中）。</summary>
    public bool Pulse
    {
        get => _pulse;
        set
        {
            if (_pulse == value) return;
            _pulse = value;
            if (value) { _phase = 0f; _timer.Start(); }
            else _timer.Stop();
            Invalidate();
        }
    }

    public PillLabel()
    {
        SetStyle(ControlStyles.UserPaint
               | ControlStyles.AllPaintingInWmPaint
               | ControlStyles.OptimizedDoubleBuffer
               | ControlStyles.ResizeRedraw, true);
        SetStyle(ControlStyles.Selectable, false);
        Font = UiTheme.UiFont(9f, FontStyle.Bold);
        ForeColor = Color.White;
        TabStop = false;
        Height = 26;
        Size = new Size(76, 26);

        _timer = new System.Windows.Forms.Timer { Interval = 45 };
        _timer.Tick += (_, _) =>
        {
            _phase += 0.09f;
            if (Visible && IsHandleCreated) Invalidate();
        };
    }

    protected override void OnTextChanged(EventArgs e) { base.OnTextChanged(e); Resize_(); }
    protected override void OnFontChanged(EventArgs e) { base.OnFontChanged(e); Resize_(); }

    private void Resize_()
    {
        var textW = TextRenderer.MeasureText(Text, Font, new Size(int.MaxValue, int.MaxValue),
            TextFormatFlags.NoPadding | TextFormatFlags.SingleLine).Width;
        var dot = Indicator ? DotDiameter + DotGap : 0;
        var w = textW + dot + PadX * 2;
        if (w != Width) Width = w;
        Invalidate();
    }

    private const int PadX = 14;
    private const int DotDiameter = 7;
    private const int DotGap = 7;

    protected override void OnPaint(PaintEventArgs e)
    {
        var g = e.Graphics;
        g.SmoothingMode = SmoothingMode.AntiAlias;
        g.Clear(Parent?.BackColor ?? UiTheme.HeaderBg);

        var r = new Rectangle(0, 0, Width - 1, Height - 1);
        if (r.Width <= 0 || r.Height <= 0) return;

        using (var path = UiTheme.RoundedRect(r, (Height - 1) / 2))
        using (var b = new SolidBrush(_fill))
            g.FillPath(b, path);

        var x = PadX;
        if (Indicator)
        {
            // 呼吸：0.45 ~ 1.0 的白色不透明度
            var alpha = _pulse
                ? 0.45f + 0.55f * (0.5f + 0.5f * MathF.Sin(_phase))
                : 1f;
            using var dot = new SolidBrush(Color.FromArgb((int)(alpha * 255), 255, 255, 255));
            g.FillEllipse(dot, x, (Height - DotDiameter) / 2f, DotDiameter, DotDiameter);
            x += DotDiameter + DotGap;
        }

        TextRenderer.DrawText(g, Text, Font,
            new Rectangle(x, 0, Math.Max(1, Width - x - PadX), Height), ForeColor,
            TextFormatFlags.Left | TextFormatFlags.VerticalCenter
            | TextFormatFlags.NoPadding | TextFormatFlags.EndEllipsis);
    }

    protected override void OnVisibleChanged(EventArgs e)
    {
        base.OnVisibleChanged(e);
        if (!Visible) _timer.Stop();
        else if (_pulse) _timer.Start();
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing) _timer.Dispose();
        base.Dispose(disposing);
    }
}

/// <summary>
/// 只读的「可点击文字」：平时是普通文字，悬停变主题蓝并加下划线，点击触发动作。
/// 用来把路径、目录这类文本变成入口（点了在资源管理器里打开）。
/// </summary>
internal sealed class LinkText : Control
{
    private bool _hover;
    private Font? _underline;

    public Color HoverColor = UiTheme.Accent;

    public LinkText()
    {
        SetStyle(ControlStyles.UserPaint
               | ControlStyles.AllPaintingInWmPaint
               | ControlStyles.OptimizedDoubleBuffer
               | ControlStyles.ResizeRedraw, true);
        SetStyle(ControlStyles.Selectable, false);
        Cursor = Cursors.Hand;
        TabStop = false;
        Height = 22;
    }

    protected override void OnMouseEnter(EventArgs e) { _hover = true; Invalidate(); base.OnMouseEnter(e); }
    protected override void OnMouseLeave(EventArgs e) { _hover = false; Invalidate(); base.OnMouseLeave(e); }
    protected override void OnTextChanged(EventArgs e) { Invalidate(); base.OnTextChanged(e); }

    protected override void OnFontChanged(EventArgs e)
    {
        base.OnFontChanged(e);
        _underline?.Dispose();
        _underline = null;
        Invalidate();
    }

    private Font Underline => _underline ??= new Font(Font, Font.Style | FontStyle.Underline);

    protected override void OnPaint(PaintEventArgs e)
    {
        var g = e.Graphics;
        g.Clear(Parent?.BackColor ?? UiTheme.PanelBg);
        var color = _hover ? HoverColor : ForeColor;
        TextRenderer.DrawText(g, Text, _hover ? Underline : Font, ClientRectangle, color,
            TextFormatFlags.Left | TextFormatFlags.VerticalCenter
            | TextFormatFlags.NoPadding | TextFormatFlags.EndEllipsis
            | TextFormatFlags.PathEllipsis);
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing) _underline?.Dispose();
        base.Dispose(disposing);
    }
}

/// <summary>圆角进度条（连续 + 不定态滑动）。</summary>
internal sealed class FlatProgressBar : Control
{
    private int _max = 100;
    private int _value;
    private bool _marquee;
    private float _phase;
    private readonly System.Windows.Forms.Timer _timer;

    public FlatProgressBar()
    {
        SetStyle(ControlStyles.UserPaint
               | ControlStyles.AllPaintingInWmPaint
               | ControlStyles.OptimizedDoubleBuffer
               | ControlStyles.ResizeRedraw, true);
        SetStyle(ControlStyles.Selectable, false);
        Height = 10;
        TabStop = false;

        _timer = new System.Windows.Forms.Timer { Interval = 16 };
        _timer.Tick += (_, _) =>
        {
            _phase += 0.018f;
            if (_phase > 1.6f) _phase = -0.3f;
            if (Visible && IsHandleCreated) Invalidate();
        };
    }

    public int Max
    {
        get => _max;
        set { _max = Math.Max(1, value); Invalidate(); }
    }

    public int Value
    {
        get => _value;
        set
        {
            var v = Math.Clamp(value, 0, _max);
            if (v == _value) return;
            _value = v;
            Invalidate();
        }
    }

    public bool Marquee
    {
        get => _marquee;
        set
        {
            if (_marquee == value) return;
            _marquee = value;
            if (value) { _timer.Start(); _phase = -0.3f; }
            else _timer.Stop();
            Invalidate();
        }
    }

    protected override void OnVisibleChanged(EventArgs e)
    {
        base.OnVisibleChanged(e);
        if (!Visible) _timer.Stop();
        else if (_marquee) _timer.Start();
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing) _timer.Dispose();
        base.Dispose(disposing);
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        var g = e.Graphics;
        g.SmoothingMode = SmoothingMode.AntiAlias;
        g.Clear(Parent?.BackColor ?? UiTheme.WindowBg);

        var r = new Rectangle(0, 0, Width - 1, Height - 1);
        if (r.Width <= 0 || r.Height <= 0) return;

        var radius = Math.Max(2, Height / 2);
        using (var track = UiTheme.RoundedRect(r, radius))
        using (var tb = new SolidBrush(UiTheme.TrackBg))
            g.FillPath(tb, track);

        if (_marquee)
        {
            var blockW = Math.Max(Height * 3, r.Width / 5);
            var span = r.Width + blockW;
            var x = (int)(_phase * span) - blockW;
            var clip = Rectangle.Intersect(r, new Rectangle(x, r.Y, blockW, r.Height));
            if (clip.Width > 0)
            {
                using var slice = UiTheme.RoundedRect(clip, Math.Min(radius, clip.Height / 2));
                using var mb = new SolidBrush(UiTheme.Accent);
                g.FillPath(mb, slice);
            }
            return;
        }

        if (_value <= 0) return;

        var done = (int)Math.Round(r.Width * (_value / (double)_max));
        done = Math.Clamp(done, Height, r.Width);
        var fillRect = new Rectangle(r.X, r.Y, done, r.Height);
        using (var fp = UiTheme.RoundedRect(fillRect, radius))
        using (var fb = new SolidBrush(_value >= _max ? UiTheme.Success : UiTheme.Accent))
            g.FillPath(fb, fp);
    }
}

/// <summary>深色标题栏：底部 3px 强调色。</summary>
internal sealed class HeaderBar : Panel
{
    public const int AccentStripHeight = 3;

    public HeaderBar()
    {
        SetStyle(ControlStyles.AllPaintingInWmPaint
               | ControlStyles.OptimizedDoubleBuffer
               | ControlStyles.UserPaint
               | ControlStyles.ResizeRedraw, true);
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        var g = e.Graphics;
        using (var b = new SolidBrush(UiTheme.HeaderBg))
            g.FillRectangle(b, ClientRectangle);

        // 顶部一道极淡的高光，让深色 header 不至于死板
        using (var hl = new SolidBrush(Color.FromArgb(12, 255, 255, 255)))
            g.FillRectangle(hl, 0, 0, Width, 1);

        using var accent = new SolidBrush(UiTheme.Accent);
        g.FillRectangle(accent, 0, Height - AccentStripHeight, Width, AccentStripHeight);
    }
}

/// <summary>托盘右键菜单配色：去默认蓝渐变，改浅灰悬停 + 主题文字色。</summary>
internal sealed class FlatMenuColors : ProfessionalColorTable
{
    public override Color MenuBorder => UiTheme.Border;
    public override Color MenuItemBorder => UiTheme.NeutralHover;
    public override Color MenuItemSelected => UiTheme.NeutralHover;
    public override Color MenuItemSelectedGradientBegin => UiTheme.NeutralHover;
    public override Color MenuItemSelectedGradientEnd => UiTheme.NeutralHover;
    public override Color MenuItemPressedGradientBegin => UiTheme.NeutralHover;
    public override Color MenuItemPressedGradientEnd => UiTheme.NeutralHover;
    public override Color ToolStripDropDownBackground => UiTheme.PanelBg;
    public override Color ImageMarginGradientBegin => UiTheme.PanelBg;
    public override Color ImageMarginGradientMiddle => UiTheme.PanelBg;
    public override Color ImageMarginGradientEnd => UiTheme.PanelBg;
    public override Color SeparatorDark => UiTheme.Border;
    public override Color SeparatorLight => UiTheme.PanelBg;
}

internal sealed class FlatMenuRenderer : ToolStripProfessionalRenderer
{
    public FlatMenuRenderer() : base(new FlatMenuColors()) => RoundedEdges = false;

    protected override void OnRenderItemText(ToolStripItemTextRenderEventArgs e)
    {
        e.TextColor = e.Item.Enabled ? UiTheme.TextPrimary : UiTheme.TextMuted;
        base.OnRenderItemText(e);
    }
}
