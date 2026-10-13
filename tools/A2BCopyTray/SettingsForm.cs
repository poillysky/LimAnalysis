namespace A2BCopyTray;

public sealed class SettingsForm : Form
{
    private readonly AppConfig _original;
    private readonly Action<AppConfig> _onSave;

    private readonly RadioButton _modeMold;
    private readonly RadioButton _modeAppearance;
    private readonly TextBox _project;
    private readonly TextBox _machine;
    private readonly TextBox _station;
    private readonly TextBox _sourceDir;
    private readonly TextBox _targetRoot;
    private readonly TextBox _excludeList;
    private readonly Label _targetHint;
    private readonly Label _excludeHint;
    private readonly TextBox _deviceAlias;
    private readonly TextBox _heartbeatUrl;
    private readonly NumericUpDown _pollSeconds;
    private readonly NumericUpDown _fileSettle;
    private readonly NumericUpDown _retryCount;
    private readonly NumericUpDown _retryInterval;
    private readonly NumericUpDown _speedLimit;
    private readonly NumericUpDown _logKeep;
    private readonly NumericUpDown _heartbeatSeconds;
    private readonly ComboBox _compareMode;
    private readonly CheckBox _autoStart;
    private readonly CheckBox _crashRestart;
    private readonly CheckBox _startPaused;
    private readonly CheckBox _desktopShortcut;
    private readonly TextBox _whitelist;
    private readonly TextBox _blacklist;

    private Label? _projectLblRef;
    private Label? _machineLblRef;

    /// <summary>必须保持引用：ToolTip 被 GC 后悬停提示会失效。</summary>
    private readonly ToolTip _tips = new() { AutoPopDelay = 20000, InitialDelay = 400, ReshowDelay = 200 };

    private const int HeaderH = 54;
    private const int FooterH = 60;

