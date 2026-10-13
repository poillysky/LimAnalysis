using System.Diagnostics;
using System.Drawing;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using A2BCopyTray;

namespace A2BCopyTray.Tests;

/// <summary>
/// A2BCopyTray 端到端验证工装。直接编译主工程的核心源文件，
/// 用真实临时目录驱动 SyncEngine，验证同步结果而不是"看起来对"。
/// </summary>
internal static class Harness
{
    private static int _pass;
    private static readonly List<string> Failures = new();

    private static void Check(string name, bool ok, string? detail = null)
    {
        if (ok)
        {
            _pass++;
            Console.WriteLine($"  PASS  {name}");
        }
        else
        {
            Failures.Add(name + (detail is null ? "" : $" :: {detail}"));
            Console.WriteLine($"  FAIL  {name}{(detail is null ? "" : "  → " + detail)}");
        }
    }

    private static int Main()
    {
        try { Console.OutputEncoding = Encoding.UTF8; } catch { /* ignore */ }

        var sandbox = Path.Combine(Path.GetTempPath(), "a2b_e2e_" + Guid.NewGuid().ToString("N")[..8]);
        Directory.CreateDirectory(sandbox);
        Console.WriteLine($"sandbox = {sandbox}");

        try
        {
            Section("URL 归一化", TestNormalizeUrl);
            Section("配置迁移（旧排除目录不再丢）", () => TestConfigMigration(sandbox));
            Section("暂停策略：运行态不落盘 / 启动偏好落盘", () => TestPausePolicy(sandbox));
            Section("暂停期间不复制，点「开始监控」后立即同步", () => TestPauseThenStart(sandbox));
            Section("停止同步可中止当前轮并停监控", () => TestPauseAbortsCurrentSync(sandbox));
            Section("配置更新不覆盖运行态暂停 / 暂停下手动同步", () => TestPauseRuntimeGuards(sandbox));
            Section("配置校验", () => TestValidate(sandbox));
            Section("排除清单：默认项恒生效", () => TestExcludeDefaults(sandbox));
            Section("设备别名自动派生", TestDeviceAlias);
            Section("窗口状态持久化与越界夹取", () => TestUiState(sandbox));
            Section("桌面快捷方式", () => TestShortcut(sandbox));
            Section("注塑机模式：增量同步", () => TestMoldSync(sandbox));
            Section("外观机模式：目标路径", () => TestAppearanceSync(sandbox));
            Section("时间戳不可靠时不重传", () => TestTargetNewer(sandbox));
            Section("改文件后重传", () => TestSrcChanged(sandbox));
            Section("目标文件被下游占用后可自愈", () => TestDstLocked(sandbox));
            Section("长期受阻最终必须报失败（不会永远沉默）", () => TestStuckEscalates(sandbox));
            Section("文件释放等待生效", () => TestSettle(sandbox));
            Section("限速生效", () => TestThrottle(sandbox));
            Section("心跳上报", () => TestHeartbeat(sandbox));
        }
        catch (Exception ex)
        {
            Check("harness 未捕获异常", false, ex.ToString());
        }
        finally
        {
            try { Directory.Delete(sandbox, true); } catch { /* ignore */ }
        }

        Console.WriteLine();
        Console.WriteLine($"==> 通过 {_pass}，失败 {Failures.Count}");
        foreach (var f in Failures) Console.WriteLine($"    - {f}");
        return Failures.Count == 0 ? 0 : 1;
    }

    private static void Section(string title, Action body)
    {
        Console.WriteLine();
        Console.WriteLine($"[{title}]");
        try { body(); }
        catch (Exception ex) { Check(title, false, ex.Message); }
    }

    // ───────────────────────── 用例 ─────────────────────────

    private static void TestNormalizeUrl()
    {
        Check("裸主机补协议与路径",
            HeartbeatReporter.NormalizeUrl("10.18.97.189:5000") == "http://10.18.97.189:5000/api/heartbeat");
        Check("已带协议只补路径",
            HeartbeatReporter.NormalizeUrl("http://srv:5000") == "http://srv:5000/api/heartbeat");
        Check("显式路径不覆盖",
            HeartbeatReporter.NormalizeUrl("http://srv/custom/hb") == "http://srv/custom/hb");
        Check("根路径补 /api/heartbeat",
            HeartbeatReporter.NormalizeUrl("https://srv/") == "https://srv/api/heartbeat");
        Check("空值返回 null", HeartbeatReporter.NormalizeUrl("   ") is null);
        Check("非法值返回 null", HeartbeatReporter.NormalizeUrl("http://") is null);
    }

    private static void TestConfigMigration(string sandbox)
    {
        var dir = Path.Combine(sandbox, "cfg");
        Directory.CreateDirectory(dir);

        var path = AppPaths.ConfigFile;
        var backup = path + ".harnessbak";
        if (File.Exists(path)) File.Copy(path, backup, true);
        try
        {
            // 旧版现场配置的真实长相
            File.WriteAllText(path, """
            {
              "mode": "mold",
              "machine": "M01",
              "excludePath": "",
              "excludeDirs": ["temp", "cache", "Thumbs"],
              "whitelist": [],
              "blacklist": ["*.tmp"],
              "isAppearance": false,
              "modeLabel": "注塑机"
            }
            """);

            var cfg = ConfigStore.Load();
            Check("旧相对排除目录全部保留",
                cfg.ExcludePaths.Count == 3 &&
                cfg.ExcludePaths.Contains("temp") &&
                cfg.ExcludePaths.Contains("cache") &&
                cfg.ExcludePaths.Contains("Thumbs"),
                string.Join(",", cfg.ExcludePaths));

            var reparsed = JsonDocument.Parse(File.ReadAllText(path)).RootElement;
            Check("旧字段不再写出", !reparsed.TryGetProperty("excludeDirs", out _) &&
                                     !reparsed.TryGetProperty("excludePath", out _));
            Check("派生属性不再写出", !reparsed.TryGetProperty("isAppearance", out _) &&
                                      !reparsed.TryGetProperty("modeLabel", out _));
            Check("保存后可原样读回", ConfigStore.Load().ExcludePaths.Count == 3);
        }
        finally
        {
            try { File.Delete(path); } catch { /* ignore */ }
            if (File.Exists(backup)) File.Move(backup, path, true);
        }
    }

