"""Flask web app for the Smart Resume Screening and Candidate Ranking Tool.

Vercel-compatible: runs as a Python serverless function.
Vercel body limit is ~4.5 MB per request, so MAX_UPLOAD_MB is capped at 4.
For larger uploads, self-host with gunicorn / waitress.
"""
from __future__ import annotations

import os

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

from screening import ALLOWED_EXTENSIONS, screen

# Vercel serverless body limit ≈ 4.5 MB; stay safely under it.
# Change to 16 if self-hosting with gunicorn / waitress.
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "4"))
MAX_FILES = int(os.environ.get("MAX_FILES", "10"))
MIN_JD_CHARS = 30
MAX_JD_CHARS = 20_000


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
    app.config["MAX_FORM_MEMORY_SIZE"] = 2 * 1024 * 1024

    @app.after_request
    def security_headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "form-action 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'none'"
        )
        resp.headers["Cache-Control"] = "no-store"
        return resp

    def read_request():
        """Validate input; return (jd, extra, files, error)."""
        jd = (request.form.get("jd_text") or "").strip()
        extra = (request.form.get("extra_skills") or "").strip()[:500]
        if len(jd) < MIN_JD_CHARS:
            return jd, extra, [], "Please paste a job description (at least a couple of sentences)."
        if len(jd) > MAX_JD_CHARS:
            return jd, extra, [], f"Job description is too long (max {MAX_JD_CHARS:,} characters)."
        uploads = [f for f in request.files.getlist("resumes") if f and f.filename]
        if not uploads:
            return jd, extra, [], "Please upload at least one resume (PDF, DOCX or TXT)."
        if len(uploads) > MAX_FILES:
            return jd, extra, [], f"Too many files - upload at most {MAX_FILES} resumes at a time."
        files = [(secure_filename(f.filename) or "resume", f.read()) for f in uploads]
        # keep filenames unique so results are not confused
        seen: dict[str, int] = {}
        unique = []
        for name, data in files:
            seen[name] = seen.get(name, 0) + 1
            unique.append((name if seen[name] == 1 else f"{seen[name]}_{name}", data))
        return jd, extra, unique, None

    @app.get("/")
    def index():
        return render_template("index.html", error=None, jd_text="", extra="",
                               exts=sorted(ALLOWED_EXTENSIONS),
                               max_files=MAX_FILES, max_mb=MAX_UPLOAD_MB)

    @app.post("/screen")
    def screen_page():
        jd, extra, files, error = read_request()
        if error:
            return render_template("index.html", error=error, jd_text=jd, extra=extra,
                                   exts=sorted(ALLOWED_EXTENSIONS),
                                   max_files=MAX_FILES, max_mb=MAX_UPLOAD_MB), 400
        data = screen(jd, files, extra)
        return render_template("results.html", **data)

    @app.post("/api/screen")
    def screen_api():
        jd, extra, files, error = read_request()
        if error:
            return jsonify({"error": error}), 400
        return jsonify(screen(jd, files, extra))

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_e):
        msg = f"Upload too large. Total size must be under {MAX_UPLOAD_MB} MB."
        if request.path.startswith("/api/"):
            return jsonify({"error": msg}), 413
        return render_template("index.html", error=msg, jd_text="", extra="",
                               exts=sorted(ALLOWED_EXTENSIONS),
                               max_files=MAX_FILES, max_mb=MAX_UPLOAD_MB), 413

    return app


app = create_app()

if __name__ == "__main__":
    # debug is OFF by default (the Werkzeug debugger allows remote code execution).
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", 5000)),
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
