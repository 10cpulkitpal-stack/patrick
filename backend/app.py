import os
import re
import uuid
import time
import base64
import binascii
import hashlib
import hmac
import secrets
import logging
from functools import wraps
from urllib.parse import urlsplit

from flask import Flask, request, jsonify, session, redirect, url_for, send_from_directory
from authlib.integrations.flask_client import OAuth
from groq import Groq
from google import genai
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import case, create_engine, delete, event, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from werkzeug.middleware.proxy_fix import ProxyFix
from backend.models import Chat, EmailVerificationToken, Message, RateLimitCounter, User
from backend.ai import AIService
from backend.chats import ChatStore
from backend.auth import AuthService

load_dotenv()

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

is_production = (
    os.environ.get("FLASK_ENV", "").lower() == "production"
    or os.environ.get("RENDER", "").lower() == "true"
)
secret_key = os.environ.get("SECRET_KEY")
if is_production and not secret_key:
    raise RuntimeError("Set a strong SECRET_KEY before running in production.")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_BUILD_DIR = os.path.join(PROJECT_ROOT, "frontend", "out")
app = Flask(__name__, static_folder=None)
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


def create_gemini_client(api_key):
    if not api_key:
        return None
    try:
        return genai.Client(api_key=api_key)
    except Exception as error:
        app.logger.warning("Gemini client initialization failed; Gemini models are disabled (%s)",
                           type(error).__name__)
        return None


gemini_client = create_gemini_client(gemini_api_key)
MODEL = os.environ.get("GROQ_TEXT_MODEL", "openai/gpt-oss-120b").strip()
TEXT_FALLBACK_MODEL = os.environ.get("GROQ_TEXT_FALLBACK_MODEL", "openai/gpt-oss-20b").strip()
VISION_MODEL = os.environ.get("GROQ_VISION_MODEL", "qwen/qwen3.8-27b").strip()
VISION_FALLBACK_MODEL = os.environ.get("GROQ_VISION_FALLBACK_MODEL", "").strip()
GEMINI_DEFAULT_MODEL = os.environ.get("GEMINI_DEFAULT_MODEL", "gemini-3.8-flash").strip()
MAX_OUTPUT_TOKENS = max(1024, min(16384, int(os.environ.get("GROQ_MAX_OUTPUT_TOKENS", "4096"))))
MODEL_CACHE_SECONDS = 1800
available_models_cache = {"expires_at": 0, "models": []}
DAILY_MESSAGE_LIMIT = max(1, int(os.environ.get("DAILY_MESSAGE_LIMIT", "100")))
NON_CHAT_MODEL_MARKERS = ("whisper", "tts", "speech", "transcribe", "embedding", "orpheus")
ai_service = AIService(
    client, gemini_client, app.logger,
    text_model=MODEL, text_fallback=TEXT_FALLBACK_MODEL,
    vision_model=VISION_MODEL, vision_fallback=VISION_FALLBACK_MODEL,
    gemini_default=GEMINI_DEFAULT_MODEL, max_output_tokens=MAX_OUTPUT_TOKENS,
)

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///patrick.db").strip()
if is_production and (not DATABASE_URL or DATABASE_URL.startswith("sqlite")):
    raise RuntimeError("Set DATABASE_URL to a persistent hosted PostgreSQL database in production.")
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
app.logger.info("Configured database backend: %s", engine.dialect.name)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
chat_store = ChatStore(SessionLocal)
auth_service = AuthService(app, SessionLocal)

# Enable SQLite foreign-key enforcement for local development.
if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    with SessionLocal() as db:
        row = db.get(User, user_id)
        if row and row.email_verified:
            user = {"id": row.id, "email": row.email, "display_name": row.display_name,
                    "auth_provider": row.auth_provider, "email_verified": row.email_verified}
        else:
            user = None
    if not user:
        session.clear()
        return None
    return user


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            session.clear()
            return jsonify({"error": "Authentication required"}), 401
        return fn(*args, **kwargs)
    return wrapper


def make_title(first_message):
    return ChatStore.make_title(first_message)


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
            if any(part in model_id.lower() for part in NON_CHAT_MODEL_MARKERS):
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
        except Exception as error:
            app.logger.warning("Gemini model discovery failed; Gemini models are disabled (%s)",
                               type(error).__name__)
    models.sort(key=lambda model: (model["provider"], model["id"].lower()))
    available_models_cache["models"] = models
    available_models_cache["expires_at"] = now + MODEL_CACHE_SECONDS
    return models