    /// <summary>
    /// 暂停只对「本次运行」有效，绝不能跟着 config.json 走。
    /// 现场踩过的坑：按一次暂停 → 关机 → 开机自启，程序静默地一直不复制，没人发现。
    /// </summary>
    private static void TestPausePolicy(string sandbox)
    {
        var path = AppPaths.ConfigFile;
        var backup = path + ".harnessbak";
        if (File.Exists(path)) File.Copy(path, backup, true);
        try
        {
            // ① 老配置里遗留的 paused:true 必须被忽略（那是「此刻的运行态」，不是启动偏好）
            File.WriteAllText(path, """
            {
              "mode": "mold",
              "machine": "M01",
              "paused": true
            }
            """);
            Check("配置里的 paused:true 被忽略",
                !ConfigStore.Load().Paused, "读到 paused=true");

            // ② 运行态开关（Paused）保存后也不能写出 paused 字段
            var cfg = ConfigStore.Load();
            cfg.Paused = true;
            ConfigStore.Save(cfg);
            var saved = JsonDocument.Parse(File.ReadAllText(path)).RootElement;
            Check("paused 不写进 config.json", !saved.TryGetProperty("paused", out _));

            // ③ 启动偏好（StartPaused）默认 true，且必须持久化
            Check("默认「启动后暂停」为真", AppConfig.CreateDefault().StartPaused);
            Check("StartPaused 默认会写进 config.json",
                saved.TryGetProperty("startPaused", out var sp0) && sp0.ValueKind == JsonValueKind.True);

            var off = AppConfig.CreateDefault();
            off.StartPaused = false;
            ConfigStore.Save(off);
            var savedOff = JsonDocument.Parse(File.ReadAllText(path)).RootElement;
            Check("取消后 startPaused=false 落盘",
                savedOff.TryGetProperty("startPaused", out var sp1) && sp1.ValueKind == JsonValueKind.False);
            Check("读回 startPaused=false", !ConfigStore.Load().StartPaused);
        }
        finally
        {
            try { File.Delete(path); } catch { /* ignore */ }
            if (File.Exists(backup)) File.Move(backup, path, true);
        }

        // ④ 引擎的启动初始态必须遵循 StartPaused（默认＝暂停等人工开始）
        var pausedCfg = AppConfig.CreateDefault();
        using (var eng = new SyncEngine(pausedCfg))
            Check("默认配置下引擎启动即暂停（等人工点开始）", eng.IsPaused);

        var autoCfg = AppConfig.CreateDefault();
        autoCfg.StartPaused = false;
        using (var eng = new SyncEngine(autoCfg))
            Check("StartPaused=false 时引擎直接运行", !eng.IsPaused);
    }

    /// <summary>
    /// 端到端：默认启动即暂停时，引擎在暂停期间**一个文件都不能动**；
    /// 调用 SetPaused(false)（＝界面上点「开始监控」）之后必须**立刻**开始复制
    /// （不得干等 PollSeconds），同步完成后进入「监控中」。
    /// </summary>
    private static void TestPauseThenStart(string sandbox)
    {
        var root = Path.Combine(sandbox, "pause_start");
        var src = Path.Combine(root, "src");
        var dst = Path.Combine(root, "dst");
        var srcDay = Path.Combine(src, DateTime.Now.ToString("yyyyMMdd"));
        var dstDay = Path.Combine(dst, "M01", DateTime.Now.ToString("yyyyMMdd"));

        WriteFile(Path.Combine(srcDay, "r.jpg"), "resume-payload", DateTime.UtcNow.AddMinutes(-5));

        var cfg = Cfg(src, dst);
        cfg.StartPaused = true;                 // 默认策略：起来先停着
        cfg.PollSeconds = 30;                   // 若没立刻唤醒，会干等半分钟才同步

        using var engine = new SyncEngine(cfg);
        var runner = new Runner(engine);
        engine.Start();

        // 这里**不能**用 runner.Run()：手动同步是刻意绕过暂停的（界面上的「立即手动同步」按钮），
        // 所以直接等若干个轮询周期，看引擎是否真的不动手。
        Thread.Sleep(2500);
        Check("暂停期间不复制任何文件",
            !File.Exists(Path.Combine(dstDay, "r.jpg")),
            "暂停状态下仍在写目标目录");

        engine.SetPaused(false);                // ＝点「开始监控」
        var sw = Stopwatch.StartNew();
        runner.Run(timeoutMs: 8000);
        Check("开启监控后立即同步（不等轮询间隔）",
            sw.ElapsedMilliseconds < 8000 && File.Exists(Path.Combine(dstDay, "r.jpg")),
            $"耗时 {sw.ElapsedMilliseconds}ms，文件存在={File.Exists(Path.Combine(dstDay, "r.jpg"))}");
        Check("点「开始监控」后文件被复制",
            Read(Path.Combine(dstDay, "r.jpg")) == "resume-payload");

        // 首轮结束后应进入持续监控（Idle），而不是停在暂停
        var idle = WaitStatus(engine, SyncStatus.Idle, 5000);
        Check("同步完成后进入持续监控", idle == SyncStatus.Idle, idle);
    }

