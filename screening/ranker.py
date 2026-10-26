"""Parse a job description and score / rank candidates against it."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from sklearn.feature_extraction.text import TfidfVectorizer

from .extractor import EDU_LABELS, Profile, detect_education_level
from .skills import SKILLS, canonicalize, has_skill, pattern_for

# Score = weighted sum of five 0-100 components.
WEIGHTS = {"skills": 0.45, "similarity": 0.25, "experience": 0.15, "education": 0.10, "extras": 0.05}
SIM_CAP = 0.5            # TF-IDF cosine at/above this counts as a 100% text match
LISTED_ONLY_CREDIT = 0.75  # skill only in a skills list (no evidence of use) gets 75% credit

_PREF_START = re.compile(r"^\W*(?:nice to have|preferred(?: skills| qualifications)?|good to have|bonus(?: points)?|desirable|optional)\b", re.I)
_REQ_START = re.compile(r"^\W*(?:requirements?|required(?: skills| qualifications)?|must[- ]have|qualifications|responsibilities|what you(?:'ll| will) need|key skills)\b", re.I)
_PREF_INLINE = re.compile(r"nice to have|good to have|preferred|a plus|bonus|desirable", re.I)
_YEARS = [
    re.compile(r"(\d{1,2})\s*(?:\+|(?:-|–|to)\s*\d{1,2})?\s*(?:years?|yrs?)(?:\s+of)?[^.\n]{0,40}?experience", re.I),
    re.compile(r"experience[^.\n]{0,40}?(\d{1,2})\s*(?:\+|(?:-|–|to)\s*\d{1,2})?\s*(?:years?|yrs?)", re.I),
]


@dataclass
class JobRequirements:
    required: list[str] = field(default_factory=list)
    preferred: list[str] = field(default_factory=list)
    min_years: float | None = None
    min_education: int = 0

    def to_dict(self) -> dict:
        return {
            "required_skills": self.required, "preferred_skills": self.preferred,
            "min_years": self.min_years, "min_education": EDU_LABELS[self.min_education] if self.min_education else None,
        }


def parse_job_description(jd: str, extra_required: list[str] | None = None) -> JobRequirements:
    required: list[str] = []
    preferred: list[str] = []
    edu_levels: list[int] = []
    in_pref = False
    for line in jd.split("\n"):
        if _PREF_START.match(line):
            in_pref = True
        elif _REQ_START.match(line):
            in_pref = False
        is_pref = in_pref or bool(_PREF_INLINE.search(line))
        bucket = preferred if is_pref else required
        for skill in SKILLS:
            if has_skill(skill, line) and skill not in bucket:
                bucket.append(skill)
        level = detect_education_level(line)
        if level and not is_pref:  # a "preferred" degree is not a minimum
            edu_levels.append(level)
    for token in extra_required or []:
        name = canonicalize(token)
        if name and name not in required:
            required.append(name)
    preferred = [s for s in preferred if s not in required]

    years = None
    for rx in _YEARS:
        m = rx.search(jd)
        if m:
            years = float(m.group(1))
            break
    return JobRequirements(required, preferred, years, min(edu_levels) if edu_levels else 0)


@dataclass
class Result:
    rank: int
    profile: Profile
    score: float
    label: str
    breakdown: dict[str, float]
    matched_required: list[str]
    missing_required: list[str]
    matched_preferred: list[str]
    listed_only: list[str]
    flags: list[str]

    def to_dict(self) -> dict:
        d = self.profile.to_dict()
        d.update({
            "rank": self.rank, "score": self.score, "label": self.label, "breakdown": self.breakdown,
            "matched_required": self.matched_required, "missing_required": self.missing_required,
            "matched_preferred": self.matched_preferred, "listed_only": self.listed_only, "flags": self.flags,
        })
        return d


def label_for(score: float) -> str:
    if score >= 75:
        return "Strong match"
    if score >= 60:
        return "Good match"
    if score >= 40:
        return "Partial match"
    return "Weak match"


def _similarities(jd: str, profiles: list[Profile]) -> list[float]:
    """TF-IDF cosine similarity (0-1) of each resume to the job description."""
    texts = [p.text for p in profiles]
    if not any(t.strip() for t in texts):
        return [0.0] * len(profiles)
    try:
        vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
        matrix = vec.fit_transform([jd] + texts)
    except ValueError:  # empty vocabulary
        return [0.0] * len(profiles)
    return [float(x) for x in (matrix[1:] @ matrix[0].T).toarray().ravel()]


def _skill_component(skills: list[str], profile: Profile) -> tuple[list[str], list[str], list[str]]:
    """Return (matched, missing, listed_only) for a list of wanted skills."""
    matched, missing, listed_only = [], [], []
    has_context = bool(profile.context_text)
    for s in skills:
        if not has_skill(s, profile.text):
            missing.append(s)
        else:
            matched.append(s)
            if has_context and not has_skill(s, profile.context_text):
                listed_only.append(s)
    return matched, missing, listed_only


def _skill_score(skills: list[str], matched: list[str], listed_only: list[str]) -> float:
    if not skills:
        return 0.0
    credit = sum(LISTED_ONLY_CREDIT if s in listed_only else 1.0 for s in matched)
    return 100.0 * credit / len(skills)


def _education_score(level: int, wanted: int) -> float:
    if wanted:
        return 100.0 if level >= wanted else 100.0 * level / wanted
    return {0: 30.0, 1: 50.0, 2: 75.0, 3: 90.0, 4: 100.0}[level]


def rank_candidates(jd_text: str, profiles: list[Profile], req: JobRequirements) -> list[Result]:
    sims = _similarities(jd_text, profiles)
    has_skill_reqs = bool(req.required or req.preferred)
    results: list[Result] = []

    for profile, sim in zip(profiles, sims):
        sim_score = min(1.0, sim / SIM_CAP) * 100
        m_req, miss_req, lo_req = _skill_component(req.required, profile)
        m_pref, _, lo_pref = _skill_component(req.preferred, profile)

        if req.required and req.preferred:
            skills = 0.85 * _skill_score(req.required, m_req, lo_req) + 0.15 * _skill_score(req.preferred, m_pref, lo_pref)
        elif req.required:
            skills = _skill_score(req.required, m_req, lo_req)
        elif req.preferred:
            skills = _skill_score(req.preferred, m_pref, lo_pref)
        else:
            skills = sim_score  # JD names no known skills: fall back to text similarity

        years_needed = req.min_years if req.min_years else 3.0
        experience = min(1.0, profile.experience_years / years_needed) * 100
        education = _education_score(profile.education_level, req.min_education)
        extras = min(100.0, len(profile.certifications) * 30 + len(profile.projects) * 20)

        breakdown = {"skills": skills, "similarity": sim_score, "experience": experience,
                     "education": education, "extras": extras}
        total = sum(WEIGHTS[k] * v for k, v in breakdown.items())
        if not profile.text.strip():
            total = 0.0

        flags = []
        if not profile.text.strip():
            flags.append("No readable text (scanned image PDF?) - cannot be scored")
        if req.required and len(miss_req) > len(req.required) / 2:
            flags.append(f"Missing {len(miss_req)} of {len(req.required)} required skills")
        if req.min_years and profile.experience_years < req.min_years:
            flags.append(f"Experience ({profile.experience_years:g} yrs) below required {req.min_years:g} yrs")
        if req.min_education and profile.education_level < req.min_education:
            flags.append(f"Education below required {EDU_LABELS[req.min_education]}")
        if not profile.email:
            flags.append("No email address found")
        if profile.word_count and profile.word_count < 80:
            flags.append("Very short resume - extraction may be incomplete")
        if not has_skill_reqs:
            flags.append("Job description lists no recognised skills - ranked mainly by text similarity")

        results.append(Result(0, profile, round(total, 1), label_for(total),
                              {k: round(v, 1) for k, v in breakdown.items()},
                              m_req, miss_req, m_pref, sorted(set(lo_req + lo_pref)), flags))

    results.sort(key=lambda r: (-r.score, -len(r.matched_required), r.profile.name.lower()))
    seen: dict[str, str] = {}
    for i, r in enumerate(results, 1):
        r.rank = i
        key = r.profile.email
        if key:
            if key in seen:
                r.flags.append(f"Possible duplicate of {seen[key]} (same email)")
            else:
                seen[key] = r.profile.name
    return results
