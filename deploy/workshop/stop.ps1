# 停止 start.ps1 拉起的三个进程
$ErrorActionPreference = "Continue"
$RunDir = Join-Path $PSScriptRoot ".run"
$PidFile = Join-Path $RunDir "pids.json"

if (-not (Test-Path $PidFile)) {
  Write-Host "没有 pids.json，无需停止。"
  exit 0
}

$procs = Get-Content $PidFile -Raw | ConvertFrom-Json
foreach ($item in @($procs)) {
  $id = [int]$item.pid
  if ($id -le 0) { continue }
  try {
    Stop-Process -Id $id -Force -ErrorAction Stop
    Write-Host ("已停止 {0} pid={1}" -f $item.name, $id)
  } catch {
    Write-Host ("进程不存在或已退出: {0} pid={1}" -f $item.name, $id)
  }
}

Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
Write-Host "完成。"
