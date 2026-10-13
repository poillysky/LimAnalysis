using System.Drawing.Drawing2D;

namespace A2BCopyTray;

internal static class UiTheme
{
    // —— 度量 ——
    public const int ContentPad = 12;   // 窗外到白卡
    public const int LabelCol = 112;    // 标签列宽
    public const int RowH = 36;         // 常规行高
    public const int StatusRowH = 28;   // 主界面状态行高
    public const int CtrlHeight = 28;   // 输入控件设计高度
    public const int BtnHeight = 34;
    public const int BtnWidth = 98;
    public const int SectionGap = 14;   // 卡片之间
    public const int CardPad = 18;      // 卡内边距
    public const int TitleH = 24;       // 卡片标题
    public const int TitleGap = 8;      // 标题 → 分隔线
    public const int RuleH = 1;
    public const int RuleGap = 9;       // 分隔线 → 内容
    public const int BrowseW = 76;
    public const int TestW = 64;
    public const int CardRadius = 8;
    public const int BtnRadius = 7;

    /// <summary>卡片正文上边界（相对卡面）。</summary>
    public const int CardBodyTop = CardPad + TitleH + TitleGap + RuleH + RuleGap;

    // —— 颜色 ——
    public static readonly Color WindowBg = Color.FromArgb(243, 245, 248);
    public static readonly Color PanelBg = Color.White;
    public static readonly Color Border = Color.FromArgb(224, 229, 236);
    public static readonly Color TextPrimary = Color.FromArgb(30, 34, 40);
    public static readonly Color TextMuted = Color.FromArgb(104, 114, 126);
    public static readonly Color Accent = Color.FromArgb(25, 118, 210);
    public static readonly Color AccentHover = Color.FromArgb(23, 106, 190);
    public static readonly Color AccentDown = Color.FromArgb(17, 88, 158);
    public static readonly Color NeutralHover = Color.FromArgb(240, 244, 249);
    public static readonly Color NeutralDown = Color.FromArgb(228, 234, 242);
    public static readonly Color Success = Color.FromArgb(46, 125, 50);
    public static readonly Color Warning = Color.FromArgb(230, 126, 34);
    public static readonly Color Danger = Color.FromArgb(198, 40, 40);
    public static readonly Color HeaderBg = Color.FromArgb(36, 48, 66);
    public static readonly Color FooterBg = Color.FromArgb(250, 251, 253);
    public static readonly Color TrackBg = Color.FromArgb(231, 236, 243);
    public static readonly Color Rule = Color.FromArgb(237, 240, 245);
    /// <summary>卡片投影（比描边更淡，只用来把卡片从灰底上"托"起来）。</summary>
    public static readonly Color CardShadow = Color.FromArgb(18, 30, 48, 80);
    /// <summary>日志：同步成功行。</summary>
    public static readonly Color LogSync = Color.FromArgb(21, 101, 192);
    /// <summary>日志：时间戳等次要信息。</summary>
    public static readonly Color LogTime = Color.FromArgb(150, 160, 172);

    /// <summary>按日志行前缀的 [级别] 决定文字颜色。</summary>
    public static Color LogColor(string line)
    {
        if (line.Contains("[错误]", StringComparison.Ordinal)) return Danger;
        if (line.Contains("[警告]", StringComparison.Ordinal)) return Warning;
        if (line.Contains("[同步]", StringComparison.Ordinal)) return LogSync;
        return TextPrimary;
    }

    public static Font UiFont(float size = 9f, FontStyle style = FontStyle.Regular) =>
        new("Microsoft YaHei UI", size, style);

    public static Font MonoFont(float size = 9f) =>
        new("Consolas", size, FontStyle.Regular);

    public static void StyleForm(Form form)
    {
        form.BackColor = WindowBg;
        form.Font = UiFont();
        form.ForeColor = TextPrimary;
        // Font 缩放比 Dpi 更稳，避免绝对行高被二次拉伸导致裁切
        form.AutoScaleMode = AutoScaleMode.Font;
    }

