# 车间一键启动：API + collector worker + agg worker（无 reload）
# 用法（仓库根或本目录）：powershell -ExecutionPolicy Bypass -File deploy/workshop/start.ps1

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Backend = Join-Path $Root "backend"
$RunDir = Join-Path $PSScriptRoot ".run"
$LogDir = Join-Path $RunDir "logs"
$PidFile = Join-Path $RunDir "pids.json"

New-Item -ItemType Directory -Force -Path $RunDir, $LogDir | Out-Null

$Py = Join-Path $Backend ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
  $Py = "python"
  Write-Warning "未找到 backend\.venv，使用系统 python：$Py"
}

$EnvFile = Join-Path $Backend ".env"
$WorkshopEnv = Join-Path $PSScriptRoot ".env.workshop"
if ((Test-Path $WorkshopEnv) -and -not (Test-Path $EnvFile)) {
  Copy-Item $WorkshopEnv $EnvFile
  Write-Host "已从 .env.workshop 创建 backend\.env"
}

if (Test-Path $PidFile) {
  Write-Host "已有 pids.json，先执行 stop.ps1 再启动。"
  exit 1
}

function Start-LimProc([string]$Name, [string[]]$ArgList) {
  $out = Join-Path $LogDir "$Name.out.log"
  $err = Join-Path $LogDir "$Name.err.log"
  $p = Start-Process -FilePath $Py `
    -ArgumentList $ArgList `
    -WorkingDirectory $Backend `
    -WindowStyle Hidden `
    -RedirectStandardOutput $out `
    -RedirectStandardError $err `
    -PassThru
  return @{ name = $Name; pid = $p.Id; args = ($ArgList -join " ") }
}

$procs = @()
$procs += Start-LimProc "api" @(
  "-m", "uvicorn", "app.main:app",
  "--host", "0.0.0.0",
  "--port", "8000",
  "--workers", "1"
)
$procs += Start-LimProc "collector" @("-m", "collector.worker")
$procs += Start-LimProc "agg" @("-m", "processor.agg_worker")

$procs | ConvertTo-Json | Set-Content -Encoding UTF8 $PidFile
Write-Host "已启动："
$procs | ForEach-Object { Write-Host ("  {0}  pid={1}" -f $_.name, $_.pid) }
Write-Host "健康检查: http://127.0.0.1:8000/api/health"
Write-Host "日志目录: $LogDir"
