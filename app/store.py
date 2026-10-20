"""SQLite store for jobs and generated documents, JSON file for the profile."""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from . import config
from .models import JobIn, Profile

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    external_id TEXT,
    title TEXT NOT NULL DEFAULT '',
    company TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    posted TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    notes TEXT NOT NULL DEFAULT '',
    applied_at TEXT,
    fit_json TEXT,
    fit_score INTEGER,
    fit_verdict TEXT,
    guard_verdict TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (source, external_id)
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    content_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

JOB_FIELDS = ("title", "company", "location", "description", "status", "notes", "applied_at")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    config.ensure_data_dir()
    # One connection per request; FastAPI may open and close it on different threads.
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def _job_dict(row: sqlite3.Row) -> dict:
    job = dict(row)
    job["fit"] = json.loads(job.pop("fit_json")) if job.get("fit_json") else None
    return job


def list_jobs(conn, status: Optional[str] = None) -> list:
    if status:
        rows = conn.execute("SELECT * FROM jobs WHERE status = ? ORDER BY updated_at DESC", (status,))
    else:
        rows = conn.execute("SELECT * FROM jobs ORDER BY updated_at DESC")
    return [_job_dict(r) for r in rows]


def get_job(conn, job_id: int) -> Optional[dict]:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _job_dict(row) if row else None


def upsert_job(conn, job: JobIn) -> tuple:
    """Insert a job; a known (source, external_id) is left as is. Returns (id, created)."""
    if job.external_id:
        row = conn.execute(
            "SELECT id FROM jobs WHERE source = ? AND external_id = ?", (job.source, job.external_id)
        ).fetchone()
        if row:
            return row["id"], False
    now = _now()
    cur = conn.execute(
        """INSERT INTO jobs (source, external_id, title, company, location, url, description,
                             posted, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (job.source, job.external_id, job.title, job.company, job.location, job.url,
         job.description, job.posted, now, now),
    )
    conn.commit()
    return cur.lastrowid, True


def update_job(conn, job_id: int, fields: dict) -> None:
    fields = {k: v for k, v in fields.items() if k in JOB_FIELDS and v is not None}
    if fields.get("status") == "applied" and not fields.get("applied_at"):
        current = get_job(conn, job_id)
        if current and not current["applied_at"]:
            fields["applied_at"] = _now()[:10]
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE jobs SET {sets}, updated_at = ? WHERE id = ?", (*fields.values(), _now(), job_id))
    conn.commit()


def save_fit(conn, job_id: int, fit: dict, score: int, verdict: str, guard_verdict: str) -> None:
    conn.execute(
        """UPDATE jobs SET fit_json = ?, fit_score = ?, fit_verdict = ?, guard_verdict = ?,
                          updated_at = ? WHERE id = ?""",
        (json.dumps(fit), score, verdict, guard_verdict, _now(), job_id),
    )
    conn.commit()


def delete_job(conn, job_id: int) -> None:
    conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    conn.commit()


def save_documents(conn, job_id: int, content: dict) -> int:
    cur = conn.execute(
        "INSERT INTO documents (job_id, content_json, created_at) VALUES (?, ?, ?)",
        (job_id, json.dumps(content), _now()),
    )
    conn.commit()
    return cur.lastrowid


def latest_documents(conn, job_id: int) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM documents WHERE job_id = ? ORDER BY id DESC LIMIT 1", (job_id,)
    ).fetchone()
    if not row:
        return None
    return {"id": row["id"], "created_at": row["created_at"], **json.loads(row["content_json"])}


def stats(conn) -> dict:
    rows = conn.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status").fetchall()
    return {r["status"]: r["n"] for r in rows}


def load_profile() -> Profile:
    if not config.PROFILE_PATH.exists():
        return Profile()
    return Profile.model_validate_json(config.PROFILE_PATH.read_text(encoding="utf-8"))


def save_profile(profile: Profile) -> None:
    config.ensure_data_dir()
    config.PROFILE_PATH.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
