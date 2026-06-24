"""
backup_engine.py
Core incremental backup logic.

For each asset reported by Immich:
  1. Resolve its real filesystem path (mapping Immich's internal path to
     the path visible to this app via immich_library_root).
  2. Compare its checksum (provided by Immich) against what we recorded
     last time we successfully backed it up.
  3. If new or changed:
       - copy to local_backup_path (mirrors original relative structure)
       - upload to S3 with the configured storage class (e.g. GLACIER)
  4. Record the result in the local SQLite state DB.

Designed to be safely re-run: failures on individual assets don't abort
the whole run, and a re-run will simply retry whatever didn't finish.
"""
import os
import shutil
import traceback
from datetime import datetime, timezone

import db
from immich_client import ImmichClient

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:
    boto3 = None


class BackupRunner:
    def __init__(self, config, log_callback=None):
        self.config = config
        self.log_lines = []
        self.log_callback = log_callback
        self._s3_client = None

    def log(self, msg):
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        self.log_lines.append(line)
        if self.log_callback:
            self.log_callback(line)

    # ---------- path resolution ----------

    def resolve_local_path(self, original_path):
        cfg = self.config
        prefix = cfg.get("immich_internal_prefix") or ""
        root = cfg.get("immich_library_root") or ""
        if not root:
            return None
        if prefix and original_path.startswith(prefix):
            rel = original_path[len(prefix):].lstrip("/")
        else:
            rel = original_path.lstrip("/")
        return os.path.join(root, rel)

    # ---------- S3 ----------

    def get_s3_client(self):
        if self._s3_client is None:
            if boto3 is None:
                raise RuntimeError("boto3 is not installed")
            cfg = self.config
            kwargs = {"region_name": cfg.get("s3_region") or "us-east-1"}
            if cfg.get("aws_access_key_id") and cfg.get("aws_secret_access_key"):
                kwargs["aws_access_key_id"] = cfg["aws_access_key_id"]
                kwargs["aws_secret_access_key"] = cfg["aws_secret_access_key"]
            if cfg.get("s3_endpoint_url"):
                kwargs["endpoint_url"] = cfg["s3_endpoint_url"]
            self._s3_client = boto3.client("s3", **kwargs)
        return self._s3_client

    def upload_to_s3(self, local_file_path, rel_path):
        cfg = self.config
        key = (cfg.get("s3_prefix") or "").rstrip("/") + "/" + rel_path.lstrip("/")
        key = key.lstrip("/")
        client = self.get_s3_client()
        extra_args = {"StorageClass": cfg.get("s3_storage_class", "GLACIER")}
        client.upload_file(local_file_path, cfg["s3_bucket"], key, ExtraArgs=extra_args)
        return key

    # ---------- main run ----------

    def run(self, trigger="manual"):
        cfg = self.config
        run_id = db.create_run(trigger)
        self.log(f"Starting backup run (trigger={trigger})")

        total = copied_local = uploaded_s3 = skipped = errors = 0

        try:
            if not cfg.get("immich_url") or not cfg.get("immich_api_key"):
                raise RuntimeError("Immich URL / API key not configured")

            client = ImmichClient(cfg["immich_url"], cfg["immich_api_key"], cfg.get("request_timeout", 30))

            local_enabled = cfg.get("local_backup_enabled") and cfg.get("local_backup_path")
            s3_enabled = cfg.get("s3_backup_enabled") and cfg.get("s3_bucket")

            if local_enabled:
                os.makedirs(cfg["local_backup_path"], exist_ok=True)

            for asset in client.iter_all_assets():
                total += 1
                asset_id = asset.get("id")
                original_path = asset.get("originalPath") or asset.get("resizePath") or ""
                checksum = asset.get("checksum", "")
                if not asset_id or not original_path:
                    continue

                state = db.get_asset_state(asset_id) or {}
                needs_local = local_enabled and state.get("local_backup_checksum") != checksum
                needs_s3 = s3_enabled and state.get("s3_backup_checksum") != checksum

                if not needs_local and not needs_s3:
                    skipped += 1
                    continue

                src_path = self.resolve_local_path(original_path)
                if not src_path or not os.path.isfile(src_path):
                    self.log(f"WARN: source file not found for asset {asset_id}: {src_path}")
                    errors += 1
                    continue

                rel_path = os.path.relpath(src_path, cfg.get("immich_library_root", "/"))
                update_fields = {
                    "original_path": original_path,
                    "checksum": checksum,
                    "file_size": os.path.getsize(src_path),
                    "last_seen_at": datetime.now(timezone.utc).isoformat(),
                }

                if needs_local:
                    try:
                        dest_path = os.path.join(cfg["local_backup_path"], rel_path)
                        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                        shutil.copy2(src_path, dest_path)
                        update_fields["local_backup_checksum"] = checksum
                        update_fields["local_backup_at"] = datetime.now(timezone.utc).isoformat()
                        copied_local += 1
                    except Exception as e:
                        self.log(f"ERROR copying {asset_id} locally: {e}")
                        errors += 1

                if needs_s3:
                    try:
                        self.upload_to_s3(src_path, rel_path)
                        update_fields["s3_backup_checksum"] = checksum
                        update_fields["s3_backup_at"] = datetime.now(timezone.utc).isoformat()
                        uploaded_s3 += 1
                    except Exception as e:
                        self.log(f"ERROR uploading {asset_id} to S3: {e}")
                        errors += 1

                db.upsert_asset_state(asset_id, **update_fields)

                if total % 50 == 0:
                    self.log(f"Progress: {total} processed, {copied_local} copied locally, "
                              f"{uploaded_s3} uploaded to S3, {skipped} skipped, {errors} errors")
                    db.update_run(run_id, total_assets=total, copied_local=copied_local,
                                   uploaded_s3=uploaded_s3, skipped=skipped, errors=errors,
                                   log="\n".join(self.log_lines))

            self.log(f"Run complete: {total} total, {copied_local} copied locally, "
                     f"{uploaded_s3} uploaded to S3, {skipped} skipped, {errors} errors")
            db.finish_run(run_id, "completed", total_assets=total, copied_local=copied_local,
                          uploaded_s3=uploaded_s3, skipped=skipped, errors=errors,
                          log="\n".join(self.log_lines))

        except Exception as e:
            self.log(f"FATAL: {e}\n{traceback.format_exc()}")
            db.finish_run(run_id, "failed", total_assets=total, copied_local=copied_local,
                          uploaded_s3=uploaded_s3, skipped=skipped, errors=errors,
                          log="\n".join(self.log_lines))
        return run_id
