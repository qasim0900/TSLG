$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    poetry install --with dev
    poetry run pytest -q
    poetry run pyinstaller packaging/TechsetLeadGen.spec --noconfirm --clean
    if (Test-Path ".env") {
        Copy-Item ".env" "dist\TechsetLeadGen\.env"
        Write-Host "Copied .env next to TechsetLeadGen.exe: every computer using this build connects to the team database."
    }
    else {
        Write-Warning "No .env in $root, so this build uses a local database file on each computer."
    }
    $version = (poetry version -s)
    $zip = "dist\TechsetLeadGen-$version-windows.zip"
    if (Test-Path $zip) { Remove-Item $zip }
    Compress-Archive -Path "dist\TechsetLeadGen\*" -DestinationPath $zip
    Write-Host "Built dist\TechsetLeadGen\TechsetLeadGen.exe and $zip"
}
finally {
    Pop-Location
}