    public SettingsForm(AppConfig cfg, Action<AppConfig> onSave)
    {
        _original = cfg;
        _onSave = onSave;

        Text = "A2B 系统配置";
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        ShowInTaskbar = false;
        StartPosition = FormStartPosition.CenterParent;
        ClientSize = new Size(680, 740);
        Icon = AppIcons.App;
        UiTheme.StyleForm(this);
        // 标题栏与 header 同色，和主界面保持一致的观感
        WindowChrome.Apply(this, UiTheme.HeaderBg, Color.White);

        var version = typeof(SettingsForm).Assembly.GetName().Version;
        var versionLbl = new Label
        {
            Text = version is null ? "" : $"v{version.Major}.{version.Minor}.{version.Build}",
            ForeColor = Color.FromArgb(150, 164, 182),
            Font = UiTheme.UiFont(8.5f),
            AutoSize = true,
            Anchor = AnchorStyles.Right,
            BackColor = UiTheme.HeaderBg,
            Margin = new Padding(0)
        };

        var scroll = new Panel
        {
            Dock = DockStyle.Fill,
            AutoScroll = true,
            Padding = new Padding(0),
            Margin = new Padding(0),
            BackColor = UiTheme.WindowBg
        };

        var stack = new FlowLayoutPanel
        {
            FlowDirection = FlowDirection.TopDown,
            WrapContents = false,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            Dock = DockStyle.None,
            Location = new Point(UiTheme.ContentPad, UiTheme.ContentPad),
            Margin = new Padding(0),
            Padding = new Padding(0),
            BackColor = UiTheme.WindowBg
        };

        // —— 站点信息：模式 / 项目 / 机台 / 工站 ——
        const int siteH = UiTheme.RowH * 4;
        var siteCard = UiTheme.SectionCard("站点信息", siteH, out var siteBody);
        _modeMold = new RadioButton
        {
            Text = "注塑机",
            AutoSize = true,
            Checked = !cfg.IsAppearance,
            Font = UiTheme.UiFont(),
            BackColor = UiTheme.PanelBg,
            Margin = new Padding(0, 0, 26, 0)
        };
        _modeAppearance = new RadioButton
        {
            Text = "外观机",
            AutoSize = true,
            Checked = cfg.IsAppearance,
            Font = UiTheme.UiFont(),
            BackColor = UiTheme.PanelBg,
            Margin = new Padding(0)
        };
        _modeMold.CheckedChanged += (_, _) => OnModeChanged();
        _modeAppearance.CheckedChanged += (_, _) => OnModeChanged();
        // FlowLayoutPanel：间距随文字宽度自适应，不再写死 90/110 这类魔法偏移
        var modeHost = new FlowLayoutPanel
        {
            FlowDirection = FlowDirection.LeftToRight,
            WrapContents = false,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            Margin = new Padding(0),
            Padding = new Padding(0),
            BackColor = UiTheme.PanelBg
        };
        modeHost.Controls.Add(_modeMold);
        modeHost.Controls.Add(_modeAppearance);
        UiTheme.PlaceRow(siteBody, 0, "运行模式", modeHost);

        _project = UiTheme.TextField(cfg.Project);
        UiTheme.PlaceRow(siteBody, UiTheme.RowH, "项目名", _project);
        _machine = UiTheme.TextField(cfg.Machine);
        UiTheme.PlaceRow(siteBody, UiTheme.RowH * 2, "机台号", _machine);
        _station = UiTheme.TextField(cfg.Station);
        UiTheme.PlaceRow(siteBody, UiTheme.RowH * 3, "工站", _station);
        CaptureLabels(siteBody, _project, _machine);
        stack.Controls.Add(siteCard);

        // —— 目录路径：源 / 目标 / 默认排除(只读) / 自定义排除 + 实际写入 / 实际排除 / 语法提示 ——
        const int hintH = 24;
        const int customH = 42;                       // 自定义排除框：约 2 行
        const int customRow = customH + 8;
        const int defaultRow = UiTheme.RowH;
        const int pathH = UiTheme.RowH * 2 + defaultRow + customRow + hintH * 3;
        var pathCard = UiTheme.SectionCard("目录路径", pathH, out var pathBody);
        _sourceDir = UiTheme.TextField(cfg.SourceDir);
        UiTheme.PlaceRow(pathBody, 0, "本地源目录", PathEditor(_sourceDir, "选择本地源目录"));
        _targetRoot = UiTheme.TextField(cfg.TargetRoot);
        UiTheme.PlaceRow(pathBody, UiTheme.RowH, "目标共享目录", PathEditor(_targetRoot, "选择目标共享目录"));

        // 默认排除项：只读展示，始终生效（由 AppConfig.DefaultExcludePaths 兜底）
        var yDefault = UiTheme.RowH * 2;
        var builtinExclude = UiTheme.ReadOnlyField(
            string.Join("   ", AppConfig.DefaultExcludePaths));
        UiTheme.PlaceRow(pathBody, yDefault, "默认排除", builtinExclude);
        _tips.SetToolTip(builtinExclude,
            "内置默认排除项，始终生效、不可修改：\r\n" +
            "    " + string.Join("    ", AppConfig.DefaultExcludePaths) + "\r\n" +
            "\r\n" +
            "含义：源目录「当天日期目录」下，任意层级里叫这些名字的目录/文件都会被跳过。\r\n" +
            "要额外排除别的，写在下面「自定义排除」里。");

        // 自定义排除项：可编辑，会与上面的默认项合并生效
        var yCustom = yDefault + defaultRow;
        _excludeList = Multi(string.Join(Environment.NewLine, cfg.CustomExcludePaths), customH);
        PlaceMulti(pathBody, yCustom, "自定义排除", _excludeList, customRow);
        _tips.SetToolTip(_excludeList,
            "自定义排除清单写法（每行一条，可留空）—— 会与上面的默认项合并生效：\r\n" +
            "\r\n" +
            "① 相对名 —— 推荐，最常用\r\n" +
            "   cache                排除任意层级下名为 cache 的目录\r\n" +
            "   Thumbs.db            排除任意层级下这个名字的文件\r\n" +
            "   20260101/temp        以「/」连写多段：只排除这条相对路径\r\n" +
            "   *.log  IMG_*_raw.*   文件名通配（* 任意串，? 单字符）\r\n" +
            "   ※ 相对路径的起点是「源目录下的当天日期目录」，不是源目录本身。\r\n" +
            "   ※ 不要写「.\\temp」或开头带斜杠 —— 那样会被当成另一个名字，匹配不上。\r\n" +
            "\r\n" +
            "② 绝对 / UNC 路径 —— 排除整棵子树\r\n" +
            @"   D:\A2B\temp          \\NAS\Share\A2B\tmp" + "\r\n" +
            "\r\n" +
            "③ 匹配范围与顺序\r\n" +
            "   · 相对名 = 逐路径段一一比对（整段相等才算，temp 不会命中 temp2）\r\n" +
            "   · 命中任一规则即排除；黑名单/白名单只比对完整相对路径或文件名，\r\n" +
            "     要按目录名排除请写在这里，不要写进黑名单。\r\n" +
            "\r\n" +
            "设置完看下方「实际排除」一行，会实时拼出「默认 + 自定义」的最终清单。");

        _targetHint = HintLabel("实际写入: -");
        _excludeHint = HintLabel("实际排除: -");
        var excludeHintText = HintLabel("每行一条；写目录名（如 cache）即排除任意层级同名；支持 * ? 通配 ← 悬停看写法");
        UiTheme.PlaceRow(pathBody, yCustom + customRow, "", _targetHint, hintH);
        UiTheme.PlaceRow(pathBody, yCustom + customRow + hintH, "", _excludeHint, hintH);
        UiTheme.PlaceRow(pathBody, yCustom + customRow + hintH * 2, "", excludeHintText, hintH);
        stack.Controls.Add(pathCard);

        // —— 连接与标识 ——
        const int connH = UiTheme.RowH * 2 + hintH * 2;
        var connCard = UiTheme.SectionCard("连接与标识", connH, out var connBody);
        _deviceAlias = UiTheme.ReadOnlyField(cfg.DeviceAlias);
        UiTheme.PlaceRow(connBody, 0, "设备别名", _deviceAlias);
        _tips.SetToolTip(_deviceAlias,
            "设备别名由运行模式自动生成，不能手工填写：\r\n" +
            "\r\n" +
            "   注塑机  →  机台号                     例：IM-0312\r\n" +
            "   外观机  →  项目-机台-工站             例：eagle_rcvr-IM-0312-1\r\n" +
            "\r\n" +
            "改上面的「项目名 / 机台号 / 工站」，这里会立刻跟着变。\r\n" +
            "日志的启动行、主界面「设备别名」、心跳报文的 deviceAlias 与 clientId\r\n" +
            "都用这一个值 —— 它同时也是服务端识别本台设备的唯一标识。\r\n" +
            "机台/项目一个都没填时，暂时退回本机主机名：" + Environment.MachineName + "。");
        var aliasHint = HintLabel("自动生成，无需填写：注塑机 = 机台号；外观机 = 项目-机台-工站");
        UiTheme.PlaceRow(connBody, UiTheme.RowH, "", aliasHint, hintH);

        _heartbeatUrl = UiTheme.TextField(cfg.HeartbeatUrl);
        UiTheme.PlaceRow(connBody, UiTheme.RowH + hintH, "心跳地址", UrlEditor(_heartbeatUrl));
        _tips.SetToolTip(_heartbeatUrl,
            "心跳上报地址（留空则不上报）。\r\n" +
            "只填主机时会自动补上 /api/heartbeat：\r\n" +
            @"   192.168.2.38:8000   →   http://192.168.2.38:8000/api/heartbeat" + "\r\n" +
            "\r\n" +
            "上报内容（HTTP POST，JSON）：设备别名 / 主机名 / 版本 / 模式 /\r\n" +
            "机台或项目 / 工站 / 运行状态 / 是否暂停 / 源与目标目录 /\r\n" +
            "本轮成功数 / 失败数 / 累计轮次 / 最后同步时间 / 时间戳。\r\n" +
            "上报间隔见下方「心跳间隔」。可点右侧「测试」立即验证一次。");
        var hbHint = HintLabel("留空则不上报；只填主机时自动补 /api/heartbeat ← 悬停看上报内容");
        UiTheme.PlaceRow(connBody, UiTheme.RowH * 2 + hintH, "", hbHint, hintH);
        stack.Controls.Add(connCard);

        // —— 同步参数：4 行两列 ——
        _pollSeconds = UiTheme.NumField(cfg.PollSeconds, 1, 3600);
        _fileSettle = UiTheme.NumField((decimal)cfg.FileSettleSeconds, 0, 120);
        _retryCount = UiTheme.NumField(cfg.RetryCount, 1, 20);
        _retryInterval = UiTheme.NumField((decimal)cfg.RetryInterval, 0.5m, 60, 0.5m);
        _speedLimit = UiTheme.NumField(cfg.SpeedLimitKbps, 0, 1_000_000);
        _logKeep = UiTheme.NumField(cfg.LogKeepDays, 1, 365);
        _heartbeatSeconds = UiTheme.NumField(cfg.HeartbeatSeconds, 10, 3600);
        _compareMode = new ComboBox
        {
            DropDownStyle = ComboBoxStyle.DropDownList,
            Font = UiTheme.UiFont(),
            Height = UiTheme.CtrlHeight,
            IntegralHeight = false,
            Margin = new Padding(0)
        };
        _compareMode.Items.AddRange(
        [
            "高速模式（大小 + 修改时间）",
            "精准模式（MD5 校验）"
        ]);
        _compareMode.SelectedIndex =
            string.Equals(cfg.CompareMode, "md5", StringComparison.OrdinalIgnoreCase) ? 1 : 0;

        const int syncH = UiTheme.RowH * 4;
        var syncCard = UiTheme.SectionCard("同步参数", syncH, out var syncBody);
        UiTheme.PlacePairRow(syncBody, 0, "扫描间隔(秒)", _pollSeconds, "文件释放等待(秒)", _fileSettle);
        UiTheme.PlacePairRow(syncBody, UiTheme.RowH, "失败重试次数", _retryCount, "重试间隔(秒)", _retryInterval);
        UiTheme.PlacePairRow(syncBody, UiTheme.RowH * 2, "限速(KB/s)", _speedLimit, "日志保留天数", _logKeep);
        UiTheme.PlacePairRow(syncBody, UiTheme.RowH * 3, "心跳间隔(秒)", _heartbeatSeconds, "文件判断模式", _compareMode);
        stack.Controls.Add(syncCard);

        // —— 启动设置 ——
        const int startH = UiTheme.RowH + hintH;
        var startCard = UiTheme.SectionCard("启动设置", startH, out var startBody);
        _autoStart = new CheckBox
        {
            Text = "开机自启",
            Checked = cfg.AutoStart,
            AutoSize = true,
            Font = UiTheme.UiFont(),
            BackColor = UiTheme.PanelBg,
            Margin = new Padding(0, 0, 24, 0)
        };
        _crashRestart = new CheckBox
        {
            Text = "崩溃自启动",
            Checked = cfg.CrashRestart,
            AutoSize = true,
            Font = UiTheme.UiFont(),
            BackColor = UiTheme.PanelBg,
            Margin = new Padding(0, 0, 24, 0)
        };
        _startPaused = new CheckBox
        {
            Text = "启动后暂停",
            Checked = cfg.StartPaused,
            AutoSize = true,
            Font = UiTheme.UiFont(),
            BackColor = UiTheme.PanelBg,
            Margin = new Padding(0, 0, 24, 0)
        };
        _desktopShortcut = new CheckBox
        {
            Text = "桌面快捷方式",
            Checked = ShortcutManager.Exists,
            AutoSize = true,
            Font = UiTheme.UiFont(),
            BackColor = UiTheme.PanelBg,
            Margin = new Padding(0)
        };
        var startHost = new FlowLayoutPanel
        {
            FlowDirection = FlowDirection.LeftToRight,
            WrapContents = false,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            Margin = new Padding(0),
            Padding = new Padding(0),
            BackColor = UiTheme.PanelBg
        };
        startHost.Controls.Add(_autoStart);
        startHost.Controls.Add(_crashRestart);
        startHost.Controls.Add(_startPaused);
        startHost.Controls.Add(_desktopShortcut);
        UiTheme.PlaceRow(startBody, 0, "", startHost);

        var startHint = HintLabel("「启动后暂停」= 每次启动都停在暂停态，点「开始监控」才复制");
        _tips.SetToolTip(startHint,
            "「启动后暂停」（默认勾选）：程序启动先不动，需要人工确认设备就绪后点「开始监控」。\r\n" +
            "「桌面快捷方式」：保存后即在桌面创建（图标取程序本体）；取消勾选则删除。\r\n" +
            "把 exe 换到别的目录后，重新勾选一次即可刷新指向。\r\n" +
            "当前桌面路径：" + ShortcutManager.DesktopPath);

        // 「开机自启」+「启动后暂停」同时勾选＝开机后停在暂停态、需人工开始。
        // 这是合理组合（值班机人工确认后开始），但很容易忘，所以就地提示出来。
        void RefreshStartHint()
        {
            var both = _autoStart.Checked && _startPaused.Checked;
            startHint.Text = both
                ? "已同时开启「开机自启」+「启动后暂停」：开机后需人工点「开始监控」"
                : "「启动后暂停」= 每次启动都停在暂停态，点「开始监控」才复制";
            startHint.ForeColor = both ? UiTheme.Warning : UiTheme.TextMuted;
        }
        _autoStart.CheckedChanged += (_, _) => RefreshStartHint();
        _startPaused.CheckedChanged += (_, _) => RefreshStartHint();
        RefreshStartHint();
        UiTheme.PlaceRow(startBody, UiTheme.RowH, "", startHint, hintH);
        stack.Controls.Add(startCard);

        // —— 过滤规则（排除清单已挪到「目录路径」）——
        const int multiH = 56;
        const int multiRow = multiH + 8;
        const int filterH = multiRow * 2 + hintH + 8;
        var filterCard = UiTheme.SectionCard("过滤规则", filterH, out var filterBody);
        _whitelist = Multi(string.Join(Environment.NewLine, cfg.Whitelist), multiH);
        _blacklist = Multi(string.Join(Environment.NewLine, cfg.Blacklist), multiH);
        _tips.SetToolTip(_whitelist,
            "白名单（每行一条，可整体留空）\r\n" +
            "留空 = 不限制，源目录里的文件全部同步。\r\n" +
            "一旦填写，只有命中其中任一条的文件才会同步（其余一律跳过）。\r\n" +
            "示例：*.jpg  *.png  20260101/IMG_*\r\n" +
            "※ 只比对「完整相对路径」或「文件名」，不支持按目录名匹配。");
        _tips.SetToolTip(_blacklist,
            "黑名单（每行一条）\r\n" +
            "命中的文件一律不同步；与白名单同时命中时，以排除为准。\r\n" +
            "示例：*.tmp  *.part  Thumbs.db  desktop.ini\r\n" +
            "※ 只比对「完整相对路径」或「文件名」，不支持按目录名匹配。\r\n" +
            "※ 要按目录名排除（如 temp、cache），请写到上面的「排除清单」里。");
        PlaceMulti(filterBody, 0, "白名单", _whitelist, multiRow);
        PlaceMulti(filterBody, multiRow, "黑名单", _blacklist, multiRow);
        var filterHint = HintLabel("每行一条；白名单可空（空=全部）；黑名单支持 *.tmp 通配");
        UiTheme.PlaceRow(filterBody, multiRow * 2, "", filterHint, hintH);
        stack.Controls.Add(filterCard);

        scroll.Controls.Add(stack);

        // —— 用 TableLayoutPanel 固定三段结构，避免 Dock 顺序造成的重叠 ——
        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 3,
            Margin = new Padding(0),
            Padding = new Padding(0)
        };
        root.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, HeaderH));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, FooterH));

        var footer = BuildFooter(out var save, out var cancel);
        root.Controls.Add(UiTheme.BuildHeader("A2B 系统配置", "修改后保存即时生效", versionLbl), 0, 0);
        root.Controls.Add(scroll, 0, 1);
        root.Controls.Add(footer, 0, 2);
        Controls.Add(root);

        AcceptButton = save;
        CancelButton = cancel;

        _project.TextChanged += (_, _) => UpdateHint();
        _machine.TextChanged += (_, _) => UpdateHint();
        _station.TextChanged += (_, _) => UpdateHint();
        _targetRoot.TextChanged += (_, _) => UpdateHint();
        _excludeList.TextChanged += (_, _) => UpdateHint();
        OnModeChanged();

        // Esc 由 CancelButton 接管；这里补 Ctrl+S = 保存
        KeyPreview = true;
        KeyDown += (_, e) =>
        {
            if (e.Control && e.KeyCode == Keys.S)
            {
                e.Handled = true;
                e.SuppressKeyPress = true;
                Save();
            }
        };

        void SyncStackWidth()
        {
            var side = UiTheme.ContentPad;
            // scroll.ClientSize.Width 已经扣掉了滚动条，不要再减一次
            var w = Math.Max(460, scroll.ClientSize.Width - side * 2);
            stack.Width = w;
            foreach (Control c in stack.Controls)
                c.Width = w;

            stack.PerformLayout();

            // 注意两点，否则拖动滚动条时页面会被弹回顶部：
            // 1) 不要在这里重设 stack.Location —— AutoScroll 正是靠改子控件坐标来滚动的，
            //    每次布局都把坐标写回 (side, side) 等于把滚动位置清零。
            // 2) 内容高度只由子控件决定，必须用 PreferredSize；不能用 stack.Top ——
            //    滚动后它是负数，用它会把滚动区间越算越小，滚动位置随即被夹回去。
            scroll.AutoScrollMinSize = new Size(0, side * 2 + stack.PreferredSize.Height);
        }
        scroll.Resize += (_, _) => SyncStackWidth();
        Shown += (_, _) =>
        {
            SyncStackWidth();
            // 滚动条出现会再次改变 ClientSize，补一次布局
            BeginInvoke(() => SyncStackWidth());
        };
    }

    private static Label HintLabel(string text) => new()
    {
        Text = text,
        AutoSize = false,
        Height = 24,
        Font = UiTheme.UiFont(8.5f),
        ForeColor = UiTheme.TextMuted,
        BackColor = UiTheme.PanelBg,
        TextAlign = ContentAlignment.MiddleLeft,
        Margin = new Padding(0)
    };

    private void CaptureLabels(Panel body, TextBox project, TextBox machine)
    {
        foreach (Control c in body.Controls)
        {
            if (c is not Label lbl) continue;
            var idx = body.Controls.GetChildIndex(lbl);
            if (idx + 1 >= body.Controls.Count) continue;
            var next = body.Controls[idx + 1];
            if (ReferenceEquals(next, project)) _projectLblRef = lbl;
            if (ReferenceEquals(next, machine)) _machineLblRef = lbl;
        }
    }

    private static void PlaceMulti(Panel body, int y, string label, TextBox box, int rowH)
    {
        var lbl = UiTheme.FieldLabel(label);
        lbl.Location = new Point(0, y);
        lbl.Size = new Size(UiTheme.LabelCol, rowH);
        lbl.TextAlign = ContentAlignment.TopLeft;
        lbl.Padding = new Padding(0, 6, 0, 0);

        box.Location = new Point(UiTheme.LabelCol, y + 4);
        box.Height = rowH - 8;
        box.Width = Math.Max(80, body.ClientSize.Width - UiTheme.LabelCol);
        box.Anchor = AnchorStyles.Left | AnchorStyles.Right | AnchorStyles.Top;

        body.Controls.Add(lbl);
        body.Controls.Add(box);
        body.Resize += (_, _) =>
        {
            box.Width = Math.Max(80, body.ClientSize.Width - UiTheme.LabelCol);
        };
    }

    private Control BuildFooter(out Button save, out Button cancel)
    {
        var footer = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 2,
            BackColor = UiTheme.FooterBg,
            Margin = new Padding(0),
            Padding = new Padding(0)
        };
        footer.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
        footer.RowStyles.Add(new RowStyle(SizeType.Absolute, 1));
        footer.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));

        // 分隔线铺满整宽，内容区再单独留边
        var topLine = new Panel { Dock = DockStyle.Fill, BackColor = UiTheme.Border, Margin = new Padding(0) };

        var body = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 2,
            RowCount = 1,
            BackColor = UiTheme.FooterBg,
            Margin = new Padding(0),
            Padding = new Padding(UiTheme.ContentPad, 0, UiTheme.ContentPad, 0)
        };
        body.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
        body.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        body.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));

        // 左侧：常用运维入口，不占主流程
        var dirLink = new LinkText
        {
            Text = "打开程序目录",
            Font = UiTheme.UiFont(8.5f),
            ForeColor = UiTheme.TextMuted,
            BackColor = UiTheme.FooterBg,
            Anchor = AnchorStyles.Left,
            Width = 110,
            Margin = new Padding(0)
        };
        var dirTip = new ToolTip { InitialDelay = 400 };
        dirTip.SetToolTip(dirLink, $"配置与日志所在目录：\n{AppPaths.AppDir}");
        dirLink.Click += (_, _) => OpenAppDir();
        body.Controls.Add(dirLink, 0, 0);

        var btns = new FlowLayoutPanel
        {
            FlowDirection = FlowDirection.RightToLeft,
            WrapContents = false,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            Dock = DockStyle.None,
            // Anchor 只给 Right：水平贴右，垂直由 TableLayoutPanel 居中（Dock=Fill 会顶到上边）
            Anchor = AnchorStyles.Right,
            BackColor = UiTheme.FooterBg,
            Margin = new Padding(0),
            Padding = new Padding(0)
        };

        cancel = UiTheme.SecondaryButton("取消");
        cancel.DialogResult = DialogResult.Cancel;
        cancel.Margin = new Padding(0);
        cancel.Click += (_, _) => Close();
        save = UiTheme.PrimaryButton("保存", UiGlyphs.Save);
        if (save is FlatButton sfb)
            save.Width = Math.Max(UiTheme.BtnWidth, sfb.PreferredContentWidth());
        save.Margin = new Padding(0, 0, 10, 0);
        save.Click += (_, _) => Save();
        btns.Controls.Add(cancel);
        btns.Controls.Add(save);

        body.Controls.Add(btns, 1, 0);
        footer.Controls.Add(topLine, 0, 0);
        footer.Controls.Add(body, 0, 1);
        return footer;
    }

    private static void OpenAppDir()
    {
        try
        {
            System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(AppPaths.AppDir)
            {
                UseShellExecute = true
            });
        }
        catch (Exception ex)
        {
            MessageBox.Show($"打开目录失败：\n{ex.Message}", "打开程序目录",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    private void OnModeChanged()
    {
        var appearance = _modeAppearance.Checked;
        _project.Enabled = appearance;
        _station.Enabled = appearance;
        if (_machineLblRef is not null)
            _machineLblRef.Text = appearance ? "外观机号" : "机台号";
        if (_projectLblRef is not null)
            _projectLblRef.Text = "项目名";
        UpdateHint();
    }

    private void UpdateHint()
    {
        try
        {
            var d = Draft();
            _targetHint.Text = $"实际写入: {d.EffectiveTarget()}";
            _excludeHint.Text = $"实际排除: {d.EffectiveExclude()}";
            _deviceAlias.Text = d.DeviceAlias;
        }
        catch
        {
            _targetHint.Text = "实际写入: -";
            _excludeHint.Text = "实际排除: -";
            _deviceAlias.Text = _original.DeviceAlias;
        }
    }

    private AppConfig Draft() => ConfigStore.Normalize(new AppConfig
    {
        Mode = _modeAppearance.Checked ? "appearance" : "mold",
        Machine = _machine.Text,
        Project = _project.Text,
        Station = _station.Text,
        SourceDir = _sourceDir.Text,
        TargetRoot = _targetRoot.Text,
        ExcludePaths = SplitLines(_excludeList.Text),
        HeartbeatUrl = _heartbeatUrl.Text,
        PollSeconds = (int)_pollSeconds.Value,
        FileSettleSeconds = (double)_fileSettle.Value,
        RetryCount = (int)_retryCount.Value,
        RetryInterval = (double)_retryInterval.Value,
        SpeedLimitKbps = (int)_speedLimit.Value,
        LogKeepDays = (int)_logKeep.Value,
        HeartbeatSeconds = (int)_heartbeatSeconds.Value,
        CompareMode = _compareMode.SelectedIndex == 1 ? "md5" : "fast",
        AutoStart = _autoStart.Checked,
        CrashRestart = _crashRestart.Checked,
        StartPaused = _startPaused.Checked,
        Paused = _original.Paused,
        Whitelist = SplitLines(_whitelist.Text),
        Blacklist = SplitLines(_blacklist.Text)
    });

    private void Save()
    {
        var cfg = Draft();
        var err = cfg.Validate();
        if (err is not null)
        {
            MessageBox.Show(this, err, "配置校验", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }
        ApplyDesktopShortcut(_desktopShortcut.Checked);
        _onSave(cfg);
        DialogResult = DialogResult.OK;
        Close();
    }

    /// <summary>按勾选状态创建 / 删除桌面快捷方式。失败只提示，不阻断配置保存。</summary>
    private void ApplyDesktopShortcut(bool wanted)
    {
        try
        {
            if (wanted == ShortcutManager.Exists) return;

            if (wanted)
            {
                var problem = ShortcutManager.Create();
                if (problem is not null)
                    MessageBox.Show(this, problem, "桌面快捷方式",
                        MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
            else if (!ShortcutManager.Remove())
            {
                MessageBox.Show(this,
                    "删除桌面快捷方式失败（文件可能被占用或没有桌面写权限）。",
                    "桌面快捷方式", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, $"处理桌面快捷方式时出错：\n{ex.Message}",
                "桌面快捷方式", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    private static List<string> SplitLines(string text) =>
        text.Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Where(x => !string.IsNullOrWhiteSpace(x))
            .ToList();

    private static TextBox Multi(string text, int height) => new()
    {
        Text = text,
        Multiline = true,
        ScrollBars = ScrollBars.Vertical,
        Height = height,
        AcceptsReturn = true,
        Font = UiTheme.UiFont(),
        Margin = new Padding(0)
    };

    /// <summary>路径行：文本框 +「测试」+「浏览...」，绝对坐标布局。</summary>
    private Control PathEditor(TextBox box, string browseTitle)
    {
        var host = new Panel
        {
            Height = UiTheme.CtrlHeight,
            BackColor = UiTheme.PanelBg,
            Margin = new Padding(0)
        };

        box.Height = UiTheme.PreferredHeight(box);
        box.Anchor = AnchorStyles.Left | AnchorStyles.Top;

        const int gap = 6;

        var test = UiTheme.SecondaryButton("测试", UiGlyphs.Check);
        test.Height = UiTheme.CtrlHeight;
        test.Width = Sized(test, UiTheme.TestW);
        test.Margin = new Padding(0);
        test.Click += (_, _) => TestPathReachable(box.Text);

        var browse = UiTheme.SecondaryButton("浏览...", UiGlyphs.Folder);
        browse.Height = UiTheme.CtrlHeight;
        browse.Width = Sized(browse, UiTheme.BrowseW);
        browse.Margin = new Padding(0);
        browse.Click += (_, _) =>
        {
            using var dlg = new FolderBrowserDialog { Description = browseTitle };
            if (dlg.ShowDialog(this) == DialogResult.OK)
                box.Text = dlg.SelectedPath;
        };

        var btnsW = test.Width + gap + browse.Width;

        host.Controls.Add(box);
        host.Controls.Add(test);
        host.Controls.Add(browse);

        void Layout(object? _, EventArgs __)
        {
            var w = host.ClientSize.Width;
            var h = UiTheme.CtrlHeight;
            browse.SetBounds(w - browse.Width, 0, browse.Width, h);
            test.SetBounds(w - btnsW, 0, test.Width, h);
            var bh = box.Height;
            // 单行文本框比按钮矮，垂直居中，不要贴顶
            box.SetBounds(0, (h - bh) / 2, Math.Max(40, w - btnsW - gap), bh);
        }
        host.Resize += Layout;
        host.HandleCreated += Layout;
        Layout(null, EventArgs.Empty);
        return host;
    }

    /// <summary>按钮宽度：至少给个下限，避免图标 + 文字被挤到省略。</summary>
    private static int Sized(Button b, int floor) =>
        b is FlatButton fb ? Math.Max(floor, fb.PreferredContentWidth()) : floor;

    /// <summary>心跳地址行：文本框 +「测试」（直接发一次心跳）。</summary>
    private Control UrlEditor(TextBox box)
    {
        var host = new Panel
        {
            Height = UiTheme.CtrlHeight,
            BackColor = UiTheme.PanelBg,
            Margin = new Padding(0)
        };

        box.Height = UiTheme.PreferredHeight(box);
        box.Anchor = AnchorStyles.Left | AnchorStyles.Top;

        const int gap = 6;

        var test = UiTheme.SecondaryButton("测试", UiGlyphs.Check);
        test.Height = UiTheme.CtrlHeight;
        test.Width = Sized(test, UiTheme.TestW);
        test.Margin = new Padding(0);
        test.Click += (_, _) => TestHeartbeat();

        host.Controls.Add(box);
        host.Controls.Add(test);

        void Layout(object? _, EventArgs __)
        {
            var w = host.ClientSize.Width;
            var h = UiTheme.CtrlHeight;
            test.SetBounds(w - test.Width, 0, test.Width, h);
            var bh = box.Height;
            box.SetBounds(0, (h - bh) / 2, Math.Max(40, w - test.Width - gap), bh);
        }
        host.Resize += Layout;
        host.HandleCreated += Layout;
        Layout(null, EventArgs.Empty);
        return host;
    }

    private void TestHeartbeat()
    {
        var cfg = Draft();
        var url = HeartbeatReporter.NormalizeUrl(cfg.HeartbeatUrl);
        if (url is null)
        {
            MessageBox.Show(this,
                "请先填写心跳地址。\n示例：http://10.18.97.189:5000",
                "心跳测试", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }

        UseWaitCursor = true;
        Enabled = false;
        try
        {
            var task = Task.Run(() => HeartbeatReporter.Test(cfg));
            if (!task.Wait(TimeSpan.FromSeconds(16)))
            {
                MessageBox.Show(this,
                    $"心跳测试超时（约 16 秒），目标可能不可达：\n{url}",
                    "心跳测试", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }

            var (ok, message) = task.Result;
            MessageBox.Show(this, message, "心跳测试",
                MessageBoxButtons.OK,
                ok ? MessageBoxIcon.Information : MessageBoxIcon.Warning);
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, $"心跳测试失败：\n{ex.Message}", "心跳测试",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        finally
        {
            Enabled = true;
            UseWaitCursor = false;
        }
    }

    /// <summary>检测目录是否存在且可列出（含 UNC），超时 8 秒。</summary>
    private void TestPathReachable(string raw)
    {
        var path = (raw ?? "").Trim();
        if (string.IsNullOrWhiteSpace(path))
        {
            MessageBox.Show(this, "请先填写路径。", "路径测试",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }

        UseWaitCursor = true;
        Enabled = false;
        try
        {
            var task = Task.Run(() => ProbePath(path));
            if (!task.Wait(TimeSpan.FromSeconds(8)))
            {
                MessageBox.Show(this,
                    $"检测超时（约 8 秒），路径可能不可达或网络较慢：\n{path}",
                    "路径测试", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }

            var (ok, message) = task.Result;
            MessageBox.Show(this, message, "路径测试",
                MessageBoxButtons.OK,
                ok ? MessageBoxIcon.Information : MessageBoxIcon.Warning);
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, $"检测失败：\n{ex.Message}", "路径测试",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        finally
        {
            Enabled = true;
            UseWaitCursor = false;
        }
    }

    private static (bool ok, string message) ProbePath(string path)
    {
        try
        {
            if (Directory.Exists(path))
            {
                // 能列出才算真正可达（排除仅 Exists 误报）
                _ = Directory.GetFileSystemEntries(path);
                return (true, $"路径可达：\n{path}");
            }

            // 目录不存在时，对 UNC 再探一下上级是否通
            if (path.StartsWith(@"\\", StringComparison.Ordinal))
            {
                try
                {
                    var parent = Path.GetDirectoryName(path.TrimEnd('\\'));
                    if (!string.IsNullOrEmpty(parent) && Directory.Exists(parent))
                        return (false, $"上级目录可达，但目标目录不存在：\n{path}\n\n上级：{parent}");
                }
                catch { /* ignore */ }

                return (false, $"目录不存在或网络不可达：\n{path}");
            }

            return (false, $"本地目录不存在：\n{path}");
        }
        catch (UnauthorizedAccessException)
        {
            return (false, $"路径存在但无访问权限：\n{path}");
        }
        catch (Exception ex)
        {
            return (false, $"无法访问：\n{path}\n\n{ex.Message}");
        }
    }
}
