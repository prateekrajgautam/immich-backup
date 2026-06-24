# Immich Incremental Backup

A small self-hosted web dashboard that incrementally backs up your Immich
photo/video library to:

- **Local external storage** (e.g. a USB/external drive)
- **Amazon S3** (with support for Glacier / Deep Archive storage classes for
  cheap cold storage)

It only copies/uploads files that are new or changed since the last
successful backup (tracked via Immich's checksum for each asset), so re-runs
are fast.

## How it works

1. The app calls the Immich API to list all assets (photos/videos) and their
   checksums.
2. It maps each asset's path to a real file on disk (you mount/share the
   Immich library folder to wherever this app runs).
3. It compares each asset's checksum to what was backed up last time
   (tracked in a local SQLite database).
4. New/changed files are copied to your local backup folder and/or uploaded
   to S3.
5. You can trigger a backup manually from the dashboard, or set up a cron
   schedule (e.g. nightly) from Settings.

## Requirements

- Python 3.9+
- Filesystem access to your Immich library's `upload` folder (mount it via
  Docker volume, NFS, SMB, etc. if this app isn't running on the same host
  as Immich)
- An Immich API key (Immich web UI → Account Settings → API Keys)
- (Optional) An AWS account + S3 bucket if you want cloud backup

## Setup

### Option A: Docker (recommended)

```bash
cd immich-backup
cp .env.example .env
# edit .env to point IMMICH_LIBRARY_PATH at your Immich library folder on
# the host, and LOCAL_BACKUP_PATH at your external drive's mount point
docker compose up -d --build
```

Open **http://localhost:2284**. In Settings, set:
- **Immich Library Root** → `/immich-library` (the in-container mount path)
- **Local backup destination** → `/backup-destination` (the in-container mount path)
- **Immich Server URL** → if Immich is also running in Docker on the same
  host, use its container/service name and internal port (e.g.
  `http://immich-server:2283`); otherwise use whatever URL/IP:port reaches
  it from this container. You may need to put both containers on the same
  Docker network — see the commented-out `networks:` section in
  `docker-compose.yml`.

The container listens on **2284** (chosen to sit next to Immich's default
**2283**) and restarts automatically; the cron schedule keeps running as
long as the container is up.

### Option B: Plain Python

```bash
cd immich-backup
python3 -m venv venv
source venv/bin/activate          # on Windows: venv\Scripts\activate
pip install -r requirements.txt
python3 app.py
```

Then open **http://localhost:2284** (override with `PORT=5000 python3
app.py` if you'd rather use a different port).

## Configuration (via the Settings page)

### Immich Connection
- **Immich Server URL** — e.g. `http://localhost:2283` (or wherever your
  Immich instance is reachable)
- **API Key** — generate this in Immich

Use "Test Connection" to confirm the app can reach Immich.

### Filesystem Access
Immich's API gives you each asset's *internal* path (e.g.
`/usr/src/app/upload/library/.../photo.jpg` — this is the path *inside the
Immich docker container*). This app needs to read the actual file from disk,
so:

1. Find the real path to Immich's `upload`/`library` folder on the host
   (check your Immich `docker-compose.yml` for the volume mapping, typically
   something like `./library:/usr/src/app/upload`).
2. Mount or point this app at that same folder. Set **Immich Library Root**
   to that path.
3. Set **Immich's internal path prefix** to whatever Immich uses internally
   (default `/usr/src/app/upload` — check your Immich version/config if
   backups report "source file not found").

If this app runs in Docker too, just bind-mount the same library volume into
the backup container (read-only is fine) and point `immich_library_root` at
the mount path.

### Local Backup
Point **Backup destination path** at your external drive's mount point. The
original folder structure is preserved under that path.

### S3 Backup
Fill in your bucket, region, and AWS credentials. Choose a storage class:

| Storage Class | Use case |
|---|---|
| STANDARD | Frequent access, highest cost |
| STANDARD_IA | Infrequent access, instant retrieval |
| GLACIER_IR | Archive, but instant retrieval |
| GLACIER | Cheapest "true" archive — retrieval takes minutes–hours |
| DEEP_ARCHIVE | Cheapest overall — retrieval takes hours |

Note: once an object is in GLACIER or DEEP_ARCHIVE, you must request a
"restore" (via the AWS console/CLI/SDK) before you can download it again —
this app only handles the upload side.

If you're using an S3-compatible provider that isn't AWS (e.g. Backblaze B2,
Wasabi, MinIO), set the **Custom S3 endpoint URL** field.

### Schedule
Enable scheduled backups and set a standard 5-field cron expression, e.g.:

- `0 3 * * *` — nightly at 3:00 AM
- `0 */6 * * *` — every 6 hours
- `0 3 * * 0` — weekly, Sunday at 3:00 AM

The schedule runs as long as the `app.py` process stays running — for a
real deployment, run it under `systemd`, `pm2`, Docker with `restart:
always`, etc.

## Data storage

- `data/config.json` — your settings (contains credentials — keep this file
  private and consider `.gitignore`-ing it)
- `data/state.db` — SQLite database tracking what's already been backed up

## Notes / Limitations

- This is a single-process Flask dev server, fine for personal/homelab use.
  For anything exposed beyond localhost/your LAN, put it behind a reverse
  proxy with auth, or run with a production WSGI server (gunicorn/waitress).
- The Immich API has changed across versions; the client tries the modern
  `/api/search/metadata` pagination endpoint first and falls back to
  `/api/asset`. If asset listing fails, check your Immich version's API docs
  and adjust `immich_client.py` if needed.
- Deleted-in-Immich assets are not automatically pruned from backups — this
  tool is additive/incremental by design (safer for a backup tool).
# immich-backup
