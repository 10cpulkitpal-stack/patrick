import os
import re
import uuid
import time
import base64
import binascii
import hashlib
import hmac
import secrets
import smtplib
from email.message import EmailMessage
from functools import wraps
from urllib.parse import urlsplit

from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from authlib.integrations.flask_client import OAuth
from groq import Groq
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()

is_production = (
    os.environ.get("FLASK_ENV", "").lower() == "production"
    or os.environ.get("RENDER", "").lower() == "true"
)
secret_key = os.environ.get("SECRET_KEY")
if is_production and not secret_key:
    raise RuntimeError("Set a strong SECRET_KEY before running in production.")

app = Flask(__name__)
app.config.update(
    SECRET_KEY=secret_key or "dev-only-change-me",
    MAX_CONTENT_LENGTH=11 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=is_production,
)

# Render terminates HTTPS at its edge proxy. Trust only its forwarded scheme;
# for client IP rate limits use Cloudflare's edge-provided CF-Connecting-IP.
if is_production:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1)

oauth = OAuth(app)
google_client_id = os.environ.get("GOOGLE_CLIENT_ID")
google_client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
google_oauth_enabled = bool(google_client_id and google_client_secret)
if google_oauth_enabled:
    oauth.register(
        name="google",
        client_id=google_client_id,
        client_secret=google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
MODEL = "openai/gpt-oss-120b"
VISION_MODEL = "qwen/qwen3.6-27b"
DAILY_MESSAGE_LIMIT = max(1, int(os.environ.get("DAILY_MESSAGE_LIMIT", "100")))

SYSTEM_PROMPT = """You are Patrick, a helpful AI assistant.

Always format your answers as clean GitHub-Flavored Markdown so the web interface can render them properly.

Formatting rules:
- Start with a concise title or opening sentence when appropriate.
- Use ## or ### headings for distinct sections.
- Use numbered lists for procedures and step-by-step instructions.
- Use bullet lists for options, features, tips, or short collections.
- Use Markdown tables when comparing structured items such as ingredients, specifications, schedules, or prices.
- Use **bold** for important terms, not excessive capitalization.
- Keep paragraphs short and easy to scan.
- For recipes, prefer: title, quick details (servings/time when known), Ingredients table, Instructions, Optional Add-ins, and Tips.
- For technical answers, prefer: Overview, Steps, Example/Code, and Notes when useful.
- Do not output raw HTML.
- Do not wrap the entire response in a code block.
- Do not mention these formatting instructions to the user.
- Prioritize accuracy and usefulness over forcing every section into every answer.
"""

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///patrick.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://") and "+psycopg" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(
    DATABASE_URL,
    future=True,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)