    public static GraphicsPath RoundedRect(Rectangle r, int radius)
    {
        var path = new GraphicsPath();
        if (r.Width <= 0 || r.Height <= 0)
        {
            path.AddRectangle(r);
            return path;
        }
        var d = Math.Max(2, radius * 2);
        if (r.Width <= d || r.Height <= d)
        {
            d = Math.Min(r.Width, r.Height) - 1;
            if (d < 2) { path.AddRectangle(r); return path; }
        }
        path.AddArc(r.X, r.Y, d, d, 180, 90);
        path.AddArc(r.Right - d - 1, r.Y, d, d, 270, 90);
        path.AddArc(r.Right - d - 1, r.Bottom - d - 1, d, d, 0, 90);
        path.AddArc(r.X, r.Bottom - d - 1, d, d, 90, 90);
        path.CloseFigure();
        return path;
    }

    // —— 卡片 ——

    /// <summary>卡片外框高度（含 1px 描边，不含卡片间距）。</summary>
    public static int CardOuterHeight(int bodyHeight) =>
        CardPad + TitleH + TitleGap + RuleH + RuleGap + bodyHeight + CardPad + 2;

    /// <summary>
    /// 白底圆角描边卡片。标题 + 细分隔线 + 正文区（正文区高度固定，内部按绝对坐标摆放）。
    /// 子控件显式给白底，避免叠在自绘面板上出现透明底噪点。
    /// </summary>
    public static Panel SectionCard(string title, int bodyRowsHeight, out Panel bodyHost)
    {
        var outer = CardOuterHeight(bodyRowsHeight);
        var wrap = new Panel
        {
            Height = outer + SectionGap,
            Margin = new Padding(0),
            // 下内边距吃掉 SectionGap，卡面本身才是 outer 高，卡片之间才有间隙
            Padding = new Padding(0, 0, 0, SectionGap),
            BackColor = WindowBg
        };

        var card = new CardSurface { Dock = DockStyle.Fill };

        var titleLbl = new Label
        {
            Text = title,
            Font = UiFont(9.5f, FontStyle.Bold),
            ForeColor = TextPrimary,
            BackColor = PanelBg,
            AutoSize = false,
            TextAlign = ContentAlignment.MiddleLeft
        };
        var rule = new Panel { BackColor = Rule, Height = RuleH, Width = 10 };
        var body = new Panel
        {
            Margin = new Padding(0),
            BackColor = PanelBg,
            Size = new Size(10, bodyRowsHeight)
        };
        bodyHost = body;

        card.Controls.Add(titleLbl);
        card.Controls.Add(rule);
        card.Controls.Add(body);
        wrap.Controls.Add(card);

        AttachCardScaffold(card, titleLbl, rule, body, bodyRowsHeight);
        return wrap;
    }

    /// <summary>
    /// 把「标题 / 分隔线 / 正文」贴到卡面里。bodyHeight &gt; 0 用固定高度，
    /// 传 0 则正文撑满卡面剩余高度。
    /// </summary>
    public static void AttachCardScaffold(Control card, Label title, Panel rule, Control body, int bodyHeight)
    {
        void Layout()
        {
            var w = Math.Max(60, card.ClientSize.Width - CardPad * 2);
            title.SetBounds(CardPad, CardPad, w, TitleH);
            rule.SetBounds(CardPad, CardPad + TitleH + TitleGap, w, RuleH);
            var h = bodyHeight > 0
                ? bodyHeight
                : Math.Max(0, card.ClientSize.Height - CardBodyTop - CardPad);
            body.SetBounds(CardPad, CardBodyTop, w, h);
        }

        card.Resize += (_, _) => Layout();
        card.HandleCreated += (_, _) => Layout();
        Layout();
    }

