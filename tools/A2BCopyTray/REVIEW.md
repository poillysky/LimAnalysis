# A2BCopyTray 缺陷审查（2026-10-12）

审查对象：`tools/A2BCopyTray/*.cs`（v1.5.0，net8.0-windows WinForms）
对照物：`refence/legacy-src/A2B/`（旧版 EXE 的字符串/路径清单）与 `backend/app/core/inspection.py` 的目录约定

**总体结论：能跑，但有两个必须修的问题。**
一是同步主循环对**每个文件**都强制等 1 秒（且排在"是否已同步"判断**之前**），当天目录文件一多，一轮同步会拖到几十分钟，`监控延迟(秒)` 形同虚设；
二是相对旧版丢了三块功能 —— **心跳上报整块没实现**（界面还留着三个配置项）、**目标磁盘余量检查**、**多个排除目录**（旧配置里的 `temp/cache/Thumbs` 会被静默丢弃）。
另外还有一条静默的"无限重传"路径，需要一并处理。

---

> ## 修复状态（2026-10-12 晚，v1.6.0）
>
> **本文件列出的问题已全部修复**，另新增/恢复了若干健壮性处理。逐条状态：
>
> | 编号 | 问题 | 状态 |
> | --- | --- | --- |
> | P0-1 | 每文件每轮固定 sleep 1s，且在 SameFile 之前 | ✅ 已修（两轮观测，零阻塞；SameFile 提前） |
> | P0-2 | `Math.Min(settle,1)` 把 10/120s 夹成 1s | ✅ 已修（settle 语义归位） |
> | P0-3 | 目标 mtime 写失败被吞 → 每轮全量重传 | ✅ 已修（降级为"目标不比源旧"即判同一 + 告警） |
> | P0-4 | 心跳上报整块未实现（死配置） | ✅ 已实现 `HeartbeatReporter`（含设置页"测试"） |
> | P0-5 | 排除目录语义回退，旧值静默全丢 | ✅ 已修（`ExcludePaths` 多行 + 三类字段合并迁移） |
> | P0-6 | 目标不可达时每轮阻塞 3×SMB 超时 + 30s PS 兜底 | ✅ 已修（45s 冷却退避 + 250ms 轮询可取消） |
> | P0-7 | `Stop()` 超时后仍 Dispose CTS → 弹"严重异常" | ✅ 已修（未 join 不 Dispose；重启前先释放互斥） |
> | 其他 | 目标磁盘余量检查（旧版有） | ⚠️ 未恢复（见下方说明） |
> | 其他 | 逐级容错递归枚举（旧版 `GetAllFilesSafe`） | ✅ 已修（`SafeEnumerateFiles` 迭代栈遍历） |
> | 其他 | tmp 失败降级直接复制 | ✅ 已修（temp→Move，失败回退 Copy） |
> | 其他 | `EnsureDir` 第三类通用 catch | ✅ 已修 |
>
> 新增健壮性：复制瞬态/硬失败区分（HResult 32/33）、`TransientStrikeLimit=10` 长阻塞升级、
> 默认黑名单补 `Thumbs.db`/`desktop.ini`、配置损坏备份 `config.broken_*.json`、
> `Validate()` 拒绝 source==target / target⊂source。
>
> 验证：`A2BCopyTray.Tests` 端到端 **56/56 通过**；主工程 `build -c Release` **0 警告 0 错误**；
> 真机 smoke（老格式配置迁移 + 实际同步 + 排除生效 + 0 个 `.a2btmp` 残留）通过。

---

## P0 — 必须修

### P0-1 每个文件每轮固定等 1 秒，且排在"已同步"判断之前 【性能硬伤】

`SyncEngine.cs:186-205`

```csharp
foreach (var srcFile in files)
{
    ...
    if (!FileReady(srcFile, cfg.FileSettleSeconds))   // ← 192：这里会 sleep
    { ... continue; }
    if (SameFile(srcFile, dstFile, cfg.CompareMode))   // ← 197：已同步的才在这里被跳过
        continue;
```

