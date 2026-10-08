# Patrick — AI Chat Bot

Patrick is a ChatGPT-style chatbot built with **Flask**, **Next.js**, **SQLAlchemy**, and the **Groq and Gemini APIs**.

It provides persistent chat conversations, image understanding, voice input/output, light/dark themes, chat management, and a responsive interface for desktop and mobile browsers.

## 🌐 Live Demo

**Try Patrick online:**  
https://patrick-c89f.onrender.com/

> The application is hosted on Render and may take a short time to wake up if the free instance has been inactive.

## ✨ Features

- 💬 **AI chat** powered by Groq or Gemini; users choose from enabled models
- 🧠 **Conversation history** stored in SQLite by default, with PostgreSQL support
- 🖼️ **Image understanding** using a vision-capable model
- 📎 **Image/file attachment UI**
- 🎙️ **Voice input** using the browser's Speech Recognition API
- 🔊 **Voice replies** using the browser's Speech Synthesis API
- 🌙 **Dark and light themes**
- 📱 **Responsive design** with mobile sidebar support
- 🗂️ **Multiple conversations**
- ✏️ **Rename chats**
- 🗑️ **Delete chats**
- 🧑‍💻 **Markdown/code-friendly AI responses**
- 🔐 User accounts with per-user conversation storage

## 🛠️ Tech Stack

| Technology | Purpose |
|---|---|
| Python | Backend programming |
| Flask | Web server and REST API |
| Groq API | AI model inference |
| Gemini API | Optional Google AI model inference |
| Next.js and React | Frontend pages and interaction |
| TypeScript | Frontend application logic |
| CSS | UI and responsive styling |
| SQLAlchemy | SQLite or PostgreSQL conversation storage |
| python-dotenv | Environment variable management |
| Highlight.js | Code syntax highlighting |

## 📁 Project Structure

```text
patrick-chatbot/
│
├── backend/
│   ├── __init__.py
│   ├── app.py              # Flask app and HTTP routes
│   ├── ai.py               # AI providers and system prompt
│   ├── auth.py             # Email verification and mail delivery
│   ├── chats.py            # ORM-backed chat persistence and history
│   ├── models.py           # SQLAlchemy ORM schema
│   └── migrations/         # Alembic database migrations
├── frontend/
│   ├── app/                # Next.js app, auth pages, and styles
│   ├── components/         # Patrick chat workspace and UI
│   ├── public/             # Browser assets
│   └── out/                # Generated static site served by Flask (not committed)
├── render-build.sh         # Builds frontend and installs Python requirements on Render
├── alembic.ini
├── tests/                 # Automated unit tests
├── requirements.txt
├── .env.example
├── .gitignore
├── patrick.db (local SQLite database; created by migrations)
```

> Local conversations are stored in `patrick.db`. Keep the database private; it contains account and chat data.

## 🚀 Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/patrick-chatbot.git
cd patrick-chatbot
```

Replace `YOUR_USERNAME/patrick-chatbot` with your actual GitHub repository URL.

### 2. Create a virtual environment

Windows:

```bash
python -m venv venv
venv\Scripts\activate
```

macOS/Linux:

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

Install Node.js 22 and pnpm 11.19.0, then build the static frontend:

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm build
cd ..
```

### 4. Configure the Groq API key

Create a `.env` file in the project root:

```env
GROQ_API_KEY=your-groq-api-key-here
SECRET_KEY=replace-with-a-long-random-secret
GOOGLE_CLIENT_ID=your-google-oauth-client-id
GOOGLE_CLIENT_SECRET=your-google-oauth-client-secret
GOOGLE_REDIRECT_URI=http://127.0.0.1:5000/auth/google/callback
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USERNAME=your-email@gmail.com
MAIL_PASSWORD=your-email-app-password
MAIL_FROM="Patrick <your-email@gmail.com>"
PUBLIC_BASE_URL=http://127.0.0.1:5000
```

You can use `.env.example` as a template.

**Never commit your `.env` file or expose your API key publicly.**

### 5. Create or upgrade the database

Run migrations before starting the web server. They create a new database or upgrade an existing Patrick database while retaining its data:

```bash
alembic upgrade head
```

### 6. Run locally

```bash
gunicorn --bind 127.0.0.1:5000 backend.app:app
```

The server will normally start at:

```text
http://127.0.0.1:5000
```

Open the address in your browser. Run commands from the repository root. For local debugging, set `FLASK_DEBUG=true` and run `python -m backend.app`; the debug server binds only to `127.0.0.1`.

