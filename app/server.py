"""FastAPI server: JSON API under /api, the single-page UI under /, documents under /jobs/{id}/."""

import shutil
from typing import List, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import ai, config, render, sources, store
from .models import JobIn, JobUpdate, Profile, overall_score, verdict_for

STATIC = config.REPO_ROOT / "app" / "static"
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}

app = FastAPI(title="Job Search", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def local_only(request: Request, call_next):
    # Host check blocks DNS rebinding; the custom header on writes forces a CORS
    # preflight (which this app never answers), so other sites can't post to it.
    host = (request.headers.get("host") or "").rsplit(":", 1)[0]
    if host not in ALLOWED_HOSTS:
        return JSONResponse({"detail": "Forbidden host"}, status_code=403)
    if request.method not in ("GET", "HEAD") and request.headers.get("x-jobsearch") != "1":
        return JSONResponse({"detail": "Missing X-JobSearch header"}, status_code=403)
    return await call_next(request)


@app.exception_handler(ai.AIError)
async def ai_error(_, exc):
    return JSONResponse({"detail": str(exc)}, status_code=502)


@app.exception_handler(sources.SourceError)
async def source_error(_, exc):
    return JSONResponse({"detail": str(exc)}, status_code=502)


def db():
    conn = store.connect()
    try:
        yield conn
    finally:
        conn.close()


def _job_or_404(conn, job_id: int) -> dict:
    job = store.get_job(conn, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


def _require_profile() -> Profile:
    profile = store.load_profile()
    if profile.is_empty():
        raise HTTPException(400, "Set up your profile first.")
    return profile


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/status")
def status():
    import os
    return {
        "api_key_set": bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")),
        "bun_installed": bool(shutil.which("bun")),
        "profile_ready": not store.load_profile().is_empty(),
        "model": config.MODEL,
    }


# --- Profile -----------------------------------------------------------------

@app.get("/api/profile")
def get_profile():
    return store.load_profile()


@app.put("/api/profile")
def put_profile(profile: Profile):
    store.save_profile(profile)
    return profile


@app.post("/api/profile/import")
async def import_profile(text: str = Form(""), file: Optional[UploadFile] = File(None)):
    pdf = None
    if file is not None and file.filename:
        data = await file.read()
        if file.filename.lower().endswith(".pdf"):
            pdf = data
        else:
            text = (text + "\n\n" + data.decode("utf-8", errors="replace")).strip()
    if not text and not pdf:
        raise HTTPException(400, "Paste your CV text or upload a PDF.")
    # Imported data is a draft for review: returned, not saved.
    return ai.import_profile(text, pdf)


# --- Search ------------------------------------------------------------------

class SearchRequest(BaseModel):
    portals: List[str]
    query: str
    location: str = ""
    jobage: int = 0
    limit: int = 25


@app.get("/api/portals")
def portals():
    return sources.list_portals()


@app.post("/api/search")
def search(req: SearchRequest, conn=Depends(db)):
    if not req.query.strip():
        raise HTTPException(400, "Enter search keywords.")
    added, seen, errors = [], 0, []
    for portal in req.portals:
        try:
            jobs = sources.search(portal, req.query, req.location, req.jobage, req.limit)
        except sources.SourceError as e:
            errors.append(str(e))
            continue
        for job in jobs:
            job_id, created = store.upsert_job(conn, job)
            if created:
                added.append(job_id)
            else:
                seen += 1
    return {"added": len(added), "already_seen": seen, "errors": errors}


# --- Jobs --------------------------------------------------------------------

class NewJob(BaseModel):
    url: str = ""
    text: str = ""
    title: str = ""
    company: str = ""
    location: str = ""


@app.get("/api/jobs")
def list_jobs(status: Optional[str] = None, conn=Depends(db)):
    return store.list_jobs(conn, status)


@app.get("/api/stats")
def stats(conn=Depends(db)):
    return store.stats(conn)


@app.post("/api/jobs")
def add_job(req: NewJob, conn=Depends(db)):
    if req.text.strip():
        description, verdict = sources.guard_text(req.text)
        job = JobIn(source="manual", title=req.title, company=req.company, location=req.location,
                    url=req.url, description=description)
    elif req.url.strip():
        fetched = sources.fetch_url(req.url.strip())
        job = JobIn(**{**fetched, **{k: v for k, v in
                                     {"title": req.title, "company": req.company, "location": req.location}.items() if v}})
    else:
        raise HTTPException(400, "Give a job URL or paste the posting text.")
    job_id, _ = store.upsert_job(conn, job)
    store.update_job(conn, job_id, {"status": "saved"})
    return store.get_job(conn, job_id)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: int, conn=Depends(db)):
    job = _job_or_404(conn, job_id)
    job["documents"] = store.latest_documents(conn, job_id)
    return job


@app.patch("/api/jobs/{job_id}")
def patch_job(job_id: int, update: JobUpdate, conn=Depends(db)):
    _job_or_404(conn, job_id)
    store.update_job(conn, job_id, update.model_dump(exclude_none=True))
    return store.get_job(conn, job_id)


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: int, conn=Depends(db)):
    _job_or_404(conn, job_id)
    store.delete_job(conn, job_id)
    return {"ok": True}


@app.post("/api/jobs/{job_id}/fetch")
def fetch_job(job_id: int, conn=Depends(db)):
    job = _job_or_404(conn, job_id)
    description, _ = sources.guard_text(sources.fetch_description(job))
    store.update_job(conn, job_id, {"description": description})
    return store.get_job(conn, job_id)


@app.post("/api/jobs/{job_id}/evaluate")
def evaluate(job_id: int, conn=Depends(db)):
    profile = _require_profile()
    job = _job_or_404(conn, job_id)
    if len(job["description"]) < 200:
        description, _ = sources.guard_text(sources.fetch_description(job))
        store.update_job(conn, job_id, {"description": description})
        job["description"] = description
    description, guard_verdict = sources.guard_text(job["description"])
    job["description"] = description
    fit = ai.evaluate_fit(profile, job)
    store.save_fit(conn, job_id, fit.model_dump(), overall_score(fit), verdict_for(fit), guard_verdict)
    if job["status"] == "new":
        store.update_job(conn, job_id, {"status": "saved"})
    return store.get_job(conn, job_id)


class TailorRequest(BaseModel):
    notes: str = ""


@app.post("/api/jobs/{job_id}/documents")
def tailor(job_id: int, req: TailorRequest, conn=Depends(db)):
    profile = _require_profile()
    job = _job_or_404(conn, job_id)
    if not job["description"]:
        raise HTTPException(400, "This job has no description yet. Fetch it or paste it first.")
    docs = ai.tailor_documents(profile, job, job["fit"], req.notes)
    store.save_documents(conn, job_id, docs.model_dump())
    return store.latest_documents(conn, job_id)


def _docs_or_404(conn, job_id: int):
    job = _job_or_404(conn, job_id)
    docs = store.latest_documents(conn, job_id)
    if not docs:
        raise HTTPException(404, "No documents generated for this job yet")
    return job, docs


@app.get("/jobs/{job_id}/cv", response_class=HTMLResponse)
def cv_page(job_id: int, conn=Depends(db)):
    _, docs = _docs_or_404(conn, job_id)
    return render.render_cv(store.load_profile(), docs)


@app.get("/jobs/{job_id}/cover", response_class=HTMLResponse)
def cover_page(job_id: int, conn=Depends(db)):
    job, docs = _docs_or_404(conn, job_id)
    return render.render_cover(store.load_profile(), docs, job)