# Enable SQLite foreign-key enforcement for local development.
from sqlalchemy import event
if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def init_db():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id VARCHAR(36) PRIMARY KEY,
                email VARCHAR(320) NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at DOUBLE PRECISION NOT NULL,
                display_name VARCHAR(120),
                auth_provider VARCHAR(20) NOT NULL DEFAULT 'password',
                email_verified BOOLEAN NOT NULL DEFAULT FALSE
            )
        """))
        # Add profile fields to existing databases without changing user data.
        user_columns = {row["name"] for row in conn.execute(text("PRAGMA table_info(users)")).mappings()} if DATABASE_URL.startswith("sqlite") else {
            row["column_name"] for row in conn.execute(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'users' AND table_schema = current_schema()
            """)).mappings()
        }
        if "display_name" not in user_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN display_name VARCHAR(120)"))
        if "auth_provider" not in user_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN auth_provider VARCHAR(20) NOT NULL DEFAULT 'password'"))
        if "email_verified" not in user_columns:
            # Existing accounts must prove address ownership before using the
            # password login again; Google OAuth can re-verify the same address.
            conn.execute(text("ALTER TABLE users ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT FALSE"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS email_verification_tokens (
                token_hash VARCHAR(64) PRIMARY KEY,
                user_id VARCHAR(36) NOT NULL,
                expires_at DOUBLE PRECISION NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS rate_limit_counters (
                bucket_key VARCHAR(64) PRIMARY KEY,
                window_id BIGINT NOT NULL,
                hit_count INTEGER NOT NULL,
                expires_at DOUBLE PRECISION NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS chats (
                id VARCHAR(36) PRIMARY KEY,
                user_id VARCHAR(36) NOT NULL,
                title VARCHAR(255) NOT NULL,
                created_at DOUBLE PRECISION NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS messages (
                id VARCHAR(36) PRIMARY KEY,
                chat_id VARCHAR(36) NOT NULL,
                role VARCHAR(20) NOT NULL,
                content TEXT NOT NULL,
                created_at DOUBLE PRECISION NOT NULL,
                FOREIGN KEY(chat_id) REFERENCES chats(id) ON DELETE CASCADE
            )
        """))


init_db()


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    with engine.connect() as conn:
        row = conn.execute(text("SELECT id, email, display_name, auth_provider, email_verified FROM users WHERE id = :id"), {"id": user_id}).mappings().first()
    if not row or not row["email_verified"]:
        session.clear()
        return None
    return dict(row)


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            session.clear()
            return jsonify({"error": "Authentication required"}), 401
        return fn(*args, **kwargs)
    return wrapper


def chat_owned(chat_id, user_id):
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id, title, created_at FROM chats WHERE id = :chat_id AND user_id = :user_id"),
            {"chat_id": chat_id, "user_id": user_id},
        ).mappings().first()
    return dict(row) if row else None


def make_title(first_message):
    title = first_message.strip().replace("\n", " ")
    return (title[:40] + "...") if len(title) > 40 else title


def get_chat_messages(chat_id):
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT role, content FROM messages WHERE chat_id = :chat_id ORDER BY created_at ASC, id ASC"),
            {"chat_id": chat_id},
        ).mappings().all()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


# ---------- request security ----------

last_rate_cleanup = 0.0


def client_ip():
    # Render's Cloudflare edge sets this header from the actual client address.
    # Do not trust a caller-supplied X-Forwarded-For chain.
    if is_production:
        edge_ip = request.headers.get("CF-Connecting-IP", "").strip()
        if edge_ip:
            return edge_ip[:128]
    return (request.remote_addr or "unknown")[:128]


def consume_rate_limit(action, identity, limit, window_seconds):
    """Atomically persist fixed-window counters shared by workers and restarts."""
    global last_rate_cleanup
    now = time.time()
    window_id = int(now // window_seconds)
    bucket_key = hmac.new(
        str(app.config["SECRET_KEY"]).encode(),
        f"{action}\0{identity}".encode(),
        hashlib.sha256,
    ).hexdigest()
    with engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO rate_limit_counters (bucket_key, window_id, hit_count, expires_at)
            VALUES (:bucket_key, :window_id, 1, :expires_at)
            ON CONFLICT (bucket_key) DO UPDATE SET
                hit_count = CASE WHEN window_id = :window_id THEN hit_count + 1 ELSE 1 END,
                window_id = :window_id,
                expires_at = :expires_at
            RETURNING hit_count
        """), {
            "bucket_key": bucket_key,
            "window_id": window_id,
            "expires_at": now + (window_seconds * 2),
        }).mappings().first()
        if now - last_rate_cleanup > 300:
            conn.execute(text("DELETE FROM rate_limit_counters WHERE expires_at < :now"), {"now": now})
            last_rate_cleanup = now
    if row["hit_count"] > limit:
        return False, max(1, int(((window_id + 1) * window_seconds) - now))
    return True, 0


def rate_limit_ip(action, limit, window_seconds):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            allowed, retry_after = consume_rate_limit(action, client_ip(), limit, window_seconds)
            if not allowed:
                response = jsonify({"error": "Too many requests. Please wait and try again."})
                response.status_code = 429
                response.headers["Retry-After"] = str(retry_after)
                return response
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def rate_limit_user(action, limit, window_seconds):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user:
                return jsonify({"error": "Authentication required"}), 401
            allowed, retry_after = consume_rate_limit(action, user["id"], limit, window_seconds)
            if not allowed:
                response = jsonify({"error": "Too many requests. Please wait and try again."})
                response.status_code = 429
                response.headers["Retry-After"] = str(retry_after)
                return response
            return fn(*args, **kwargs)
        return wrapper
    return decorator


@app.before_request
def protect_state_changing_requests():
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    origin = request.headers.get("Origin")
    if not origin and request.headers.get("Referer"):
        referer = urlsplit(request.headers["Referer"])
        origin = f"{referer.scheme}://{referer.netloc}"
    parsed_origin = urlsplit(origin or "")
    expected_scheme = "https" if is_production else request.scheme
    if (
        not parsed_origin.scheme
        or not parsed_origin.netloc
        or parsed_origin.scheme.lower() != expected_scheme.lower()
        or parsed_origin.netloc.lower() != request.host.lower()
    ):
        return jsonify({"error": "Request origin could not be verified."}), 403
    return None


@app.after_request
def add_security_headers(response):
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "script-src 'self' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
        "style-src 'self' https://fonts.googleapis.com https://cdnjs.cloudflare.com; style-src-attr 'none'; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data: blob:; connect-src 'self'; "
        "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'",
    )
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(self), geolocation=()")
    if is_production:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response


def mail_settings():
    try:
        port = int(os.environ.get("MAIL_PORT", "587"))
    except ValueError:
        return None
    settings = {
        "host": os.environ.get("MAIL_SERVER"),
        "port": port,
        "username": os.environ.get("MAIL_USERNAME"),
        "password": os.environ.get("MAIL_PASSWORD"),
        "sender": os.environ.get("MAIL_FROM"),
    }
    if not all(settings[key] for key in ("host", "username", "password", "sender")) or not 1 <= port <= 65535:
        return None
    return settings


def send_verification_email(email, token):
    settings = mail_settings()
    if not settings:
        return False
    base_url = os.environ.get("PUBLIC_BASE_URL", request.url_root.rstrip("/"))
    verification_url = f"{base_url.rstrip('/')}{url_for('verify_email')}?token={token}"
    message = EmailMessage()
    message["Subject"] = "Verify your Patrick account"
    message["From"] = settings["sender"]
    message["To"] = email
    message.set_content(
        "Verify your email address to finish creating your Patrick account.\n\n"
        f"{verification_url}\n\nThis link expires in 30 minutes."
    )
    try:
        if settings["port"] == 465:
            with smtplib.SMTP_SSL(settings["host"], settings["port"], timeout=10) as smtp:
                smtp.login(settings["username"], settings["password"])
                smtp.send_message(message)
        else:
            with smtplib.SMTP(settings["host"], settings["port"], timeout=10) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                smtp.login(settings["username"], settings["password"])
                smtp.send_message(message)
        return True
    except Exception:
        app.logger.exception("Failed to send a verification email")
        return False


def issue_verification_token(user_id, email):
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM email_verification_tokens WHERE user_id = :user_id"), {"user_id": user_id})
        conn.execute(text("""
            INSERT INTO email_verification_tokens (token_hash, user_id, expires_at)
            VALUES (:token_hash, :user_id, :expires_at)
        """), {"token_hash": token_hash, "user_id": user_id, "expires_at": time.time() + 1800})
    if not send_verification_email(email, token):
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM email_verification_tokens WHERE user_id = :user_id"), {"user_id": user_id})
        return False
    return True


# ---------- authentication ----------

@app.route("/api/me", methods=["GET"])
def me():
    user = current_user()
    if not user:
        return jsonify({"authenticated": False}), 401
    return jsonify({"authenticated": True, "user": user})


@app.route("/api/profile", methods=["PATCH"])
@login_required
@rate_limit_user("profile_update", 30, 3600)
def update_profile():
    user = current_user()
    data = request.get_json(silent=True) or {}
    display_name = (data.get("name") or "").strip()
    if not display_name or len(display_name) > 120:
        return jsonify({"error": "Name must be between 1 and 120 characters."}), 400
    with engine.begin() as conn:
        conn.execute(text("UPDATE users SET display_name = :name WHERE id = :id"), {"name": display_name, "id": user["id"]})
    return jsonify({"name": display_name, "email": user["email"]})


@app.route("/api/profile/password", methods=["POST"])
@login_required
@rate_limit_user("password_update", 5, 3600)
def update_password():
    user = current_user()
    data = request.get_json(silent=True) or {}
    current_password = data.get("current_password") or ""
    new_password = data.get("new_password") or ""
    google_verified_recently = time.time() - session.get("google_verified_at", 0) < 300
    if len(current_password) > 128 or len(new_password) > 128:
        return jsonify({"error": "Passwords must be 128 characters or fewer."}), 400
    if len(new_password) < 8:
        return jsonify({"error": "New password must be at least 8 characters."}), 400

    with engine.begin() as conn:
        row = conn.execute(text("SELECT password_hash, auth_provider FROM users WHERE id = :id"), {"id": user["id"]}).mappings().first()
        if row["auth_provider"] != "google" and not google_verified_recently and not check_password_hash(row["password_hash"], current_password):
            return jsonify({"error": "Current password is incorrect."}), 400
        provider = "both" if row["auth_provider"] == "google" else row["auth_provider"]
        conn.execute(text("UPDATE users SET password_hash = :password_hash, auth_provider = :provider WHERE id = :id"), {
            "password_hash": generate_password_hash(new_password), "provider": provider, "id": user["id"]
        })
    session.pop("google_verified_at", None)
    return jsonify({"status": "ok"})


@app.route("/api/auth/register", methods=["POST"])
@rate_limit_ip("register_ip", 5, 3600)
def register():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    display_name = (data.get("name") or "").strip()

    if "@" not in email or len(email) > 320:
        return jsonify({"error": "Enter a valid email address."}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters."}), 400
    if len(password) > 128:
        return jsonify({"error": "Password must be 128 characters or fewer."}), 400
    if not display_name or len(display_name) > 120:
        return jsonify({"error": "Name must be between 1 and 120 characters."}), 400
    if not mail_settings():
        return jsonify({"error": "Email verification is not configured. Please use Google sign-in or contact the site owner."}), 503

    user_id = str(uuid.uuid4())
    verification_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(verification_token.encode()).hexdigest()

    try:
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO users (id, email, password_hash, created_at, display_name, auth_provider, email_verified) VALUES (:id, :email, :password_hash, :created_at, :name, 'password', FALSE)"),
                {"id": user_id, "email": email, "password_hash": generate_password_hash(password), "created_at": time.time(), "name": display_name},
            )
            conn.execute(text("""
                INSERT INTO email_verification_tokens (token_hash, user_id, expires_at)
                VALUES (:token_hash, :user_id, :expires_at)
            """), {"token_hash": token_hash, "user_id": user_id, "expires_at": time.time() + 1800})
    except IntegrityError:
        return jsonify({"error": "An account with that email already exists."}), 409

    if not send_verification_email(email, verification_token):
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM users WHERE id = :id AND email_verified = FALSE"), {"id": user_id})
        return jsonify({"error": "We couldn't send the verification email. Please try again later."}), 503
    return jsonify({"verification_required": True, "message": "Check your email for a verification link. It expires in 30 minutes."}), 202


@app.route("/verify-email", methods=["GET", "POST"])
def verify_email():
    if request.method == "GET":
        token = request.args.get("token", "")
        token_hash = hashlib.sha256(token.encode()).hexdigest() if token else ""
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT token_hash FROM email_verification_tokens
                WHERE token_hash = :token_hash AND expires_at > :now
            """), {"token_hash": token_hash, "now": time.time()}).first()
        if not row:
            flash("That verification link is invalid or expired. Sign in with your password to request a fresh link.", "error")
            return redirect(url_for("signup"))
        return render_template("verify_email.html", token=token)

    token = request.form.get("token", "")
    token_hash = hashlib.sha256(token.encode()).hexdigest() if token else ""
    with engine.begin() as conn:
        row = conn.execute(text("""
            SELECT user_id FROM email_verification_tokens
            WHERE token_hash = :token_hash AND expires_at > :now
        """), {"token_hash": token_hash, "now": time.time()}).mappings().first()
        if not row:
            flash("That verification link is invalid or expired. Sign in with your password to request a fresh link.", "error")
            return redirect(url_for("signup"))
        conn.execute(text("UPDATE users SET email_verified = TRUE WHERE id = :id"), {"id": row["user_id"]})
        conn.execute(text("DELETE FROM email_verification_tokens WHERE user_id = :id"), {"id": row["user_id"]})
    flash("Email verified. You can now sign in.", "success")
    return redirect(url_for("signin"))


@app.route("/api/auth/login", methods=["POST"])
@rate_limit_ip("login_ip", 20, 900)
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if len(password) > 128:
        return jsonify({"error": "Incorrect email or password."}), 401
    allowed, retry_after = consume_rate_limit("login_account", email, 8, 900)
    if not allowed:
        response = jsonify({"error": "Too many sign-in attempts. Please wait and try again."})
        response.status_code = 429
        response.headers["Retry-After"] = str(retry_after)
        return response

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id, email, password_hash, email_verified FROM users WHERE email = :email"),
            {"email": email},
        ).mappings().first()

    if not row or not check_password_hash(row["password_hash"], password):
        return jsonify({"error": "Incorrect email or password."}), 401
    if not row["email_verified"]:
        if issue_verification_token(row["id"], row["email"]):
            return jsonify({"error": "This account needs email verification. We sent a fresh verification link."}), 403
        return jsonify({"error": "Email verification is not configured or could not be sent. Please contact the site owner."}), 503

    session.clear()
    session["user_id"] = row["id"]
    session.permanent = True
    return jsonify({"authenticated": True, "user": {"id": row["id"], "email": row["email"]}})


@app.route("/auth/google")
def google_login():
    if not google_oauth_enabled:
        flash("Google sign-in is not configured yet. You can sign in with email and password.", "error")
        return redirect(url_for("signin"))

    redirect_uri = os.environ.get("GOOGLE_REDIRECT_URI") or url_for("google_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@app.route("/auth/google/callback")
def google_callback():
    if not google_oauth_enabled:
        flash("Google sign-in is not configured yet. You can sign in with email and password.", "error")
        return redirect(url_for("signin"))

    try:
        oauth.google.authorize_access_token()
        profile = oauth.google.get("userinfo").json()
        email = (profile.get("email") or "").strip().lower()
        if not profile.get("sub") or not email or profile.get("email_verified") is not True:
            flash("Google did not provide a verified email address. Please try again.", "error")
            return redirect(url_for("signin"))

        with engine.begin() as conn:
            row = conn.execute(
                text("SELECT id, display_name, email_verified FROM users WHERE email = :email"), {"email": email}
            ).mappings().first()
            if row:
                user_id = row["id"]
                if not row["email_verified"]:
                    # A verified Google identity proves ownership of the address.
                    # Replace any password chosen by an unverified registrant.
                    conn.execute(text("""
                        UPDATE users
                        SET email_verified = TRUE, auth_provider = 'google',
                            password_hash = :password_hash,
                            display_name = COALESCE(NULLIF(display_name, ''), :name)
                        WHERE id = :id
                    """), {
                        "password_hash": generate_password_hash(secrets.token_urlsafe(48)),
                        "name": (profile.get("name") or "")[:120],
                        "id": user_id,
                    })
                    conn.execute(text("DELETE FROM email_verification_tokens WHERE user_id = :id"), {"id": user_id})
                else:
                    conn.execute(text("UPDATE users SET auth_provider = 'both', display_name = COALESCE(NULLIF(display_name, ''), :name) WHERE id = :id"), {
                        "name": (profile.get("name") or "")[:120], "id": user_id
                    })
            else:
                user_id = str(uuid.uuid4())
                conn.execute(
                    text("""
                        INSERT INTO users (id, email, password_hash, created_at, display_name, auth_provider, email_verified)
                        VALUES (:id, :email, :password_hash, :created_at, :name, 'google', TRUE)
                    """),
                    {
                        "id": user_id,
                        "email": email,
                        "password_hash": generate_password_hash(uuid.uuid4().hex),
                        "created_at": time.time(),
                        "name": (profile.get("name") or "")[:120],
                    },
                )

        session.clear()
        session["user_id"] = user_id
        session["google_verified_at"] = time.time()
        session.permanent = True
        return redirect(url_for("index"))
    except Exception:
        app.logger.exception("Google sign-in failed")
        flash("Google sign-in failed. Please try again or use email and password.", "error")
        return redirect(url_for("signin"))


@app.route("/api/auth/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"status": "ok"})


# ---------- page ----------

@app.route("/")
def index():
    # Keep authentication completely separate from the chat page.
    user = current_user()
    if not user:
        return redirect(url_for("signin"))
    can_set_password = user["auth_provider"] == "google" or time.time() - session.get("google_verified_at", 0) < 300
    return render_template("index.html", user=user, can_set_password=can_set_password)


@app.route("/signin")
def signin():
    if current_user():
        return redirect(url_for("index"))
    return render_template("signin.html")


@app.route("/signup")
def signup():
    if current_user():
        return redirect(url_for("index"))
    return render_template("signup.html")


# ---------- chat endpoints (every query is scoped to the logged-in user) ----------

@app.route("/api/chats", methods=["GET"])
@login_required
def list_chats():
    user = current_user()
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, title FROM chats WHERE user_id = :user_id ORDER BY created_at DESC"),
            {"user_id": user["id"]},
        ).mappings().all()
    return jsonify([{"id": r["id"], "title": r["title"]} for r in rows])


@app.route("/api/chats", methods=["POST"])
@login_required
def create_chat():
    user = current_user()
    chat_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO chats (id, user_id, title, created_at) VALUES (:id, :user_id, :title, :created_at)"),
            {"id": chat_id, "user_id": user["id"], "title": "New Chat", "created_at": time.time()},
        )
    return jsonify({"id": chat_id, "title": "New Chat"})


@app.route("/api/chats/<chat_id>", methods=["GET"])
@login_required
def get_chat(chat_id):
    user = current_user()
    chat = chat_owned(chat_id, user["id"])
    if not chat:
        # Do not reveal whether another user's chat ID exists.
        return jsonify({"error": "Chat not found"}), 404
    return jsonify({"id": chat_id, "title": chat["title"], "messages": get_chat_messages(chat_id)})


@app.route("/api/chats/<chat_id>", methods=["DELETE"])
@login_required
def delete_chat(chat_id):
    user = current_user()
    with engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM chats WHERE id = :chat_id AND user_id = :user_id"),
            {"chat_id": chat_id, "user_id": user["id"]},
        )
    if result.rowcount == 0:
        return jsonify({"error": "Chat not found"}), 404
    return jsonify({"status": "ok"})


@app.route("/api/chats/<chat_id>", methods=["PATCH"])
@login_required
def rename_chat(chat_id):
    data = request.get_json(silent=True) or {}
    new_title = (data.get("title") or "").strip()
    if not new_title:
        return jsonify({"error": "Title cannot be empty"}), 400

    user = current_user()
    with engine.begin() as conn:
        result = conn.execute(
            text("UPDATE chats SET title = :title WHERE id = :chat_id AND user_id = :user_id"),
            {"title": new_title, "chat_id": chat_id, "user_id": user["id"]},
        )
    if result.rowcount == 0:
        return jsonify({"error": "Chat not found"}), 404
    return jsonify({"id": chat_id, "title": new_title})


# ---------- messaging ----------

@app.route("/api/chats/<chat_id>/message", methods=["POST"])
@login_required
@rate_limit_ip("message_ip", 60, 3600)
def send_message(chat_id):
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid request body."}), 400
    raw_message = data.get("message", "")
    if not isinstance(raw_message, str):
        return jsonify({"error": "Message must be text."}), 400
    user_message = raw_message.strip()
    image_data_url = data.get("image")
    image_name = data.get("image_name")

    if not user_message and not image_data_url:
        return jsonify({"error": "Message cannot be empty"}), 400
    if len(user_message) > 12000:
        return jsonify({"error": "Messages must be 12,000 characters or fewer."}), 400

    if image_data_url:
        if not isinstance(image_data_url, str) or len(image_data_url) > 11 * 1024 * 1024:
            return jsonify({"error": "Image is too large. Maximum image size is 8 MB."}), 413
        image_match = re.fullmatch(
            r"data:image/(?:jpeg|png|webp|gif);base64,([A-Za-z0-9+/]+={0,2})",
            image_data_url,
        )
        if not image_match:
            return jsonify({"error": "Please attach a valid PNG, JPEG, WebP, or GIF image."}), 400
        try:
            image_bytes = base64.b64decode(image_match.group(1), validate=True)
        except (binascii.Error, ValueError):
            return jsonify({"error": "The attached image could not be read."}), 400
        if not image_bytes or len(image_bytes) > 8 * 1024 * 1024:
            return jsonify({"error": "Image is too large. Maximum image size is 8 MB."}), 413
        image_name = os.path.basename(str(image_name or "image"))[:255]

    user = current_user()
    chat = chat_owned(chat_id, user["id"])
    if not chat:
        return jsonify({"error": "Chat not found"}), 404

    allowed, retry_after = consume_rate_limit("message_user", user["id"], 20, 3600)
    if not allowed:
        response = jsonify({"error": "You have reached the hourly message limit. Please wait and try again."})
        response.status_code = 429
        response.headers["Retry-After"] = str(retry_after)
        return response
    day_start = int(time.time() // 86400) * 86400
    with engine.connect() as conn:
        today_count = conn.execute(text("""
            SELECT COUNT(*) FROM messages m
            JOIN chats c ON c.id = m.chat_id
            WHERE c.user_id = :user_id AND m.role = 'user' AND m.created_at >= :day_start
        """), {"user_id": user["id"], "day_start": day_start}).scalar_one()
    if today_count >= DAILY_MESSAGE_LIMIT:
        return jsonify({"error": f"Daily message limit reached ({DAILY_MESSAGE_LIMIT}). Please try again tomorrow."}), 429

    existing_messages = get_chat_messages(chat_id)
    stored_user_text = user_message
    if image_data_url:
        label = f"[Image attached: {image_name}]" if image_name else "[Image attached]"
        stored_user_text = f"{label} {user_message}".strip()

    try:
        if image_data_url:
            vision_messages = existing_messages + [{
                "role": "user",
                "content": [
                    {"type": "text", "text": user_message or "Describe this image."},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ],
            }]
            response = client.chat.completions.create(
                model=VISION_MODEL,
                max_tokens=1024,
                messages=[{"role": "system", "content": SYSTEM_PROMPT}] + vision_messages,
            )
        else:
            response = client.chat.completions.create(
                model=MODEL,
                max_tokens=1024,
                messages=[{"role": "system", "content": SYSTEM_PROMPT}] + existing_messages + [{"role": "user", "content": user_message}],
            )

        reply = response.choices[0].message.content
        now = time.time()
        new_title = make_title(stored_user_text) if chat["title"] == "New Chat" else chat["title"]

        with engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO messages (id, chat_id, role, content, created_at)
                        VALUES (:id, :chat_id, 'user', :content, :created_at)
                    """),
                    {
                        "id": str(uuid.uuid4()),
                        "chat_id": chat_id,
                        "content": stored_user_text,
                        "created_at": now,
                    },
                )

                conn.execute(
                    text("""
                        INSERT INTO messages (id, chat_id, role, content, created_at)
                        VALUES (:id, :chat_id, 'assistant', :content, :created_at)
                    """),
                    {
                        "id": str(uuid.uuid4()),
                        "chat_id": chat_id,
                        "content": reply,
                        "created_at": time.time(),
                    },
                )
                if new_title != chat["title"]:
                    conn.execute(
                        text("UPDATE chats SET title = :title WHERE id = :chat_id AND user_id = :user_id"),
                        {"title": new_title, "chat_id": chat_id, "user_id": user["id"]},
                    )

        return jsonify({"reply": reply, "title": new_title})

    except Exception:
        app.logger.exception("Message generation failed for chat %s", chat_id)
        return jsonify({"error": "Patrick couldn't generate a reply right now. Please try again."}), 502


if __name__ == "__main__":
    if not os.environ.get("GROQ_API_KEY"):
        print("\n⚠️  GROQ_API_KEY is not set.")
        print('   Create a .env file with GROQ_API_KEY="your-key-here"\n')

    if app.config["SECRET_KEY"] == "dev-only-change-me":
        print("⚠️  SECRET_KEY is using the development fallback. Set a strong SECRET_KEY in .env/Render.")

    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true" and not is_production
    app.run(debug=debug_mode, host="127.0.0.1", port=port)