## 🔑 Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | Yes | API key used to access Groq models |
| `GROQ_TEXT_MODEL` | No | Primary text model; defaults to `openai/gpt-oss-120b`. |
| `GROQ_TEXT_FALLBACK_MODEL` | No | Text fallback for retired/unavailable models; defaults to `openai/gpt-oss-20b`. |
| `GROQ_VISION_MODEL` | No | Primary image-capable model; defaults to `qwen/qwen3.8-27b`. |
| `GROQ_VISION_FALLBACK_MODEL` | No | Optional image-capable fallback model. |
| `GROQ_MAX_OUTPUT_TOKENS` | No | Output-token budget; defaults to `4096` and is limited to 1,024–16,384. |
| `GEMINI_API_KEY` | Optional | Google AI Studio API key. Enables the Gemini models in the in-app model picker. |
| `GEMINI_DEFAULT_MODEL` | No | Gemini model selected for new accounts when available; defaults to `gemini-3.8-flash`. |
| `SECRET_KEY` | Yes in production | Flask session signing key. Set a long, random value before deployment. |
| `GOOGLE_CLIENT_ID` | Optional | OAuth client ID from Google Cloud Console. Enables Google sign-in when paired with the secret. |
| `GOOGLE_CLIENT_SECRET` | Optional | OAuth client secret. Keep it private and store it as a Render environment variable in production. |
| `GOOGLE_REDIRECT_URI` | Optional | OAuth callback URL. Defaults to the current host's `/auth/google/callback`. |
| `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM` | Required for email/password signup | SMTP settings used to send account verification links. Keep the password private. Gmail users should use an app password. |
| `PUBLIC_BASE_URL` | Recommended | Public base URL used in verification emails (for example, `https://patrick-c89f.onrender.com`). |
| `DAILY_MESSAGE_LIMIT` | No | Maximum user messages per account per UTC day. Defaults to `100`; each account is also limited to 20 messages per hour and each IP to 60 per hour. |
| `DATABASE_URL` | Yes in production | Persistent PostgreSQL connection URL. Local development defaults to `sqlite:///patrick.db`; production startup refuses SQLite because Render's local filesystem is ephemeral. |
| `PORT` | No | Port for the Flask application. Defaults to `5000` |
| `FLASK_DEBUG` | No | Enables Flask debug mode only for local development; defaults to `false` and is ignored in production. |

When deploying to the existing Render Python web service, set its **Build Command** to `bash render-build.sh` and keep its **Start Command** as `alembic upgrade head && gunicorn backend.app:app`. The build command creates `frontend/out`, which Flask serves from the same origin as the API and login session. Keep the service's health-check path set to `/healthz`. Add the mail settings and `PUBLIC_BASE_URL` as service environment variables. Until SMTP is configured, email/password signup and verification for existing password accounts are unavailable; Google sign-in continues to work.

### Set up Google sign-in

1. Create a **Web application** OAuth client in Google Cloud Console and configure the OAuth consent screen.
2. Add your local callback URL, `http://127.0.0.1:5000/auth/google/callback`, as an authorized redirect URI.
3. Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_REDIRECT_URI` in your local `.env` file.
4. For Render, add the production callback URL `https://YOUR-APP.onrender.com/auth/google/callback` to the OAuth client's authorized redirect URIs. Set the same URL as `GOOGLE_REDIRECT_URI` and add both Google credentials in Render's environment settings.

Google sign-in requires a verified Google email. If that email already has a Patrick account, signing in with Google opens that account; otherwise, Patrick creates one. Email/password sign-in remains available without Google credentials, but new email/password accounts must verify their email first. Configure the SMTP settings above before enabling email/password registration in production.

Example:

```env
GROQ_API_KEY=your-groq-api-key
PORT=5000
FLASK_DEBUG=true
```

## 🤖 AI Models

Users can choose a model from the selector in the chat header. It lists active Groq chat models available to `GROQ_API_KEY` and Gemini models available to `GEMINI_API_KEY`; each user's choice is saved to their account. The Gemini list comes from Google's Models API and only includes models that support `generateContent`.

The default Groq models are configured through environment variables:

### Text model

```python
GROQ_TEXT_MODEL=openai/gpt-oss-120b
GROQ_TEXT_FALLBACK_MODEL=openai/gpt-oss-20b
```

The primary model handles normal text conversations. If Groq rejects it as retired or unavailable, Patrick tries the configured fallback.

### Vision model

```python
GROQ_VISION_MODEL=qwen/qwen3.8-27b
```

This model is used when a recent message includes an image. Image attachments and text-file contents are retained for subsequent follow-up questions. The previous `qwen/qwen3.6-27b` default was retired by Groq in September 2026; `qwen/qwen3.8-27b` is its listed replacement.

If Groq changes model availability, set these environment variables to model IDs enabled for your Groq account. The app bounds prompt history to the latest 16 messages and 32,000 characters, and falls back for empty or unavailable default Groq model responses.

To enable Gemini in production, create an API key in Google AI Studio and add it to Render as `GEMINI_API_KEY`. All users share the API credentials configured by the site owner, so availability, quotas, and billing follow those provider accounts. Users can only select models exposed by the configured keys.

## 🔄 How It Works

The basic request flow is:

