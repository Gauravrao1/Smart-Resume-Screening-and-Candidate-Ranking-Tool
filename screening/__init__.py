"""Smart resume screening: parse -> extract -> rank."""
from __future__ import annotations

from datetime import date

from .extractor import Profile, build_profile
from .parser import ALLOWED_EXTENSIONS, ParseError, extract_text
from .ranker import JobRequirements, Result, parse_job_description, rank_candidates

__all__ = ["screen", "ALLOWED_EXTENSIONS", "ParseError", "Profile", "JobRequirements", "Result"]


def screen(jd_text: str, files: list[tuple[str, bytes]], extra_required: str = "",
           today: date | None = None) -> dict:
    """Screen resumes against a job description.

    ``files`` is a list of ``(filename, bytes)``. Files that cannot be read are
    reported in ``errors`` instead of aborting the whole run.
    """
    extras = [t.strip() for t in extra_required.replace("\n", ",").split(",") if t.strip()][:30]
    req = parse_job_description(jd_text, extras)

    profiles, errors = [], []
    for filename, data in files:
        try:
            text = extract_text(filename, data)
        except ParseError as exc:
            errors.append({"filename": filename, "error": str(exc)})
            continue
        profiles.append(build_profile(filename, text, today))

    results = rank_candidates(jd_text, profiles, req) if profiles else []
    return {"requirements": req.to_dict(), "results": [r.to_dict() for r in results], "errors": errors}
