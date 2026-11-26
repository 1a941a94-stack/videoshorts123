# ClipFactory

Python 3.10+, FFmpeg/ffprobe in PATH. Automated discovery of YouTube replay heatmaps, selection of clips, vertical rendering and banner overlays for authorized sources.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -U -r requirements.txt
.venv\Scripts\python.exe clipfactory.py search "подкаст интервью" --limit 20
.venv\Scripts\python.exe -m unittest -v
```

Autoposting is not implemented yet. Adaptive framing and optional local captions are available. Live YouTube extraction requires validation. Keep credentials outside Git.

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

## Local captions

Requires FFmpeg with libass and an installed font (e.g. Arial or DejaVu Sans). First transcription downloads model weights. Subsequent transcriptions run locally.

PowerShell:

```powershell
python -m pip install -r requirements-captions.txt
$env:CLIP_CAPTIONS="1"
$env:CLIP_MODEL="small"
$env:CLIP_DEVICE="cpu"
$env:CLIP_FONT="Arial"
python pipeline.py work --limit 10
```

Optional settings: CLIP_LANGUAGE (e.g. ru), CLIP_COMPUTE, CLIP_FONT_SIZE (default 64), CLIP_CAPTION_MARGIN (480 pixels), CLIP_HIGHLIGHT (ASS BGR hex, default 00D5FF). For CUDA use a compatible CTranslate2/CUDA installation. Caption rendering is not yet validated on real speech. Captions are disabled by default.

## Local dashboard

Install requirements and run `python dashboard.py`, then open http://127.0.0.1:8080/. The dashboard supports source management, search settings, scan and render jobs, retry, logs, video previews, and static banner campaign creation. It binds only to localhost; do not expose it to the public Internet. Do not run separate CLI workers simultaneously during initial testing. For optional captions install requirements-captions.txt. The UI is not yet integration-tested.

## Autonomous production

Run `python supervisor.py --daily 30 --workers 1 --scan-interval 3600 --min-free-gb 5 --max-cpu 85`. Optionally pass `--config settings.json` and `--campaigns campaigns.json`. Set CLIP_CAPTIONS=1 before starting to enable installed local captions. Use `--once` for one scan and one batch. Daily accounting uses UTC and counts completed clips. The CPU/disk checks are admission checks, not hard resource quotas. Do not start another producer against the same database; the CLI and supervisor share a file lock. A restarted supervisor resets interrupted jobs, with a maximum of three attempts. Failed jobs are retried after 15 minutes. Stop with Ctrl+C. External process supervision (systemd or equivalent) is needed for OS reboot autostart. No live end-to-end validation yet.
