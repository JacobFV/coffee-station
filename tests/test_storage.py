import time

from coffee_station.schemas import ChatMessage, ScheduledAction
from coffee_station.storage import Storage


def test_storage_persists_sessions_messages_and_due_actions(tmp_path):
    storage = Storage(tmp_path / "sessions.sqlite3")
    session = storage.create_session(model="gemini-flash-latest", title="Test")

    storage.add_message(session.id, ChatMessage(role="user", content="hello"))
    messages = storage.list_messages(session.id)

    assert [message.content for message in messages] == ["hello"]

    action = ScheduledAction(
        session_id=session.id,
        tool_name="set_joint_pose",
        args={"joints": [0, 1, 2, 3, 4, 5]},
        due_at=time.time() - 1,
        created_at=time.time() - 2,
    )
    storage.save_action(action)

    due = storage.due_actions(time.time())
    assert [item.id for item in due] == [action.id]
