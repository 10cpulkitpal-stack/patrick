import os
import uuid
import time
from functools import wraps

from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from groq import Groq
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

load_dotenv()

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("FLASK_ENV", "").lower() == "production",
)

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
MODEL = "openai/gpt-oss-120b"
VISION_MODEL = "qwen/qwen3.6-27b"

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
                created_at DOUBLE PRECISION NOT NULL
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
        row = conn.execute(text("SELECT id, email FROM users WHERE id = :id"), {"id": user_id}).mappings().first()
    return dict(row) if row else None


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


# ---------- authentication ----------

@app.route("/api/me", methods=["GET"])
def me():
    user = current_user()
    if not user:
        return jsonify({"authenticated": False}), 401
    return jsonify({"authenticated": True, "user": {"id": user["id"], "email": user["email"]}})


@app.route("/api/auth/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if "@" not in email or len(email) > 320:
        return jsonify({"error": "Enter a valid email address."}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters."}), 400

    try:
        with engine.begin() as conn:
            user_id = str(uuid.uuid4())
            conn.execute(
                text("INSERT INTO users (id, email, password_hash, created_at) VALUES (:id, :email, :password_hash, :created_at)"),
                {"id": user_id, "email": email, "password_hash": generate_password_hash(password), "created_at": time.time()},
            )
    except IntegrityError:
        return jsonify({"error": "An account with that email already exists."}), 409

    session.clear()
    session["user_id"] = user_id
    session.permanent = True
    return jsonify({"authenticated": True, "user": {"id": user_id, "email": email}}), 201


@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id, email, password_hash FROM users WHERE email = :email"),
            {"email": email},
        ).mappings().first()

    if not row or not check_password_hash(row["password_hash"], password):
        return jsonify({"error": "Incorrect email or password."}), 401

    session.clear()
    session["user_id"] = row["id"]
    session.permanent = True
    return jsonify({"authenticated": True, "user": {"id": row["id"], "email": row["email"]}})


@app.route("/api/auth/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"status": "ok"})


# ---------- page ----------

@app.route("/")
def index():
    # Keep authentication completely separate from the chat page.
    if not current_user():
        return redirect(url_for("signin"))
    return render_template("index.html")


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
def send_message(chat_id):
    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()
    image_data_url = data.get("image")
    image_name = data.get("image_name")

    if not user_message and not image_data_url:
        return jsonify({"error": "Message cannot be empty"}), 400

    user = current_user()
    chat = chat_owned(chat_id, user["id"])
    if not chat:
        return jsonify({"error": "Chat not found"}), 404

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

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    if not os.environ.get("GROQ_API_KEY"):
        print("\n⚠️  GROQ_API_KEY is not set.")
        print('   Create a .env file with GROQ_API_KEY="your-key-here"\n')

    if app.config["SECRET_KEY"] == "dev-only-change-me":
        print("⚠️  SECRET_KEY is using the development fallback. Set a strong SECRET_KEY in .env/Render.")

    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
    app.run(debug=debug_mode, host="0.0.0.0", port=port)
