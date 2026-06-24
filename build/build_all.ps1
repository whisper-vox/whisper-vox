$ErrorActionPreference = 'Stop'
$root        = Split-Path $PSScriptRoot -Parent
$pyinstaller = "$root\.venv\Scripts\pyinstaller.exe"
Set-Location $root

# ── Version is single-sourced from launcher.py (APP_VERSION) ─────────────────
$verLine = Select-String -Path "build\launcher.py" -Pattern "APP_VERSION\s*=\s*'(.+)'"
$version = $verLine.Matches[0].Groups[1].Value
$outExe  = "release\WhisperVox-Setup-v$version.exe"
Write-Host "`nBuilding Whisper Vox (WebUI) v$version" -ForegroundColor Cyan

# ── Stamp today's build date into launcher.py ────────────────────────────────
$today = Get-Date -Format 'yyyy-MM-dd'
# Read/write as UTF-8 explicitly (Windows PowerShell defaults to ANSI on read,
# which would mangle any non-ASCII char on the round-trip). launcher.py is kept
# ASCII-only anyway, but this keeps the stamp safe regardless.
$launcherSrc = Get-Content "build\launcher.py" -Raw -Encoding UTF8
$launcherSrc = $launcherSrc -replace "BUILD_DATE\s*=\s*'[^']*'", "BUILD_DATE  = '$today'"
Set-Content "build\launcher.py" $launcherSrc -Encoding UTF8 -NoNewline
Write-Host "Build date stamped: $today"

# ── [1/4] Build the app (onedir) ─────────────────────────────────────────────
Write-Host "`n=== [1/4] Building app (onedir) ===" -ForegroundColor Cyan
& $pyinstaller build\WhisperVox.spec --distpath dist --workpath build\work --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed for app" }
# .version sits next to the exe and is read by version.get_version().
Set-Content "dist\WhisperVox\.version" $version -NoNewline -Encoding ASCII

# ── [2/4] Zip the app -> build\app.zip ───────────────────────────────────────
Write-Host "`n=== [2/4] Zipping dist\WhisperVox -> build\app.zip ===" -ForegroundColor Cyan
$zipPath = "build\app.zip"
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path "dist\WhisperVox\*" -DestinationPath $zipPath -CompressionLevel Optimal
Write-Host "app.zip: $([math]::Round((Get-Item $zipPath).Length/1MB, 1)) MB"

# ── [3/4] Build the setup/updater (onefile, bundles app.zip) ─────────────────
Write-Host "`n=== [3/4] Building setup ===" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path "release" | Out-Null
Remove-Item "build\launcher_work" -Recurse -Force -ErrorAction SilentlyContinue
& $pyinstaller build\launcher.spec --distpath build\launcher_dist --workpath build\launcher_work --noconfirm
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed for setup" }
Copy-Item "build\launcher_dist\WhisperVox-Setup.exe" $outExe -Force
$exeSize = [math]::Round((Get-Item $outExe).Length/1MB, 1)
Write-Host "  $outExe  ($exeSize MB)" -ForegroundColor Green

# ── [4/4] Friendly download .zip (avoids the browser 'dangerous .exe' prompt) ─
Write-Host "`n=== [4/4] Packaging release zip ===" -ForegroundColor Cyan
$zipOut = "release\WhisperVox-Setup-v$version.zip"
$stage  = "release\_zip_stage"
Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $stage | Out-Null
Copy-Item $outExe (Join-Path $stage 'WhisperVox-Setup.exe') -Force
$readme = @"
Whisper Vox v$version - per-user installer (no admin rights needed).

1. Run WhisperVox-Setup.exe.
   - First run installs the app to %LOCALAPPDATA%\Programs\WhisperVox and
     starts it in the tray (a short 'Installing...' splash shows progress, ~15 s).
   - If Windows SmartScreen says "Windows protected your PC":
       click  More info  ->  Run anyway.
       (It is safe - the app simply isn't code-signed yet.)
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
Write-Host "  Installs to: %LOCALAPPDATA%\Programs\WhisperVox" -ForegroundColor Yellow
