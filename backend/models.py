"""SQLAlchemy ORM models for the application database."""

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120))
    auth_provider: Mapped[str] = mapped_column(String(20), nullable=False, default="password", server_default="password")
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    preferred_provider: Mapped[str | None] = mapped_column(String(20))
    preferred_model: Mapped[str | None] = mapped_column(String(160))

    chats: Mapped[list["Chat"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    verification_tokens: Mapped[list["EmailVerificationToken"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Chat(Base):
    __tablename__ = "chats"
    __table_args__ = (Index("ix_chats_user_id", "user_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)

    user: Mapped[User] = relationship(back_populates="chats")
    messages: Mapped[list["Message"]] = relationship(back_populates="chat", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_chat_created_at", "chat_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chat_id: Mapped[str] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    attachment_type: Mapped[str | None] = mapped_column(String(20))
    attachment_name: Mapped[str | None] = mapped_column(String(255))
    attachment_data: Mapped[str | None] = mapped_column(Text)
    attachment_truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    chat: Mapped[Chat] = relationship(back_populates="messages")


class EmailVerificationToken(Base):
    __tablename__ = "email_verification_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    expires_at: Mapped[float] = mapped_column(Float, nullable=False)

    user: Mapped[User] = relationship(back_populates="verification_tokens")


class RateLimitCounter(Base):
    __tablename__ = "rate_limit_counters"

    bucket_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_id: Mapped[int] = mapped_column(Integer, nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[float] = mapped_column(Float, nullable=False, index=True)
