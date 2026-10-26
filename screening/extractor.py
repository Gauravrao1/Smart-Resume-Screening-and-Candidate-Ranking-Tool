"""Turn raw resume text into a structured profile.

Rule-based NLP: section detection, regular expressions and a skill taxonomy.
No external model downloads are needed, so it works offline and is fast.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from .skills import find_skills

# --------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------
_SECTION_HEADS = {
    "skills": r"(?:technical\s+|key\s+|core\s+)?skills?(?:\s*(?:&|and)\s*tools?)?|core competencies|technologies|tech stack|technical proficiency",
    "education": r"education(?:al)?(?:\s+(?:background|qualifications?))?|academics?(?:\s+(?:background|qualifications?))?|qualifications?",
    "experience": r"(?:work|professional|employment|relevant|industry)?\s*experience|work history|employment(?:\s+history)?|career history|internships?",
    "projects": r"(?:academic\s+|personal\s+|key\s+|major\s+|selected\s+)?projects?",
    "certifications": r"(?:licenses?\s*(?:&|and)\s*)?certifications?|certificates?|courses|training|licenses?",
    "summary": r"(?:professional\s+|career\s+)?(?:summary|profile|objective)|about me",
    "other": r"awards?|achievements?|publications?|languages?|interests?|hobbies|references?|declaration|extra[- ]?curricular(?:\s+activities)?|volunteer(?:ing)?",
}
_SECTION_RES = {k: re.compile(rf"^(?:{v})$", re.I) for k, v in _SECTION_HEADS.items()}
_BULLET = "•●▪◦○‣∙·*-–—■□➢➤>"


def _heading_of(line: str) -> str | None:
    cleaned = line.strip().strip(_BULLET + ":|_=# \t").strip()
    if not cleaned or len(cleaned) > 40:
        return None
    for name, rx in _SECTION_RES.items():
        if rx.match(cleaned):
            return name
    return None


def split_sections(text: str) -> dict[str, str]:
    """Split resume text into named sections ('header' = text before first heading)."""
    sections: dict[str, list[str]] = {"header": []}
    current = "header"
    for line in text.split("\n"):
        head = _heading_of(line)
        if head:
            current = head
            sections.setdefault(current, [])
        else:
            sections[current].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items() if "\n".join(v).strip()}


# --------------------------------------------------------------------------
# Contact
# --------------------------------------------------------------------------
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<![\d/])(\+?\d[\d\s().\-]{8,17}\d)(?![\d/])")
_NOT_NAME = re.compile(r"resume|curriculum|vitae|\bcv\b|profile|summary|http|www\.|@|\d", re.I)


def extract_email(text: str) -> str | None:
    m = _EMAIL.search(text)
    return m.group(0).lower() if m else None


def extract_phone(text: str) -> str | None:
    for m in _PHONE.finditer(text[:3000]):
        digits = re.sub(r"\D", "", m.group(1))
        groups = re.findall(r"\d+", m.group(1))
        looks_like_years = all(len(g) == 4 and g[:2] in ("19", "20") for g in groups)
        if 10 <= len(digits) <= 13 and not looks_like_years:
            return re.sub(r"\s+", " ", m.group(1)).strip()
    return None


def extract_name(text: str) -> str | None:
    for line in [l.strip() for l in text.split("\n") if l.strip()][:8]:
        if _NOT_NAME.search(line) or _heading_of(line):
            continue
        words = line.split()
        if 2 <= len(words) <= 4 and all(re.fullmatch(r"[A-Za-z][A-Za-z.'\-]*", w) for w in words):
            return " ".join(w.capitalize() if w.isupper() else w for w in words)
    return None


# --------------------------------------------------------------------------
# Education
# --------------------------------------------------------------------------
EDU_LABELS = {0: "Not found", 1: "Diploma", 2: "Bachelor's", 3: "Master's", 4: "PhD"}
_EDU_PATTERNS = {
    4: r"\bph\.?\s?d\b|\bdoctorate\b|\bdoctoral\b",
    3: r"\bmaster(?:'s|s)?\b|\bm\.?\s?tech\b|\bm\.\s?e\.|\bm\.?\s?sc\b|\bm\.s\.|\bmba\b|\bmca\b|\bpost[- ]?graduate\b|\bm\.?\s?com\b",
    2: r"\bbachelor(?:'s|s)?\b|\bb\.?\s?tech\b|\bb\.\s?e\.|\bb\.?\s?sc\b|\bb\.s\.|\bbca\b|\bbba\b|\bb\.?\s?com\b|\bundergraduate\b",
    1: r"\bdiploma\b|\bassociate(?:'s)? degree\b|\bpolytechnic\b",
}
_EDU_RES = {lvl: re.compile(p, re.I) for lvl, p in _EDU_PATTERNS.items()}


def detect_education_level(text: str) -> int:
    for level in (4, 3, 2, 1):
        if _EDU_RES[level].search(text):
            return level
    return 0


def extract_education(text: str, sections: dict[str, str]) -> tuple[int, str]:
    source = sections.get("education") or text
    level = detect_education_level(source)
    if level == 0 and source is not text:
        level = detect_education_level(text)
        source = text
    detail = ""
    if level:
        for line in source.split("\n"):
            if _EDU_RES[level].search(line):
                detail = line.strip(" " + _BULLET)[:110]
                break
    return level, detail


# --------------------------------------------------------------------------
# Experience
# --------------------------------------------------------------------------
_MON = r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
_MONTH_NUM = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _date_part(suffix: str) -> str:
    return (
        rf"(?:(?:(?P<m{suffix}>{_MON})[a-z]*\.?,?\s+)|(?:(?P<n{suffix}>\d{{1,2}})[/.\-]))?"
        rf"(?P<y{suffix}>(?:19|20)\d{{2}})"
    )


_RANGE = re.compile(
    rf"(?<![\d])(?:{_date_part('1')})\s*(?:-|–|—|to|until|till)\s*"
    rf"(?:(?P<pres>present|current|currently|now|ongoing|till date|to date|today)|(?:{_date_part('2')}))(?![\d])",
    re.I,
)
_EXPLICIT = [
    re.compile(r"(\d{1,2}(?:\.\d)?)\s*\+?\s*(?:years?|yrs?)(?:\s+of)?\s+(?:[\w\-]+\s+){0,3}?experience", re.I),
    re.compile(r"experience\s*(?:of|:|-)?\s*(\d{1,2}(?:\.\d)?)\s*\+?\s*(?:years?|yrs?)", re.I),
]


def _month(m_name: str | None, m_num: str | None) -> int:
    if m_name:
        return _MONTH_NUM.get(m_name[:3].lower(), 1)
    if m_num and 1 <= int(m_num) <= 12:
        return int(m_num)
    return 1


def computed_experience_years(text: str, today: date | None = None) -> float:
    """Sum of non-overlapping date ranges (e.g. 'Jan 2020 - Present') in months / 12."""
    today = today or date.today()
    now_idx = today.year * 12 + today.month - 1
    spans: list[tuple[int, int]] = []
    for m in _RANGE.finditer(text):
        y1 = int(m.group("y1"))
        start = y1 * 12 + _month(m.group("m1"), m.group("n1")) - 1
        if m.group("pres"):
            end = now_idx
        else:
            y2 = int(m.group("y2"))
            end = y2 * 12 + _month(m.group("m2"), m.group("n2")) - 1
        end = min(end, now_idx)
        if start > now_idx or end < start or end - start > 12 * 50:
            continue
        spans.append((start, end))
    if not spans:
        return 0.0
    spans.sort()
    merged = [list(spans[0])]
    for s, e in spans[1:]:
        if s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    months = sum(e - s for s, e in merged)
    return round(months / 12, 1)


def explicit_experience_years(text: str) -> float:
    found = [float(m.group(1)) for rx in _EXPLICIT for m in rx.finditer(text)]
    found = [f for f in found if f <= 40]
    return max(found) if found else 0.0


def extract_experience_years(text: str, sections: dict[str, str], today: date | None = None) -> float:
    if sections.get("experience"):
        scope = sections["experience"]
    else:  # drop education so graduation dates are not counted as work
        scope = "\n".join(v for k, v in sections.items() if k not in ("education", "certifications"))
    computed = computed_experience_years(scope, today)
    return computed if computed > 0 else explicit_experience_years(text)


# --------------------------------------------------------------------------
# Certifications & projects
# --------------------------------------------------------------------------
_CERT_KEYWORDS = re.compile(
    r"\b(?:PMP|CISSP|CISA|CEH|CCNA|CCNP|ITIL|Six Sigma|Scrum Master|CompTIA\s+[A-Za-z+]+|"
    r"AWS Certified[A-Za-z\- ]{0,40}|Google Cloud (?:Certified|Professional)[A-Za-z\- ]{0,40}|"
    r"Microsoft Certified[A-Za-z:\- ]{0,40}|Oracle Certified[A-Za-z\- ]{0,40}|"
    r"TensorFlow Developer Certificate|AZ-\d{3}|DP-\d{3}|Databricks Certified[A-Za-z\- ]{0,30})",
)


def _items(block: str) -> list[str]:
    out = []
    for line in block.split("\n"):
        item = line.strip(" " + _BULLET + "\t").strip()
        if len(item) >= 4 and not re.fullmatch(r"[\d\s\-–/.,]+", item):
            out.append(item[:100])
    return out


def extract_certifications(text: str, sections: dict[str, str]) -> list[str]:
    certs = _items(sections.get("certifications", ""))
    low = " ".join(certs).lower()
    for m in _CERT_KEYWORDS.finditer(text):
        found = m.group(0).strip(" -:,")
        if found.lower() not in low:
            certs.append(found)
            low += " " + found.lower()
    seen, unique = set(), []
    for c in certs:
        if c.lower() not in seen:
            seen.add(c.lower())
            unique.append(c)
    return unique[:12]


def extract_projects(sections: dict[str, str]) -> list[str]:
    block = sections.get("projects", "")
    if not block:
        return []
    titles, bullets = [], []
    for line in block.split("\n"):
        raw = line.strip()
        if len(raw) < 3:
            continue
        if raw[0] in _BULLET:
            bullets.append(raw.strip(_BULLET + " ")[:80])
        elif len(raw) <= 100:
            titles.append(raw[:80])
    return (titles or bullets)[:10]


# --------------------------------------------------------------------------
# Profile
# --------------------------------------------------------------------------
@dataclass
class Profile:
    filename: str
    name: str
    email: str | None
    phone: str | None
    skills: list[str]
    education_level: int
    education_label: str
    education_detail: str
    experience_years: float
    certifications: list[str]
    projects: list[str]
    word_count: int
    # internal use (not serialised)
    text: str = field(default="", repr=False)
    context_text: str = field(default="", repr=False)

    def to_dict(self) -> dict:
        return {
            "filename": self.filename, "name": self.name, "email": self.email, "phone": self.phone,
            "skills": self.skills, "education_level": self.education_level,
            "education_label": self.education_label, "education_detail": self.education_detail,
            "experience_years": self.experience_years, "certifications": self.certifications,
            "projects": self.projects, "word_count": self.word_count,
        }


def build_profile(filename: str, text: str, today: date | None = None) -> Profile:
    sections = split_sections(text)
    level, detail = extract_education(text, sections)
    stem = filename.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").strip()
    # Evidence: where skills are *used* (experience/projects) rather than only listed.
    context = "\n".join(sections.get(k, "") for k in ("experience", "projects")).strip()
    return Profile(
        filename=filename,
        name=extract_name(text) or stem.title() or "Unknown",
        email=extract_email(text),
        phone=extract_phone(text),
        skills=find_skills(text),
        education_level=level,
        education_label=EDU_LABELS[level],
        education_detail=detail,
        experience_years=extract_experience_years(text, sections, today),
        certifications=extract_certifications(text, sections),
        projects=extract_projects(sections),
        word_count=len(text.split()),
        text=text,
        context_text=context,
    )
