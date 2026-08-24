# Patrick — AI Chat Bot

Patrick is a modern, ChatGPT-style AI chatbot built with **Python Flask**, **JavaScript**, **HTML/CSS**, and the **Groq API**.

It provides persistent chat conversations, image understanding, voice input/output, light/dark themes, chat management, and a responsive interface for desktop and mobile browsers.

## ✨ Features

- 💬 **AI chat** powered by Groq
- 🧠 **Conversation history** stored locally in `chats.json`
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
- ⚡ Simple Flask backend with JSON-based local storage

## 🛠️ Tech Stack

| Technology | Purpose |
|---|---|
| Python | Backend programming |
| Flask | Web server and REST API |
| Groq API | AI model inference |
| HTML5 | Application structure |
| CSS3 | UI and responsive styling |
| JavaScript | Frontend interaction |
| JSON | Local conversation storage |
| python-dotenv | Environment variable management |
| Highlight.js | Code syntax highlighting |

## 📁 Project Structure

```text
patrick-chatbot/
│
├── app.py
├── requirements.txt
├── .env.example
├── .gitignore
├── chats.json
│
├── templates/
│   └── index.html
│
└── static/
    ├── script.js
    └── style.css
```

> `chats.json` is used for local conversation storage and should not be committed to a public repository if it contains personal conversations.

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

### 4. Configure the Groq API key

Create a `.env` file in the project root:

```env
GROQ_API_KEY=your-groq-api-key-here
```

You can use `.env.example` as a template.

**Never commit your `.env` file or expose your API key publicly.**

### 5. Run the application

```bash
python app.py
```

The Flask server will normally start at:

```text
http://127.0.0.1:5000
```

Open the address in your browser.

## 🔑 Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | Yes | API key used to access Groq models |
| `PORT` | No | Port for the Flask application. Defaults to `5000` |
| `FLASK_DEBUG` | No | Enables/disables Flask debug mode |

Example:

```env
GROQ_API_KEY=your-groq-api-key
PORT=5000
FLASK_DEBUG=true
```

## 🤖 AI Models

The application currently uses two model configurations in `app.py`:

### Text model

```python
MODEL = "openai/gpt-oss-120b"
```

This model handles normal text conversations.

### Vision model

```python
VISION_MODEL = "qwen/qwen3.6-27b"
```

This model is used when an image is attached to a message.

If Groq changes model availability, update these values in `app.py` to models available for your account.

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
Conversation saved to chats.json
```

## 🔌 API Endpoints

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

For simplicity, Patrick uses a local JSON file:

```text
chats.json
```

This makes the project easy to run without installing a database.

For a production application, consider replacing JSON storage with a database such as:

- PostgreSQL
- MySQL
- SQLite
- MongoDB

## 🔒 Security Notes

Before deploying Patrick publicly:

1. Keep API keys in environment variables.
2. Never commit `.env`.
3. Do not expose private conversation data.
4. Add authentication and authorization.
5. Add request rate limiting.
6. Validate uploaded files and enforce size limits.
7. Use HTTPS in production.
8. Replace the local JSON storage with a proper database for multi-user applications.
9. Disable Flask debug mode in production.

For production:

```env
FLASK_DEBUG=false
```

## 🧪 Development

Run the application with:

```bash
python app.py
```

The project is configured to use Flask's development server.

For production deployment, use a production WSGI server such as Gunicorn or another appropriate deployment platform.

## 📌 Future Improvements

Possible improvements include:

- [ ] User authentication
- [ ] PostgreSQL/MySQL database
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
- [ ] Automated tests

## 👨‍💻 Author

**Pulkit Pal**

B.Tech Student  
Shri Ramswaroop College of Engineering and Management

## 📄 License

This project is intended for learning and development purposes.

Add a license such as the MIT License if you want to explicitly define how others can use, modify, and distribute the project.
