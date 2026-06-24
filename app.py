"""
app.py
Flask web dashboard for the Immich incremental backup tool.

Run with: python app.py
Then open http://localhost:5000
"""
import threading
from flask import Flask, render_template, request, jsonify, redirect, url_for

import config as cfg_module
import db
import scheduler
from backup_engine import BackupRunner
from immich_client import ImmichClient

app = Flask(__name__)

_run_lock = threading.Lock()
_run_state = {"running": False, "current_run_id": None}


def trigger_backup(trigger="manual"):
    if not _run_lock.acquire(blocking=False):
        return None
    try:
        _run_state["running"] = True
        cfg = cfg_module.load_config()
        runner = BackupRunner(cfg)
        run_id = runner.run(trigger=trigger)
        _run_state["current_run_id"] = run_id
        return run_id
    finally:
        _run_state["running"] = False
        _run_lock.release()


def trigger_backup_async(trigger="manual"):
    if _run_state["running"]:
        return False
    thread = threading.Thread(target=trigger_backup, kwargs={"trigger": trigger}, daemon=True)
    thread.start()
    return True


@app.route("/")
def index():
    cfg = cfg_module.load_config()
    stats = db.get_stats()
    runs = db.get_recent_runs(10)
    next_run = scheduler.get_next_run_time()
    return render_template(
        "index.html",
        cfg=cfg,
        stats=stats,
        runs=runs,
        running=_run_state["running"],
        next_run=next_run,
    )


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        form = request.form
        new_cfg = {
            "immich_url": form.get("immich_url", "").strip(),
            "immich_api_key": form.get("immich_api_key", "").strip(),
            "immich_library_root": form.get("immich_library_root", "").strip(),
            "immich_internal_prefix": form.get("immich_internal_prefix", "").strip(),
            "local_backup_enabled": "local_backup_enabled" in form,
            "local_backup_path": form.get("local_backup_path", "").strip(),
            "s3_backup_enabled": "s3_backup_enabled" in form,
            "s3_bucket": form.get("s3_bucket", "").strip(),
            "s3_prefix": form.get("s3_prefix", "").strip(),
            "s3_region": form.get("s3_region", "").strip(),
            "s3_storage_class": form.get("s3_storage_class", "GLACIER"),
            "aws_access_key_id": form.get("aws_access_key_id", "").strip(),
            "aws_secret_access_key": form.get("aws_secret_access_key", "").strip(),
            "s3_endpoint_url": form.get("s3_endpoint_url", "").strip(),
            "schedule_enabled": "schedule_enabled" in form,
            "schedule_cron": form.get("schedule_cron", "0 3 * * *").strip(),
        }
        cfg_module.save_config(new_cfg)
        scheduler.apply_schedule_from_config()
        return redirect(url_for("index"))

    cfg = cfg_module.load_config()
    return render_template("settings.html", cfg=cfg)


@app.route("/api/test-connection", methods=["POST"])
def test_connection():
    cfg = cfg_module.load_config()
    if not cfg.get("immich_url") or not cfg.get("immich_api_key"):
        return jsonify({"ok": False, "message": "Set Immich URL and API key first"})
    client = ImmichClient(cfg["immich_url"], cfg["immich_api_key"])
    ok, message = client.test_connection()
    return jsonify({"ok": ok, "message": message})


@app.route("/api/run", methods=["POST"])
def api_run():
    started = trigger_backup_async(trigger="manual")
    if not started:
        return jsonify({"ok": False, "message": "A backup run is already in progress"})
    return jsonify({"ok": True, "message": "Backup started"})


@app.route("/api/status")
def api_status():
    stats = db.get_stats()
    runs = db.get_recent_runs(5)
    return jsonify({
        "running": _run_state["running"],
        "stats": stats,
        "runs": runs,
        "next_run": scheduler.get_next_run_time(),
    })


@app.route("/api/run/<int:run_id>")
def api_run_detail(run_id):
    run = db.get_run(run_id)
    if not run:
        return jsonify({"ok": False, "message": "Run not found"}), 404
    return jsonify({"ok": True, "run": run})


if __name__ == "__main__":
    import os
    db.init_db()
    scheduler.init_scheduler(trigger_backup_async)
    port = int(os.environ.get("PORT", 2284))
    app.run(host="0.0.0.0", port=port, debug=False)
