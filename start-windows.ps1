$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Install Python 3.11 and add it to PATH." }
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { throw "Install FFmpeg and add it to PATH (winget install Gyan.FFmpeg)." }
if (-not (Test-Path ".venv\Scripts\python.exe")) { python -m venv .venv; if ($LASTEXITCODE -ne 0) { throw "venv failed" } }
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $py -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }
& $py -m unittest discover -v
if ($LASTEXITCODE -ne 0) { throw "Tests failed; dashboard not started" }
Start-Process "http://127.0.0.1:8080/"
& $py dashboard.py
