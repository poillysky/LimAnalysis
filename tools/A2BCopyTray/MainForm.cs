using System.Diagnostics;

namespace A2BCopyTray;

public sealed class MainForm : Form
{
    private readonly Action _onSync;
    private readonly Action _onSettings;
    private readonly Action _onTogglePause;
    private readonly Dictionary<string, Control> _values = new();
    private readonly Dictionary<string, LinkText> _links = new();
    private readonly PillLabel _statusBadge;
    private readonly Button _pauseBtn;
    private readonly FlatProgressBar _progress;
    private readonly RichTextBox _logBox;
    private readonly CheckBox _autoScroll;
    private readonly ToolTip _rowTips = new() { InitialDelay = 500, ReshowDelay = 250 };

    // 日志批量刷新：同步高峰时每文件一行，逐行刷 UI 会把界面拖卡
    private readonly List<string> _pending = new();
    private readonly System.Windows.Forms.Timer _flushTimer;
    private const int MaxLogChars = 200_000;
    private const int KeepLogChars = 80_000;

    private readonly UiState _uiState = UiStateStore.Current;

    private const int HeaderH = 56;
    private const int ToolbarH = 62;

    private static readonly string[] StatusRows =
    [
        "设备别名", "当前监控日期", "当前运行状态", "源目录", "目标目录",
        "最后同步时间", "同步进度", "今日统计", "当前文件"
    ];

    /// <summary>可点击打开的路径行。</summary>
    private static readonly string[] PathRows = ["源目录", "目标目录", "当前文件"];

    /// <summary>窗口被收起（点关闭按钮）而不是退出时触发 —— 托盘据此弹一次气泡。</summary>
    public event Action? HiddenToTray;

