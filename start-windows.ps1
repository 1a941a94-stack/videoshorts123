$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (!(Test-Path $python)) { throw 'Run setup-windows.ps1 first' }
if (!(Get-Command ffmpeg -ErrorAction SilentlyContinue)) { throw 'FFmpeg not found on PATH' }
& $python dashboard.py
