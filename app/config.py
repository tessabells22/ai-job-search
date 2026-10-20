"""Paths and settings. Everything personal lives under DATA_DIR, which git ignores."""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("JOBSEARCH_DATA_DIR", REPO_ROOT / "data"))
DB_PATH = DATA_DIR / "jobs.db"
PROFILE_PATH = DATA_DIR / "profile.json"
SKILLS_DIR = REPO_ROOT / ".agents" / "skills"
TOOLS_DIR = REPO_ROOT / "tools"

MODEL = os.environ.get("JOBSEARCH_MODEL", "claude-opus-5-5")
HOST = os.environ.get("JOBSEARCH_HOST", "127.0.0.1")
PORT = int(os.environ.get("JOBSEARCH_PORT", "8000"))


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
