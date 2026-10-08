# Patrick — AI Chat Bot

Patrick is a ChatGPT-style chatbot built with **Flask**, **Next.js**, **SQLAlchemy**, and the **Groq and Gemini APIs**.

It provides persistent chat conversations, image understanding, voice input/output, light/dark themes, chat management, and a responsive interface for desktop and mobile browsers.

## 🌐 Deployment

Patrick is configured as one Vercel project. Add the deployed Vercel URL after the first successful deployment.

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
│   └── out/                # Generated static site for local Flask serving (not committed)
├── public/                 # Generated Vercel static files (not committed)
├── vercel-build.sh         # Exports Next.js and copies files into public/
├── vercel.json             # Function region, streaming duration, and build settings
├── app.py                  # Vercel Flask Function entry point
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
pip install -r requirements-dev.txt
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
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USERNAME=your-email@gmail.com
MAIL_PASSWORD=your-email-app-password
MAIL_FROM="Patrick <your-email@gmail.com>"
```

You can use `.env.example` as a template.
For local Google sign-in, leave `GOOGLE_REDIRECT_URI` unset so Flask uses the local callback automatically. Set `PUBLIC_BASE_URL` and `GOOGLE_REDIRECT_URI` only for your deployed Vercel domain.

**Never commit your `.env` file or expose your API key publicly.**

### 5. Create or upgrade the database

Run migrations before starting the web server. They create a new database or upgrade an existing Patrick database while retaining its data:

```bash
alembic upgrade head
```

### 6. Run locally

```bash
python -m backend.app
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
| `GEMINI_DEFAULT_MODEL` | No | Gemini model selected for new accounts when available; defaults to the stable `gemini-3.8-flash`. |
| `SECRET_KEY` | Yes in production | Flask session signing key. Set a long, random value before deployment. |
| `GOOGLE_CLIENT_ID` | Optional | OAuth client ID from Google Cloud Console. Enables Google sign-in when paired with the secret. |
| `GOOGLE_CLIENT_SECRET` | Optional | OAuth client secret. Keep it private and store it as a Vercel environment variable in production. |
| `GOOGLE_REDIRECT_URI` | Optional | On Vercel, use `https://<your-vercel-domain>/auth/google/callback`. |
| `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM` | Required for email/password signup | SMTP settings used to send account verification links. Keep the password private. Gmail users should use an app password. |
| `PUBLIC_BASE_URL` | Required in production | Set to `https://<your-vercel-domain>` for verification links. |
| `DAILY_MESSAGE_LIMIT` | No | Maximum user messages per account per UTC day. Defaults to `100`; each account is also limited to 20 messages per hour and each IP to 60 per hour. |
| `DATABASE_URL` | Yes in production | Persistent Aiven PostgreSQL URL ending in `?sslmode=require`. Local development defaults to `sqlite:///patrick.db`; production startup refuses SQLite. |
| `PORT` | No | Port for the Flask application. Defaults to `5000` |
| `FLASK_DEBUG` | No | Enables Flask debug mode only for local development; defaults to `false` and is ignored in production. |

## Vercel deployment

Patrick is one Vercel project with one public origin. The root `app.py` exports the Flask WSGI app as a Python Function; Vercel sends dynamic requests to Flask. The Next.js app is statically exported from `frontend/out` and copied to the root `public/` directory at build time, which Vercel serves as static files. Browser requests stay on the same origin: `/api/*`, `/auth/*`, `/verify-email`, and `/healthz` are Flask routes, while pages and `/_next/*` assets are static files. Session cookies remain `SameSite=Lax`, and the existing same-origin/CSRF check stays enabled.

Vercel's current Services feature is still private beta and requires access. This project uses the documented single-Flask-Function approach, which works without that beta and supports Python streaming.

Configure the Vercel project:

| Setting | Value |
|---|---|
| Root Directory | Repository root (`.`) |
| Framework Preset | Flask |
| Install Command | `cd frontend && pnpm install --frozen-lockfile` |
| Build Command | `bash vercel-build.sh` |
| Function region | `bom1` (Mumbai) |
| Fluid Compute | Enabled; `vercel.json` configures it |
| Function duration | 300 seconds, Vercel Hobby's current maximum with Fluid Compute |