`FileReady()`（`SyncEngine.cs:296-309`）在 `settle > 0` 时无条件 `Thread.Sleep`，也就是说**已经同步过的文件，每轮仍要付 1 秒**。

后果（默认 `fileSettleSeconds = 10`，`pollSeconds = 5`）：

| 当天目录文件数 | 单轮耗时下限 |
|---|---|
| 50 | ≈ 50 s |
| 500 | ≈ 8.3 min |
| 2000 | ≈ 33 min |

现场一天几百到几千张图，实际效果是"新图要等十几分钟才开始传"，而且 `监控延迟(秒)=5` 完全不起作用。同时每个文件还会 `Publish()` 一次 → 托盘/主界面 UI 消息与日志刷屏（`SyncEngine.cs:191`）。

**修法**：把 `SameFile` 判断提到 `FileReady` 之前，`FileReady` 只对"确实需要复制"的文件调用。更好的做法是去掉 sleep 型探测，改成"记录上轮 (size, mtime)，连续两轮一致才认为稳定"——不阻塞、语义更准。

### P0-2 `文件释放等待` 的配置值被夹到 1 秒，与界面语义不符

`SyncEngine.cs:304`

```csharp
Thread.Sleep(TimeSpan.FromSeconds(Math.Min(settle, 1)));
```

`Math.Min(settle, 1)` 意味着不管界面填 10 秒还是 120 秒，实际只观察 1 秒。设置页却写"文件释放等待"（`SettingsForm.cs:177`），用户会以为"文件写完 10 秒后才同步"。

具体风险：相机/外观机写图较慢时，1 秒内 size+mtime 没变就会被判"已就绪"，复制出**半截文件**；好在下轮源文件 mtime 变了会被重新覆盖，属于自愈，但白白多传一次（且目标上短暂存在坏图，下游若在扫描会读到）。

### P0-3 覆盖时间戳失败被静默忽略 → 已同步的文件每轮全量重传

`SyncEngine.cs:342` + `311-324`

```csharp
try { File.SetLastWriteTimeUtc(dst, File.GetLastWriteTimeUtc(src)); } catch { /* ignore */ }
```

fast 模式判定"同一文件"靠 `|src.LastWriteTimeUtc - dst.LastWriteTimeUtc| < 2s`。如果目标共享盘不允许改时间戳（SMB 权限、某些 NAS/网关），这个 catch 会**无声吞掉失败**，于是 `SameFile` 永远返回 `false` → 每个文件每轮重传一遍，且日志里只看到"已同步"，看不出异常。配合 P0-1，性能雪上加霜。

**修法**：① 该 catch 至少 `AppLogger.Warn` 一次（去重）；② 增加兜底判定（例如时间戳写入失败则退回"大小 + 名称"判定），或干脆在设置页把该状态暴露出来。

### P0-4 心跳上报：整块功能缺失，但界面保留了三个配置项

- `AppConfig.cs:20-21, 28` 定义了 `DeviceAlias` / `HeartbeatUrl` / `HeartbeatSeconds`
- `SettingsForm.cs:143-150, 159, 177-180` 把"设备别名 / 心跳地址 / 心跳间隔(秒)"三个输入框放到了界面上
- 全仓检索：**没有任何一处 HTTP 调用**，`System.Net.Http` 未被引用，配置读进来就再也没被用过

旧版是有这一块的（`refence/legacy-src/A2B/_method_strings_utf8.txt:63-68`）：

```
==== HeartbeatReporter::SendHeartbeat ====
  POST / application/json
  心跳响应状态: / 心跳上报已恢复 / 心跳上报失败:
```

旧版设置页还会把心跳地址自动补全（`http://` 前缀 + `/api/heartbeat` 后缀）。现在：
1. 运维以为客户端在向服务端报道，实际上从来不报；
2. `HeartbeatSeconds` 这个数字调了没有任何反应。

