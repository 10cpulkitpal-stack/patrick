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
from google import genai
from google.genai import types as genai_types
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
gemini_api_key = os.environ.get("GEMINI_API_KEY", "").strip()
gemini_client = genai.Client(api_key=gemini_api_key) if gemini_api_key else None
MODEL = os.environ.get("GROQ_TEXT_MODEL", "openai/gpt-oss-120b").strip()
TEXT_FALLBACK_MODEL = os.environ.get("GROQ_TEXT_FALLBACK_MODEL", "openai/gpt-oss-20b").strip()
VISION_MODEL = os.environ.get("GROQ_VISION_MODEL", "qwen/qwen3.8-27b").strip()
VISION_FALLBACK_MODEL = os.environ.get("GROQ_VISION_FALLBACK_MODEL", "").strip()
GEMINI_DEFAULT_MODEL = os.environ.get("GEMINI_DEFAULT_MODEL", "gemini-3.8-flash").strip()
MAX_OUTPUT_TOKENS = max(1024, min(16384, int(os.environ.get("GROQ_MAX_OUTPUT_TOKENS", "4096"))))
MODEL_CACHE_SECONDS = 1800
available_models_cache = {"expires_at": 0, "models": []}
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
        if "preferred_provider" not in user_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN preferred_provider VARCHAR(20)"))
        if "preferred_model" not in user_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN preferred_model VARCHAR(160)"))
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
        message_columns = {row["name"] for row in conn.execute(text("PRAGMA table_info(messages)")).mappings()} if DATABASE_URL.startswith("sqlite") else {
            row["column_name"] for row in conn.execute(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'messages' AND table_schema = current_schema()
            """)).mappings()
        }
        for column, definition in (
            ("attachment_type", "VARCHAR(20)"),
            ("attachment_name", "VARCHAR(255)"),
            ("attachment_data", "TEXT"),
            ("attachment_truncated", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ):
            if column not in message_columns:
                conn.execute(text(f"ALTER TABLE messages ADD COLUMN {column} {definition}"))


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
            text("SELECT role, content, attachment_type, attachment_name, attachment_data, attachment_truncated FROM messages WHERE chat_id = :chat_id ORDER BY created_at ASC, id ASC"),
            {"chat_id": chat_id},
        ).mappings().all()
    messages = []
    for row in rows:
        message = {"role": row["role"], "content": row["content"]}
        if row["attachment_type"]:
            attachment = {
                "kind": row["attachment_type"],
                "name": row["attachment_name"] or "attachment",
                "truncated": bool(row["attachment_truncated"]),
            }
            if row["attachment_type"] == "image":
                attachment["data_url"] = row["attachment_data"]
            message["attachment"] = attachment
        messages.append(message)
    return messages


def get_model_history(chat_id):
    """Build a bounded prompt history while retaining recent uploaded context."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT role, content, attachment_type, attachment_name, attachment_data, attachment_truncated
            FROM messages WHERE chat_id = :chat_id ORDER BY created_at DESC, id DESC LIMIT 16
        """), {"chat_id": chat_id}).mappings().all()
    rows = list(reversed(rows))
    history = []
    remaining_chars = 32000
    image_indices = [index for index, row in enumerate(rows) if row["role"] == "user" and row["attachment_type"] == "image"]
    keep_image_indices = set(image_indices[-3:])
    for index, row in enumerate(rows):
        role = row["role"]
        content = (row["content"] or "")[:8000]
        attachment_type = row["attachment_type"]
        if attachment_type == "text" and row["attachment_data"]:
            file_text = row["attachment_data"][:6000]
            clipped_note = " (file was truncated to 6,000 characters)" if row["attachment_truncated"] else ""
            content = f"{content}\n\n[Attached text file: {row['attachment_name'] or 'file'}{clipped_note}]\n{file_text}".strip()
        content = content[:remaining_chars]
        remaining_chars -= len(content)
        if role == "user" and attachment_type == "image" and row["attachment_data"] and index in keep_image_indices:
            content_parts = [{"type": "text", "text": content or "Describe this image."}]
            content_parts.append({"type": "image_url", "image_url": {"url": row["attachment_data"]}})
            history.append({"role": role, "content": content_parts})
        elif role == "user" and attachment_type == "image":
            history.append({"role": role, "content": (content + "\n[An older image attachment was omitted from the recent visual context.] ").strip()})
        elif role == "user" and attachment_type == "file":
            history.append({"role": role, "content": (content + f"\n[Attached file: {row['attachment_name']}; file contents could not be read.] ").strip()})
        else:
            history.append({"role": role, "content": content})
        if remaining_chars <= 0:
            break
    return history


def available_models():
    now = time.time()
    if available_models_cache["expires_at"] > now:
        return available_models_cache["models"]
    models = []
    try:
        for model in client.models.list().data:
            model_id = getattr(model, "id", "")
            if not model_id or getattr(model, "active", True) is False:
                continue
            if any(part in model_id.lower() for part in ("whisper", "tts", "speech", "transcribe", "embedding")):
                continue
            models.append({"provider": "groq", "id": model_id, "label": f"Groq · {model_id}"})
    except Exception:
        app.logger.exception("Could not load available Groq models")

    if gemini_client:
        try:
            for model in gemini_client.models.list():
                actions = getattr(model, "supported_actions", None) or getattr(model, "supported_generation_methods", None) or []
                if actions and not any("generatecontent" in str(action).lower() for action in actions):
                    continue
                model_id = getattr(model, "base_model_id", None) or getattr(model, "name", "")
                model_id = model_id.removeprefix("models/")
                if model_id and not any(part in model_id.lower() for part in ("embedding", "tts", "live", "transcri", "image")):
                    models.append({"provider": "gemini", "id": model_id, "label": f"Gemini · {model_id}"})
        except Exception:
            app.logger.exception("Could not load available Gemini models")
    models.sort(key=lambda model: (model["provider"], model["id"].lower()))
    available_models_cache["models"] = models
    available_models_cache["expires_at"] = now + MODEL_CACHE_SECONDS
    return models


def get_user_model_preference(user_id):
    with engine.connect() as conn:
        row = conn.execute(text("SELECT preferred_provider, preferred_model FROM users WHERE id = :id"), {"id": user_id}).mappings().first()
    return (row["preferred_provider"], row["preferred_model"]) if row else (None, None)


def gemini_contents(messages):
    contents = []
    for message in messages:
        role = "model" if message["role"] == "assistant" else "user"
        value = message["content"]
        parts = []
        if isinstance(value, str):
            if value:
                parts.append(genai_types.Part.from_text(text=value))
        else:
            for item in value:
                if item.get("type") == "text" and item.get("text"):
                    parts.append(genai_types.Part.from_text(text=item["text"]))
                elif item.get("type") == "image_url":
                    image_url = item.get("image_url", {}).get("url", "")
                    match = re.fullmatch(r"data:(image/(?:jpeg|png|webp|gif));base64,([A-Za-z0-9+/]+={0,2})", image_url)
                    if match:
                        image_bytes = base64.b64decode(match.group(2), validate=True)
                        parts.append(genai_types.Part.from_bytes(data=image_bytes, mime_type=match.group(1)))
        if parts:
            contents.append(genai_types.Content(role=role, parts=parts))
    return contents


def generate_reply(messages, vision=False, provider="groq", selected_model=None):
    if provider == "gemini":
        if not gemini_client:
            raise RuntimeError("Gemini is not configured. Set GEMINI_API_KEY on the server.")
        model = selected_model or GEMINI_DEFAULT_MODEL
        response = gemini_client.models.generate_content(
            model=model,
            contents=gemini_contents(messages),
            config=genai_types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            ),
        )
        reply = (response.text or "").strip()
        if not reply:
            raise RuntimeError(f"Gemini model {model} returned an empty answer")
        candidates = getattr(response, "candidates", None) or []
        if candidates and "MAX_TOKENS" in str(getattr(candidates[0], "finish_reason", "")):
            reply += "\n\n_(This answer reached the output limit and may be incomplete.)_"
        return reply

    primary = selected_model or (VISION_MODEL if vision else MODEL)
    fallback = VISION_FALLBACK_MODEL if vision and primary == VISION_MODEL else TEXT_FALLBACK_MODEL if not vision and primary == MODEL else ""
    candidates = list(dict.fromkeys(model for model in (primary, fallback) if model))
    last_error = None
    for index, model in enumerate(candidates):
        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=MAX_OUTPUT_TOKENS,
                messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
            )
            choice = response.choices[0] if response.choices else None
            reply = (choice.message.content or "").strip() if choice else ""
            if not reply:
                last_error = RuntimeError(f"Groq model {model} returned an empty answer")
                continue
            if choice.finish_reason == "length":
                reply += "\n\n_(This answer reached the output limit and may be incomplete.)_"
            return reply
        except Exception as error:
            last_error = error
            status_code = getattr(error, "status_code", None)
            if index + 1 >= len(candidates) or status_code not in {400, 404, 410, 422}:
                raise
            app.logger.warning("Groq model %s unavailable; retrying with configured fallback %s", model, candidates[index + 1])
    if last_error:
        raise last_error
    raise RuntimeError("No Groq model is configured")


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


@app.route("/api/models", methods=["GET"])
@login_required
def list_available_models():
    models = available_models()
    user = current_user()
    provider, model = get_user_model_preference(user["id"])
    available = {(item["provider"], item["id"]) for item in models}
    saved_preference = (provider, model) in available
    if (provider, model) not in available:
        defaults = [("groq", MODEL), ("gemini", GEMINI_DEFAULT_MODEL)]
        provider, model = next((choice for choice in defaults if choice in available), (None, None))
    return jsonify({"models": models, "provider": provider, "model": model, "saved": saved_preference})


@app.route("/api/model-preference", methods=["POST"])
@login_required
@rate_limit_user("model_preference", 30, 3600)
def save_model_preference():
    user = current_user()
    data = request.get_json(silent=True) or {}
    provider = data.get("provider")
    model = data.get("model")
    if not isinstance(provider, str) or provider not in {"groq", "gemini"} or not isinstance(model, str):
        return jsonify({"error": "Choose a supported AI provider and model."}), 400
    if (provider, model) not in {(item["provider"], item["id"]) for item in available_models()}:
        return jsonify({"error": "That model is not available with the server's configured API keys."}), 400
    with engine.begin() as conn:
        conn.execute(text("UPDATE users SET preferred_provider = :provider, preferred_model = :model WHERE id = :id"), {
            "provider": provider, "model": model, "id": user["id"]
        })
    return jsonify({"provider": provider, "model": model})


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
        token = oauth.google.authorize_access_token()
        # Authlib's OpenID Connect flow validates the ID token and places its
        # claims in the token response. This avoids depending on an API base URL.
        profile = token.get("userinfo")
        if not profile and token.get("id_token"):
            profile = oauth.google.parse_id_token(token)
        if not profile:
            raise ValueError("Google did not return verified OpenID profile claims")
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
    file_text = data.get("file_text", "")
    file_name = data.get("file_name")
    file_truncated = data.get("file_truncated") is True
    unsupported_name = data.get("unsupported_name")

    if not user_message and not image_data_url and not file_name and not unsupported_name:
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

    if file_name:
        if not isinstance(file_text, str) or len(file_text) > 6000:
            return jsonify({"error": "Text attachments must be 6,000 characters or fewer."}), 400
        file_name = os.path.basename(str(file_name))[:255]
    if unsupported_name:
        unsupported_name = os.path.basename(str(unsupported_name))[:255]

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

    stored_user_text = user_message
    attachment_type = None
    attachment_name = None
    attachment_data = None
    attachment_truncated = False
    if image_data_url:
        attachment_type = "image"
        attachment_name = image_name
        attachment_data = image_data_url
    elif file_name:
        attachment_type = "text"
        attachment_name = file_name
        attachment_data = file_text
        attachment_truncated = file_truncated
    elif unsupported_name:
        attachment_type = "file"
        attachment_name = unsupported_name
    if attachment_type:
        stored_user_text = user_message

    now = time.time()
    new_title = make_title(stored_user_text or attachment_name or "New Chat") if chat["title"] == "New Chat" else chat["title"]
    # Commit the user's turn before contacting Groq, so it remains in chat
    # history even if generation fails or times out.
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO messages (id, chat_id, role, content, created_at,
                                  attachment_type, attachment_name, attachment_data, attachment_truncated)
            VALUES (:id, :chat_id, 'user', :content, :created_at,
                    :attachment_type, :attachment_name, :attachment_data, :attachment_truncated)
        """), {
            "id": str(uuid.uuid4()), "chat_id": chat_id, "content": stored_user_text,
            "created_at": now, "attachment_type": attachment_type,
            "attachment_name": attachment_name, "attachment_data": attachment_data,
            "attachment_truncated": attachment_truncated,
        })
        if new_title != chat["title"]:
            conn.execute(text("UPDATE chats SET title = :title WHERE id = :chat_id AND user_id = :user_id"), {
                "title": new_title, "chat_id": chat_id, "user_id": user["id"]
            })

    try:
        model_history = get_model_history(chat_id)
        needs_vision = any(
            message["role"] == "user" and isinstance(message["content"], list)
            for message in model_history
        )
        preferred_provider, preferred_model = get_user_model_preference(user["id"])
        selected_provider = preferred_provider or "groq"
        selected_model = preferred_model or (VISION_MODEL if needs_vision else MODEL)
        reply = generate_reply(model_history, vision=needs_vision, provider=selected_provider, selected_model=selected_model)
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO messages (id, chat_id, role, content, created_at)
                VALUES (:id, :chat_id, 'assistant', :content, :created_at)
            """), {
                "id": str(uuid.uuid4()), "chat_id": chat_id, "content": reply, "created_at": time.time()
            })

        return jsonify({"reply": reply, "title": new_title})

    except Exception:
        app.logger.exception("Message generation failed for chat %s", chat_id)
        return jsonify({"error": "Patrick couldn't generate a reply right now. Please try again."}), 502


@app.route("/api/chats/<chat_id>/shortcut", methods=["POST"])
@login_required
@rate_limit_ip("shortcut_ip", 60, 3600)
def save_shortcut(chat_id):
    user = current_user()
    data = request.get_json(silent=True) or {}
    command = data.get("command", "")
    query = data.get("query", "")
    if not isinstance(command, str) or not isinstance(query, str) or not command.strip() or not query.strip():
        return jsonify({"error": "A search command and query are required."}), 400
    if len(command) > 12000 or len(query) > 2000:
        return jsonify({"error": "Search command is too long."}), 400
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
    with engine.begin() as conn:
        today_count = conn.execute(text("""
            SELECT COUNT(*) FROM messages m JOIN chats c ON c.id = m.chat_id
            WHERE c.user_id = :user_id AND m.role = 'user' AND m.created_at >= :day_start
        """), {"user_id": user["id"], "day_start": day_start}).scalar_one()
        if today_count >= DAILY_MESSAGE_LIMIT:
            return jsonify({"error": f"Daily message limit reached ({DAILY_MESSAGE_LIMIT}). Please try again tomorrow."}), 429
        now = time.time()
        conn.execute(text("""
            INSERT INTO messages (id, chat_id, role, content, created_at)
            VALUES (:id, :chat_id, 'user', :content, :created_at)
        """), {"id": str(uuid.uuid4()), "chat_id": chat_id, "content": command.strip(), "created_at": now})
        reply = f'Opening a Google search for "{query.strip()}" in a new tab.'
        conn.execute(text("""
            INSERT INTO messages (id, chat_id, role, content, created_at)
            VALUES (:id, :chat_id, 'assistant', :content, :created_at)
        """), {"id": str(uuid.uuid4()), "chat_id": chat_id, "content": reply, "created_at": time.time()})
        new_title = make_title(command) if chat["title"] == "New Chat" else chat["title"]
        if new_title != chat["title"]:
            conn.execute(text("UPDATE chats SET title = :title WHERE id = :chat_id"), {"title": new_title, "chat_id": chat_id})
    return jsonify({"reply": reply, "title": new_title})


if __name__ == "__main__":
    if not os.environ.get("GROQ_API_KEY"):
        print("\n⚠️  GROQ_API_KEY is not set.")
        print('   Create a .env file with GROQ_API_KEY="your-key-here"\n')

    if app.config["SECRET_KEY"] == "dev-only-change-me":
        print("⚠️  SECRET_KEY is using the development fallback. Set a strong SECRET_KEY in .env/Render.")

    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true" and not is_production
    app.run(debug=debug_mode, host="127.0.0.1", port=port)
