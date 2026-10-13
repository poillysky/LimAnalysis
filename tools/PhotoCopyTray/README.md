# PhotoCopyTray

Windows 托盘增量复制工具（合注塑机 / 外观机）。路径规则对齐 LimAnalysis「注塑机图片 / 自动外观图片」识别结构。参考旧版 `refence/legacy-src/A2B/A2BCopyTray.exe`。

## 功能

1. **站点配置**
   - **注塑机模式**：填写机台号
   - **外观机模式**：填写项目名 + 外观机号
2. **复制**：本地源目录 → 目标根（支持 `\\` 网络路径）
3. **排除**：排除相对目录名、通配文件（`*.tmp` 等）
4. 托盘常驻：打开主界面 / 配置 / 立即同步 / 暂停 / 退出；单实例；可选开机自启

## 目标路径（与系统一致）

| 模式 | 实际写入 |
|------|----------|
| 注塑机 | `{target_root}/{机台号}/{yyyyMMdd}/...` |
| 外观机 | `{target_root}/{项目名}/{外观机号}/GVIMAGES/LIM外观检测/{yyyy.MM.dd}/...` |

`target_root` 分别对应系统里的 `mold_root_path` / `appearance_root_path`。

源侧优先同步**当天日期文件夹**（注塑 `yyyyMMdd`，外观 `yyyy.MM.dd`）；没有当天目录则静默等待。

## 现场机器：零依赖

打包后的 **`PhotoCopyTray.exe` 自带运行时**，现场 PC：

- **不用装 Python**
- **不用装 .NET / VC++ 额外包**（常见 Win10/11 即可）
- **只拷一个 exe** 到目录里运行；同目录自动生成 `config.json`、`logs/`

开发机调试才需要 Python：

```powershell
cd tools\PhotoCopyTray
python -m pip install -r requirements.txt
python src\main.py
```

打现场 EXE（在开发机执行）：

```powershell
.\build.ps1
```

输出：`dist\PhotoCopyTray.exe`（PyInstaller onefile，已 `--collect-all` 收齐 pystray/Pillow）。

## 配置说明

见 `config.example.json`。主界面「系统配置」可改。

| 字段 | 说明 |
|------|------|
| `mode` | `mold` / `appearance` |
| `machine` | 注塑机台号，或外观机号 |
| `project` | 仅外观：NAS 上项目文件夹名 |
| `source_dir` | 本机采集目录 |
| `target_root` | NAS 根（注塑根或外观根） |
| `exclude_dirs` | 排除的相对目录名 |
| `exclude_globs` | 排除文件通配 |
| `compare_mode` | `fast`（大小+时间）/ `md5` |

## 注意

- 目标是网络路径时，现场账号需有写权限；创建失败会尝试 PowerShell 兜底
- 与旧 A2B 一样按「当天目录」增量同步，不扫历史全盘
- 本工具**不**改 LimAnalysis 服务端规则，只负责把文件拷到系统能认的目录结构
