$ErrorActionPreference = 'Stop'
$root        = Split-Path $PSScriptRoot -Parent
$pyinstaller = "$root\.venv\Scripts\pyinstaller.exe"
Set-Location $root

# ── Version: the tag when CI passes one, otherwise the next local build number
# One decision, made once here and handed to the specs through the environment,
# so every part of this build agrees on what it is. See build/version_for_build.py.
$python = "$root\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = 'python' }
$version = & $python "build\version_for_build.py"
if ($LASTEXITCODE -ne 0 -or -not $version) { throw "could not decide the version" }
$env:WHISPERVOX_VERSION = $version
$outExe  = "release\WhisperVox-Setup-v$version.exe"
Write-Host "`nBuilding Whisper Vox (WebUI) v$version" -ForegroundColor Cyan

# ── [1/3] Build the app (onedir) ─────────────────────────────────────────────
Write-Host "`n=== [1/3] Building app (onedir) ===" -ForegroundColor Cyan
& $pyinstaller build\WhisperVox.spec --distpath dist --workpath build\work --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed for app" }
# .version sits next to the exe and is read by version.get_version().
Set-Content "dist\WhisperVox\.version" $version -NoNewline -Encoding ASCII
# The update toast lives in WinRT modules imported inside a function, where the
# analysis cannot follow. If they ever dropped out of the bundle the app would
# still build and still run - it would just announce updates with the old tray
# balloon, and nobody would notice. So fail the build here instead.
$pyz = Get-Content "build\work\WhisperVox\PYZ-00.toc" -Raw
foreach ($m in 'winrt.windows.ui.notifications', 'winrt.windows.data.xml.dom', 'winrt.runtime') {
    if ($pyz -notmatch [regex]::Escape("'$m'")) {
        throw "The bundle is missing $m - the update toast would silently fall back to the balloon"
    }
}
Write-Host "  WinRT toast modules are in the bundle" -ForegroundColor Green

# ── [2/3] Build the setup (Inno Setup, build\WhisperVox.iss) ─────────────────
# Looked for where a per-user install puts it first - that is how it is set up
# on a developer's machine, no admin rights - then the machine-wide places,
# which is where CI's package manager puts it. $env:ISCC overrides all of them.
function Find-Iscc {
    $candidates = @(
        $env:ISCC,
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    ) | Where-Object { $_ -and (Test-Path $_) }
    if ($candidates) { return @($candidates)[0] }
    $cmd = Get-Command iscc.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw "Inno Setup 6 not found. Install it with:  winget install JRSoftware.InnoSetup --scope user"
}
Write-Host "`n=== [2/3] Building setup (Inno Setup) ===" -ForegroundColor Cyan
$iscc = Find-Iscc
# The Win32 version resource only takes up to four plain numbers, so a CI
# build's "1.3.0-ci.22" goes in as 1.3.0.22 there; the text version keeps it whole.
$numeric = (($version -split '[^0-9]+') | Where-Object { $_ -ne '' } | Select-Object -First 4) -join '.'
New-Item -ItemType Directory -Force -Path "release" | Out-Null
& $iscc "/DAppVersion=$version" "/DAppFileVersion=$numeric" `
        "/DSourceDir=$root\dist\WhisperVox" "/DOutputDir=$root\release" `
        "/DOutputBase=WhisperVox-Setup-v$version" /Q "build\WhisperVox.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed to build the setup" }
$exeSize = [math]::Round((Get-Item $outExe).Length/1MB, 1)
Write-Host "  $outExe  ($exeSize MB)" -ForegroundColor Green

# ── [3/3] Friendly download .zip (avoids the browser 'dangerous .exe' prompt) ─
Write-Host "`n=== [3/3] Packaging release zip ===" -ForegroundColor Cyan
$zipOut = "release\WhisperVox-Setup-v$version.zip"
$stage  = "release\_zip_stage"
Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $stage | Out-Null
Copy-Item $outExe (Join-Path $stage 'WhisperVox-Setup.exe') -Force
$readme = @"
Whisper Vox v$version - per-user installer (no admin rights needed).

1. Run WhisperVox-Setup.exe.
   - If Windows SmartScreen says "Windows protected your PC":
       click  More info  ->  Run anyway.
       (It is safe - the app simply isn't code-signed yet.)
   - Choose where to install it (the default is fine), then it starts in the tray.
   - Already have Whisper Vox? The setup finds it and updates it in place,
     keeping your settings and API key.
2. It lives in the tray near the clock. Press your activation key (F2 by default) to dictate.
3. Autostart + Desktop icon are on by default (toggle them in Misc).

Update later: the app checks for updates and can update itself in one click,
or download a newer setup and run it - it replaces the old version automatically.
Uninstall: Settings > Apps (Apps & Features) > Whisper Vox > Uninstall.
"@
Set-Content (Join-Path $stage 'README.txt') $readme -Encoding UTF8
if (Test-Path $zipOut) { Remove-Item $zipOut -Force }
Compress-Archive -Path "$stage\*" -DestinationPath $zipOut -CompressionLevel Optimal
Remove-Item $stage -Recurse -Force
$zipSize = [math]::Round((Get-Item $zipOut).Length/1MB, 1)
$sha = (Get-FileHash $outExe -Algorithm SHA256).Hash

Write-Host "`n=== Done ===" -ForegroundColor Cyan
Write-Host "  $outExe  ($exeSize MB)" -ForegroundColor Green
Write-Host "  $zipOut  ($zipSize MB)" -ForegroundColor Green
Write-Host "  Setup SHA-256: $sha" -ForegroundColor Yellow
Write-Host "  Installs to: %LOCALAPPDATA%\Programs\WhisperVox by default (user's choice)" -ForegroundColor Yellow
