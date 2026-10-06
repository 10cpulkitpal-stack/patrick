from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from chats import ChatStore
from models import Base, Chat, Message, User


def test_chat_store_scopes_chats_and_keeps_recent_message_history():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    store = ChatStore(session_factory)

    with session_factory.begin() as db:
        db.add(User(id="owner", email="owner@example.test", password_hash="unused",
                    created_at=1, auth_provider="password", email_verified=True))
        db.add(User(id="other", email="other@example.test", password_hash="unused",
                    created_at=1, auth_provider="password", email_verified=True))
        db.add(Chat(id="chat-1", user_id="owner", title="Test", created_at=1))
        db.add(Message(id="message-1", chat_id="chat-1", role="user", content="Hello", created_at=2))

    assert store.owned_chat("chat-1", "owner")["title"] == "Test"
    assert store.owned_chat("chat-1", "other") is None
    assert store.messages("chat-1") == [{"role": "user", "content": "Hello"}]
    assert store.model_history("chat-1") == [{"role": "user", "content": "Hello"}]
    engine.dispose()
