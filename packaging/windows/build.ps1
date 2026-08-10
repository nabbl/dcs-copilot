param(
    [string]$Version = "0.1.0",
    [string]$ServiceUrl = "ws://127.0.0.1:8000/v1/realtime",
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$BuildRoot = Join-Path $RepoRoot "build\windows"
$DistRoot = Join-Path $RepoRoot "dist\windows"

New-Item -ItemType Directory -Force -Path $BuildRoot, $DistRoot | Out-Null
Push-Location $RepoRoot
try {
    uv sync --all-packages
    uv run --with "pyinstaller>=6.15,<7" pyinstaller `
        --noconfirm `
        --clean `
        --windowed `
        --name "DCS Copilot" `
        --distpath $DistRoot `
        --workpath (Join-Path $BuildRoot "desktop") `
        --specpath $BuildRoot `
        --hidden-import keyring.backends.Windows `
        (Join-Path $PSScriptRoot "desktop_entry.py")

    uv run --with "pyinstaller>=6.15,<7" pyinstaller `
        --noconfirm `
        --clean `
        --console `
        --name "dcs-copilot" `
        --distpath $DistRoot `
        --workpath (Join-Path $BuildRoot "cli") `
        --specpath $BuildRoot `
        --hidden-import keyring.backends.Windows `
        (Join-Path $PSScriptRoot "cli_entry.py")

    if (-not $SkipInstaller) {
        $Iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
        if (-not $Iscc) {
            throw "Inno Setup 6 (ISCC.exe) is required to build the installer."
        }
        & $Iscc.Source "/DAppVersion=$Version" "/DServiceUrl=$ServiceUrl" (Join-Path $PSScriptRoot "dcs-copilot.iss")
    }
}
finally {
    Pop-Location
}
