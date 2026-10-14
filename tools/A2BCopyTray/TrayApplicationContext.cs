namespace A2BCopyTray;

public sealed class TrayApplicationContext : ApplicationContext
{
    private readonly NotifyIcon _tray;
    private readonly SyncEngine _engine;
    private readonly HeartbeatReporter _heartbeat;
    private readonly MainForm _main;
    private AppConfig _cfg;
    private SettingsForm? _settings;

    private readonly Icon _okIcon;
    private readonly Icon _pauseIcon;
    private readonly Icon _errIcon;

    /// <summary>菜单项图标位图 —— 必须留着引用，Dispose 时一起释放。</summary>
    private readonly List<Bitmap> _menuImages = new();

    private ToolStripMenuItem _pauseItem = null!;

    /// <summary>第二实例发来的"唤出界面"信号；null 表示没有（本进程即主实例时应不为 null）。</summary>
    private readonly EventWaitHandle? _activateEvent;
    private volatile bool _disposed;

    public TrayApplicationContext(AppConfig cfg, EventWaitHandle? activateEvent = null)
    {
        _cfg = cfg;
        _activateEvent = activateEvent;
        _okIcon = StatusIcons.Create(TrayState.Ok);
        _pauseIcon = StatusIcons.Create(TrayState.Paused);
        _errIcon = StatusIcons.Create(TrayState.Error);

        _engine = new SyncEngine(_cfg);
        _engine.SnapshotChanged += OnSnapshotChanged;

        _heartbeat = new HeartbeatReporter(_cfg);
        _heartbeat.SetSnapshotProvider(() => _engine.Snapshot());

        _main = new MainForm(
            onSync: () => _engine.RequestManualSync(),
            onSettings: OpenSettings,
            onTogglePause: TogglePause);
        _main.HiddenToTray += OnHiddenToTray;
        _main.ApplySnapshot(_engine.Snapshot());

        _tray = new NotifyIcon
        {
            Icon = _okIcon,
            Text = "A2B 增量复制托盘程序",
            Visible = true,
            ContextMenuStrip = BuildMenu()
        };
        _tray.DoubleClick += (_, _) => _main.ShowFront();

        AutoStartManager.Apply(_cfg.AutoStart);
        _engine.Start();
        _heartbeat.Start();
        AppLogger.Info("A2B 客户端启动");

        // 监听"第二实例请主实例唤出界面"的信号（双击桌面图标 / 再次运行 exe）
        if (_activateEvent is not null)
        {
            var t = new Thread(ActivateLoop)
            {
                IsBackground = true,
                Name = "A2BCopyTray.ActivateListener"
            };
            t.Start();
        }

        // 启动时先弹出主界面；关掉窗口只是隐藏回托盘，不会退出
        _main.ShowFront();
    }

    /// <summary>后台等激活信号；收到就把隐藏的主窗口唤回前台。</summary>
    private void ActivateLoop()
    {
        var ev = _activateEvent!;
        while (!_disposed)
        {
            try
            {
                // 带超时的等待，这样退出时最多 1 秒就能收敛，不用等信号
                if (!ev.WaitOne(TimeSpan.FromSeconds(1))) continue;
            }
            catch (ObjectDisposedException) { break; }
            catch { continue; }

            if (_disposed) break;
            try { _main.ShowFront(); } catch { /* ignore */ }
        }
    }

    private ContextMenuStrip BuildMenu()
    {
        var menu = new ContextMenuStrip
        {
            // 与窗口同一套配色，避免默认蓝色渐变菜单
            Renderer = new FlatMenuRenderer(),
            Font = UiTheme.UiFont(),
            ShowImageMargin = true,
            BackColor = UiTheme.PanelBg,
            ImageScalingSize = new Size(16, 16),
            Padding = new Padding(0, 4, 0, 4)
        };

        menu.Items.Add(MenuItem("打开主界面", UiGlyphs.OpenInNewWindow, (_, _) => _main.ShowFront()));
        menu.Items.Add(MenuItem("系统配置", UiGlyphs.Settings, (_, _) => OpenSettings()));
        menu.Items.Add(MenuItem("立即手动同步", UiGlyphs.Sync, (_, _) => _engine.RequestManualSync()));
        _pauseItem = MenuItem(
            _cfg.StartPaused ? "开始监控" : "暂停监控",
            _cfg.StartPaused ? UiGlyphs.Play : UiGlyphs.Pause,
            (_, _) => TogglePause());
        menu.Items.Add(_pauseItem);
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add(MenuItem("创建桌面快捷方式", UiGlyphs.Monitor, (_, _) => CreateDesktopShortcut()));
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add(MenuItem("退出程序", UiGlyphs.Power, (_, _) => ExitApp()));

        foreach (ToolStripItem item in menu.Items)
            if (item is ToolStripMenuItem mi)
                mi.Padding = new Padding(6, 5, 18, 5);
        return menu;
    }

    private ToolStripMenuItem MenuItem(string text, string glyph, EventHandler onClick)
    {
        var item = new ToolStripMenuItem(text, null, onClick)
        {
            ImageScaling = ToolStripItemImageScaling.None
        };
        var bmp = UiGlyphs.Bitmap(glyph, 16, UiTheme.TextMuted);
        if (bmp is not null)
        {
            _menuImages.Add(bmp);
            item.Image = bmp;
        }
        return item;
    }

