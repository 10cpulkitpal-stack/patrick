"""Persistence helpers for chat and message data."""

from sqlalchemy import select

from models import Chat, Message


class ChatStore:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    def owned_chat(self, chat_id, user_id):
        with self.session_factory() as db:
            row = db.scalar(select(Chat).where(Chat.id == chat_id, Chat.user_id == user_id))
            return {"id": row.id, "title": row.title, "created_at": row.created_at} if row else None

    @staticmethod
    def make_title(first_message):
        title = first_message.strip().replace("\n", " ")
        return (title[:40] + "...") if len(title) > 40 else title

    def messages(self, chat_id):
        with self.session_factory() as db:
            rows = db.scalars(select(Message).where(Message.chat_id == chat_id)
                              .order_by(Message.created_at, Message.id)).all()
        messages = []
        for row in rows:
            message = {"role": row.role, "content": row.content}
            if row.attachment_type:
                attachment = {"kind": row.attachment_type,
                              "name": row.attachment_name or "attachment",
                              "truncated": bool(row.attachment_truncated)}
                if row.attachment_type == "image":
                    attachment["data_url"] = row.attachment_data
                message["attachment"] = attachment
            messages.append(message)
        return messages

    def model_history(self, chat_id):
        """Build bounded model context and retain the newest image attachments."""
        with self.session_factory() as db:
            rows = db.scalars(select(Message).where(Message.chat_id == chat_id)
                              .order_by(Message.created_at.desc(), Message.id.desc()).limit(16)).all()
        rows = list(reversed(rows))
        history = []
        remaining_chars = 32000
        image_indices = [i for i, row in enumerate(rows)
                         if row.role == "user" and row.attachment_type == "image"]
        keep_image_indices = set(image_indices[-3:])
        for index, row in enumerate(rows):
            role = row.role
            content = (row.content or "")[:8000]
            attachment_type = row.attachment_type
            if attachment_type == "text" and row.attachment_data:
                file_text = row.attachment_data[:6000]
                clipped_note = " (file was truncated to 6,000 characters)" if row.attachment_truncated else ""
                content = f"{content}\n\n[Attached text file: {row.attachment_name or 'file'}{clipped_note}]\n{file_text}".strip()
            content = content[:remaining_chars]
            remaining_chars -= len(content)
            if role == "user" and attachment_type == "image" and row.attachment_data and index in keep_image_indices:
                parts = [{"type": "text", "text": content or "Describe this image."},
                         {"type": "image_url", "image_url": {"url": row.attachment_data}}]
                history.append({"role": role, "content": parts})
            elif role == "user" and attachment_type == "image":
                history.append({"role": role, "content": (content + "\n[An older image attachment was omitted from the recent visual context.] ").strip()})
            elif role == "user" and attachment_type == "file":
                history.append({"role": role, "content": (content + f"\n[Attached file: {row.attachment_name}; file contents could not be read.] ").strip()})
            else:
                history.append({"role": role, "content": content})
            if remaining_chars <= 0:
                break
        return history
