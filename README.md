# Smart Resume Screening and Candidate Ranking Tool

An NLP-powered web app that reads resumes (PDF, DOCX, TXT), extracts skills, education, experience, certifications and projects, compares each candidate with a job description, and ranks them with a clear, explainable score.

## Quick start

```bash
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000, click **Load sample**, upload the files in `sample_data/` and press **Screen & rank candidates**.

Production: `gunicorn app:app` (Linux/Mac) or `waitress-serve app:app` (Windows).
Settings via environment variables: `HOST`, `PORT`, `FLASK_DEBUG=1` (development only).

## How it works

1. **Parse** (`screening/parser.py`) - reads PDF/DOCX/TXT safely (type + magic-byte checks, page and size limits, encrypted/corrupt files reported instead of crashing).
2. **Extract** (`screening/extractor.py`) - detects resume sections, then pulls out name, email, phone, ~120 skills (with aliases such as `sklearn`, `k8s`), highest education level, years of experience, certifications and projects.
   - Experience is computed from real date ranges (`Jan 2020 - Present`), merging overlaps and ignoring education dates; it falls back to "5+ years of experience" statements.
3. **Understand the job** (`screening/ranker.py`) - finds required vs "nice to have" skills, minimum years and minimum degree. You can add extra required skills in the form.
4. **Score** - 0-100 per candidate:

| Component | Weight | What it measures |
|---|---|---|
| Skills match | 45% | Required skills (85%) and preferred skills (15%) found |
| Text similarity | 25% | TF-IDF cosine similarity between resume and job description |
| Experience | 15% | Years vs the requirement |
| Education | 10% | Degree level vs the requirement |
| Certifications & projects | 5% | Evidence of extra learning and hands-on work |

   Skills that appear **only in a skills list** (not in experience/projects) get 75% credit, so keyword-stuffed resumes rank below candidates who show the skill in use.
5. **Explain** - every candidate shows matched/missing skills, a score breakdown and review notes (missing skills, low experience, duplicate email, unreadable PDF...).

Verdicts: 75+ Strong, 60+ Good, 40+ Partial, below 40 Weak. Weights and thresholds are constants at the top of `screening/ranker.py`.

## API

```bash
curl -F "jd_text=<job description text>" -F "resumes=@cv1.pdf" -F "resumes=@cv2.docx" http://127.0.0.1:5000/api/screen
```

Returns JSON with `requirements`, ranked `results` and per-file `errors`.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

35 tests cover skill matching, extraction, scoring, PDF/DOCX parsing, validation, XSS escaping and upload limits.

## Security and privacy

- Resumes are processed in memory and never written to disk or a database.
- Strict Content-Security-Policy, safe filename handling, upload size/count limits, autoescaped templates, CSV-export formula-injection protection.
- Debug mode is off by default.

## Limitations

- Scanned (image-only) PDFs have no text layer and are flagged rather than scored (add OCR such as Tesseract to support them).
- Skill detection uses the built-in taxonomy in `screening/skills.py`; add new skills and aliases there.
- Scores support human decisions - they should not replace them. Review the explanations, especially for borderline candidates.

## Project structure

```
app.py                  Flask app (routes, validation, security headers)
screening/              parser, extractor, ranker, skill taxonomy
templates/, static/     UI
sample_data/            job description + sample resumes
tests/                  pytest suite
```
