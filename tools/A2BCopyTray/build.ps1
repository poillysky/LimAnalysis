#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$dotnet = Get-Command dotnet -ErrorAction SilentlyContinue
if (-not $dotnet) {
    $candidates = @(
        "$env:LOCALAPPDATA\Microsoft\dotnet\dotnet.exe",
        "$env:ProgramFiles\dotnet\dotnet.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) {
            $env:PATH = "$(Split-Path $c);$env:PATH"
            break
        }
    }
}

if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    Write-Error "未找到 dotnet。请先安装 .NET 8 SDK。"
}

Write-Host "Publishing self-contained single-file A2BCopyTray..." -ForegroundColor Cyan
dotnet publish .\A2BCopyTray.csproj -c Release -r win-x64 --self-contained true `
    -p:PublishSingleFile=true `
    -p:IncludeNativeLibrariesForSelfExtract=true `
    -p:EnableCompressionInSingleFile=true `
    -o .\dist

if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$exe = Join-Path $Root "dist\A2BCopyTray.exe"
if (Test-Path $exe) {
    $size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
    Write-Host "OK: $exe ($size MB)" -ForegroundColor Green
} else {
    Write-Error "Publish finished but EXE missing."
}