    public MainForm(Action onSync, Action onSettings, Action onTogglePause)
    {
        _onSync = onSync;
        _onSettings = onSettings;
        _onTogglePause = onTogglePause;

        Text = "A2B 增量复制托盘程序";
        MinimumSize = new Size(760, 660);
        ClientSize = new Size(800, 700);
        Icon = AppIcons.App;
        UiTheme.StyleForm(this);

        RestoreWindowState();
        // 让系统标题栏与应用内 header 同色，整窗看起来是一体的
        WindowChrome.Apply(this, UiTheme.HeaderBg, Color.White);

        var statusH = UiTheme.CardOuterHeight(StatusRows.Length * UiTheme.StatusRowH) + UiTheme.SectionGap;

        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 4,
            Padding = new Padding(0),
            Margin = new Padding(0)
        };
        root.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, HeaderH));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, statusH));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, ToolbarH));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));

        root.Controls.Add(BuildHeader(out _statusBadge), 0, 0);
        root.Controls.Add(BuildStatusCard(), 0, 1);
        root.Controls.Add(BuildToolbar(out _pauseBtn, out _progress), 0, 2);
        root.Controls.Add(BuildLogPanel(out _logBox, out _autoScroll), 0, 3);

        Controls.Add(root);
        FormClosing += OnFormClosing;

        _flushTimer = new System.Windows.Forms.Timer { Interval = 120 };
        _flushTimer.Tick += (_, _) => FlushPending();

        foreach (var line in AppLogger.SnapshotRecent())
            _pending.Add(line);
        FlushPending();
        AppLogger.LineWritten += OnLogLine;
    }

    private static Control BuildHeader(out PillLabel badge)
    {
        badge = new PillLabel { Text = SyncStatus.Idle, Margin = new Padding(0) };
        return UiTheme.BuildHeader("A2B 增量复制", "站点图片同步 · 托盘运行", badge);
    }

    private Control BuildStatusCard()
    {
        var host = new Panel
        {
            Dock = DockStyle.Fill,
            Padding = new Padding(UiTheme.ContentPad, UiTheme.SectionGap, UiTheme.ContentPad, 0),
            BackColor = UiTheme.WindowBg,
            Margin = new Padding(0)
        };

        var card = new CardSurface { Dock = DockStyle.Fill, Margin = new Padding(0) };
        var (title, rule) = UiTheme.CardHeader("运行状态");

        var info = new TableLayoutPanel
        {
            ColumnCount = 3,
            RowCount = StatusRows.Length,
            BackColor = UiTheme.PanelBg,
            Margin = new Padding(0),
            Padding = new Padding(0)
        };
        info.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, UiTheme.LabelCol));
        info.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
        // 第三列放"在资源管理器中打开"的小图标
        info.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 22));

        for (var i = 0; i < StatusRows.Length; i++)
        {
            var row = StatusRows[i];
            info.RowStyles.Add(new RowStyle(SizeType.Percent, 100f / StatusRows.Length));
            info.Controls.Add(new Label
            {
                Text = row,
                Dock = DockStyle.Fill,
                TextAlign = ContentAlignment.MiddleLeft,
                ForeColor = UiTheme.TextMuted,
                BackColor = UiTheme.PanelBg,
                Font = UiTheme.UiFont(),
                Margin = new Padding(0, 0, 10, 0)
            }, 0, i);

            if (PathRows.Contains(row))
            {
                // 路径做成可点的链接：点了直接在资源管理器里打开（省得手工复制路径）
                var link = new LinkText
                {
                    Text = "-",
                    Dock = DockStyle.Fill,
                    Font = UiTheme.MonoFont(9f),
                    ForeColor = UiTheme.TextPrimary,
                    BackColor = UiTheme.PanelBg,
                    Margin = new Padding(0)
                };
                link.Click += (_, _) => OpenInExplorer(link.Text, selectFile: row == "当前文件");
                _values[row] = link;
                _links[row] = link;

                var open = new Label
                {
                    Text = UiGlyphs.Available ? UiGlyphs.OpenInNewWindow : "",
                    Dock = DockStyle.Fill,
                    TextAlign = ContentAlignment.MiddleCenter,
                    Font = UiGlyphs.FontPx(13f),
                    ForeColor = UiTheme.TextMuted,
                    BackColor = UiTheme.PanelBg,
                    Cursor = Cursors.Hand,
                    Margin = new Padding(0)
                };
                var tip = new ToolTip { InitialDelay = 400 };
                tip.SetToolTip(open, row == "当前文件" ? "在资源管理器中定位当前文件" : "在资源管理器中打开");
                open.Click += (_, _) => OpenInExplorer(link.Text, selectFile: row == "当前文件");

                info.Controls.Add(link, 1, i);
                info.Controls.Add(open, 2, i);
            }
            else
            {
                var value = new Label
                {
                    Text = "-",
                    Dock = DockStyle.Fill,
                    TextAlign = ContentAlignment.MiddleLeft,
                    Font = UiTheme.UiFont(9.5f),
                    ForeColor = UiTheme.TextPrimary,
                    BackColor = UiTheme.PanelBg,
                    AutoEllipsis = true,
                    Margin = new Padding(0)
                };
                _values[row] = value;
                info.Controls.Add(value, 1, i);
                info.SetColumnSpan(value, 2);
            }
        }

        card.Controls.Add(title);
        card.Controls.Add(rule);
        card.Controls.Add(info);
        host.Controls.Add(card);

        UiTheme.AttachCardScaffold(card, title, rule, info, 0);
        return host;
    }

    private Control BuildToolbar(out Button pauseBtn, out FlatProgressBar progress)
    {
        var host = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 2,
            RowCount = 1,
            Padding = new Padding(UiTheme.ContentPad, UiTheme.SectionGap, UiTheme.ContentPad, UiTheme.SectionGap),
            BackColor = UiTheme.WindowBg,
            Margin = new Padding(0)
        };
        host.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        host.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
        host.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));

        var btns = new FlowLayoutPanel
        {
            FlowDirection = FlowDirection.LeftToRight,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            WrapContents = false,
            Anchor = AnchorStyles.Left,
            BackColor = UiTheme.WindowBg,
            Margin = new Padding(0),
            Padding = new Padding(0)
        };

        var syncBtn = UiTheme.PrimaryButton("立即同步", UiGlyphs.Sync);
        syncBtn.Click += (_, _) => _onSync();
        var cfgBtn = UiTheme.SecondaryButton("系统配置", UiGlyphs.Settings);
        cfgBtn.Click += (_, _) => _onSettings();
        pauseBtn = UiTheme.SecondaryButton("暂停监控", UiGlyphs.Pause);
        pauseBtn.Click += (_, _) => _onTogglePause();
        var exportBtn = UiTheme.SecondaryButton("导出日志", UiGlyphs.Download);
        exportBtn.Click += (_, _) => ExportTodayLog();

        foreach (var b in new[] { syncBtn, cfgBtn, pauseBtn, exportBtn })
        {
            // 宽度按「图标 + 文字」实测，避免固定宽度把长标签挤成省略号
            if (b is FlatButton fb) b.Width = Math.Max(UiTheme.BtnWidth, fb.PreferredContentWidth());
            b.Margin = new Padding(0, 0, 8, 0);
        }
        exportBtn.Margin = new Padding(0);

        btns.Controls.Add(syncBtn);
        btns.Controls.Add(cfgBtn);
        btns.Controls.Add(pauseBtn);
        btns.Controls.Add(exportBtn);
        host.Controls.Add(btns, 0, 0);

        progress = new FlatProgressBar
        {
            Height = 10,
            Anchor = AnchorStyles.Left | AnchorStyles.Right,
            Margin = new Padding(20, 0, 2, 0)
        };
        host.Controls.Add(progress, 1, 0);
        return host;
    }

    private static Control BuildLogPanel(out RichTextBox logBox, out CheckBox autoScroll)
    {
        var host = new Panel
        {
            Dock = DockStyle.Fill,
            Padding = new Padding(UiTheme.ContentPad, 0, UiTheme.ContentPad, UiTheme.SectionGap),
            BackColor = UiTheme.WindowBg,
            Margin = new Padding(0)
        };

        var card = new CardSurface { Dock = DockStyle.Fill, Margin = new Padding(0) };
        var (title, rule) = UiTheme.CardHeader("运行日志");

        var box = new RichTextBox
        {
            Multiline = true,
            ReadOnly = true,
            ScrollBars = RichTextBoxScrollBars.Vertical,
            WordWrap = true,
            BorderStyle = BorderStyle.None,
            Font = UiTheme.MonoFont(9f),
            BackColor = Color.White,
            ForeColor = UiTheme.TextPrimary,
            DetectUrls = false,
            Margin = new Padding(0)
        };
        logBox = box;

        var chk = new CheckBox
        {
            Text = "自动滚动",
            Checked = true,
            AutoSize = false,
            Font = UiTheme.UiFont(8.5f),
            ForeColor = UiTheme.TextMuted,
            BackColor = UiTheme.PanelBg,
            TextAlign = ContentAlignment.MiddleRight,
            Height = 26,
            Width = 78,
            Margin = new Padding(0)
        };
        autoScroll = chk;

        var clear = UiTheme.IconButton(UiGlyphs.Delete, "清空日志窗口（磁盘上的日志文件不受影响）");
        clear.Click += (_, _) => ClearLogOn(box);

        card.Controls.Add(title);
        card.Controls.Add(rule);
        card.Controls.Add(box);
        card.Controls.Add(chk);
        card.Controls.Add(clear);

        void Layout()
        {
            var right = card.ClientSize.Width - UiTheme.CardPad;
            var y = UiTheme.CardPad + (UiTheme.TitleH - 26) / 2;
            clear.SetBounds(right - clear.Width, y, clear.Width, 26);
            chk.SetBounds(clear.Left - 6 - chk.Width, y, chk.Width, 26);

            var titleW = Math.Max(60, chk.Left - UiTheme.CardPad - 12);
            // 标题文字 +2，与日志框内文本的默认内缩对齐
            title.SetBounds(UiTheme.CardPad + 2, UiTheme.CardPad, titleW, UiTheme.TitleH);
            rule.SetBounds(UiTheme.CardPad, UiTheme.CardPad + UiTheme.TitleH + UiTheme.TitleGap,
                Math.Max(60, card.ClientSize.Width - UiTheme.CardPad * 2), UiTheme.RuleH);

            var top = UiTheme.CardBodyTop + 3;
            var h = Math.Max(0, card.ClientSize.Height - top - UiTheme.CardPad);
            box.SetBounds(UiTheme.CardPad, top,
                Math.Max(60, card.ClientSize.Width - UiTheme.CardPad * 2), h);
        }

        card.Resize += (_, _) => Layout();
        card.HandleCreated += (_, _) => Layout();
        Layout();

        host.Controls.Add(card);
        return host;
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            AppLogger.LineWritten -= OnLogLine;
            _flushTimer.Dispose();
            _rowTips.Dispose();
            SaveWindowState();
        }
        base.Dispose(disposing);
    }

    // —— 日志 ——

    private void OnLogLine(string line)
    {
        if (IsDisposed) return;
        lock (_pending)
        {
            _pending.Add(line);
            // 队列本身也不能无限涨（后台线程疯狂刷日志时界面还没轮到刷新）
            if (_pending.Count > 2000) _pending.RemoveRange(0, _pending.Count - 2000);
        }
        if (InvokeRequired)
        {
            try { BeginInvoke(EnsureFlushTimer); } catch { /* ignore */ }
            return;
        }
        EnsureFlushTimer();
    }

    private void EnsureFlushTimer()
    {
        if (IsDisposed || !IsHandleCreated) return;
        if (!_flushTimer.Enabled) _flushTimer.Start();
    }

    private void FlushPending()
    {
        List<string> batch;
        lock (_pending)
        {
            if (_pending.Count == 0)
            {
                _flushTimer.Stop();
                return;
            }
            batch = new List<string>(_pending);
            _pending.Clear();
        }

        if (IsDisposed) return;
        if (InvokeRequired)
        {
            try { BeginInvoke(() => AppendBatch(batch)); } catch { /* ignore */ }
            return;
        }
        AppendBatch(batch);
    }

    private void AppendBatch(List<string> batch)
    {
        if (_logBox.IsDisposed) return;
        _logBox.SuspendLayout();
        try
        {
            // 超量先裁掉最早的一段（只截文本，不重建控件）
            var excess = _logBox.TextLength + batch.Count * 90 - MaxLogChars;
            if (excess > 0 && _logBox.TextLength > 0)
            {
                var cut = Math.Min(excess, Math.Max(0, _logBox.TextLength - KeepLogChars));
                if (cut > 0)
                {
                    _logBox.Select(0, cut);
                    _logBox.SelectedText = string.Empty;
                }
            }

            foreach (var line in batch) AppendOne(line);
        }
        finally
        {
            _logBox.ResumeLayout();
        }

        if (_autoScroll.Checked) ScrollLogToEnd();
    }

    private void AppendOne(string line)
    {
        var start = _logBox.TextLength;
        var prefix = start > 0 ? Environment.NewLine : "";
        _logBox.AppendText(prefix + line);

        _logBox.Select(start, prefix.Length + line.Length);
        _logBox.SelectionColor = UiTheme.LogColor(line);

        // 时间戳用浅灰，让 [级别] 和信息本身更跳
        if (line.Length >= 19 && line[4] == '-' && line[7] == '-')
        {
            _logBox.Select(start + prefix.Length, 19);
            _logBox.SelectionColor = UiTheme.LogTime;
        }
        _logBox.SelectionLength = 0;
        _logBox.SelectionStart = _logBox.TextLength;
    }

    private void ScrollLogToEnd()
    {
        _logBox.SelectionStart = _logBox.TextLength;
        _logBox.SelectionLength = 0;
        _logBox.ScrollToCaret();
    }

    private static void ClearLogOn(RichTextBox box)
    {
        box.Clear();
        AppLogger.Info("已清空日志窗口（磁盘上的日志文件不受影响）");
    }

    // —— 快照 ——

    public void ApplySnapshot(SyncSnapshot snap)
    {
        if (InvokeRequired)
        {
            try { BeginInvoke(() => ApplySnapshot(snap)); } catch { /* ignore */ }
            return;
        }
        Set("设备别名", snap.DeviceAlias);
        Set("当前监控日期", snap.WatchDate);
        Set("当前运行状态", snap.Status);
        Set("源目录", snap.Source);
        Set("目标目录", snap.Target);
        Set("最后同步时间", snap.LastSync);
        Set("同步进度", snap.ProgressTotal > 0
            ? $"{snap.ProgressDone}/{snap.ProgressTotal}（{snap.ProgressDone * 100 / snap.ProgressTotal}%）"
            : "-");
        Set("今日统计", $"成功 {snap.OkCount} / 失败 {snap.FailCount} / 总次数 {snap.TotalRuns}");
        Set("当前文件", snap.CurrentFile);

        _statusBadge.Text = string.IsNullOrWhiteSpace(snap.Status) ? "-" : snap.Status;
        _statusBadge.Fill = snap.Status switch
        {
            SyncStatus.Syncing => UiTheme.Accent,
            SyncStatus.Paused => UiTheme.Warning,
            SyncStatus.Error => UiTheme.Danger,
            _ => UiTheme.Success
        };
        _statusBadge.Pulse = snap.Status == SyncStatus.Syncing;

        // 同步中 →「停止同步」（中止本轮 + 停监控）；监控中 →「暂停监控」；已暂停 →「开始监控」
        _pauseBtn.Text = snap.Status switch
        {
            SyncStatus.Paused => "开始监控",
            SyncStatus.Syncing => "停止同步",
            _ => "暂停监控"
        };
        if (_pauseBtn is FlatButton pb)
        {
            pb.Glyph = snap.Status == SyncStatus.Paused ? UiGlyphs.Play : UiGlyphs.Pause;
            pb.Width = Math.Max(UiTheme.BtnWidth, pb.PreferredContentWidth());
            pb.Invalidate();
        }

        if (snap.Status == SyncStatus.Syncing && snap.ProgressTotal <= 0)
        {
            _progress.Marquee = true;
        }
        else if (snap.Status == SyncStatus.Syncing)
        {
            _progress.Marquee = false;
            _progress.Max = snap.ProgressTotal;
            _progress.Value = snap.ProgressDone;
        }
        else
        {
            // 非同步态进度条归零：留着满格会被误读成"还在跑/已完成"
            _progress.Marquee = false;
            _progress.Value = 0;
        }
    }

    private void Set(string key, string? value)
    {
        if (!_values.TryGetValue(key, out var control)) return;
        var text = string.IsNullOrWhiteSpace(value) ? "-" : value!;
        control.Text = text;
        if (_links.ContainsKey(key)) _rowTips.SetToolTip(control, text);
    }

    // —— 窗口 ——

    private void RestoreWindowState()
    {
        if (!_uiState.HasBounds)
        {
            StartPosition = FormStartPosition.CenterScreen;
            return;
        }

        var saved = new Rectangle(_uiState.MainX, _uiState.MainY, _uiState.MainW, _uiState.MainH);
        var screen = Screen.AllScreens.FirstOrDefault(s => s.WorkingArea.IntersectsWith(saved))
                     ?? Screen.PrimaryScreen;
        var area = screen?.WorkingArea ?? new Rectangle(0, 0, 1280, 800);
        var fitted = UiState.Fit(saved, MinimumSize, area);

        // 保存的是外框，ClientSize 要扣掉边框标题栏的差值
        var chromeW = Width - ClientSize.Width;
        var chromeH = Height - ClientSize.Height;

        StartPosition = FormStartPosition.Manual;
        Location = fitted.Location;
        ClientSize = new Size(
            Math.Max(MinimumSize.Width - chromeW, fitted.Width - chromeW),
            Math.Max(MinimumSize.Height - chromeH, fitted.Height - chromeH));
        if (_uiState.Maximized) WindowState = FormWindowState.Maximized;
    }

    /// <summary>把当前窗口位置/大小记进 ui.json（退出或收起时调用）。</summary>
    public void SaveWindowState()
    {
        try
        {
            var maximized = WindowState == FormWindowState.Maximized;
            var bounds = maximized ? RestoreBounds : Bounds;
            _uiState.Maximized = maximized;
            if (bounds.Width > 0 && bounds.Height > 0)
            {
                _uiState.MainX = bounds.X;
                _uiState.MainY = bounds.Y;
                _uiState.MainW = bounds.Width;
                _uiState.MainH = bounds.Height;
                UiStateStore.Save(_uiState);
            }
        }
        catch { /* 记不住窗口位置不值得打断用户 */ }
    }

    public bool MinimizeTipShown
    {
        get => _uiState.MinimizeTipShown;
        set
        {
            if (_uiState.MinimizeTipShown == value) return;
            _uiState.MinimizeTipShown = value;
            UiStateStore.Save(_uiState);
        }
    }

    private void OnFormClosing(object? sender, FormClosingEventArgs e)
    {
        SaveWindowState();

        // 托盘程序的主窗口只允许"收起"。只有系统真的关机/注销、或进程整体退出
        // （Application.Exit）才放行真退出；其余任何来源的关闭请求都必须拦下来 ——
        // 窗口一旦真被销毁，托盘就再也唤不回界面了（会变成"进程活着但没界面"的僵尸）。
        //
        // 实测（.NET 8 / win-x64）各来源的 CloseReason：
        //   点标题栏 X / Alt+F4 → UserClosing
        //   外部 PostMessage(WM_CLOSE) / 任务管理器"结束任务" → TaskManagerClosing（两者无法区分！）
        //   注销 / 关机 → WindowsShutDown
        //   内部 Application.Exit() → ApplicationExitCall
        // 所以"白名单"只留 WindowsShutDown + ApplicationExitCall：
        // 本程序真正的退出走托盘菜单 → ExitThread()，根本不经过 FormClosing，不依赖 TaskManagerClosing。
        // TaskManagerClosing 若放行，任何一个外部 WM_CLOSE 都会静默把托盘程序杀掉，这正是要避免的。
        if (e.CloseReason is CloseReason.WindowsShutDown or CloseReason.ApplicationExitCall)
        {
            AppLogger.Info($"主窗口退出（{e.CloseReason}）");
            return;
        }

        e.Cancel = true;
        Hide();
        AppLogger.Info($"主窗口已收起（关闭原因={e.CloseReason}）");
        HiddenToTray?.Invoke();
    }

    public void ShowFront()
    {
        if (IsDisposed) return;
        if (InvokeRequired)
        {
            try { BeginInvoke(ShowFront); } catch { /* ignore */ }
            return;
        }
        Show();
        if (WindowState == FormWindowState.Minimized)
            WindowState = FormWindowState.Normal;
        Activate();
        BringToFront();
    }

    // —— 其它 ——

    private void OpenInExplorer(string rawPath, bool selectFile)
    {
        var path = (rawPath ?? "").Trim();
        if (path.Length == 0 || path == "-") return;

        try
        {
            if (selectFile && File.Exists(path))
            {
                Process.Start(new ProcessStartInfo("explorer.exe", $"/select,\"{path}\"")
                {
                    UseShellExecute = true
                });
                return;
            }

            var dir = Directory.Exists(path) ? path : Path.GetDirectoryName(path);
            if (string.IsNullOrEmpty(dir) || !Directory.Exists(dir))
            {
                MessageBox.Show(this,
                    $"路径当前不可访问：\n{path}\n\n（网络共享未连接或目录尚未生成）",
                    "打开目录", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }

            Process.Start(new ProcessStartInfo(dir) { UseShellExecute = true });
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, $"打开失败：\n{ex.Message}", "打开目录",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    private void ExportTodayLog()
    {
        var src = AppLogger.TodayLogPath;
        if (!File.Exists(src))
        {
            MessageBox.Show(this, "今日尚未生成日志文件。", "导出日志",
                MessageBoxButtons.OK, MessageBoxIcon.Information);
            return;
        }
        using var dlg = new SaveFileDialog
        {
            Title = "导出日志",
            Filter = "Log Files (*.log)|*.log|All Files (*.*)|*.*",
            FileName = $"A2B_{DateTime.Now:yyyyMMdd_HHmmss}.log"
        };
        if (dlg.ShowDialog(this) != DialogResult.OK) return;
        try
        {
            File.Copy(src, dlg.FileName, overwrite: true);
            MessageBox.Show(this, "日志导出完成。", "导出日志",
                MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, "导出日志",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
