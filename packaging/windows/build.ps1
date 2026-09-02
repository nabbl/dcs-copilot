param(
    [string]$Version = "0.1.0",
    [string]$ServiceUrl = "ws://127.0.0.1:47100/v2/realtime",
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
        --collect-binaries PySide6 `
        --collect-data dcs_copilot `
        (Join-Path $PSScriptRoot "desktop_entry.py")

    $QtPlatformPlugin = Join-Path $DistRoot "DCS Copilot\_internal\PySide6\plugins\platforms\qwindows.dll"
    if (-not (Test-Path $QtPlatformPlugin)) {
        throw "Desktop bundle is missing the Qt Windows platform plugin."
    }

    uv run --with "pyinstaller>=6.15,<7" pyinstaller `
        --noconfirm `
        --clean `
        --console `
        --name "dcs-copilot" `
        --distpath $DistRoot `
        --workpath (Join-Path $BuildRoot "cli") `
        --specpath $BuildRoot `
        --hidden-import keyring.backends.Windows `
        --collect-data dcs_copilot `
        (Join-Path $PSScriptRoot "cli_entry.py")

    uv run --package dcs-copilot-cloud --with "pyinstaller>=6.15,<7" pyinstaller `
        --noconfirm `
        --clean `
        --console `
        --name "MaraBackend" `
        --distpath $DistRoot `
        --workpath (Join-Path $BuildRoot "backend") `
        --specpath $BuildRoot `
        --hidden-import keyring.backends.Windows `
        --hidden-import aiosqlite `
        --hidden-import asyncpg `
        --hidden-import sqlalchemy.dialects.sqlite.aiosqlite `
        --collect-submodules pipecat.services.kokoro `
        --collect-submodules scipy._external.array_api_compat.numpy `
        --collect-all kokoro_onnx `
        --collect-all espeakng_loader `
        --collect-data certifi `
        --collect-data language_tags `
        --copy-metadata pipecat-ai `
        --copy-metadata kokoro-onnx `
        (Join-Path $PSScriptRoot "backend_entry.py")

    $BackendBundle = Join-Path $BuildRoot "backend-bundle"
    if (Test-Path $BackendBundle) {
        Remove-Item $BackendBundle -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $BackendBundle | Out-Null
    Copy-Item (Join-Path $DistRoot "MaraBackend\*") $BackendBundle -Recurse -Force
    Copy-Item (Join-Path $PSScriptRoot "backend-config.example.json") (Join-Path $BackendBundle "config.example.json")
    Copy-Item (Join-Path $PSScriptRoot "BACKEND_README.txt") (Join-Path $BackendBundle "README.txt")
    Copy-Item (Join-Path $RepoRoot "THIRD_PARTY_NOTICES.md") $BackendBundle
    $BackendZip = Join-Path $DistRoot "MARA-Backend-$Version-windows-x64.zip"
    if (Test-Path $BackendZip) {
        Remove-Item $BackendZip -Force
    }
    Compress-Archive -Path (Join-Path $BackendBundle "*") -DestinationPath $BackendZip -CompressionLevel Optimal

    if (-not $SkipInstaller) {
        $Iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
        if (-not $Iscc) {
            throw "Inno Setup 6 (ISCC.exe) is required to build the installer."
        }
        & $Iscc.Source "/DAppVersion=$Version" "/DServiceUrl=$ServiceUrl" (Join-Path $PSScriptRoot "dcs-copilot.iss")
    }

    $Artifacts = Get-ChildItem $DistRoot -File | Where-Object {
        $_.Name -like "MARA-Backend-*.zip" -or $_.Name -like "MARA-Setup-*.exe"
    }
    $ChecksumLines = foreach ($Artifact in $Artifacts) {
        $Hash = (Get-FileHash $Artifact.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        "$Hash  $($Artifact.Name)"
    }
    Set-Content -Path (Join-Path $DistRoot "checksums.txt") -Value $ChecksumLines -Encoding ascii
}
finally {
    Pop-Location
}
