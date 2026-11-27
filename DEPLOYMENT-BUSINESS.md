# ClipFactory Business: Ubuntu VPS

This profile is separate from the legacy producer compose configuration.
Install Docker Engine and the Docker Compose plugin using the official Docker
installation instructions for Ubuntu. Clone the repository, then run
`bash deploy.sh`. The dashboard is bound to the server's loopback address.

Access from your workstation using an SSH tunnel:
`ssh -N -L 8080:127.0.0.1:8080 user@server`
Then open http://127.0.0.1:8080. Do not expose the Flask port publicly.

Persistent data lives in ./data. For migration, stop the old application before
copying its database, settings and media directories. Windows absolute paths
and hardware-specific encoder settings require review before migration.
Use CPU encoding on a VPS without compatible GPU acceleration.
The base business image includes FFmpeg and Russian/English Tesseract;
optional Whisper dependencies are not included.

Configure Telegram reporting in .env; keep it private. Do not commit secrets.
Run `bash backup.sh` to create a cold backup (brief production downtime).
Backups include database, media and any credentials stored inside data.
Keep backups private, encrypted at rest where possible, and copy them offsite.
The .env file is excluded; retain it separately in a secure secret store.

Update: create a backup first, then git pull --ff-only and bash deploy.sh.
Restore a trusted backup with bash restore.sh backups/<filename>.tar.gz.
The previous data directory is retained; verify the restored app before deleting it.

Inspect with docker compose -f compose.business.yaml ps and
docker compose -f compose.business.yaml logs --tail=100 factory.
Health status checks HTTP liveness, not the success of production or publication.
A container restart does not guarantee recovery of interrupted jobs.
