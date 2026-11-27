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

## External integration acceptance

The business image includes YouTube Data API client dependencies. Authorize a
channel locally with youtube_publish.py and transfer the resulting credential
file securely into data/youtube-sessions. YouTube uploads remain private.
For Telegram publishing, configure the account's named token environment
variable in .env and authorize the bot in a test channel you control.
For Telegram source access, authorize a local Telethon session and configure
TG_API_ID and TG_API_HASH. Only import media you have permission to reuse.
For Instagram Graph publishing, use an authorized professional test account
and its token. Do not store access tokens in source control.
Browser-based Instagram and optional Whisper are not included in this image.
The automated deployment test validates dependencies but does not contact
external services, publish videos or validate credentials. Perform a controlled
single-video acceptance run before enabling real publishing. Verify the remote
ID, visibility and destination manually. Statistics and partner payouts are
recorded manually; they are not fetched automatically.