    private void OnSnapshotChanged(SyncSnapshot snap)
    {
        void apply()
        {
            _main.ApplySnapshot(snap);
            _tray.Text = BuildTrayText(snap);
            _tray.Icon = snap.Status switch
            {
                SyncStatus.Paused => _pauseIcon,
                SyncStatus.Error => _errIcon,
                _ => _okIcon
            };
            _pauseItem.Text = snap.Status switch
            {
                SyncStatus.Paused => "开始监控",
                SyncStatus.Syncing => "停止同步",
                _ => "暂停监控"
            };

            var img = UiGlyphs.Bitmap(
                snap.Status == SyncStatus.Paused ? UiGlyphs.Play : UiGlyphs.Pause, 16, UiTheme.TextMuted);
            if (img is not null)
            {
                var old = _pauseItem.Image;
                _menuImages.Add(img);
                _pauseItem.Image = img;
                if (old is Bitmap ob && _menuImages.Remove(ob)) ob.Dispose();
            }
        }
        if (_main.IsDisposed) return;

        if (_main.IsHandleCreated)
        {
            try { _main.BeginInvoke(apply); } catch { /* 窗口正在销毁 */ }
        }
        else
        {
            apply();
        }
    }

    private static string BuildTrayText(SyncSnapshot snap)
    {
        var text = $"A2B - {snap.Status} - {snap.DeviceAlias}";
        return text.Length <= 63 ? text : text[..63];
    }

    private void OnHiddenToTray()
    {
        // 只提示一次：老用户每天都在用，每次都弹会很烦
        if (_main.MinimizeTipShown) return;
        _main.MinimizeTipShown = true;
        Balloon("程序已收起，仍在后台同步", "双击托盘图标可以重新打开主界面。");
    }

    private void Balloon(string title, string text, ToolTipIcon icon = ToolTipIcon.Info)
    {
        try
        {
            _tray.BalloonTipTitle = title;
            _tray.BalloonTipText = text;
            _tray.BalloonTipIcon = icon;
            _tray.ShowBalloonTip(3000);
        }
        catch { /* 气泡失败无所谓 */ }
    }

    private void CreateDesktopShortcut()
    {
        var problem = ShortcutManager.Create();
        if (problem is not null)
        {
            MessageBox.Show(problem, "桌面快捷方式", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }
        AppLogger.Info($"已创建桌面快捷方式：{ShortcutManager.DesktopPath}");
        Balloon("A2BCopyTray", "已在桌面创建快捷方式");
    }

    private void TogglePause()
    {
        // 这是「此刻」的开关，只对本次运行有效（AppConfig.Paused 带 [JsonIgnore]，不落盘）。
        // 「启动后是否默认暂停」是另一个配置项（AppConfig.StartPaused），在系统配置里改。
        var next = !_cfg.Paused;
        _cfg.Paused = next;
        _engine.SetPaused(next);
    }

    private void OpenSettings()
    {
        // 必须先显示主窗并设为 Owner，CenterParent 才会落在主界面正中
        _main.ShowFront();
        if (_settings is { IsDisposed: false })
        {
            _settings.Activate();
            _settings.BringToFront();
            return;
        }

        using var dlg = new SettingsForm(_cfg, OnConfigChanged);
        _settings = dlg;
        try
        {
            dlg.ShowDialog(_main);
        }
        finally
        {
            _settings = null;
        }
    }

    private void OnConfigChanged(AppConfig cfg)
    {
        // 运行态以引擎为准，避免设置页打开期间托盘切换了暂停而被 Draft 旧值盖掉
        cfg.Paused = _engine.IsPaused;
        _cfg = cfg;
        if (!ConfigStore.TrySave(cfg))
            AppLogger.Warn("配置未能写入磁盘，本次运行有效但重启后会丢失");
        AutoStartManager.Apply(cfg.AutoStart);
        _engine.UpdateConfig(cfg);
        _heartbeat.UpdateConfig(cfg);
        Balloon("A2BCopyTray", "配置已更新");
        AppLogger.Info("配置已更新");
    }

    private void ExitApp()
    {
        AppLogger.Info("A2B 客户端正常退出");
        StopActivateListener();
        _main.SaveWindowState();
        _tray.Visible = false;
        try { _heartbeat.Dispose(); } catch { /* ignore */ }
        _engine.Dispose();
        _okIcon.Dispose();
        _pauseIcon.Dispose();
        _errIcon.Dispose();
        _tray.Dispose();
        _main.Dispose();
        ExitThread();
    }

    /// <summary>停掉激活监听线程（带超时等待，最多 1 秒收敛）。</summary>
    private void StopActivateListener()
    {
        _disposed = true;
        try { _activateEvent?.Dispose(); } catch { /* ignore */ }
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            StopActivateListener();
            try { _heartbeat.Dispose(); } catch { /* ignore */ }
            try { _engine.Dispose(); } catch { /* ignore */ }
            try { _tray.Dispose(); } catch { /* ignore */ }
            try { _okIcon.Dispose(); } catch { /* ignore */ }
            try { _pauseIcon.Dispose(); } catch { /* ignore */ }
            try { _errIcon.Dispose(); } catch { /* ignore */ }
            try { _main.Dispose(); } catch { /* ignore */ }
            foreach (var b in _menuImages)
                try { b.Dispose(); } catch { /* ignore */ }
            _menuImages.Clear();
        }
        base.Dispose(disposing);
    }
}