**修法**：要么把 `HeartbeatReporter` 补回来（POST JSON，失败按间隔重试并在日志里区分"已恢复/失败"），要么把这三项从 `SettingsForm` 摘掉并在 `AppConfig` 标注 deprecated。**保持现状最糟**——界面在说谎。

### P0-5 排除目录：语义被改掉，旧配置被静默丢弃

旧版是「排除目录(相对路径，每行一条)」，可写多条；新版 `AppConfig.cs:37` 换成了**单个绝对路径** `ExcludePath`，迁移逻辑在 `ConfigStore.cs:78-85`：

```csharp
var abs = cfg.ExcludeDirs.Select(x => x.Trim())
    .FirstOrDefault(x => x.StartsWith(@"\\") || x.Contains(':') || x.Contains('\\') || x.Contains('/'));
```

旧配置的实际长相（`dist/config.json` 里就是）：

```json
"excludeDirs": ["temp", "cache", "Thumbs"]
```

三条**都不含** `\` 或 `:` → 全部被判为"不是路径"→ 丢弃，随后 `cfg.ExcludeDirs = null` 永久抹掉。结果：
- 现场从旧版升级，排除规则**全部失效**，`temp/cache/Thumbs` 里的文件会开始往目标同步；
- 新版也只能排**一个**目录，表达能力下降；
- `Thumbs.db` 这类垃圾文件没有任何默认拦截（黑名单默认只有 `*.tmp/*.temp/*.part`，`SyncEngine.cs:35`）。

**修法**：把 `ExcludePath` 改回 `List<string>`（相对名 + 绝对路径都支持），或至少保留旧值到日志/提示里，别静默丢。

### P0-6 目标共享不可达时，一轮会阻塞 1~2 分钟，期间暂停/退出都无响应

`SyncEngine.cs:159` 每轮都调 `EnsureDir(target)`，而 `EnsureDir`（`376-396`）：

- 失败重试 3 次，每次之间 `Thread.Sleep(1000)`
- 3 次都失败且是 UNC → 再拉 `powershell.exe` 做兜底，`WaitForExit(30_000)`

网络抖动/交换机重启时，`Directory.CreateDirectory` 本身还会先耗掉 SMB 超时（常见 20 s 量级）。最坏单轮 ≈ `3×20 + 3 + 30` ≈ **90 s+**，这段时间 `_cts` 检查不到（都在 sleep 里），界面按钮点了没反应。`Stop()` 只 `Join(8s)` 且**不检查返回值**（`SyncEngine.cs:35-41`）。

### P0-7 退出时可能在引擎线程存活的情况下释放同步原语 → 弹"严重异常"框

`SyncEngine.cs:43-50`

```csharp
Stop();                  // 内部 Join(8s)，超时也不报错
_cts.Dispose();          // 48
_wake.Dispose();         // 49
```

线程若正卡在限速 `Thread.Sleep(n / limit)`（`SyncEngine.cs:370`，限速越低睡越久）、重试间隔、或上面的 PowerShell 兜底里，`Join` 会超时，然后 `_cts`/`_wake` 就被释放了。线程醒来后执行 `while (!_cts.IsCancellationRequested)`（`89`）或 `_wake.WaitOne`（`116`）→ **`ObjectDisposedException`** → 走 `AppDomain.UnhandledException` → 后台线程上弹模态框并终止进程（`Program.cs:57-73`）。

**修法**：`Stop()` 返回是否成功；未成功就不要 Dispose（或用独立 `volatile bool` 标志代替对已释放 CTS 的读取）。

---

## P1 — 相对旧版的功能缺失 / 健壮性

| # | 问题 | 位置 | 旧版对应 |
|---|---|---|---|
| P1-1 | 目标磁盘余量检查被删掉了，磁盘写满时只会疯狂重试并留下半截文件 | 缺失 | `SyncEngine::EnsureTargetHasSpace` +「目标磁盘空间不足」 |
| P1-2 | 递归枚举用 `EnumerateFiles(..., AllDirectories)`，**任一子目录无权限或路径过长就整体抛异常**，后续文件全部漏掉（只留一条警告），下轮再来一遍 | `SyncEngine.cs:238-262` | `SyncEngine::GetAllFilesSafe` 逐目录递归，逐级 catch（无权访问目录/子目录列表 IO 错误…） |
| P1-3 | 临时文件方式失败后**没有降级到直接复制**，某些 SMB/网关对 `File.Move(overwrite)` 不友好时会一直失败 | `SyncEngine.cs:355-374` | `CopyFileWithThrottle` 有「使用临时文件方式复制失败，尝试直接复制」 |
| P1-4 | `EnsureDir` 只 catch `UnauthorizedAccessException` / `IOException`，缺通用 `catch`；非法路径（如 `\\SERVER`）会以 `ArgumentException`/`NotSupportedException` 冒到主循环 | `SyncEngine.cs:376-396` | 旧版有第三类「创建目录异常」 |
| P1-5 | 目标目录会短暂出现 `xxx.jpg.a2btmp`；**崩溃/断电后残留的 tmp 永远没人清理**（只有下次复制同一文件时才删） | `SyncEngine.cs:357,373` | 旧版有「清理了旧的临时文件」日志（说明有清扫） |
| P1-6 | 「崩溃自启动」与单实例互斥体存在竞态：`TryRestart` 里 `Process.Start` 后立刻 `Environment.Exit(1)`，新进程可能在旧进程释放 `Global\A2BCopyTray.SingleInstance` 之前起来 → 弹「已在运行」后退出，自愈失败 | `Program.cs:75-88`、`12-18` | 同 |
| P1-7 | `new Mutex(...)` 写在 `try` 之外：跨用户会话或高低完整性级别（操作员有时用管理员跑一次）下可能抛 `UnauthorizedAccessException`，此时异常处理器尚未注册，进程**无日志静默消失** | `Program.cs:12` | 同 |
| P1-8 | `ConfigStore.Save()` 无异常处理，被 `TogglePause`/`OnConfigChanged` 直接调用；EXE 放在 `Program Files` 或只读盘时点"暂停"会弹异常框 | `ConfigStore.cs:38-43`、`TrayApplicationContext.cs:95,125` | — |
| P1-9 | `ConfigStore.Load()` 解析失败**静默回落默认值且不备份**损坏文件；磁盘错误也一并被吞，现场无法定位"配置为什么变了" | `ConfigStore.cs:32-35` | — |

---

## P2 — 正确性细节

1. **`TrimEnd('\\','/')` 会破坏根路径**（`AppConfig.cs:78`、`90`）
   `\\SERVER\` → `\\SERVER`（非法 UNC）；`D:\` → `D:`（语义从"根"变成"当前盘当前目录"）。同理 `ExcludePath`。

2. **`Validate()` 不检查源/目标重叠**（`AppConfig.cs:60-74`）
   若目标目录落在源目录树内（现场手填很容易发生），当天的图会被复制进自己的扫描范围，越传越多。建议加一句"目标不能位于源目录内"。

3. **fast 模式 2 秒容差在非 NTFS 目标上偏紧**（`SyncEngine.cs:321`）
   exFAT/SMB 网关的时间戳粒度可能正好 2 秒 → `Math.Abs(...) < 2` 为 false → 反复重传。建议改成比较"截断到秒"的差 ≤ 2，或把容差放宽到 3 秒。

4. **通配符只按 `/` 匹配相对路径**（`SyncEngine.cs:248-253`）
   相对路径已被 `.Replace('\\','/')`，用户按 Windows 习惯写 `sub\*.jpg` 会匹配不上；`MatchWildcard` 每文件每规则都 `new Regex` 且**没有超时**，写 `*a*a*a*a*a*a*` 会造成回溯卡顿。

5. **md5 模式每轮对全部文件（含已同步的）双向读取**（`SyncEngine.cs:319-320`）
   走网络共享时开销很大，建议先过一遍 size 再算 hash。

6. **日志开销**：`AppLogger.Write` 每行都 `AppPaths.LogsDir`（内含 `Directory.CreateDirectory`）+ `AppendAllText`（开关文件两次）；`Cleanup()` 只在"当天目录存在且走完文件循环"后才调用（`SyncEngine.cs:214`），源目录缺失时永远不清理。

7. **无扩展名过滤**：源目录里任何类型文件都会同步，`Thumbs.db`/`*.ini`/临时导出文件都会进目标盘。

8. **每轮重复告警**：目标不可用、文件仍在写入等日志每轮重写一遍，日志文件膨胀很快。

---

## P3 — 体验与可维护性

1. **状态用中文字符串硬比较**，贯穿三处：`SyncEngine.cs:465`、`TrayApplicationContext.cs:72-77`、`MainForm.cs:324-332`。旧版用的是枚举 + `EnumDisplayExtensions.ToDisplayText()`。现在只要有人改一个字的文案，托盘图标/按钮文字就会错。
2. **进度条没有真进度**：只有 marquee 滚来滚去（`MainForm.cs:334-344`），既不给"第 N / 共 M 个文件"，也不给百分比 —— 在 P0-1 那么慢的情况下用户完全看不出到底有没有在动。
3. **设置页存在死配置**（见 P0-4）：设备别名、心跳地址、心跳间隔；另外"文件释放等待"文案与实现不符（P0-2）。
4. **`config.json` 写入了派生属性** `isAppearance` / `modeLabel` / `identityLabel`（见 `dist/config.json`）。反序列化时因无 setter 被忽略，不影响功能，但会让人误以为可以手改。建议给它们加 `[JsonIgnore]`。
5. **`_envLogged` 只记一次**（`SyncEngine.cs:141-149`）：改完配置后不再重新诊断，排查时看不到新目标路径的诊断行。
6. **打包产物冗余**：`dist/` 与 `dist_new/` 里两个 EXE 的 MD5 完全相同（`8f29412947623c1cea839a02c78f56a1`），`dist_new` 可以删掉。
7. **`README.md` 没提心跳/设备别名**，与界面不一致（建议与 P0-4 一起收口）。
8. 无测试、无 CI。

---

## 目标路径核对（结论：与 LimAnalysis 一致）

| 模式 | A2BCopyTray 实际写入 | LimAnalysis 约定 | 结论 |
|---|---|---|---|
| 注塑机 | `{目标}/{机台号}/{yyyyMMdd}/…` | `mold_root_path/机台/生产日` | ✔ |
| 外观机 | `{目标}/{项目}/{外观机号}/GVIMAGES/LIM外观检测/{yyyy.MM.dd}/…` | `project/tester/GVIMAGES/LIM外观检测/date/截图/view/file`（`inspection.py:53-54`、`constants.py:26`） | ✔ |

`FindSourceDayDir`（`SyncEngine.cs:224-236`）对 `yyyyMMdd` / `yyyy.MM.dd` / `yyyy-MM-dd` 三种源目录命名都做了兼容，这块没问题。

---

## 建议修复顺序

1. **P0-1 / P0-2**：调整 `Execute` 中 `SameFile` 与 `FileReady` 的先后，并让稳定判定不再阻塞（收益最大，改动最小）
2. **P0-3**：时间戳写入失败要告警，并加兜底判定（防"每轮全量重传"）
3. **P0-4**：心跳要么实现、要么从界面撤掉（不要留着骗人）
4. **P0-5**：排除规则恢复成多条目并兼容旧的相对名
5. **P0-6 / P0-7**：`EnsureDir` 的阻塞与退出流程的释放时序
6. **P1-1 ~ P1-4**：把旧版丢掉的三块兜底补回来（磁盘余量、逐级容错枚举、直接复制降级、通用 catch）
