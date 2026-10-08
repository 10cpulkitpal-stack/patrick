import os
import uuid

os.environ["PYTHON_DOTENV_DISABLED"] = "true"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["GROQ_API_KEY"] = "test-groq-key"
os.environ.pop("GEMINI_API_KEY", None)
os.environ["DATABASE_URL"] = "sqlite://"

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import app as backend_app
from backend.chats import ChatStore
from backend.models import Base, Chat, Message, User


@pytest.fixture
def message_client(monkeypatch):
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(test_engine)
    event.listen(test_engine, "before_cursor_execute", backend_app.count_message_database_queries)
    session_factory = sessionmaker(bind=test_engine, expire_on_commit=False)
    monkeypatch.setattr(backend_app, "SessionLocal", session_factory)
    monkeypatch.setattr(backend_app, "chat_store", ChatStore(session_factory))

    user_id = str(uuid.uuid4())
    chat_id = str(uuid.uuid4())
    with session_factory.begin() as db:
        db.add(User(
            id=user_id,
            email=f"{user_id}@example.test",
            password_hash="unused",
            created_at=1,
            display_name="Test user",
            auth_provider="password",
            email_verified=True,
            preferred_provider="groq",
            preferred_model="test-model",
        ))
        db.add(Chat(id=chat_id, user_id=user_id, title="New Chat", created_at=1))

    backend_app.app.config.update(TESTING=True)
    client = backend_app.app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = user_id
    yield client, chat_id, user_id, session_factory
    test_engine.dispose()


def test_message_streams_tokens_saves_reply_and_uses_saved_model(message_client, monkeypatch, caplog):
    client, chat_id, _user_id, session_factory = message_client
    session_creations = []
    def counted_session_factory(*args, **kwargs):
        session_creations.append(True)
        return session_factory(*args, **kwargs)
    monkeypatch.setattr(backend_app, "SessionLocal", counted_session_factory)
    caplog.set_level("INFO", logger="backend.app")
    selected = {}

    def fake_stream(messages, **kwargs):
        selected.update(kwargs)
        yield "First "
        yield "reply."

    monkeypatch.setattr(backend_app.ai_service, "generate_reply_stream", fake_stream)
    monkeypatch.setattr(
        backend_app,
        "available_models",
        lambda: pytest.fail("model discovery must stay off the send-message path"),
    )

    response = client.post(
        f"/api/chats/{chat_id}/message",
        json={"message": "Hello"},
        headers={"Origin": "http://localhost"},
        buffered=False,
    )
    chunks = list(response.response)
    body = b"".join(chunks)

    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"
    assert response.headers["X-Accel-Buffering"] == "no"
    assert "no-transform" in response.headers["Cache-Control"]
    assert chunks[0] == b": stream-open\n\n"
    assert chunks[1].startswith(b"event: token")
    assert chunks[2].startswith(b"event: token")
    assert body.count(b"event: token") == 2
    assert b'"text": "First "' in body
    assert b'"text": "reply."' in body
    assert b"event: done" in body
    assert selected["provider"] == "groq"
    assert selected["selected_model"] == "test-model"
    assert len(session_creations) == 1
    for stage in ("auth_user_read", "rate_limit_ip", "chat_and_preference_read",
                  "rate_limit_user", "daily_message_count", "user_message_write",
                  "history_read", "model_selection", "available_models_skipped",
                  "groq_first_token", "groq_call",
                  "assistant_message_write", "total"):
        assert f"stage={stage} duration_ms=" in caplog.text
    assert "db_queries=" in caplog.text
    assert "Hello" not in caplog.text
    with session_factory() as db:
        messages = db.scalars(select(Message).where(Message.chat_id == chat_id)).all()
    assert [(message.role, message.content) for message in messages] == [
        ("user", "Hello"),
        ("assistant", "First reply."),
    ]


def test_message_stream_reports_provider_failure_without_saving_partial_reply(message_client, monkeypatch):
    client, chat_id, _user_id, session_factory = message_client

    def failing_stream(messages, **kwargs):
        yield "partial"
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(backend_app.ai_service, "generate_reply_stream", failing_stream)
    response = client.post(
        f"/api/chats/{chat_id}/message",
        json={"message": "Hello"},
        headers={"Origin": "http://localhost"},
        buffered=False,
    )
    body = b"".join(response.response)

    assert response.status_code == 200
    assert b"event: token" in body
    assert b"event: error" in body
    assert b"couldn't generate a reply" in body
    with session_factory() as db:
        messages = db.scalars(select(Message).where(Message.chat_id == chat_id)).all()
    assert [(message.role, message.content) for message in messages] == [("user", "Hello")]


def test_frontend_routes_and_signed_out_health(message_client):
    client, chat_id, _user_id, _session_factory = message_client
    with client.session_transaction() as session:
        session.clear()

    assert client.get("/").status_code == 200
    assert client.get("/signin").status_code == 200
    assert client.get("/signup").status_code == 200
    assert client.get("/healthz").status_code == 200
    assert client.get("/api/me").status_code == 401
    assert client.post(
        f"/api/chats/{chat_id}/message",
        json={"message": "Hello"},
        headers={"Origin": "https://untrusted.example"},
    ).status_code == 403


def test_vercel_client_ip_uses_edge_header_and_ignores_forwarded_for(monkeypatch):
    monkeypatch.setattr(backend_app, "is_vercel", True)
    with backend_app.app.test_request_context(
        "/", headers={
            "X-Vercel-Forwarded-For": "203.0.113.45",
            "X-Forwarded-For": "198.51.100.99",
        }, environ_base={"REMOTE_ADDR": "192.0.2.8"},
    ):
        assert backend_app.client_ip() == "203.0.113.45"

    with backend_app.app.test_request_context(
        "/", headers={"X-Vercel-Forwarded-For": "not-an-ip",
                       "X-Forwarded-For": "198.51.100.99"},
        environ_base={"REMOTE_ADDR": "192.0.2.8"},
    ):
        assert backend_app.client_ip() == "192.0.2.8"


def test_image_larger_than_vercel_safe_limit_is_rejected(message_client):
    import base64

    client, chat_id, _user_id, _session_factory = message_client
    image = base64.b64encode(b"x" * (backend_app.MAX_IMAGE_BYTES + 1)).decode("ascii")
    response = client.post(
        f"/api/chats/{chat_id}/message",
        json={"message": "Describe this", "image": f"data:image/png;base64,{image}"},
        headers={"Origin": "http://localhost"},
    )
    assert response.status_code == 413
    assert "2.5 MB" in response.json["error"]
