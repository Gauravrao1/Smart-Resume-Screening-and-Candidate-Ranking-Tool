import io
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from screening import screen  # noqa: E402
from screening.extractor import (  # noqa: E402
    computed_experience_years, detect_education_level, extract_email, extract_name, extract_phone,
    build_profile, split_sections,
)
from screening.parser import ParseError, extract_text  # noqa: E402
from screening.ranker import parse_job_description  # noqa: E402
from screening.skills import find_skills  # noqa: E402

TODAY = date(2026, 10, 25)
SAMPLES = ROOT / "sample_data"
JD = (SAMPLES / "job_description.txt").read_text()


# ---------------- skills ----------------
def test_java_does_not_match_javascript():
    assert "Java" not in find_skills("Expert in JavaScript and React")
    assert "JavaScript" in find_skills("Expert in JavaScript and React")


def test_special_character_skills():
    found = find_skills("Worked with C++, C#, .NET and Node.js daily.")
    assert {"C++", "C#", ".NET", "Node.js"} <= set(found)


def test_aliases_and_case():
    assert {"scikit-learn", "Kubernetes", "AWS"} <= set(find_skills("SKLEARN, k8s and Amazon Web Services"))


def test_no_false_positive_inside_words():
    assert "Git" not in find_skills("I am digital and legitimate")
    assert "R" not in find_skills("Our team is great")


# ---------------- extraction ----------------
def test_contact_extraction():
    text = "Jane Doe\njane.doe@Example.com\n+1 (415) 555-2671\n"
    assert extract_email(text) == "jane.doe@example.com"
    assert "415" in extract_phone(text)
    assert extract_name(text) == "Jane Doe"


def test_phone_ignores_year_ranges():
    assert extract_phone("Worked 2015 - 2019 2020") is None


@pytest.mark.parametrize("text,level", [
    ("PhD in Physics", 4), ("M.Tech in CSE", 3), ("MBA, 2019", 3), ("B.Tech Computer Science", 2),
    ("Bachelor of Science", 2), ("Diploma in IT", 1), ("High school", 0),
])
def test_education_levels(text, level):
    assert detect_education_level(text) == level


def test_experience_merges_overlaps_and_handles_present():
    text = "Jan 2020 - Dec 2021\nJun 2021 - Present\n"
    years = computed_experience_years(text, TODAY)
    assert 6.5 <= years <= 7.0  # Jan 2020 .. Oct 2026, overlap counted once


def test_experience_ignores_future_and_invalid_ranges():
    assert computed_experience_years("2030 - 2035", TODAY) == 0.0
    assert computed_experience_years("2021 - 2019", TODAY) == 0.0


def test_education_dates_not_counted_as_work():
    text = "EDUCATION\nB.Tech 2012 - 2016\n\nSKILLS\nPython"
    p = build_profile("a.txt", text, TODAY)
    assert p.experience_years == 0.0


def test_explicit_years_fallback():
    p = build_profile("a.txt", "Senior engineer with 8+ years of experience in Python.", TODAY)
    assert p.experience_years == 8.0


def test_sections_split():
    s = split_sections("Name\n\nSKILLS\nPython\n\nEducation:\nB.Tech")
    assert s["skills"] == "Python" and s["education"] == "B.Tech"


# ---------------- job description ----------------
def test_jd_required_vs_preferred_and_requirements():
    req = parse_job_description(JD)
    assert "Python" in req.required and "Docker" in req.required
    assert "Kubernetes" in req.preferred and "Kubernetes" not in req.required
    assert req.min_years == 3.0
    assert req.min_education == 2


def test_preferred_degree_is_not_a_minimum():
    req = parse_job_description("Requirements\n- Python\n\nNice to have\n- Master's degree\n")
    assert req.min_education == 0


def test_extra_required_skills_are_canonicalised():
    req = parse_job_description("We need a developer.", ["docker", "Rust", "my-custom-tool"])
    assert req.required == ["Docker", "Rust", "my-custom-tool"]


# ---------------- end-to-end ranking ----------------
def _sample_files():
    return [(p.name, p.read_bytes()) for p in sorted(SAMPLES.glob("*.txt")) if not p.name.startswith("job")]


def test_ranking_order_and_scores():
    out = screen(JD, _sample_files(), today=TODAY)
    names = [r["name"] for r in out["results"]]
    assert names == ["Priya Sharma", "Anita Desai", "Rahul Verma"]
    scores = [r["score"] for r in out["results"]]
    assert scores == sorted(scores, reverse=True)
    assert all(0 <= s <= 100 for s in scores)
    assert out["results"][0]["label"] == "Strong match"
    assert [r["rank"] for r in out["results"]] == [1, 2, 3]