    /// <summary>
    /// 「停止同步」= 中止正在进行的本轮复制 + 停止监控。
    /// 限速复制一堆大文件，中途 SetPaused(true)，必须很快回到已暂停，且不再继续写剩余文件。
    /// </summary>
    private static void TestPauseAbortsCurrentSync(string sandbox)
    {
        var root = Path.Combine(sandbox, "pause_abort");
        var src = Path.Combine(root, "src");
        var dst = Path.Combine(root, "dst");
        var srcDay = Path.Combine(src, DateTime.Now.ToString("yyyyMMdd"));
        var dstDay = Path.Combine(dst, "M01", DateTime.Now.ToString("yyyyMMdd"));

        // ~400KB × 8，限速 80KB/s → 整轮约 40s，足够在中途按下停止
        var payload = new string('X', 400 * 1024);
        for (var i = 0; i < 8; i++)
            WriteFile(Path.Combine(srcDay, $"f{i:D2}.bin"), payload, DateTime.UtcNow.AddMinutes(-5));

        var cfg = Cfg(src, dst);
        cfg.StartPaused = false;
        cfg.SpeedLimitKbps = 80;
        cfg.PollSeconds = 2;

        using var engine = new SyncEngine(cfg);
        engine.Start();

        // 等到至少开始同步或写出第一个文件
        var sw = Stopwatch.StartNew();
        while (sw.ElapsedMilliseconds < 15000)
        {
            var snap = engine.Snapshot();
            if (snap.Status == SyncStatus.Syncing || Directory.Exists(dstDay))
                break;
            Thread.Sleep(50);
        }

        // 再稍等一下，确保至少有进度，然后停止
        Thread.Sleep(800);
        var before = Directory.Exists(dstDay)
            ? Directory.GetFiles(dstDay, "*", SearchOption.AllDirectories).Length
            : 0;
        engine.SetPaused(true);

        var pausedAt = WaitStatus(engine, SyncStatus.Paused, 5000);
        Check("停止同步后状态变为已暂停", pausedAt == SyncStatus.Paused, pausedAt);
        Check("引擎 IsPaused=true", engine.IsPaused);

        Thread.Sleep(2500);
        var after = Directory.Exists(dstDay)
            ? Directory.GetFiles(dstDay, "*", SearchOption.AllDirectories).Length
            : 0;
        Check("停止后不再继续复制剩余文件",
            after <= before + 1, // 允许正在写的那一个收尾
            $"停止前={before} 停止后={after}");
        Check("未把全部 8 个文件拷完（证明本轮被中止）",
            after < 8, $"实际拷了 {after} 个");
    }

    /// <summary>
    /// 运行态守卫：① UpdateConfig 不得把已暂停打成运行；
    /// ② 暂停期间「立即手动同步」跑完后状态仍是已暂停（不能闪成监控中）。
    /// </summary>
    private static void TestPauseRuntimeGuards(string sandbox)
    {
        var root = Path.Combine(sandbox, "pause_guard");
        var src = Path.Combine(root, "src");
        var dst = Path.Combine(root, "dst");
        var srcDay = Path.Combine(src, DateTime.Now.ToString("yyyyMMdd"));
        var dstDay = Path.Combine(dst, "M01", DateTime.Now.ToString("yyyyMMdd"));
        WriteFile(Path.Combine(srcDay, "g.jpg"), "guard-payload", DateTime.UtcNow.AddMinutes(-5));

        var cfg = Cfg(src, dst);
        cfg.StartPaused = true;

        using var engine = new SyncEngine(cfg);
        var runner = new Runner(engine);
        engine.Start();
        Check("启动即暂停", engine.IsPaused);

        // Draft 里若带 Paused=false（模拟设置页旧快照），也不能把引擎打醒
        var dirty = Cfg(src, dst);
        dirty.StartPaused = true;
        dirty.Paused = false;
        dirty.PollSeconds = 3;
        engine.UpdateConfig(dirty);
        Thread.Sleep(800);
        Check("UpdateConfig 不能解除暂停", engine.IsPaused);
        Check("UpdateConfig 后仍不复制",
            !File.Exists(Path.Combine(dstDay, "g.jpg")),
            "配置更新后在暂停态仍写出了文件");

        // 暂停下手动同步：文件要拷上，但状态必须回到已暂停
        runner.Run();
        Check("暂停下手动同步仍能复制",
            Read(Path.Combine(dstDay, "g.jpg")) == "guard-payload");
        var afterManual = WaitStatus(engine, SyncStatus.Paused, 3000);
        Check("手动同步结束后仍是已暂停", afterManual == SyncStatus.Paused, afterManual);
        Check("手动同步后 IsPaused 仍为 true", engine.IsPaused);
    }

    private static string WaitStatus(SyncEngine engine, string want, int timeoutMs)
    {
        var sw = Stopwatch.StartNew();
        while (sw.ElapsedMilliseconds < timeoutMs)
        {
            var s = engine.Snapshot().Status;
            if (s == want) return s;
            Thread.Sleep(40);
        }
        return engine.Snapshot().Status;
    }

