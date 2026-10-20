"""Data shapes shared by the store, the Claude calls and the API."""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# --- Profile -----------------------------------------------------------------

class Language(BaseModel):
    language: str
    level: str


class Experience(BaseModel):
    title: str
    company: str
    location: str = ""
    start: str = ""
    end: str = ""
    bullets: List[str] = Field(default_factory=list)


class Education(BaseModel):
    degree: str
    institution: str
    start: str = ""
    end: str = ""
    details: str = ""


class Profile(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin: str = ""
    headline: str = ""
    summary: str = ""
    languages: List[Language] = Field(default_factory=list)
    experience: List[Experience] = Field(default_factory=list)
    education: List[Education] = Field(default_factory=list)
    primary_skills: List[str] = Field(default_factory=list)
    secondary_skills: List[str] = Field(default_factory=list)
    tools: List[str] = Field(default_factory=list)
    certifications: List[str] = Field(default_factory=list)
    strengths: str = ""
    work_style: str = ""
    career_goals: str = ""
    target_roles: List[str] = Field(default_factory=list)
    target_locations: List[str] = Field(default_factory=list)
    work_rights: str = ""
    dealbreakers: List[str] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.name or self.experience or self.primary_skills)


# --- Fit evaluation ----------------------------------------------------------

GateVerdict = Literal["PASS", "FLAG", "FAIL"]


class Gate(BaseModel):
    verdict: GateVerdict
    note: str


class Dimension(BaseModel):
    score: int = Field(description="0-100")
    reasoning: str


class FitAssessment(BaseModel):
    role: str
    company: str
    eligibility: Gate
    language: Gate
    location: Gate
    technical_skills: Dimension
    experience: Dimension
    culture: Dimension
    career_alignment: Dimension
    strengths: List[str]
    gaps: List[str]
    recommendation: str


# Weighting and thresholds from .claude/skills/job-application-assistant/04-job-evaluation.md
WEIGHTS = {"technical_skills": 0.30, "experience": 0.25, "culture": 0.15, "career_alignment": 0.30}
THRESHOLDS = [(75, "Strong Fit"), (60, "Good Fit"), (45, "Moderate Fit"), (30, "Weak Fit"), (0, "Poor Fit")]


def overall_score(fit: FitAssessment) -> int:
    total = sum(getattr(fit, k).score * w for k, w in WEIGHTS.items())
    return round(total)


def verdict_for(fit: FitAssessment) -> str:
    if fit.eligibility.verdict == "FAIL":
        return "Ineligible"
    if fit.language.verdict == "FAIL":
        return "Language mismatch"
    if fit.location.verdict == "FAIL":
        return "Location deal-breaker"
    score = overall_score(fit)
    return next(label for floor, label in THRESHOLDS if score >= floor)


# --- Tailored documents ------------------------------------------------------

class SkillGroup(BaseModel):
    name: str
    items: List[str]


class TailoredExperience(BaseModel):
    source_index: int = Field(description="Index of the entry in the profile's experience list")
    bullets: List[str]


class CVContent(BaseModel):
    headline: str
    summary: str
    skill_groups: List[SkillGroup]
    experience: List[TailoredExperience]


class CoverLetter(BaseModel):
    recipient: str = Field(description="Named person if the posting gives one, else 'Hiring Manager'")
    paragraphs: List[str]
    closing: str = Field(description="e.g. 'Kind regards'")


class TailoredDocuments(BaseModel):
    cv: CVContent
    cover_letter: CoverLetter
    keywords_covered: List[str]
    keywords_missing: List[str]


# --- Jobs --------------------------------------------------------------------

Status = Literal["new", "saved", "applied", "interview", "offer", "rejected", "archived"]
STATUSES = ["new", "saved", "applied", "interview", "offer", "rejected", "archived"]


class JobIn(BaseModel):
    title: str = ""
    company: str = ""
    location: str = ""
    url: str = ""
    description: str = ""
    source: str = "manual"
    external_id: Optional[str] = None
    posted: Optional[str] = None


class JobUpdate(BaseModel):
    status: Optional[Status] = None
    notes: Optional[str] = None
    applied_at: Optional[str] = None
    title: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
