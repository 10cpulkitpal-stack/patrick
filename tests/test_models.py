from backend.models import Base, Chat, Message


def test_chat_and_message_indexes_are_declared():
    chat_indexes = {index.name: tuple(column.name for column in index.columns)
                    for index in Chat.__table__.indexes}
    message_indexes = {index.name: tuple(column.name for column in index.columns)
                       for index in Message.__table__.indexes}

    assert chat_indexes["ix_chats_user_id"] == ("user_id",)
    assert message_indexes["ix_messages_chat_created_at"] == ("chat_id", "created_at")
    assert set(Base.metadata.tables) >= {"users", "chats", "messages"}