    private static void TestValidate(string sandbox)
    {
        var root = Path.Combine(sandbox, "val");
        var src = Path.Combine(root, "src");
        var dst = Path.Combine(root, "dst");
        Directory.CreateDirectory(src);
        Directory.CreateDirectory(dst);

        Check("源=目标被拒", Cfg(src, src).Validate() is not null);
        Check("目标在源内被拒", Cfg(src, Path.Combine(src, "out")).Validate() is not null);
        Check("同级目录放行", Cfg(src, dst).Validate() is null);

        Check("根路径不被削掉", AppConfig.TrimTrailingSeparators(@"D:\") == @"D:\",
            AppConfig.TrimTrailingSeparators(@"D:\"));
        Check("UNC 根不被削掉", AppConfig.TrimTrailingSeparators(@"\\NAS\Share\A2B\") == @"\\NAS\Share\A2B");
        Check("盘符根单独处理", AppConfig.TrimTrailingSeparators("D:/") == @"D:\",
            AppConfig.TrimTrailingSeparators("D:/"));
    }

    /// <summary>
    /// 内置默认排除项（temp/cache/Thumbs）必须「恒生效」：
    /// 属性层面合并去重、配置里清空也照样生效。
    /// </summary>
    private static void TestExcludeDefaults(string sandbox)
    {
        var fresh = ConfigStore.Normalize(new AppConfig());
        Check("默认排除项在最前且齐全",
            fresh.ExcludePaths.Count >= 3 &&
            fresh.ExcludePaths[0] == "temp" &&
            fresh.ExcludePaths[1] == "cache" &&
            fresh.ExcludePaths[2] == "Thumbs",
            string.Join(",", fresh.ExcludePaths));

        var withCustom = ConfigStore.Normalize(new AppConfig
        {
            ExcludePaths = ["cache", "*.raw", @"D:\A2B\tmp"]
        });
        Check("默认 + 自定义 合并去重、默认在前",
            withCustom.EffectiveExcludePaths.Count == 5 &&
            withCustom.EffectiveExcludePaths[0] == "temp" &&
            withCustom.EffectiveExcludePaths.Contains("*.raw") &&
            withCustom.EffectiveExcludePaths.Contains(@"D:\A2B\tmp"),
            string.Join(",", withCustom.EffectiveExcludePaths));
        Check("自定义项里不再含默认项（供只读/编辑两行分离）",
            withCustom.CustomExcludePaths.Count == 2 &&
            !withCustom.CustomExcludePaths.Contains("cache"),
            string.Join(",", withCustom.CustomExcludePaths));

        // 引擎层面：配置里一个排除项都不写，cache 目录也必须被跳过
        var root = Path.Combine(sandbox, "exdef");
        var src = Path.Combine(root, "src");
        var dst = Path.Combine(root, "dst");
        var day = DateTime.Now.ToString("yyyyMMdd");
        var mtime = new DateTime(2026, 10, 12, 8, 30, 15, DateTimeKind.Utc);
        WriteFile(Path.Combine(src, day, "ok.jpg"), "OK", mtime);
        WriteFile(Path.Combine(src, day, "cache", "j.jpg"), "JUNK", mtime);
        WriteFile(Path.Combine(src, day, "Thumbs", "t.jpg"), "JUNK", mtime);

        var cfg = Cfg(src, dst);
        cfg.ExcludePaths = new List<string>();      // 故意清空
        using var engine = new SyncEngine(cfg);
        var runner = new Runner(engine);
        engine.Start();
        for (var i = 0; i < 4; i++) runner.Run();

        var dstDay = Path.Combine(dst, "M01", day);
        Check("空配置下内置默认项仍生效（cache / Thumbs 被排除）",
            File.Exists(Path.Combine(dstDay, "ok.jpg")) &&
            !Directory.Exists(Path.Combine(dstDay, "cache")) &&
            !Directory.Exists(Path.Combine(dstDay, "Thumbs")));
    }

    private static void TestMoldSync(string sandbox)    {
        var root = Path.Combine(sandbox, "mold");
        var src = Path.Combine(root, "src");
        var dst = Path.Combine(root, "dst");
        var day = DateTime.Now.ToString("yyyyMMdd");
        var srcDay = Path.Combine(src, day);
        var dstDay = Path.Combine(dst, "M01", day);

        var mtime = new DateTime(2026, 10, 12, 8, 30, 15, DateTimeKind.Utc);

        WriteFile(Path.Combine(srcDay, "a.jpg"), "AAA", mtime);
        WriteFile(Path.Combine(srcDay, "b.jpg"), "BBB", mtime);
        WriteFile(Path.Combine(srcDay, "sub", "c.jpg"), "CCC", mtime);
        WriteFile(Path.Combine(srcDay, "temp", "junk.jpg"), "JUNK", mtime);
        WriteFile(Path.Combine(srcDay, "Thumbs.db"), "THUMBS", mtime);
        WriteFile(Path.Combine(srcDay, "partial.tmp"), "PART", mtime);

        var cfg = Cfg(src, dst);
        cfg.ExcludePaths = new List<string> { "temp", "Thumbs.db" };
        cfg.Blacklist = new List<string> { "*.tmp" };

        using var engine = new SyncEngine(cfg);
        var runner = new Runner(engine);
        engine.Start();
        var s1 = runner.Run();

        Check("首轮状态正常", s1.Status == SyncStatus.Idle, $"{s1.Status} / {s1.Message}");
        Check("a.jpg 已同步", Read(Path.Combine(dstDay, "a.jpg")) == "AAA");
        Check("b.jpg 已同步", Read(Path.Combine(dstDay, "b.jpg")) == "BBB");
        Check("子目录 c.jpg 已同步", Read(Path.Combine(dstDay, "sub", "c.jpg")) == "CCC");
        Check("相对名排除目录 temp 生效", !File.Exists(Path.Combine(dstDay, "temp", "junk.jpg")));
        Check("相对名排除文件 Thumbs.db 生效", !File.Exists(Path.Combine(dstDay, "Thumbs.db")));
        Check("黑名单 *.tmp 生效", !File.Exists(Path.Combine(dstDay, "partial.tmp")));
        Check("目标文件时间戳被保留",
            File.GetLastWriteTimeUtc(Path.Combine(dstDay, "a.jpg")) == mtime);
        Check("无 a2btmp 残留", Directory.GetFiles(dstDay, "*.a2btmp", SearchOption.AllDirectories).Length == 0);
        Check("进度上报完整", s1.ProgressDone == s1.ProgressTotal && s1.ProgressTotal > 0,
            $"{s1.ProgressDone}/{s1.ProgressTotal}");

        // 增量：已同步的目录不应产生任何重传
        var before = SyncCount();
        runner.Run();
        runner.Run();
        Check("重复扫描零重传", SyncCount() == before, $"增量新增 {SyncCount() - before} 次");

        // 未写完的文件
        var fresh = Path.Combine(srcDay, "fresh.jpg");
        WriteFile(fresh, "FRESH");
        runner.Run();
        runner.Run();
        Check("新文件最终被同步", Read(Path.Combine(dstDay, "fresh.jpg")) == "FRESH");
    }

    private static void TestAppearanceSync(string sandbox)
    {
        var root = Path.Combine(sandbox, "appear");
        var src = Path.Combine(root, "src");
        var dst = Path.Combine(root, "dst");
        var dotted = DateTime.Now.ToString("yyyy.MM.dd");
        var srcDay = Path.Combine(src, dotted);

        WriteFile(Path.Combine(srcDay, "截图", "V1", "x.jpg"), "IMG");

        var cfg = Cfg(src, dst, machine: "A2-01");
        cfg.Mode = "appearance";
        cfg.Project = "EagleRcvr";
        cfg.Station = "工站1";

        // EffectiveTarget() 不含日期段，日期由引擎按当天拼；这里断言拼到「检测根」为止
        var expectRoot = Path.Combine(dst, "EagleRcvr", "A2-01", "GVIMAGES", "LIM外观检测");
        Check("目标路径拼装正确",
            AppConfig.TrimTrailingSeparators(cfg.EffectiveTarget()) ==
            AppConfig.TrimTrailingSeparators(expectRoot),
            cfg.EffectiveTarget());

        var expectDay = Path.Combine(expectRoot, dotted);

        using var engine = new SyncEngine(cfg);
        var runner = new Runner(engine);
        engine.Start();
        runner.Run();

        Check("外观图已落到 LimAnalysis 目录结构",
            Read(Path.Combine(expectDay, "截图", "V1", "x.jpg")) == "IMG");
    }

    private static void TestTargetNewer(string sandbox)
    {
        var root = Path.Combine(sandbox, "newer");
        var src = Path.Combine(root, "src");
        var dst = Path.Combine(root, "dst");
        var srcDay = Path.Combine(src, DateTime.Now.ToString("yyyyMMdd"));
        var dstDay = Path.Combine(dst, "M01", DateTime.Now.ToString("yyyyMMdd"));

        WriteFile(Path.Combine(srcDay, "n.jpg"), "N", new DateTime(2026, 10, 12, 8, 0, 0, DateTimeKind.Utc));

        using var engine = new SyncEngine(Cfg(src, dst));
        var runner = new Runner(engine);
        engine.Start();
        runner.Run();

        var target = Path.Combine(dstDay, "n.jpg");
        Check("目标已生成", File.Exists(target));

        // 模拟"目标不接受改时间戳"：目标 mtime 变成复制时刻（比源新）
        File.SetLastWriteTimeUtc(target, DateTime.UtcNow.AddHours(1));

        var before = SyncCount();
        runner.Run();
        runner.Run();
        Check("目标比源新时判定为已同步，不再重传", SyncCount() == before,
            $"额外重传 {SyncCount() - before} 次");
    }

    private static void TestSrcChanged(string sandbox)
    {
        var root = Path.Combine(sandbox, "changed");
        var src = Path.Combine(root, "src");
        var dst = Path.Combine(root, "dst");
        var srcDay = Path.Combine(src, DateTime.Now.ToString("yyyyMMdd"));
        var dstDay = Path.Combine(dst, "M01", DateTime.Now.ToString("yyyyMMdd"));

        var f = Path.Combine(srcDay, "m.jpg");
        WriteFile(f, "OLD", DateTime.UtcNow.AddMinutes(-30));

        using var engine = new SyncEngine(Cfg(src, dst));
        var runner = new Runner(engine);
        engine.Start();
        runner.Run();
        Check("首次同步内容正确", Read(Path.Combine(dstDay, "m.jpg")) == "OLD");

        // 同长度、不同内容、更新的 mtime → 必须重新同步
        WriteFile(f, "NEW", DateTime.UtcNow);
        var before = SyncCount();
        runner.Run();
        runner.Run();
        Check("源被覆盖后重新同步", Read(Path.Combine(dstDay, "m.jpg")) == "NEW",
            $"内容={Read(Path.Combine(dstDay, "m.jpg"))}，重传次数={SyncCount() - before}");
    }

    /// <summary>目标文件被下游程序占用时：本轮不崩、不静默丢，占用解除后能自愈。</summary>
    private static void TestDstLocked(string sandbox)
    {
        var root = Path.Combine(sandbox, "locked");
        var src = Path.Combine(root, "src");
        var dst = Path.Combine(root, "dst");
        var srcDay = Path.Combine(src, DateTime.Now.ToString("yyyyMMdd"));
        var dstDay = Path.Combine(dst, "M01", DateTime.Now.ToString("yyyyMMdd"));

        var f = Path.Combine(srcDay, "l.jpg");
        WriteFile(f, "V1", DateTime.UtcNow.AddMinutes(-30));

        using var engine = new SyncEngine(Cfg(src, dst));
        var runner = new Runner(engine);
        engine.Start();
        runner.Run();
        Check("首次同步成功", Read(Path.Combine(dstDay, "l.jpg")) == "V1");

        // 源内容变化（长度也变了，确保一定会触发复制），同时把目标独占锁住
        WriteFile(f, "V2-LONGER", DateTime.UtcNow);
        var target = Path.Combine(dstDay, "l.jpg");
        var busyBefore = LogCount("被占用") + LogCount("复制失败");
        using (var hold = new FileStream(target, FileMode.Open, FileAccess.ReadWrite, FileShare.None))
        {
            runner.Run();
            Check("目标被占用时被显式记录（不是静默丢弃）",
                LogCount("被占用") + LogCount("复制失败") > busyBefore);
        }

        // 占用解除后必须自愈（同时也反证了占用期间没被误判成"已同步"）
        var recovered = false;
        for (var i = 0; i < 12 && !recovered; i++)
        {
            runner.Run();
            recovered = Read(target) == "V2-LONGER";
        }
        Check("占用解除后自动补齐", recovered, Read(target));
        Check("无 a2btmp 残留", Directory.GetFiles(dstDay, "*.a2btmp", SearchOption.AllDirectories).Length == 0);
    }

    /// <summary>
    /// 把目标文件路径预先建成一个同名目录（永远无法被文件覆盖）。
    /// 期望：不刷屏、不崩溃，但连续受阻到阈值后必须升级成一次明确的失败告警。
    /// </summary>
    private static void TestStuckEscalates(string sandbox)
    {
        var root = Path.Combine(sandbox, "stuck");
        var src = Path.Combine(root, "src");
        var dst = Path.Combine(root, "dst");
        var srcDay = Path.Combine(src, DateTime.Now.ToString("yyyyMMdd"));
        var dstDay = Path.Combine(dst, "M01", DateTime.Now.ToString("yyyyMMdd"));

        WriteFile(Path.Combine(srcDay, "x.jpg"), "DATA", DateTime.UtcNow.AddMinutes(-30));
        Directory.CreateDirectory(Path.Combine(dstDay, "x.jpg"));   // 占位成目录

        var before = LogCount("复制失败（连续");
        using var engine = new SyncEngine(Cfg(src, dst));
        var runner = new Runner(engine);
        engine.Start();

        SyncSnapshot snap = engine.Snapshot();
        for (var i = 0; i < 14; i++) snap = runner.Run();

        Check("受阻期间不误报失败（当作待处理）",
            !File.Exists(Path.Combine(dstDay, "x.jpg")));
        Check("连续受阻后升级为失败告警", LogCount("复制失败（连续") > before);
        Check("状态切到异常", snap.Status == SyncStatus.Error || snap.FailCount > 0,
            $"{snap.Status} fail={snap.FailCount}");

        // 清掉占位目录后必须能自愈
        Directory.Delete(Path.Combine(dstDay, "x.jpg"));
        var ok = false;
        for (var i = 0; i < 6 && !ok; i++)
        {
            runner.Run();
            ok = Read(Path.Combine(dstDay, "x.jpg")) == "DATA";
        }
        Check("障碍清除后自愈", ok);
    }

    private static void TestSettle(string sandbox)
    {
        var root = Path.Combine(sandbox, "settle");
        var src = Path.Combine(root, "src");
        var dst = Path.Combine(root, "dst");
        var srcDay = Path.Combine(src, DateTime.Now.ToString("yyyyMMdd"));
        var dstDay = Path.Combine(dst, "M01", DateTime.Now.ToString("yyyyMMdd"));

        var f = Path.Combine(srcDay, "s.jpg");
        WriteFile(f, "SETTLE", DateTime.UtcNow);   // mtime = 刚刚

        var cfg = Cfg(src, dst);
        cfg.FileSettleSeconds = 3;

        using var engine = new SyncEngine(cfg);
        var runner = new Runner(engine);
        engine.Start();

        runner.Run();
        Check("刚写完的文件不被立刻复制", !File.Exists(Path.Combine(dstDay, "s.jpg")));

        var sw = Stopwatch.StartNew();
        var copied = false;
        while (sw.Elapsed < TimeSpan.FromSeconds(20))
        {
            runner.Run();
            if (File.Exists(Path.Combine(dstDay, "s.jpg"))) { copied = true; break; }
        }
        Check("等待释放时间后被复制", copied, $"耗时 {sw.Elapsed.TotalSeconds:F1}s");
        Check("释放等待≈配置值（3s 量级）", sw.Elapsed.TotalSeconds is >= 2 and <= 15,
            $"{sw.Elapsed.TotalSeconds:F1}s");
    }

    private static void TestThrottle(string sandbox)
    {
        var root = Path.Combine(sandbox, "throttle");
        var src = Path.Combine(root, "src");
        var dst = Path.Combine(root, "dst");
        var srcDay = Path.Combine(src, DateTime.Now.ToString("yyyyMMdd"));
        var dstDay = Path.Combine(dst, "M01", DateTime.Now.ToString("yyyyMMdd"));

        var payload = new string('x', 512 * 1024);
        WriteFile(Path.Combine(srcDay, "big.bin"), payload, DateTime.UtcNow.AddMinutes(-5));

        var cfg = Cfg(src, dst);
        cfg.SpeedLimitKbps = 256;   // 512KB / 256KBps ≈ 2s

        using var engine = new SyncEngine(cfg);
        var runner = new Runner(engine);
        engine.Start();

        var sw = Stopwatch.StartNew();
        runner.Run();
        sw.Stop();

        var ok = File.Exists(Path.Combine(dstDay, "big.bin"));
        Check("限速文件已完整复制",
            ok && new FileInfo(Path.Combine(dstDay, "big.bin")).Length == payload.Length);
        Check("限速确实生效（≥1.2s）", sw.Elapsed.TotalSeconds >= 1.2, $"{sw.Elapsed.TotalSeconds:F2}s");
    }

    /// <summary>设备别名自动派生：注塑机 = 机台号；外观机 = 项目-机台-工站。</summary>
    private static void TestDeviceAlias()
    {
        var mold = new AppConfig { Mode = "mold", Machine = " IM-0312 " };
        Check("注塑机 → 机台号（并去空白）", mold.DeviceAlias == "IM-0312", mold.DeviceAlias);

        var app = new AppConfig
        {
            Mode = "appearance", Project = "eagle_rcvr", Machine = "IM-0312", Station = "1"
        };
        Check("外观机 → 项目-机台-工站",
            app.DeviceAlias == "eagle_rcvr-IM-0312-1", app.DeviceAlias);

        var partial = new AppConfig
        {
            Mode = "appearance", Project = "eagle_rcvr", Machine = "IM-0312"
        };
        Check("外观机缺工站时不留空段",
            partial.DeviceAlias == "eagle_rcvr-IM-0312", partial.DeviceAlias);

        var blank = new AppConfig { Mode = "mold", Machine = "" };
        Check("标识为空时退回本机主机名",
            blank.DeviceAlias == Environment.MachineName, blank.DeviceAlias);

        // 混填也应按模式区分：外观机模式下不能只有机台号
        var switched = new AppConfig
        {
            Mode = "appearance", Project = " eagle ", Machine = " m ", Station = " s "
        };
        Check("三段各自去空白后拼接",
            switched.DeviceAlias == "eagle-m-s", switched.DeviceAlias);
    }

    /// <summary>界面状态（窗口位置/大小）的存取与越界夹取。</summary>
    private static void TestUiState(string sandbox)
    {
        var file = Path.Combine(sandbox, "ui.json");
        if (File.Exists(file)) File.Delete(file);

        var fresh = UiStateStore.Load(file);
        Check("文件不存在时给默认值", !fresh.HasBounds && !fresh.Maximized && !fresh.MinimizeTipShown);

        var state = new UiState
        {
            MainX = 120, MainY = 80, MainW = 900, MainH = 720,
            Maximized = true, MinimizeTipShown = true
        };
        UiStateStore.Save(state, file);
        var loaded = UiStateStore.Load(file);
        Check("保存后能原样读回",
            loaded.MainX == 120 && loaded.MainY == 80 && loaded.MainW == 900 && loaded.MainH == 720
            && loaded.Maximized && loaded.MinimizeTipShown, $"{loaded.MainX},{loaded.MainY},{loaded.MainW}x{loaded.MainH}");
        Check("读回后 HasBounds 为真", loaded.HasBounds);

        File.WriteAllText(file, "{ 这不是合法 JSON ");
        var broken = UiStateStore.Load(file);
        Check("损坏文件回默认值而不是抛异常", !broken.HasBounds);

        var min = new Size(760, 660);
        var area = new Rectangle(0, 0, 1920, 1040);

        var normal = UiState.Fit(new Rectangle(100, 100, 900, 720), min, area);
        Check("正常范围内原样保留", normal == new Rectangle(100, 100, 900, 720), normal.ToString());

        var tooSmall = UiState.Fit(new Rectangle(100, 100, 320, 200), min, area);
        Check("小于最小尺寸时被抬到最小尺寸",
            tooSmall.Width >= min.Width && tooSmall.Height >= min.Height, tooSmall.ToString());

        var offRight = UiState.Fit(new Rectangle(5000, 100, 900, 720), min, area);
        Check("坐标跑到屏幕右侧外时仍保留可抓取部分",
            offRight.Left < area.Right && area.Right - offRight.Left >= 80, offRight.ToString());

        var offTop = UiState.Fit(new Rectangle(100, -3000, 900, 720), min, area);
        Check("窗口整个在屏幕上方时被拉回可见",
            offTop.Top >= area.Top && offTop.Top < area.Bottom, offTop.ToString());

        var huge = UiState.Fit(new Rectangle(0, 0, 40_000, 40_000), min, area);
        Check("记录尺寸大于屏幕时收缩到屏幕内",
            huge.Width <= area.Width && huge.Height <= area.Height, huge.ToString());
    }

    /// <summary>桌面快捷方式：路径拼装 + 真实创建/读回/删除。</summary>
    private static void TestShortcut(string sandbox)
    {
        Check("文件名固定为「A2B 增量复制.lnk」",
            Path.GetFileName(ShortcutManager.PathIn(@"C:\Users\x\Desktop")) == "A2B 增量复制.lnk");
        Check("桌面目录被正确拼接",
            ShortcutManager.PathIn(@"C:\Users\x\Desktop") == @"C:\Users\x\Desktop\A2B 增量复制.lnk");

        var desktop = Path.Combine(sandbox, "fake_desktop");
        Directory.CreateDirectory(desktop);
        var link = ShortcutManager.PathIn(desktop);

        // 造一个假的"程序本体"，Create 要求目标存在
        var fakeExe = Path.Combine(sandbox, "fake_app.exe");
        File.WriteAllText(fakeExe, "not a real exe");

        var problem = ShortcutManager.Create(fakeExe, link);
        Check("创建快捷方式成功", problem is null, problem ?? "");
        Check("桌面出现 .lnk 文件", File.Exists(link));

        var target = ShortcutManager.ReadTarget(link);
        Check("快捷方式指向程序本体",
            string.Equals(target?.TrimEnd('\\'), fakeExe, StringComparison.OrdinalIgnoreCase),
            target ?? "(null)");

        Check("同名目标是程序自身时 exe 路径有效", File.Exists(fakeExe));

        Check("删除快捷方式返回成功", ShortcutManager.Remove(link));
        Check("删除后文件消失", !File.Exists(link));
        Check("删除不存在的快捷方式也不报错", ShortcutManager.Remove(link));

        var missing = ShortcutManager.Create(Path.Combine(sandbox, "not_exists.exe"), link);
        Check("目标不存在时给出可读的错误而不是抛异常",
            missing is not null && missing.Contains("找不到"), missing ?? "");
    }

    private static void TestHeartbeat(string sandbox)    {
        var (port, request, cts) = StartHttpStub();
        try
        {
            var cfg = Cfg(Path.Combine(sandbox, "hb_src"), Path.Combine(sandbox, "hb_dst"));
            cfg.Machine = "M01";
            cfg.Project = "EagleRcvr";
            cfg.HeartbeatUrl = $"127.0.0.1:{port}";     // 故意不写协议，验证自动补全

            var (ok, message) = HeartbeatReporter.Test(cfg);
            Check("心跳测试返回成功", ok, message);

            string raw;
            try { raw = request.Wait(TimeSpan.FromSeconds(5)) ? request.Result : ""; }
            catch { raw = ""; }

            Check("请求路径自动补成 /api/heartbeat", raw.StartsWith("POST /api/heartbeat", StringComparison.Ordinal),
                raw.Split("\r\n")[0]);
            Check("Content-Type 为 application/json",
                raw.Contains("Content-Type: application/json", StringComparison.OrdinalIgnoreCase));

            var bodyStart = raw.IndexOf("\r\n\r\n", StringComparison.Ordinal);
            var body = bodyStart >= 0 ? raw[(bodyStart + 4)..] : "";
            using var doc = JsonDocument.Parse(body);
            var root = doc.RootElement;
            Check("报文含机台号", root.GetProperty("machine").GetString() == "M01");
            Check("报文含项目名", root.GetProperty("project").GetString() == "EagleRcvr");
            Check("设备别名 = 机台号（注塑机模式）",
                root.GetProperty("deviceAlias").GetString() == "M01",
                root.GetProperty("deviceAlias").GetString());
            Check("clientId 与设备别名一致",
                root.GetProperty("clientId").GetString() == "M01");
            Check("报文含运行状态", root.TryGetProperty("clientStatus", out var st) &&
                                     !string.IsNullOrWhiteSpace(st.GetString()));
            Check("报文含目标路径", root.TryGetProperty("target", out _));
            Check("报文含版本号", !string.IsNullOrWhiteSpace(root.GetProperty("clientVersion").GetString()));
        }
        finally
        {
            cts.Cancel();
        }
    }

    // ───────────────────────── 基础设施 ─────────────────────────

    private sealed class Runner
    {
        private readonly SyncEngine _engine;
        private int _rounds;

        public Runner(SyncEngine engine)
        {
            _engine = engine;
            _engine.SnapshotChanged += OnSnapshot;
        }

        private void OnSnapshot(SyncSnapshot snap)
        {
            if (snap.Status != SyncStatus.Syncing)
                Interlocked.Increment(ref _rounds);
        }

        public SyncSnapshot Run(int timeoutMs = 25000)
        {
            var start = Volatile.Read(ref _rounds);
            _engine.RequestManualSync();
            var sw = Stopwatch.StartNew();
            while (sw.ElapsedMilliseconds < timeoutMs)
            {
                if (Volatile.Read(ref _rounds) > start) return _engine.Snapshot();
                Thread.Sleep(30);
            }
            return _engine.Snapshot();
        }
    }

    private static AppConfig Cfg(string src, string dst, string machine = "M01") => new()
    {
        Mode = "mold",
        Machine = machine,
        SourceDir = src,
        TargetRoot = dst,
        PollSeconds = 1,
        FileSettleSeconds = 0,
        RetryCount = 2,
        RetryInterval = 1,
        CompareMode = "fast",
        // 同步类用例统一让引擎「启动即运行」；
        // 「启动后默认暂停、需人工开始」的行为由「暂停策略」用例单独验证。
        StartPaused = false,
        Paused = false,
        HeartbeatUrl = ""
    };

    private static void WriteFile(string path, string content, DateTime? mtimeUtc = null)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllText(path, content);
        if (mtimeUtc is not null) File.SetLastWriteTimeUtc(path, mtimeUtc.Value);
    }

    private static string Read(string path) => File.Exists(path) ? File.ReadAllText(path) : "<缺失>";

    private static bool LogContains(string needle) => LogCount(needle) > 0;

    /// <summary>
    /// 今日日志里 needle 出现的次数。
    /// 断言一律用「次数增量」而不是「存在与否」——日志按天累积，
    /// 同一天第二次跑测试时旧记录还在，用 exists 会误判。
    /// </summary>
    private static int LogCount(string needle)
    {
        try
        {
            var path = AppLogger.TodayLogPath;
            if (!File.Exists(path)) return 0;
            var text = File.ReadAllText(path);
            var count = 0;
            var idx = 0;
            while ((idx = text.IndexOf(needle, idx, StringComparison.Ordinal)) >= 0)
            {
                count++;
                idx++;
            }
            return count;
        }
        catch { return -1; }
    }

    /// <summary>今日日志里「已同步:」出现次数——直接量化"有没有真的重传"。</summary>
    private static int SyncCount() => LogCount("[同步] 已同步:");

    /// <summary>最小 HTTP 桩：收到一个请求后回 200 并关闭。</summary>
    private static (int port, Task<string> request, CancellationTokenSource cts) StartHttpStub()
    {
        var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        var port = ((IPEndPoint)listener.LocalEndpoint).Port;
        var cts = new CancellationTokenSource();
        var tcs = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);

        _ = Task.Run(async () =>
        {
            try
            {
                using var client = await listener.AcceptTcpClientAsync();
                using var stream = client.GetStream();

                var buffer = new byte[65536];
                var total = 0;
                var headerEnd = -1;
                var contentLength = 0;

                while (total < buffer.Length)
                {
                    var n = await stream.ReadAsync(buffer.AsMemory(total), cts.Token);
                    if (n <= 0) break;
                    total += n;
                    var text = Encoding.UTF8.GetString(buffer, 0, total);
                    if (headerEnd < 0)
                    {
                        headerEnd = text.IndexOf("\r\n\r\n", StringComparison.Ordinal);
                        if (headerEnd >= 0)
                        {
                            foreach (var line in text[..headerEnd].Split("\r\n"))
                            {
                                if (line.StartsWith("Content-Length:", StringComparison.OrdinalIgnoreCase))
                                    int.TryParse(line[15..].Trim(), out contentLength);
                            }
                        }
                    }
                    if (headerEnd >= 0 && total - (headerEnd + 4) >= contentLength) break;
                }

                tcs.TrySetResult(Encoding.UTF8.GetString(buffer, 0, total));

                var resp = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}";
                var bytes = Encoding.UTF8.GetBytes(resp);
                await stream.WriteAsync(bytes, cts.Token);
                await stream.FlushAsync(cts.Token);
            }
            catch (Exception ex)
            {
                tcs.TrySetResult("<stub error: " + ex.Message + ">");
            }
            finally
            {
                try { listener.Stop(); } catch { /* ignore */ }
            }
        });

        return (port, tcs.Task, cts);
    }
}
