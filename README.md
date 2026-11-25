# ClipFactory

Python 3.10+, FFmpeg/ffprobe in PATH. Automated discovery of YouTube replay heatmaps, selection of clips, vertical rendering and banner overlays for authorized sources.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -U -r requirements.txt
.venv\Scripts\python.exe clipfactory.py search "подкаст интервью" --limit 20
.venv\Scripts\python.exe -m unittest -v
```

Initial version: no autoposting, face tracking or subtitles yet. Live YouTube extraction requires validation. Keep credentials outside Git.

## Persistent pipeline

Run from the repository directory. Add search terms or YouTube channel/playlist URLs, then scan and process the queue.

```powershell
python pipeline.py add "подкаст интервью"
python pipeline.py scan
python pipeline.py status
python pipeline.py work --limit 10 --banner banner.png
python pipeline.py retry
python -m unittest -v
```

Default filters: 10,000 views, 2–180 minutes, peak score >= 0.7, 45-second clips, three clips per scan per source video, 24-hour metadata cache. Override settings with `python pipeline.py --config settings.json scan`. Failed jobs can be retried up to three total attempts. Interrupted running jobs currently require manual recovery. No recurring scheduler or live integration test yet.
