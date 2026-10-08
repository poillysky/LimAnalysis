# 用 NSSM 把三个进程装成 Windows 服务（需管理员 PowerShell）
# 1) 安装 NSSM: https://nssm.cc/download 并把 nssm.exe 加入 PATH
# 2) 本机已建好 backend\.venv 与 backend\.env（可参考 .env.workshop.example）
# 3) 管理员执行本脚本

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Backend = Join-Path $Root "backend"
$LogDir = Join-Path $PSScriptRoot ".run\logs"
$Py = Join-Path $Backend ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { throw "缺少 $Py，请先创建 venv 并 pip install" }

$Nssm = Get-Command nssm -ErrorAction SilentlyContinue
if (-not $Nssm) { throw "未找到 nssm.exe，请先安装并加入 PATH" }

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Install-LimService([string]$Name, [string]$AppParameters) {
  $svc = "LimAnalysis-$Name"
  & nssm stop $svc 2>$null | Out-Null
  & nssm remove $svc confirm 2>$null | Out-Null
  & nssm install $svc $Py
  & nssm set $svc AppParameters $AppParameters
  & nssm set $svc AppDirectory $Backend
  & nssm set $svc Start SERVICE_AUTO_START
  & nssm set $svc AppStdout (Join-Path $LogDir "$Name.svc.out.log")
  & nssm set $svc AppStderr (Join-Path $LogDir "$Name.svc.err.log")
  & nssm set $svc AppRotateFiles 1
  & nssm start $svc
  Write-Host "服务已安装并启动: $svc"
}

Install-LimService "api" "-m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"
Install-LimService "collector" "-m collector.worker"
Install-LimService "agg" "-m processor.agg_worker"

Write-Host "完成。卸载示例: nssm remove LimAnalysis-api confirm"
