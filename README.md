# ClipFactory

Python 3.10+, FFmpeg/ffprobe in PATH. Automated discovery of YouTube replay heatmaps, selection of clips, vertical rendering and banner overlays for authorized sources.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -U -r requirements.txt
.venv\Scripts\python.exe clipfactory.py search "подкаст интервью" --limit 20
.venv\Scripts\python.exe -m unittest -v
```

Initial version: no autoposting, face tracking or subtitles yet. Live YouTube extraction requires validation. Keep credentials outside Git.