def default_chat_model(models, *, vision=False, provider_hint=None, allow_unlisted=False):
    """Choose a chat-capable configured model, never a speech-only model."""
    groq_primary = VISION_MODEL if vision else MODEL
    groq_fallback = VISION_FALLBACK_MODEL if vision else TEXT_FALLBACK_MODEL
    groq_choices = [("groq", model) for model in (groq_primary, groq_fallback)
                    if model and not any(marker in model.lower() for marker in NON_CHAT_MODEL_MARKERS)]
    gemini_choices = [("gemini", GEMINI_DEFAULT_MODEL)] if gemini_client and GEMINI_DEFAULT_MODEL else []
    choices = gemini_choices + groq_choices if provider_hint == "gemini" else groq_choices + gemini_choices
    available = {(item["provider"], item["id"]) for item in models}
    for choice in choices:
        if choice in available:
            return choice
    if models:
        first = models[0]
        return first["provider"], first["id"]
    return choices[0] if allow_unlisted and choices else (None, None)


def get_user_model_preference(user_id):
    with SessionLocal() as db:
        row = db.get(User, user_id)
        return (row.preferred_provider, row.preferred_model) if row else (None, None)


def generate_reply(messages, vision=False, provider="groq", selected_model=None, user=None):
    return ai_service.generate_reply(
        messages, vision=vision, provider=provider,
        selected_model=selected_model, user=user,
    )

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
    insert = sqlite_insert if engine.dialect.name == "sqlite" else pg_insert
    statement = insert(RateLimitCounter).values(
        bucket_key=bucket_key, window_id=window_id, hit_count=1,
        expires_at=now + (window_seconds * 2),
    ).on_conflict_do_update(
        index_elements=[RateLimitCounter.bucket_key],
        set_={
            "hit_count": case(
                (RateLimitCounter.window_id == window_id, RateLimitCounter.hit_count + 1),
                else_=1,
            ),
            "window_id": window_id,
            "expires_at": now + (window_seconds * 2),
        },
    ).returning(RateLimitCounter.hit_count)
    with SessionLocal.begin() as db:
        hit_count = db.execute(statement).scalar_one()
        if now - last_rate_cleanup > 300:
            db.execute(delete(RateLimitCounter).where(RateLimitCounter.expires_at < now))
            last_rate_cleanup = now
    if hit_count > limit:
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


_frontend_script_hash_sources = None


def frontend_script_hash_sources():
    """Allow only the inline bootstrap scripts emitted by this static Next build."""
    global _frontend_script_hash_sources
    if _frontend_script_hash_sources is None:
        hashes = set()
        if os.path.isdir(FRONTEND_BUILD_DIR):
            for root, _directories, filenames in os.walk(FRONTEND_BUILD_DIR):
                for filename in filenames:
                    if not filename.endswith(".html"):
                        continue
                    try:
                        with open(os.path.join(root, filename), "rb") as html_file:
                            document = html_file.read()
                    except OSError:
                        continue
                    for script in re.findall(rb"<script(?:\s[^>]*)?>(.*?)</script\s*>", document, re.DOTALL | re.IGNORECASE):
                        if script.strip():
                            digest = base64.b64encode(hashlib.sha256(script).digest()).decode("ascii")
                            hashes.add(f"'sha256-{digest}'")
        _frontend_script_hash_sources = " ".join(sorted(hashes))
    return _frontend_script_hash_sources


@app.after_request
def add_security_headers(response):
    inline_script_hashes = frontend_script_hash_sources()
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        f"script-src 'self' {inline_script_hashes}; "
        "style-src 'self'; style-src-attr 'unsafe-inline'; "
        "font-src 'self' data:; "
        "img-src 'self' data: blob:; connect-src 'self'; "
        "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'",
    )
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(self), geolocation=()")
    if is_production:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


