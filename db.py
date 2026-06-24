"""
db.py
SQLite-backed state tracking so backups are incremental:
we only copy/upload assets that are new or whose checksum changed
since the last successful backup.
"""
import sqlite3
import os
import threading

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "state.db")

_local = threading.local()


def get_conn():
    if not hasattr(_local, "conn"):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
    return _local.conn


def init_db():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS assets (
            asset_id TEXT PRIMARY KEY,
            original_path TEXT,
            checksum TEXT,
            file_size INTEGER,
            local_backup_checksum TEXT,
            local_backup_at TEXT,
            s3_backup_checksum TEXT,
            s3_backup_at TEXT,
            last_seen_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT,
            finished_at TEXT,
            trigger TEXT,
            status TEXT,
            total_assets INTEGER DEFAULT 0,
            copied_local INTEGER DEFAULT 0,
            uploaded_s3 INTEGER DEFAULT 0,
            skipped INTEGER DEFAULT 0,
            errors INTEGER DEFAULT 0,
            log TEXT DEFAULT ''
        )
    """)
    conn.commit()


def get_asset_state(asset_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM assets WHERE asset_id = ?", (asset_id,)).fetchone()
    return dict(row) if row else None


def upsert_asset_state(asset_id, **fields):
    conn = get_conn()
    existing = get_asset_state(asset_id)
    if existing:
        cols = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE assets SET {cols} WHERE asset_id = ?", (*fields.values(), asset_id))
    else:
        fields["asset_id"] = asset_id
        cols = ", ".join(fields.keys())
        placeholders = ", ".join("?" for _ in fields)
        conn.execute(f"INSERT INTO assets ({cols}) VALUES ({placeholders})", tuple(fields.values()))
    conn.commit()


def create_run(trigger):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO runs (started_at, trigger, status) VALUES (datetime('now'), ?, 'running')",
        (trigger,),
    )
    conn.commit()
    return cur.lastrowid


def update_run(run_id, **fields):
    conn = get_conn()
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE runs SET {cols} WHERE id = ?", (*fields.values(), run_id))
    conn.commit()


def finish_run(run_id, status, **fields):
    fields["status"] = status
    conn = get_conn()
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(
        f"UPDATE runs SET finished_at = datetime('now'), {cols} WHERE id = ?",
        (*fields.values(), run_id),
    )
    conn.commit()


def get_recent_runs(limit=20):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_run(run_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def get_stats():
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) c FROM assets").fetchone()["c"]
    local_done = conn.execute(
        "SELECT COUNT(*) c FROM assets WHERE local_backup_checksum IS NOT NULL AND local_backup_checksum = checksum"
    ).fetchone()["c"]
    s3_done = conn.execute(
        "SELECT COUNT(*) c FROM assets WHERE s3_backup_checksum IS NOT NULL AND s3_backup_checksum = checksum"
    ).fetchone()["c"]
    return {"total_assets": total, "local_backed_up": local_done, "s3_backed_up": s3_done}
