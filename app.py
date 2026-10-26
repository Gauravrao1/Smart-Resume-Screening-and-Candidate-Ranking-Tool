"""Flask web app for the Smart Resume Screening and Candidate Ranking Tool.

Vercel-compatible: runs as a Python serverless function.
Vercel body limit is ~4.5 MB per request, so MAX_UPLOAD_MB is capped at 4.
For larger uploads, self-host with gunicorn / waitress.
"""
from __future__ import annotations

import os
import re
import secrets
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone

from flask import Flask, g, jsonify, redirect, render_template, request, url_for
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from screening import ALLOWED_EXTENSIONS, screen

# Vercel serverless body limit ≈ 4.5 MB; stay safely under it.
# Change to 16 if self-hosting with gunicorn / waitress.
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "4"))
MAX_FILES = int(os.environ.get("MAX_FILES", "10"))
MIN_JD_CHARS = 30
MAX_JD_CHARS = 20_000
SESSION_DAYS = 30
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^\+?[0-9\s().-]{7,20}$")


def create_app(database_path: str | None = None) -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "local-development-key")
    default_database = os.path.join(os.path.dirname(__file__), "smartscreen.sqlite3")
    if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        # Vercel/Lambda only permits writes in the temporary directory.
        default_database = os.path.join(tempfile.gettempdir(), "smartscreen.sqlite3")
    app.config["DATABASE"] = database_path or os.environ.get("DATABASE_PATH", default_database)
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

    def database():
        if "database" not in g:
            g.database = sqlite3.connect(app.config["DATABASE"])
            g.database.row_factory = sqlite3.Row
        return g.database

    def init_database():
        with sqlite3.connect(app.config["DATABASE"]) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    phone TEXT NOT NULL,
                    company_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS login_sessions (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires_at TEXT NOT NULL
                );
                """
            )

    @app.teardown_appcontext
    def close_database(_error=None):
        db = g.pop("database", None)
        if db is not None:
            db.close()

    @app.before_request
    def load_user():
        g.user = None
        token = request.cookies.get("auth_token")
        if not token:
            return
        now = datetime.now(timezone.utc)
        row = database().execute(
            """
            SELECT users.* FROM login_sessions
            JOIN users ON users.id = login_sessions.user_id
            WHERE login_sessions.token = ? AND login_sessions.expires_at > ?
            """,
            (token, now.isoformat()),
        ).fetchone()
        if row:
            g.user = row
        else:
            database().execute("DELETE FROM login_sessions WHERE token = ?", (token,))
            database().commit()

    def auth_response(template, **context):
        return render_template(template, user=getattr(g, "user", None), **context)

    def set_auth_cookie(response, token):
        response.set_cookie(
            "auth_token",
            token,
            max_age=SESSION_DAYS * 24 * 60 * 60,
            httponly=True,
            secure=request.is_secure,
            samesite="Lax",
        )
        return response

    def require_login():
        if g.user is None:
            return redirect(url_for("login", next=request.path))
        return None

    init_database()

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
        auth_redirect = require_login()
        if auth_redirect:
            return auth_redirect
        return auth_response("index.html", error=None, jd_text="", extra="",
                               exts=sorted(ALLOWED_EXTENSIONS),
                               max_files=MAX_FILES, max_mb=MAX_UPLOAD_MB)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if g.user:
            return redirect(url_for("index"))
        error = None
        identifier = ""
        if request.method == "POST":
            identifier = (request.form.get("identifier") or "").strip()
            password = request.form.get("password") or ""
            row = database().execute(
                "SELECT * FROM users WHERE email = ? COLLATE NOCASE OR phone = ?",
                (identifier, identifier),
            ).fetchone()
            if not row or not check_password_hash(row["password_hash"], password):
                error = "The email, phone number, or password is not correct."
            else:
                token = secrets.token_urlsafe(32)
                expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
                database().execute(
                    "INSERT INTO login_sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
                    (token, row["id"], expires.isoformat()),
                )
                database().commit()
                next_url = request.args.get("next") or ""
                if not next_url.startswith("/") or next_url.startswith("//"):
                    next_url = url_for("index")
                response = redirect(next_url)
                return set_auth_cookie(response, token)
        return auth_response("auth.html", mode="login", error=error, identifier=identifier)

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if g.user:
            return redirect(url_for("index"))
        error = None
        values = {key: "" for key in ("name", "email", "phone", "company_name")}
        if request.method == "POST":
            values = {key: (request.form.get(key) or "").strip() for key in values}
            password = request.form.get("password") or ""
            if not all(values.values()) or not password:
                error = "Please complete all fields."
            elif not EMAIL_RE.fullmatch(values["email"]):
                error = "Enter a valid email address."
            elif not PHONE_RE.fullmatch(values["phone"]):
                error = "Enter a valid phone number."
            elif len(password) < 8:
                error = "Password must be at least 8 characters."
            else:
                try:
                    database().execute(
                        """
                        INSERT INTO users (name, email, phone, company_name, password_hash, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (*values.values(), generate_password_hash(password),
                         datetime.now(timezone.utc).isoformat()),
                    )
                    database().commit()
                except sqlite3.IntegrityError:
                    error = "An account with that email already exists."
                else:
                    return redirect(url_for("login", registered="1"))
        return auth_response("auth.html", mode="register", error=error, **values)

    @app.post("/logout")
    def logout():
        token = request.cookies.get("auth_token")
        if token:
            database().execute("DELETE FROM login_sessions WHERE token = ?", (token,))
            database().commit()
        response = redirect(url_for("login"))
        response.delete_cookie("auth_token")
        return response

    @app.post("/screen")
    def screen_page():
        auth_redirect = require_login()
        if auth_redirect:
            return auth_redirect
        jd, extra, files, error = read_request()
        if error:
            return auth_response("index.html", error=error, jd_text=jd, extra=extra,
                                   exts=sorted(ALLOWED_EXTENSIONS),
                                   max_files=MAX_FILES, max_mb=MAX_UPLOAD_MB), 400
        data = screen(jd, files, extra)
        return auth_response("results.html", **data)

    @app.post("/api/screen")
    def screen_api():
        if g.user is None:
            return jsonify({"error": "Authentication required."}), 401
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
        return auth_response("index.html", error=msg, jd_text="", extra="",
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
