"""
config.py
Handles loading/saving app configuration to a local JSON file.
Keeping it simple and dependency-free (no DB needed for config).
"""
import json
import os
from threading import Lock

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "data", "config.json")

_lock = Lock()

DEFAULT_CONFIG = {
    # Immich connection
    "immich_url": "",          # e.g. http://localhost:2283
    "immich_api_key": "",

    # Filesystem access to the Immich library (must be mounted/visible to this app)
    # This is the path on disk that corresponds to Immich's internal "upload" root.
    "immich_library_root": "",   # e.g. /mnt/immich/library
    # If Immich reports paths like /usr/src/app/upload/... internally, set the prefix
    # that needs to be replaced with immich_library_root.
    "immich_internal_prefix": "/usr/src/app/upload",

    # Local external storage backup destination
    "local_backup_enabled": True,
    "local_backup_path": "",     # e.g. /mnt/external-drive/immich-backup

    # S3 / Glacier backup destination
    "s3_backup_enabled": False,
    "s3_bucket": "",
    "s3_prefix": "immich-backup/",
    "s3_region": "us-east-1",
    "s3_storage_class": "GLACIER",  # GLACIER | DEEP_ARCHIVE | GLACIER_IR | STANDARD
    "aws_access_key_id": "",
    "aws_secret_access_key": "",
    "s3_endpoint_url": "",       # optional, for S3-compatible providers

    # Scheduling
    "schedule_enabled": False,
    "schedule_cron": "0 3 * * *",  # default: nightly at 3am

    # Misc
    "request_timeout": 30,
}


def _ensure_file():
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)


def load_config():
    with _lock:
        _ensure_file()
        with open(CONFIG_PATH, "r") as f:
            cfg = json.load(f)
        # backfill any missing keys from defaults (handles upgrades)
        merged = {**DEFAULT_CONFIG, **cfg}
        return merged


def save_config(new_values: dict):
    with _lock:
        _ensure_file()
        cfg = load_config()
        cfg.update(new_values)
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2)
        return cfg
