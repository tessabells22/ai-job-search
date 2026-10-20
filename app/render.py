"""Render the CV and cover letter as print-ready HTML (browser Print -> Save as PDF)."""

from datetime import date

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import config
from .models import Profile

env = Environment(
    loader=FileSystemLoader(config.REPO_ROOT / "app" / "templates"),
    autoescape=select_autoescape(["html"]),
)


def merge_experience(profile: Profile, tailored: list) -> list:
    """Titles, companies and dates always come from the profile, never from the model.
    A role the model dropped is kept with its first two original bullets; an index
    that points nowhere is discarded."""
    bullets_by_index = {}
    for entry in tailored:
        i = entry["source_index"]
        if 0 <= i < len(profile.experience) and i not in bullets_by_index:
            bullets_by_index[i] = entry["bullets"]
    merged = []
    for i, exp in enumerate(profile.experience):
        item = exp.model_dump()
        item["bullets"] = bullets_by_index.get(i, exp.bullets[:2])
        merged.append(item)
    return merged


def render_cv(profile: Profile, docs: dict) -> str:
    cv = docs["cv"]
    return env.get_template("cv.html").render(
        p=profile, cv=cv, experience=merge_experience(profile, cv["experience"]),
    )


def render_cover(profile: Profile, docs: dict, job: dict) -> str:
    return env.get_template("cover.html").render(
        p=profile, letter=docs["cover_letter"], job=job, today=date.today().strftime("%d %B %Y"),
    )