Vercel's Hobby plan supports selecting one Function region; `bom1` is available. Static assets remain served at the edge. The project uses Vercel's Flask adapter and Python runtime, which Vercel documents as supporting streamed responses.

Set these variables in Vercel Project Settings → Environment Variables. Add secrets separately for Production and Preview as needed; do not commit them:

- Required: `FLASK_ENV=production`, `SECRET_KEY`, `GROQ_API_KEY`, `DATABASE_URL`, `PUBLIC_BASE_URL`.
- Optional Gemini: `GEMINI_API_KEY`; optionally `GEMINI_DEFAULT_MODEL` (defaults to `gemini-3.8-flash`). A missing or invalid Gemini key disables Gemini only.
- Optional Google sign-in: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`.
- Email verification: `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM`.
- Optional message cap: `DAILY_MESSAGE_LIMIT` (defaults to `100`).

Set `PUBLIC_BASE_URL` to `https://<your-vercel-domain>` and `GOOGLE_REDIRECT_URI` to `https://<your-vercel-domain>/auth/google/callback`. The latter must exactly match a Google Cloud Console **Authorized redirect URI**. Add `https://<your-vercel-domain>` as an authorized JavaScript origin. Use the production domain for production deployment; configure a separate callback if you enable Google OAuth in Preview.

Email/password sign-up requires working SMTP settings. Google sign-in remains available when configured.

### Prepare Aiven PostgreSQL

Set `DATABASE_URL` to the Aiven PostgreSQL connection URL with `sslmode=require`. The app converts `postgres://` and `postgresql://` URLs to the installed `psycopg` SQLAlchemy driver form. Vercel requests use SQLAlchemy `NullPool`, a 5-second connection timeout, and 15-second statement/5-second lock timeouts; transactions are short so the AI stream does not hold a database connection. Aiven's Free PostgreSQL plan has a server-enforced maximum of 20 connections and does not include a connection pooler. If concurrent traffic reaches that hard limit, extra connections will be refused; monitor Aiven's connection metrics.

Do not create or migrate the schema during Flask import or a Vercel Function invocation. Before the first deployment and after each schema migration, run this from the repository root on a machine with network access to Aiven and local development dependencies installed. Keep the Aiven URL in an uncommitted local `.env` file:

```bash
python -m pip install -r requirements-dev.txt
alembic upgrade head
```

The `alembic` command reads `DATABASE_URL` from `.env`. Confirm it points to the Aiven database before running the migration.

### Set up Google sign-in

1. Create a **Web application** OAuth client in Google Cloud Console and configure the OAuth consent screen.
2. For local testing, add `http://127.0.0.1:5000/auth/google/callback` as an authorized redirect URI. Leave `GOOGLE_REDIRECT_URI` unset locally so Flask uses that host automatically.
3. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in your local `.env` file.
4. For Vercel, add `https://<your-vercel-domain>/auth/google/callback` to the OAuth client's authorized redirect URIs. Set that exact URL as `GOOGLE_REDIRECT_URI` and add both Google credentials in Vercel's environment settings. Add `https://<your-vercel-domain>` as an authorized JavaScript origin.

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

To enable Gemini in production, create an API key in Google AI Studio and add it to Vercel as `GEMINI_API_KEY`. All users share the API credentials configured by the site owner, so availability, quotas, and billing follow those provider accounts. Users can only select models exposed by the configured keys.

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

Set `DATABASE_URL` to a PostgreSQL connection string for a hosted deployment. Before the first deployment and each schema change, run `alembic upgrade head` locally from the repository root with the Aiven URL in `.env`. Do not create schema at Python import time.

## 🔒 Security Notes

Before deploying Patrick publicly:

1. Keep API keys in environment variables.
2. Never commit `.env`.
3. Do not expose private conversation data.
4. Set a strong `SECRET_KEY` (required when `FLASK_ENV=production`).
5. Keep SMTP verification, persisted IP/user rate limits, and same-origin request checks enabled.
6. Use HTTPS in production.
7. Disable Flask debug mode in production.

For production:

```env
FLASK_ENV=production
FLASK_DEBUG=false
PUBLIC_BASE_URL=https://<your-vercel-domain>
```

## 🧪 Development

Run the application with:

```bash
python -m backend.app
```

The deployment server is Vercel's Python Function runtime. Use `/healthz` for a database readiness check. Run migrations before deploying code that requires a new schema revision.

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
