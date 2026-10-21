# Build the Windows desktop application with PyInstaller.
# Requires Python 3.12+ and Poetry on PATH. Run from any folder:
#   powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    poetry install --with dev
    poetry run pytest -q
    poetry run pyinstaller packaging/TechsetLeadGen.spec --noconfirm --clean
    $version = (poetry version -s)
    $zip = "dist\TechsetLeadGen-$version-windows.zip"
    if (Test-Path $zip) { Remove-Item $zip }
    Compress-Archive -Path "dist\TechsetLeadGen\*" -DestinationPath $zip
    Write-Host "Built dist\TechsetLeadGen\TechsetLeadGen.exe and $zip"
}
finally {
    Pop-Location
}
