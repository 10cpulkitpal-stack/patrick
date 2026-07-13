import os
import json
import uuid
import threading
from flask import Flask, render_template, request, jsonify
from groq import Groq
from dotenv import load_dotenv

load_dotenv()  # reads variables from a .env file in this folder, if present

app = Flask(__name__)

# Reads GROQ_API_KEY from the .env file (see .env.example for the format)
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# Note: Groq retired "llama-3.3-70b-versatile" (June 2026) — using the
# officially recommended replacement instead so this keeps working.
# Vision model list confirmed live against https://console.groq.com/docs/vision
MODEL = "openai/gpt-oss-120b"
VISION_MODEL = "qwen/qwen3.6-27b"  # supports image input; Groq preview model

DATA_FILE = os.path.join(os.path.dirname(__file__), "chats.json")
_lock = threading.Lock()  # guards read/write of the JSON store


# ---------- storage helpers ----------

def load_chats():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def save_chats(chats):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(chats, f, indent=2)


def make_title(first_message):
    title = first_message.strip().replace("\n", " ")
    return (title[:40] + "...") if len(title) > 40 else title


# ---------- page ----------

@app.route("/")
def index():
    return render_template("index.html")


# ---------- chat list endpoints ----------

@app.route("/api/chats", methods=["GET"])
def list_chats():
    with _lock:
        chats = load_chats()
    summary = [
        {"id": cid, "title": c["title"]}
        for cid, c in sorted(chats.items(), key=lambda kv: kv[1]["created_at"], reverse=True)
    ]
    return jsonify(summary)


@app.route("/api/chats", methods=["POST"])
def create_chat():
    import time
    with _lock:
        chats = load_chats()
        chat_id = str(uuid.uuid4())
        chats[chat_id] = {
            "title": "New Chat",
            "messages": [],
            "created_at": time.time(),
        }
        save_chats(chats)
    return jsonify({"id": chat_id, "title": "New Chat"})


@app.route("/api/chats/<chat_id>", methods=["GET"])
def get_chat(chat_id):
    with _lock:
        chats = load_chats()
    chat = chats.get(chat_id)
    if not chat:
        return jsonify({"error": "Chat not found"}), 404
    return jsonify({"id": chat_id, "title": chat["title"], "messages": chat["messages"]})


@app.route("/api/chats/<chat_id>", methods=["DELETE"])
def delete_chat(chat_id):
    with _lock:
        chats = load_chats()
        if chat_id in chats:
            del chats[chat_id]
            save_chats(chats)
    return jsonify({"status": "ok"})


@app.route("/api/chats/<chat_id>", methods=["PATCH"])
def rename_chat(chat_id):
    data = request.get_json(force=True)
    new_title = (data.get("title") or "").strip()

    if not new_title:
        return jsonify({"error": "Title cannot be empty"}), 400

    with _lock:
        chats = load_chats()
        chat = chats.get(chat_id)
        if not chat:
            return jsonify({"error": "Chat not found"}), 404
        chat["title"] = new_title
        save_chats(chats)

    return jsonify({"id": chat_id, "title": new_title})


# ---------- messaging ----------

@app.route("/api/chats/<chat_id>/message", methods=["POST"])
def send_message(chat_id):
    data = request.get_json(force=True)
    user_message = (data.get("message") or "").strip()
    image_data_url = data.get("image")       # optional: "data:image/png;base64,...."
    image_name = data.get("image_name")      # optional: original filename, for display

    if not user_message and not image_data_url:
        return jsonify({"error": "Message cannot be empty"}), 400

    with _lock:
        chats = load_chats()
        chat = chats.get(chat_id)
        if not chat:
            return jsonify({"error": "Chat not found"}), 404

        # What gets saved to chat history is always plain text — image bytes
        # are only used for the one-off vision call, never stored, to keep
        # chats.json small and keep the rest of the conversation on the
        # regular (cheaper, faster) text model.
        stored_user_text = user_message
        if image_data_url:
            label = f"[Image attached: {image_name}]" if image_name else "[Image attached]"
            stored_user_text = f"{label} {user_message}".strip()

        chat["messages"].append({"role": "user", "content": stored_user_text})

        try:
            if image_data_url:
                vision_messages = chat["messages"][:-1] + [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_message or "Describe this image."},
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                    ],
                }]
                response = client.chat.completions.create(
                    model=VISION_MODEL,
                    max_tokens=1024,
                    messages=vision_messages,
                )
            else:
                response = client.chat.completions.create(
                    model=MODEL,
                    max_tokens=1024,
                    messages=chat["messages"],
                )

            reply = response.choices[0].message.content
            chat["messages"].append({"role": "assistant", "content": reply})

            if chat["title"] == "New Chat":
                chat["title"] = make_title(stored_user_text)

            save_chats(chats)
            return jsonify({"reply": reply, "title": chat["title"]})

        except Exception as e:
            chat["messages"].pop()  # remove the user message since the call failed
            save_chats(chats)
            return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    if not os.environ.get("GROQ_API_KEY"):
        print("\n⚠️  GROQ_API_KEY is not set.")
        print("   Create a .env file in this folder with:")
        print('   GROQ_API_KEY="your-key-here"\n')

    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
    app.run(debug=debug_mode, host="0.0.0.0", port=port)