```text
User
  │
  ▼
Browser UI
  │
  ▼
Flask API
  │
  ├── Text message ──► Groq text model
  │
  └── Image message ─► Groq vision model
  │
  ▼
AI response
  │
  ▼
Browser displays response
  │
  ▼
Conversation saved to the configured SQL database
```

## 🔌 API Endpoints

### Authentication and profile

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/signin`, `/signup` | Static Next.js sign-in and sign-up pages |
| `POST` | `/api/auth/register` | Register with email/password; sends a verification email |
| `POST` | `/api/auth/login` | Sign in with a verified email/password account |
| `GET`, `POST` | `/verify-email` | Verify an email/password account |
| `GET` | `/auth/google` | Begin Google OAuth sign-in |
| `GET` | `/auth/google/callback` | Complete Google OAuth sign-in |
| `POST` | `/api/auth/logout` | Sign out |
| `GET` | `/api/me` | Get the current account |
| `PATCH` | `/api/profile` | Update profile name |
| `POST` | `/api/profile/password` | Set or change the account password |
| `GET` | `/api/models` | List models available to configured provider keys |
| `POST` | `/api/model-preference` | Save the user's provider/model choice |
| `GET` | `/healthz` | Health check; returns 503 if the database cannot be reached |

Chat endpoints require a signed-in session. Mutating requests must be same-origin.

### Get all chats

```http
GET /api/chats
```

Returns a list of saved conversations.

### Create a chat

```http
POST /api/chats
```

Creates a new conversation.

### Get a conversation

```http
GET /api/chats/<chat_id>
```

Returns the selected chat and its messages.

### Rename a conversation

```http
PATCH /api/chats/<chat_id>
```

Request body:

```json
{
  "title": "My New Chat"
}
```

### Delete a conversation

```http
DELETE /api/chats/<chat_id>
```

Deletes the selected conversation.

### Send a message

```http
POST /api/chats/<chat_id>/message
```

Example:

```json
{
  "message": "Explain binary search"
}
```

For image messages, the endpoint can additionally receive an image data URL and image filename.

## 🎙️ Voice Features

Patrick uses browser-native Web APIs for voice functionality:

- **Speech Recognition** → converts microphone speech into text
- **Speech Synthesis** → reads AI responses aloud

Browser support can vary. If your browser does not support one of these APIs, the corresponding feature is disabled automatically.

## 🎨 UI Features

The frontend is designed around a ChatGPT-inspired interface and includes:

- Conversation sidebar
- New chat button
- Chat rename/delete controls
- Message bubbles
- Typing indicator
- Code blocks
- Image attachment preview
- Dark/light mode
- Responsive mobile sidebar
- Voice controls

## 💾 Data Storage

Patrick uses SQLAlchemy ORM models with Alembic-managed schema migrations. Local development uses SQLite:

```text
patrick.db
```

Set `DATABASE_URL` to a PostgreSQL connection string for a hosted deployment. Run `alembic upgrade head` from the repository root as a deployment pre-start step, before Gunicorn launches workers. On Render, set the service's **Pre-Deploy Command** to `alembic upgrade head` when available; otherwise use a Start Command of `alembic upgrade head && gunicorn backend.app:app`. Do not create schema at Python import time.

## 🔒 Security Notes

Before deploying Patrick publicly:

1. Keep API keys in environment variables.
2. Never commit `.env`.
3. Do not expose private conversation data.
4. Set a strong `SECRET_KEY` (required when `FLASK_ENV=production` or running on Render).
5. Keep SMTP verification, persisted IP/user rate limits, and same-origin request checks enabled.
6. Use HTTPS in production.
7. Disable Flask debug mode in production.

For production:

```env
FLASK_DEBUG=false
PUBLIC_BASE_URL=https://patrick-c89f.onrender.com
```

## 🧪 Development

Run the application with:

```bash
python -m backend.app
```

The production server is Gunicorn (`gunicorn backend.app:app`). Set the Render health-check path to `/healthz`. Run migrations before deploying code that requires a new schema revision.

Run the automated tests with:

```bash
pytest
```

## 📌 Future Improvements

Possible improvements include:

- [ ] Streaming AI responses
- [ ] Better file/document understanding
- [ ] PDF support
- [ ] Conversation search
- [ ] Chat export
- [ ] User profiles
- [ ] Token/cost tracking
- [ ] Admin dashboard
- [ ] Production deployment
- [ ] Better error handling and API validation
- [x] Email verification for password accounts
- [x] Per-IP/per-user rate limits and daily message cap
- [x] Same-origin checks, CSP/security headers, and SRI-pinned CDN scripts
- [x] Password length limits and loopback-only local debug server
- [x] Automated tests for prompt behavior and ORM indexes
- [x] Alembic schema migrations, query indexes, logging, and health check

## 👨‍💻 Author

**Pulkit Pal**

B.Tech Student  
Shri Ramswaroop College of Engineering and Management

## 📄 License

This project is intended for learning and development purposes.

Add a license such as the MIT License if you want to explicitly define how others can use, modify, and distribute the project.
