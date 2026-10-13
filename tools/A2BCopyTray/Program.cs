using System.Diagnostics;

namespace A2BCopyTray;

internal static class Program
{
    private const string MutexName = @"Global\A2BCopyTray.SingleInstance";

    /// <summary>"请把主界面唤到前台"信号。第二个实例靠它唤醒已在运行的那个实例。</summary>
    private const string ActivateEventName = @"Global\A2BCopyTray.Activate";

    /// <summary>持有单实例互斥体；自动重启前必须先释放，否则新进程会误判"已在运行"。</summary>
    private static Mutex? _mutex;

    [STAThread]
    private static void Main()
    {
        // 命令行工具型开关先处理：不启动界面、不占单实例锁，
        // 这样部署脚本可以在程序已在运行时照样建/删桌面快捷方式。
        if (HandleCommandLine()) return;

        // 互斥体创建本身也可能抛（跨用户会话 / 完整性级别不同），必须包起来，
        // 否则异常处理器还没注册，进程会无日志静默退出。
        try
        {
            _mutex = new Mutex(true, MutexName, out var created);
            if (!created)
            {
                // 已经有实例在跑：不是弹个"已在运行"就完事 —— 那是用户在双击图标，
                // 他的意图是"把界面调出来"。让老实例把主窗口唤到前台，然后自己静默退出。
                SignalExistingInstance();
                return;
            }
        }
        catch (Exception ex)
        {
            try
            {
                File.AppendAllText(
                    Path.Combine(AppPaths.AppDir, "startup_error.log"),
                    $"{DateTime.Now:yyyy-MM-dd HH:mm:ss} 单实例互斥体创建失败: {ex}\n");
            }
            catch { /* ignore */ }
        }

        Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
        Application.ThreadException += OnThreadException;
        AppDomain.CurrentDomain.UnhandledException += OnUnhandledException;

        try
        {
            ApplicationConfiguration.Initialize();
            var cfg = ConfigStore.Load();
            Application.Run(new TrayApplicationContext(cfg, CreateActivateEvent()));
            AppLogger.Info("A2B 客户端正常退出");
        }
        catch (Exception ex)
        {
            try
            {
                File.AppendAllText(
                    Path.Combine(AppPaths.AppDir, "startup_error.log"),
                    $"{DateTime.Now:yyyy-MM-dd HH:mm:ss} {ex}\n");
            }
            catch { /* ignore */ }
            MessageBox.Show($"程序启动失败: {ex.Message}", "A2BCopyTray 错误",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        finally
        {
            try { _mutex?.Dispose(); } catch { /* ignore */ }
        }
    }

    /// <summary>
    /// 静默命令行开关（部署脚本用），返回 true 表示已处理、不进界面。
    ///
    ///   A2BCopyTray.exe --create-shortcut   在桌面创建/刷新快捷方式
    ///   A2BCopyTray.exe --remove-shortcut   删除桌面快捷方式
    ///
    /// 退出码：0 成功，1 失败。因为没有控制台，结果同时写进 logs 目录。
    /// </summary>
    private static bool HandleCommandLine()
    {
        string[] args;
        try { args = Environment.GetCommandLineArgs().Skip(1).ToArray(); }
        catch { return false; }
        if (args.Length == 0) return false;

        var cmd = args[0].TrimStart('-', '/').ToLowerInvariant();
        int code;
        switch (cmd)
        {
            case "create-shortcut":
            {
                var problem = ShortcutManager.Create();
                if (problem is null)
                {
                    AppLogger.Info($"命令行创建桌面快捷方式成功：{ShortcutManager.DesktopPath}");
                    code = 0;
                }
                else
                {
                    AppLogger.Error($"命令行创建桌面快捷方式失败：{problem}");
                    code = 1;
                }
                break;
            }
            case "remove-shortcut":
            {
                if (ShortcutManager.Remove())
                {
                    AppLogger.Info("命令行删除桌面快捷方式完成");
                    code = 0;
                }
                else
                {
                    AppLogger.Error("命令行删除桌面快捷方式失败");
                    code = 1;
                }
                break;
            }
            default:
                return false;
        }

        try { Environment.Exit(code); } catch { /* ignore */ }
        return true;
    }

    /// <summary>本进程作为"主实例"时创建激活事件；由 TrayApplicationContext 监听。</summary>
    private static EventWaitHandle? CreateActivateEvent()
    {
        try { return new EventWaitHandle(false, EventResetMode.AutoReset, ActivateEventName); }
        catch { return null; }
    }

    /// <summary>本进程作为"第二实例"时，通知已在运行的实例把主界面唤到前台。</summary>
    private static void SignalExistingInstance()
    {
        // 主实例可能正好卡在"建好互斥体、还没建激活事件"的瞬间，给它一点时间。
        for (var i = 0; i < 20; i++)
        {
            try
            {
                if (EventWaitHandle.TryOpenExisting(ActivateEventName, out var handle))
                {
                    using (handle) handle.Set();
                    return;
                }
            }
            catch { /* ignore */ }
            Thread.Sleep(100);
        }

        // 实在唤不醒（例如对面是更老的、没有这个机制的版本）→ 退回原来的提示。
        MessageBox.Show("A2B 托盘程序已在运行（请在系统托盘找到它的图标）。", "A2BCopyTray",
            MessageBoxButtons.OK, MessageBoxIcon.Information);
    }

    private static void OnThreadException(object sender, ThreadExceptionEventArgs e)
    {
        AppLogger.Error($"UI 线程异常: {e.Exception.Message}");
        var result = MessageBox.Show(
            $"程序发生异常: {e.Exception.Message}\n\n点击\"确定\"继续运行，点击\"取消\"重启程序。",
            "A2BCopyTray 异常",
            MessageBoxButtons.OKCancel,
            MessageBoxIcon.Warning);
        if (result == DialogResult.Cancel)
            TryRestart();
    }

    private static void OnUnhandledException(object sender, UnhandledExceptionEventArgs e)
    {
        var ex = e.ExceptionObject as Exception;
        AppLogger.Error($"全局未处理异常: {ex?.Message ?? "未知未处理异常"}");

        try
        {
            var cfg = ConfigStore.Load();
            if (cfg.CrashRestart)
            {
                TryRestart();      // 内部会先释放互斥体再拉起新进程
                return;
            }
        }
        catch { /* ignore */ }

        try
        {
            MessageBox.Show(
                $"程序发生严重异常: {ex?.Message ?? "未知错误"}",
                "A2BCopyTray 错误",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
        }
        catch { /* ignore */ }
    }

    private static void TryRestart()
    {
        try
        {
            AppLogger.Warn("程序崩溃，尝试自动重启...");

            // 先彻底放开单实例锁，再拉起新进程，消除"新进程看到旧实例还在"的竞态
            try { _mutex?.ReleaseMutex(); } catch { /* ignore */ }
            try { _mutex?.Dispose(); } catch { /* ignore */ }
            _mutex = null;

            var exe = Environment.ProcessPath ?? Application.ExecutablePath;
            Process.Start(new ProcessStartInfo(exe) { UseShellExecute = true });
            Environment.Exit(1);
        }
        catch
        {
            AppLogger.Error("自动重启失败");
        }
    }
}
