$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (!(Test-Path '.venv\Scripts\python.exe')) {
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 is required' }
}
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $python -m pip install -r requirements-captions.txt -r requirements-telegram.txt -r requirements-browser.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& $python -m playwright install chromium
if ($LASTEXITCODE -ne 0) { throw 'Chromium installation failed' }
& $python -m compileall -q -x '[\\/]\.venv[\\/]' .
if ($LASTEXITCODE -ne 0) { throw 'Python syntax check failed' }
foreach ($tool in @('ffmpeg','ffprobe','deno','tesseract')) {
    if (!(Get-Command $tool -ErrorAction SilentlyContinue)) {
        Write-Warning "$tool not found on PATH. Install before using the corresponding feature."
    }
}
if (Get-Command tesseract -ErrorAction SilentlyContinue) {
    tesseract --list-langs
}
Write-Host 'Setup complete. Run .\start-windows.ps1'