def test_listed_only_skills_get_less_credit():
    jd = "Requirements\n- Python\n- Docker\n"
    used = "Dev One\nEXPERIENCE\nBuilt services in Python and Docker.\nSKILLS\nPython, Docker\n" * 1
    listed = "Dev Two\nEXPERIENCE\nWorked on spreadsheets and reports at a bank.\nSKILLS\nPython, Docker\n"
    out = screen(jd, [("one.txt", used.encode()), ("two.txt", listed.encode())], today=TODAY)
    by = {r["filename"]: r for r in out["results"]}
    assert by["one.txt"]["breakdown"]["skills"] == 100.0
    assert by["two.txt"]["breakdown"]["skills"] == 75.0
    assert sorted(by["two.txt"]["listed_only"]) == ["Docker", "Python"]


def test_duplicate_email_flagged():
    a = "Sam Lee\nsam@example.com\nSKILLS\nPython"
    out = screen("Python developer needed for our team.", [("a.txt", a.encode()), ("b.txt", a.encode())], today=TODAY)
    assert any("duplicate" in f.lower() for r in out["results"] for f in r["flags"])


def test_bad_files_do_not_abort_the_run():
    files = [("good.txt", b"Ann Lee\nann@example.com\nSKILLS\nPython"), ("bad.pdf", b"not a pdf"),
             ("empty.txt", b""), ("evil.exe", b"MZ")]
    out = screen("Python developer needed for our team.", files, today=TODAY)
    assert len(out["results"]) == 1
    assert {e["filename"] for e in out["errors"]} == {"bad.pdf", "empty.txt", "evil.exe"}


def test_jd_without_known_skills_falls_back_to_similarity():
    out = screen("We need a friendly baker who loves bread and pastries every morning.",
                 [("a.txt", b"Bo Chan\nbo@example.com\nI love baking bread and pastries every morning.")], today=TODAY)
    r = out["results"][0]
    assert r["breakdown"]["skills"] == r["breakdown"]["similarity"]
    assert any("no recognised skills" in f for f in r["flags"])


# ---------------- parser ----------------
def _make_pdf(text: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for line in text.split("\n"):
        c.drawString(50, y, line)
        y -= 16
    c.save()
    return buf.getvalue()


def _make_docx(text: str) -> bytes:
    from docx import Document
    d = Document()
    for line in text.split("\n"):
        d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_pdf_and_docx_parsing_match_text():
    sample = (SAMPLES / "priya_sharma.txt").read_text()
    pdf_text = extract_text("r.pdf", _make_pdf(sample))
    docx_text = extract_text("r.docx", _make_docx(sample))
    for text in (pdf_text, docx_text):
        assert "priya.sharma@example.com" in text
        assert "Python" in find_skills(text)


def test_parser_rejects_bad_input():
    with pytest.raises(ParseError):
        extract_text("x.pdf", b"hello")
    with pytest.raises(ParseError):
        extract_text("x.docx", b"hello")
    with pytest.raises(ParseError):
        extract_text("x.exe", b"hello")
    with pytest.raises(ParseError):
        extract_text("x.txt", b"")


# ---------------- web app ----------------
@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _post(client, path, jd=JD, files=None, extra=""):
    data = {"jd_text": jd, "extra_skills": extra}
    data["resumes"] = [(io.BytesIO(b), n) for n, b in (files if files is not None else _sample_files())]
    return client.post(path, data=data, content_type="multipart/form-data")


def test_home_and_health(client):
    assert client.get("/").status_code == 200
    assert client.get("/health").get_json() == {"status": "ok"}


def test_security_headers(client):
    h = client.get("/").headers
    assert h["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'self'" in h["Content-Security-Policy"]


def test_screen_page_renders_ranked_results(client):
    r = _post(client, "/screen")
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert html.index("Priya Sharma") < html.index("Anita Desai") < html.index("Rahul Verma")


def test_api_returns_json(client):
    r = _post(client, "/api/screen")
    assert r.status_code == 200
    assert r.get_json()["results"][0]["name"] == "Priya Sharma"


def test_validation_errors(client):
    assert _post(client, "/screen", jd="short").status_code == 400
    assert _post(client, "/screen", files=[]).status_code == 400
    r = _post(client, "/api/screen", files=[("r%d.txt" % i, b"x") for i in range(31)])
    assert r.status_code == 400 and "Too many" in r.get_json()["error"]


def test_xss_is_escaped(client):
    evil = b"<script>alert(1)</script> Mal Lory\nmal@example.com\nSKILLS\nPython"
    r = _post(client, "/screen", files=[("<img src=x onerror=alert(1)>.txt", evil)])
    html = r.get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html
    assert "<img src=x" not in html


def test_upload_too_large(client):
    client.application.config["MAX_CONTENT_LENGTH"] = 1024
    r = _post(client, "/api/screen", files=[("big.txt", b"a" * 5000)])
    assert r.status_code == 413