@app.route("/healthz", methods=["GET"])
def health_check():
    """Readiness check for Render and other HTTP health monitors."""
    try:
        with engine.connect() as connection:
            connection.execute(select(1))
        return jsonify({"status": "ok"}), 200
    except Exception:
        app.logger.exception("Health check failed while checking the database")
        return jsonify({"status": "unavailable"}), 503


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
        provider, model = default_chat_model(models, provider_hint=provider)
        if provider and model:
            with SessionLocal.begin() as db:
                account = db.get(User, user["id"])
                if account:
                    account.preferred_provider, account.preferred_model = provider, model
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
    with SessionLocal.begin() as db:
        account = db.get(User, user["id"])
        account.preferred_provider, account.preferred_model = provider, model
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
    with SessionLocal.begin() as db:
        account = db.get(User, user["id"])
        account.display_name = display_name
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

    with SessionLocal.begin() as db:
        row = db.get(User, user["id"])
        if row.auth_provider != "google" and not google_verified_recently and not check_password_hash(row.password_hash, current_password):
            return jsonify({"error": "Current password is incorrect."}), 400
        if row.auth_provider == "google":
            row.auth_provider = "both"
        row.password_hash = generate_password_hash(new_password)
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
    if not auth_service.mail_settings():
        return jsonify({"error": "Email verification is not configured. Please use Google sign-in or contact the site owner."}), 503

    user_id = str(uuid.uuid4())
    verification_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(verification_token.encode()).hexdigest()

    try:
        with SessionLocal.begin() as db:
            db.add(User(id=user_id, email=email, password_hash=generate_password_hash(password),
                        created_at=time.time(), display_name=display_name, auth_provider="password", email_verified=False))
            db.add(EmailVerificationToken(token_hash=token_hash, user_id=user_id, expires_at=time.time() + 1800))
    except IntegrityError:
        return jsonify({"error": "An account with that email already exists."}), 409

    if not auth_service.send_verification_email(email, verification_token):
        with SessionLocal.begin() as db:
            account = db.get(User, user_id)
            if account and not account.email_verified:
                db.delete(account)
        return jsonify({"error": "We couldn't send the verification email. Please try again later."}), 503
    return jsonify({"verification_required": True, "message": "Check your email for a verification link. It expires in 30 minutes."}), 202


@app.route("/verify-email", methods=["GET", "POST"])
def verify_email():
    if request.method == "GET":
        token = request.args.get("token", "")
        token_hash = hashlib.sha256(token.encode()).hexdigest() if token else ""
        with SessionLocal() as db:
            row = db.scalar(select(EmailVerificationToken).where(
                EmailVerificationToken.token_hash == token_hash, EmailVerificationToken.expires_at > time.time()))
        if not row:
            return redirect(url_for("signup", error="verification_expired"))
        return send_from_directory(FRONTEND_BUILD_DIR, "verify-email.html")

    data = request.get_json(silent=True) or {}
    token = data.get("token", "") if request.is_json else request.form.get("token", "")
    token_hash = hashlib.sha256(token.encode()).hexdigest() if token else ""
    with SessionLocal.begin() as db:
        row = db.scalar(select(EmailVerificationToken).where(
            EmailVerificationToken.token_hash == token_hash, EmailVerificationToken.expires_at > time.time()))
        if not row:
            if request.is_json:
                return jsonify({"error": "This verification link is invalid or expired."}), 400
            return redirect(url_for("signup", error="verification_expired"))
        account = db.get(User, row.user_id)
        account.email_verified = True
        db.delete(row)
        for old_token in db.scalars(select(EmailVerificationToken).where(EmailVerificationToken.user_id == account.id)):
            db.delete(old_token)
    if request.is_json:
        return jsonify({"verified": True})
    return redirect(url_for("signin", verified="1"))


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

    with SessionLocal() as db:
        account = db.scalar(select(User).where(User.email == email))
        row = {"id": account.id, "email": account.email, "password_hash": account.password_hash,
               "email_verified": account.email_verified} if account else None

    if not row or not check_password_hash(row["password_hash"], password):
        return jsonify({"error": "Incorrect email or password."}), 401
    if not row["email_verified"]:
        if auth_service.issue_verification_token(row["id"], row["email"]):
            return jsonify({"error": "This account needs email verification. We sent a fresh verification link."}), 403
        return jsonify({"error": "Email verification is not configured or could not be sent. Please contact the site owner."}), 503

    session.clear()
    session["user_id"] = row["id"]
    session.permanent = True
    return jsonify({"authenticated": True, "user": {"id": row["id"], "email": row["email"]}})


