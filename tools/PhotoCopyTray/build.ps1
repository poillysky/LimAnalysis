# Build a self-contained EXE for shop-floor PCs (no Python / no extra DLL install).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python -m pip install -r requirements.txt
python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
  --name PhotoCopyTray `
  --distpath dist `
  --workpath build `
  --specpath build `
  --collect-all pystray `
  --collect-all PIL `
  --hidden-import PIL._tkinter_finder `
  --hidden-import tkinter `
  --hidden-import tkinter.ttk `
  --hidden-import tkinter.filedialog `
  --hidden-import tkinter.messagebox `
  src\main.py

$exe = Join-Path $PSScriptRoot "dist\PhotoCopyTray.exe"
if (-not (Test-Path $exe)) {
  throw "Build failed: $exe not found"
}
$sizeMb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host "OK: $exe ($sizeMb MB)"
Write-Host "Copy ONLY this exe to the PC. No Python install. config.json / logs appear beside the exe."
