$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$pyi  = "$root\.venv\Scripts\pyinstaller.exe"
$version = '1.2.0'
Set-Location $root

Write-Host "`nBuilding Whisper Vox (WebUI) v$version" -ForegroundColor Cyan
& $pyi build\WhisperVox.spec --distpath dist --workpath build\work --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# Version file read by version.get_version() (sits next to the exe).
Set-Content "dist\WhisperVox\.version" $version -NoNewline -Encoding ASCII

$exe = "dist\WhisperVox\WhisperVox.exe"
$size = [math]::Round((Get-ChildItem dist\WhisperVox -Recurse | Measure-Object Length -Sum).Sum / 1MB, 1)
Write-Host "`nBuilt: $exe" -ForegroundColor Green
Write-Host "Folder size: $size MB" -ForegroundColor Green