    /// <summary>
    /// 深色标题栏：标题 + 副标题 +（可选）右侧控件，底部 3px 强调条。
    /// 两个窗口共用，保证视觉一致。
    /// </summary>
    public static Control BuildHeader(string title, string subtitle, Control? right = null)
    {
        var bar = new HeaderBar
        {
            Dock = DockStyle.Fill,
            Margin = new Padding(0),
            // 底部让出强调条高度，标题内容才真正居中于「去条」后的区域
            Padding = new Padding(0, 0, 0, HeaderBar.AccentStripHeight)
        };

        var tlp = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 3,
            RowCount = 1,
            BackColor = HeaderBg,
            Padding = new Padding(18, 0, 18, 0),
            Margin = new Padding(0)
        };
        tlp.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        tlp.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
        tlp.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        tlp.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));

        var titleLbl = new Label
        {
            Text = title,
            ForeColor = Color.White,
            Font = UiFont(12.5f, FontStyle.Bold),
            AutoSize = true,
            Anchor = AnchorStyles.Left,
            TextAlign = ContentAlignment.MiddleLeft,
            BackColor = HeaderBg,
            Margin = new Padding(0, 0, 14, 0)
        };
        var subLbl = new Label
        {
            Text = subtitle,
            ForeColor = Color.FromArgb(158, 172, 190),
            Font = UiFont(8.5f),
            AutoSize = true,
            Anchor = AnchorStyles.Left,
            TextAlign = ContentAlignment.MiddleLeft,
            BackColor = HeaderBg,
            Margin = new Padding(0)
        };

        tlp.Controls.Add(titleLbl, 0, 0);
        tlp.Controls.Add(subLbl, 1, 0);
        if (right is not null)
        {
            right.Anchor = AnchorStyles.Right;
            right.Margin = new Padding(0);
            tlp.Controls.Add(right, 2, 0);
        }

        bar.Controls.Add(tlp);
        return bar;
    }

    /// <summary>卡片标题行（供自绘卡片复用）。</summary>
    public static (Label Title, Panel Rule) CardHeader(string text)
    {
        var title = new Label
        {
            Text = text,
            Font = UiFont(9.5f, FontStyle.Bold),
            ForeColor = TextPrimary,
            BackColor = PanelBg,
            AutoSize = false,
            TextAlign = ContentAlignment.MiddleLeft
        };
        var rule = new Panel { BackColor = Rule, Height = RuleH, Width = 10 };
        return (title, rule);
    }

    // —— 控件尺寸 ——

    /// <summary>
    /// 控件的真实渲染高度。单行 TextBox / NumericUpDown / ComboBox 的高度由字体决定，
    /// 硬按 CtrlHeight 居中会整体偏高 2~3px —— 布局一律走这里取高度。
    /// </summary>
    public static int PreferredHeight(Control c) => c switch
    {
        TextBox t when !t.Multiline => t.PreferredHeight,
        NumericUpDown n => n.PreferredHeight,
        ComboBox cb => cb.PreferredHeight,
        _ => c.Height
    };

    // —— 按钮 ——

    public static Button PrimaryButton(string text, string glyph = "") => new FlatButton
    {
        Text = text,
        Glyph = glyph,
        Bg = Accent,
        ForeColor = Color.White,
        HoverBg = AccentHover,
        DownBg = AccentDown,
        ShowBorder = false
    };

    public static Button SecondaryButton(string text, string glyph = "") => new FlatButton
    {
        Text = text,
        Glyph = glyph,
        Bg = PanelBg,
        ForeColor = TextPrimary,
        HoverBg = NeutralHover,
        DownBg = NeutralDown,
        ShowBorder = true,
        BorderColor = Border
    };

    /// <summary>无边框的小图标按钮（用于卡片标题行这类次要操作）。</summary>
    public static Button IconButton(string glyph, string tooltip)
    {
        var b = new FlatButton
        {
            Text = "",
            Glyph = glyph,
            GlyphPx = 16f,
            Bg = PanelBg,
            ForeColor = TextMuted,
            HoverBg = NeutralHover,
            DownBg = NeutralDown,
            ShowBorder = false,
            Size = new Size(30, 26),
            Cursor = Cursors.Hand
        };
        var tip = new ToolTip { InitialDelay = 350, ReshowDelay = 200 };
        tip.SetToolTip(b, tooltip);
        b.Disposed += (_, _) => tip.Dispose();
        return b;
    }

    // —— 行布局 ——

    public static Label FieldLabel(string text) => new()
    {
        Text = text,
        AutoSize = false,
        Size = new Size(LabelCol, RowH),
        TextAlign = ContentAlignment.MiddleLeft,
        ForeColor = TextMuted,
        BackColor = PanelBg,
        Font = UiFont(),
        Margin = new Padding(0),
        Padding = new Padding(0)
    };

    public static TextBox TextField(string text = "") => new()
    {
        Text = text,
        Font = UiFont(),
        Height = CtrlHeight,
        Margin = new Padding(0),
        Anchor = AnchorStyles.Left | AnchorStyles.Right | AnchorStyles.Top
    };

    /// <summary>
    /// 只读展示框：用于「自动派生、不允许手工填写」的字段。
    /// 保留 TextBox 的外观与可选中复制能力，但用浅底 + 不可编辑表明它是算出来的。
    /// </summary>
    public static TextBox ReadOnlyField(string text = "") => new()
    {
        Text = text,
        Font = UiFont(),
        Height = CtrlHeight,
        Margin = new Padding(0),
        Anchor = AnchorStyles.Left | AnchorStyles.Right | AnchorStyles.Top,
        ReadOnly = true,
        TabStop = false,
        BackColor = TrackBg,
        ForeColor = TextPrimary
    };

    public static NumericUpDown NumField(decimal value, decimal min, decimal max, decimal increment = 1)
    {
        return new NumericUpDown
        {
            Minimum = min,
            Maximum = max,
            Increment = increment,
            DecimalPlaces = increment < 1 ? 1 : 0,
            Value = Math.Min(max, Math.Max(min, value)),
            Font = UiFont(),
            Height = CtrlHeight,
            Width = 120,
            Margin = new Padding(0),
            Anchor = AnchorStyles.Left | AnchorStyles.Top
        };
    }

    /// <summary>在 body 里放一行：左标签 + 右控件，控件按真实高度垂直居中。</summary>
    public static void PlaceRow(Panel body, int y, string label, Control editor, int rowH = RowH)
    {
        var lbl = FieldLabel(label);
        lbl.Location = new Point(0, y);
        lbl.Size = new Size(LabelCol, rowH);

        var autoW = editor is FlowLayoutPanel;
        var h = PreferredHeight(editor);
        editor.Height = h;
        if (!autoW)
        {
            editor.Width = Math.Max(60, body.ClientSize.Width - LabelCol);
            editor.Anchor = AnchorStyles.Left | AnchorStyles.Right | AnchorStyles.Top;
        }
        else
        {
            editor.Anchor = AnchorStyles.Left | AnchorStyles.Top;
        }
        editor.Location = new Point(LabelCol, y + (rowH - h) / 2);

        body.Controls.Add(lbl);
        body.Controls.Add(editor);

        void Sync(object? _, EventArgs __)
        {
            var hh = PreferredHeight(editor);
            editor.Location = new Point(LabelCol, y + (rowH - hh) / 2);
            if (!autoW)
                editor.Width = Math.Max(60, body.ClientSize.Width - LabelCol);
        }
        body.Resize += Sync;
    }

    /// <summary>一行两列：标签+控件 | 标签+控件。左右两块的右边缘都贴到 body 边界。</summary>
    public static void PlacePairRow(
        Panel body, int y,
        string leftLabel, Control leftCtrl,
        string rightLabel, Control rightCtrl,
        int rowH = RowH)
    {
        const int midGap = 20;

        EnsureChild(body, leftLabel, leftCtrl);
        EnsureChild(body, rightLabel, rightCtrl);

        void Layout(object? _, EventArgs __)
        {
            var total = body.ClientSize.Width;
            var half = Math.Max(170, (total - midGap) / 2);
            var editW = Math.Max(60, half - LabelCol);

            PlaceOrMove(body, leftLabel, leftCtrl, 0, y, rowH, editW);
            PlaceOrMove(body, rightLabel, rightCtrl, half + midGap, y, rowH, editW);
        }

        body.Resize += Layout;
        Layout(null, EventArgs.Empty);
    }

    private static void EnsureChild(Panel body, string label, Control editor)
    {
        if (body.Controls.Contains(editor)) return;
        var lbl = FieldLabel(label);
        lbl.Tag = editor;
        body.Controls.Add(lbl);
        body.Controls.Add(editor);
    }

    private static void PlaceOrMove(
        Panel body, string labelText, Control editor,
        int x, int y, int rowH, int editW)
    {
        Label? lbl = null;
        foreach (Control c in body.Controls)
        {
            if (c is Label l && ReferenceEquals(l.Tag, editor))
            {
                lbl = l;
                break;
            }
        }
        if (lbl is null) return;

        lbl.Text = labelText;
        lbl.Location = new Point(x, y);
        lbl.Size = new Size(LabelCol, rowH);

        var h = PreferredHeight(editor);
        editor.Size = new Size(editW, h);
        editor.Location = new Point(x + LabelCol, y + (rowH - h) / 2);
        editor.Anchor = AnchorStyles.Top | AnchorStyles.Left;
    }
}