@app.route("/auth/google")
def google_login():
    if not google_oauth_enabled:
        return redirect(url_for("signin", error="google_unavailable"))

    redirect_uri = os.environ.get("GOOGLE_REDIRECT_URI") or url_for("google_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@app.route("/auth/google/callback")
def google_callback():
    if not google_oauth_enabled:
        return redirect(url_for("signin", error="google_unavailable"))

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
            return redirect(url_for("signin", error="google_unverified"))

        with SessionLocal.begin() as db:
            row = db.scalar(select(User).where(User.email == email))
            if row:
                user_id = row.id
                if not row.email_verified:
                    # A verified Google identity proves ownership of the address.
                    # Replace any password chosen by an unverified registrant.
                    row.email_verified = True
                    row.auth_provider = "google"
                    row.password_hash = generate_password_hash(secrets.token_urlsafe(48))
                    row.display_name = row.display_name or (profile.get("name") or "")[:120]
                    for token_row in db.scalars(select(EmailVerificationToken).where(EmailVerificationToken.user_id == user_id)):
                        db.delete(token_row)
                else:
                    row.auth_provider = "both"
                    row.display_name = row.display_name or (profile.get("name") or "")[:120]
            else:
                user_id = str(uuid.uuid4())
                db.add(User(id=user_id, email=email, password_hash=generate_password_hash(uuid.uuid4().hex),
                            created_at=time.time(), display_name=(profile.get("name") or "")[:120],
                            auth_provider="google", email_verified=True))

        session.clear()
        session["user_id"] = user_id
        session["google_verified_at"] = time.time()
        session.permanent = True
        return redirect(url_for("index"))
    except Exception:
        app.logger.exception("Google sign-in failed")
        return redirect(url_for("signin", error="google_failed"))


@app.route("/api/auth/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"status": "ok"})


# ---------- page ----------

@app.route("/")
def index():
    return send_from_directory(FRONTEND_BUILD_DIR, "index.html")


@app.route("/signin")
def signin():
    return send_from_directory(FRONTEND_BUILD_DIR, "signin.html")


@app.route("/signup")
def signup():
    return send_from_directory(FRONTEND_BUILD_DIR, "signup.html")


@app.route("/<path:asset_path>")
def frontend_asset(asset_path):
    """Serve exported Next.js assets and static routes from the same origin."""
    return send_from_directory(FRONTEND_BUILD_DIR, asset_path)


@app.errorhandler(404)
def not_found(error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Not found"}), 404
    not_found_page = os.path.join(FRONTEND_BUILD_DIR, "404.html")
    if os.path.isfile(not_found_page):
        return send_from_directory(FRONTEND_BUILD_DIR, "404.html"), 404
    return error


# ---------- chat endpoints (every query is scoped to the logged-in user) ----------

@app.route("/api/chats", methods=["GET"])
@login_required
def list_chats():
    user = current_user()
    with SessionLocal() as db:
        rows = db.scalars(select(Chat).where(Chat.user_id == user["id"]).order_by(Chat.created_at.desc())).all()
        result = [{"id": row.id, "title": row.title} for row in rows]
    return jsonify(result)


@app.route("/api/chats", methods=["POST"])
@login_required
def create_chat():
    user = current_user()
    chat_id = str(uuid.uuid4())
    with SessionLocal.begin() as db:
        db.add(Chat(id=chat_id, user_id=user["id"], title="New Chat", created_at=time.time()))
    return jsonify({"id": chat_id, "title": "New Chat"})


@app.route("/api/chats/<chat_id>", methods=["GET"])
@login_required
def get_chat(chat_id):
    user = current_user()
    chat = chat_store.owned_chat(chat_id, user["id"])
    if not chat:
        # Do not reveal whether another user's chat ID exists.
        return jsonify({"error": "Chat not found"}), 404
    return jsonify({"id": chat_id, "title": chat["title"], "messages": chat_store.messages(chat_id)})


@app.route("/api/chats/<chat_id>", methods=["DELETE"])
@login_required
def delete_chat(chat_id):
    user = current_user()
    with SessionLocal.begin() as db:
        row = db.scalar(select(Chat).where(Chat.id == chat_id, Chat.user_id == user["id"]))
        if row:
            db.delete(row)
    if not row:
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
    with SessionLocal.begin() as db:
        row = db.scalar(select(Chat).where(Chat.id == chat_id, Chat.user_id == user["id"]))
        if row:
            row.title = new_title[:255]
    if not row:
        return jsonify({"error": "Chat not found"}), 404
    return jsonify({"id": chat_id, "title": new_title[:255]})


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
    chat = chat_store.owned_chat(chat_id, user["id"])
    if not chat:
        return jsonify({"error": "Chat not found"}), 404

    allowed, retry_after = consume_rate_limit("message_user", user["id"], 20, 3600)
    if not allowed:
        response = jsonify({"error": "You have reached the hourly message limit. Please wait and try again."})
        response.status_code = 429
        response.headers["Retry-After"] = str(retry_after)
        return response
    day_start = int(time.time() // 86400) * 86400
    with SessionLocal() as db:
        today_count = db.scalar(select(func.count(Message.id)).join(Chat, Message.chat_id == Chat.id)
                                .where(Chat.user_id == user["id"], Message.role == "user", Message.created_at >= day_start)) or 0
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
    with SessionLocal.begin() as db:
        db.add(Message(id=str(uuid.uuid4()), chat_id=chat_id, role="user", content=stored_user_text,
                       created_at=now, attachment_type=attachment_type, attachment_name=attachment_name,
                       attachment_data=attachment_data, attachment_truncated=attachment_truncated))
        if new_title != chat["title"]:
            chat_row = db.scalar(select(Chat).where(Chat.id == chat_id, Chat.user_id == user["id"]))
            if chat_row:
                chat_row.title = new_title[:255]

    selected_provider = None
    selected_model = None
    try:
        model_history = chat_store.model_history(chat_id)
        needs_vision = any(
            message["role"] == "user" and isinstance(message["content"], list)
            for message in model_history
        )
        preferred_provider, preferred_model = get_user_model_preference(user["id"])
        models = available_models()
        model_pairs = {(item["provider"], item["id"]) for item in models}
        if (preferred_provider, preferred_model) in model_pairs:
            selected_provider, selected_model = preferred_provider, preferred_model
        else:
            selected_provider, selected_model = default_chat_model(
                models, vision=needs_vision, provider_hint=preferred_provider, allow_unlisted=True,
            )
            if selected_provider and selected_model:
                with SessionLocal.begin() as db:
                    account = db.get(User, user["id"])
                    if account:
                        account.preferred_provider, account.preferred_model = selected_provider, selected_model
        reply = generate_reply(model_history, vision=needs_vision, provider=selected_provider, selected_model=selected_model, user=user)
        with SessionLocal.begin() as db:
            db.add(Message(id=str(uuid.uuid4()), chat_id=chat_id, role="assistant", content=reply, created_at=time.time()))

        return jsonify({"reply": reply, "title": new_title})

    except Exception:
        app.logger.exception(
            "Message generation failed for chat %s (provider=%s, model=%s)",
            chat_id, selected_provider, selected_model,
        )
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
    chat = chat_store.owned_chat(chat_id, user["id"])
    if not chat:
        return jsonify({"error": "Chat not found"}), 404
    allowed, retry_after = consume_rate_limit("message_user", user["id"], 20, 3600)
    if not allowed:
        response = jsonify({"error": "You have reached the hourly message limit. Please wait and try again."})
        response.status_code = 429
        response.headers["Retry-After"] = str(retry_after)
        return response
    day_start = int(time.time() // 86400) * 86400
    with SessionLocal() as db:
        today_count = db.scalar(select(func.count(Message.id)).join(Chat, Message.chat_id == Chat.id)
                                .where(Chat.user_id == user["id"], Message.role == "user", Message.created_at >= day_start)) or 0
    if today_count >= DAILY_MESSAGE_LIMIT:
        return jsonify({"error": f"Daily message limit reached ({DAILY_MESSAGE_LIMIT}). Please try again tomorrow."}), 429
    now = time.time()
    reply = f'Opening a Google search for "{query.strip()}" in a new tab.'
    new_title = make_title(command) if chat["title"] == "New Chat" else chat["title"]
    with SessionLocal.begin() as db:
        db.add_all([
            Message(id=str(uuid.uuid4()), chat_id=chat_id, role="user", content=command.strip(), created_at=now),
            Message(id=str(uuid.uuid4()), chat_id=chat_id, role="assistant", content=reply, created_at=time.time()),
        ])
        if new_title != chat["title"]:
            chat_row = db.scalar(select(Chat).where(Chat.id == chat_id, Chat.user_id == user["id"]))
            if chat_row:
                chat_row.title = new_title[:255]
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
