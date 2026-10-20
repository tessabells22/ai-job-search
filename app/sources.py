"""Job sources: the repo's portal CLIs (run with bun) and single-URL fetches.

Every portal CLI under .agents/skills/*/cli emits the same contract on
`search --format json`: {"meta": {...}, "results": [{id, title, company,
location, date, url, ...}]}. Posting text from any source passes through
tools/posting_guard.py before anything else reads it.
"""

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import config
from .models import JobIn

sys.path.insert(0, str(config.TOOLS_DIR))
import posting_guard  # noqa: E402

TIMEOUT = 90
# Portals whose CLI takes a free-text --location. The others are searched by keyword only.
LOCATION_FLAG = {"linkedin-search": "--location"}
LINKEDIN_URL = re.compile(r"linkedin\.com/jobs/view/(?:[^/?#]*-)?(\d+)")


class SourceError(Exception):
    pass


def _frontmatter(skill_md: Path) -> dict:
    text = skill_md.read_text(encoding="utf-8")
    meta = {}
    match = re.match(r"---\n(.*?)\n---", text, re.S)
    if match:
        for line in match.group(1).splitlines():
            m = re.match(r"^(\w[\w-]*):\s*(.*?)\s*(?:#.*)?$", line)
            if m:
                meta[m.group(1)] = m.group(2)
    return meta


def list_portals() -> list:
    portals = []
    for cli in sorted(config.SKILLS_DIR.glob("*/cli/src/cli.ts")):
        skill_dir = cli.parents[2]
        meta = _frontmatter(skill_dir / "SKILL.md") if (skill_dir / "SKILL.md").exists() else {}
        portals.append({
            "name": skill_dir.name,
            "enabled": meta.get("enabled", "true").lower() != "false",
            "takes_location": skill_dir.name in LOCATION_FLAG,
        })
    return portals


def _bun() -> str:
    bun = shutil.which("bun")
    if not bun:
        raise SourceError("Bun is not installed. Install it from https://bun.sh to search job portals.")
    return bun


def _run_cli(portal: str, args: list) -> str:
    cli = config.SKILLS_DIR / portal / "cli" / "src" / "cli.ts"
    if not cli.exists():
        raise SourceError(f"Unknown portal: {portal}")
    try:
        proc = subprocess.run(
            [_bun(), "run", str(cli), *args],
            capture_output=True, text=True, encoding="utf-8", timeout=TIMEOUT, cwd=config.REPO_ROOT,
        )
    except subprocess.TimeoutExpired:
        raise SourceError(f"{portal} timed out after {TIMEOUT}s")
    if proc.returncode != 0:
        err = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "no output"
        try:
            err = json.loads(err).get("error", err)
        except ValueError:
            pass
        raise SourceError(f"{portal}: {err}")
    return proc.stdout


def search(portal: str, query: str, location: str = "", jobage: int = 0, limit: int = 25) -> list:
    args = ["search", "--format", "json", "--query", query]
    if location and portal in LOCATION_FLAG:
        args += [LOCATION_FLAG[portal], location]
    elif portal in LOCATION_FLAG:
        raise SourceError(f"{portal} needs a location (a city, country or 'Remote')")
    if jobage:
        args += ["--jobage", str(jobage)]
    if limit:
        args += ["--limit", str(limit)]
    payload = json.loads(_run_cli(portal, args))
    jobs = []
    for r in payload.get("results", []):
        jobs.append(JobIn(
            source=portal,
            external_id=str(r.get("id") or r.get("url")),
            title=r.get("title") or "",
            company=r.get("company") or "",
            location=r.get("location") or "",
            url=r.get("url") or "",
            description=r.get("description") or "",
            posted=r.get("date"),
        ))
    return jobs


def guard_text(raw: str, mode: str = "text") -> tuple:
    """Run the integrity gate. Returns (cleaned_text, verdict_line)."""
    cleaned, findings = posting_guard.guard(raw, mode)
    return cleaned, findings["verdict"]


def fetch_description(job: dict) -> str:
    """Full posting text for a job that came from a portal search without one."""
    if job["source"] in {p["name"] for p in list_portals()} and job.get("external_id"):
        out = _run_cli(job["source"], ["detail", job["external_id"], "--format", "plain"])
        return out.strip()
    if job.get("url"):
        return fetch_url(job["url"])["description"]
    raise SourceError("This job has no URL or portal ID to fetch a description from.")


def fetch_url(url: str) -> dict:
    """Fetch one posting by URL. LinkedIn goes through its CLI, anything else through
    tools/fetch_page.py (GET only, robots.txt enforced). Returns JobIn-shaped fields."""
    m = LINKEDIN_URL.search(url)
    if m:
        detail = json.loads(_run_cli("linkedin-search", ["detail", m.group(1), "--format", "json"]))
        return {
            "source": "linkedin-search", "external_id": m.group(1), "url": detail.get("url") or url,
            "title": detail.get("title") or "", "company": detail.get("company") or "",
            "location": detail.get("location") or "", "description": detail.get("description") or "",
            "posted": detail.get("date"),
        }

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "page.html"
        proc = subprocess.run(
            [sys.executable, str(config.TOOLS_DIR / "fetch_page.py"), url, "--out", str(out)],
            capture_output=True, text=True, encoding="utf-8", timeout=TIMEOUT,
        )
        if proc.returncode != 0:
            raise SourceError((proc.stderr or proc.stdout).strip() or "Fetch failed")
        status = re.search(r"HTTP (\d+)", proc.stdout)
        if status and not status.group(1).startswith("2"):
            raise SourceError(f"The site answered HTTP {status.group(1)}. Paste the posting text instead.")
        raw = out.read_text(encoding="utf-8", errors="replace")
    title = re.search(r"<title[^>]*>(.*?)</title>", raw, re.S | re.I)
    text, _ = guard_text(raw, "html")
    return {
        "source": "url", "external_id": url, "url": url,
        "title": (title.group(1).strip() if title else "")[:200],
        "company": "", "location": "", "description": text, "posted": None,
    }
