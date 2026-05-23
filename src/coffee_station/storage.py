from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from .schemas import CalibrationPoint, CameraConfig, ChatMessage, ScheduledAction, SessionRecord


class Storage:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                create table if not exists sessions (
                    id text primary key,
                    title text not null,
                    status text not null,
                    created_at text not null,
                    updated_at text not null,
                    model text not null
                );
                create table if not exists messages (
                    id text primary key,
                    session_id text not null,
                    role text not null,
                    content text not null,
                    created_at text not null,
                    metadata text not null,
                    foreign key(session_id) references sessions(id)
                );
                create index if not exists idx_messages_session on messages(session_id, created_at);
                create table if not exists actions (
                    id text primary key,
                    session_id text not null,
                    tool_name text not null,
                    args text not null,
                    due_at real not null,
                    created_at real not null,
                    status text not null,
                    result text,
                    error text,
                    foreign key(session_id) references sessions(id)
                );
                create index if not exists idx_actions_due on actions(status, due_at);
                create table if not exists camera_configs (
                    session_id text not null,
                    camera_id integer not null,
                    enabled integer not null,
                    auto_include integer not null,
                    frequency_hz real not null,
                    label text,
                    primary key(session_id, camera_id),
                    foreign key(session_id) references sessions(id)
                );
                create table if not exists calibration_points (
                    id text primary key,
                    session_id text not null,
                    believed_x real not null,
                    believed_y real not null,
                    believed_z real not null,
                    actual_x real not null,
                    actual_y real not null,
                    actual_z real not null,
                    note text,
                    created_at text not null,
                    foreign key(session_id) references sessions(id)
                );
                create index if not exists idx_calibration_session on calibration_points(session_id, created_at);
                """
            )

    def create_session(self, model: str, title: str = "Untitled session") -> SessionRecord:
        session = SessionRecord(title=title, model=model)
        with self.connect() as conn:
            conn.execute(
                "insert into sessions(id, title, status, created_at, updated_at, model) values (?, ?, ?, ?, ?, ?)",
                (
                    session.id,
                    session.title,
                    session.status,
                    session.created_at.isoformat(),
                    session.updated_at.isoformat(),
                    session.model,
                ),
            )
        return session

    def list_sessions(self) -> list[SessionRecord]:
        with self.connect() as conn:
            rows = conn.execute("select * from sessions order by updated_at desc").fetchall()
        return [self._session_from_row(row) for row in rows]

    def get_session(self, session_id: str) -> SessionRecord | None:
        with self.connect() as conn:
            row = conn.execute("select * from sessions where id=?", (session_id,)).fetchone()
        return None if row is None else self._session_from_row(row)

    def update_session_status(self, session_id: str, status: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "update sessions set status=?, updated_at=? where id=?",
                (status, datetime.now(UTC).isoformat(), session_id),
            )

    def add_message(self, session_id: str, message: ChatMessage) -> ChatMessage:
        with self.connect() as conn:
            conn.execute(
                "insert into messages(id, session_id, role, content, created_at, metadata) values (?, ?, ?, ?, ?, ?)",
                (
                    message.id,
                    session_id,
                    message.role,
                    message.content,
                    message.created_at.isoformat(),
                    json.dumps(message.metadata),
                ),
            )
            conn.execute("update sessions set updated_at=? where id=?", (datetime.now(UTC).isoformat(), session_id))
        return message

    def list_messages(self, session_id: str, limit: int = 200) -> list[ChatMessage]:
        with self.connect() as conn:
            rows = conn.execute(
                "select * from messages where session_id=? order by created_at asc limit ?",
                (session_id, limit),
            ).fetchall()
        return [self._message_from_row(row) for row in rows]

    def upsert_camera_config(self, session_id: str, config: CameraConfig) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                insert into camera_configs(session_id, camera_id, enabled, auto_include, frequency_hz, label)
                values (?, ?, ?, ?, ?, ?)
                on conflict(session_id, camera_id) do update set
                    enabled=excluded.enabled,
                    auto_include=excluded.auto_include,
                    frequency_hz=excluded.frequency_hz,
                    label=excluded.label
                """,
                (
                    session_id,
                    config.camera_id,
                    int(config.enabled),
                    int(config.auto_include),
                    config.frequency_hz,
                    config.label,
                ),
            )

    def list_camera_configs(self, session_id: str) -> list[CameraConfig]:
        with self.connect() as conn:
            rows = conn.execute("select * from camera_configs where session_id=? order by camera_id", (session_id,)).fetchall()
        return [
            CameraConfig(
                camera_id=row["camera_id"],
                enabled=bool(row["enabled"]),
                auto_include=bool(row["auto_include"]),
                frequency_hz=row["frequency_hz"],
                label=row["label"],
            )
            for row in rows
        ]

    def save_action(self, action: ScheduledAction) -> ScheduledAction:
        with self.connect() as conn:
            conn.execute(
                """
                insert into actions(id, session_id, tool_name, args, due_at, created_at, status, result, error)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(id) do update set
                    status=excluded.status,
                    result=excluded.result,
                    error=excluded.error
                """,
                (
                    action.id,
                    action.session_id,
                    action.tool_name,
                    json.dumps(action.args),
                    action.due_at,
                    action.created_at,
                    action.status,
                    json.dumps(action.result) if action.result is not None else None,
                    action.error,
                ),
            )
        return action

    def update_action_status(
        self,
        action_id: str,
        status: str,
        result: dict | None = None,
        error: str | None = None,
    ) -> ScheduledAction | None:
        with self.connect() as conn:
            conn.execute(
                "update actions set status=?, result=?, error=? where id=?",
                (
                    status,
                    json.dumps(result) if result is not None else None,
                    error,
                    action_id,
                ),
            )
            row = conn.execute("select * from actions where id=?", (action_id,)).fetchone()
        return None if row is None else self._action_from_row(row)

    def cancel_action(self, action_id: str) -> ScheduledAction | None:
        with self.connect() as conn:
            conn.execute(
                "update actions set status='canceled', error='canceled by operator' where id=? and status in ('queued', 'running')",
                (action_id,),
            )
            row = conn.execute("select * from actions where id=?", (action_id,)).fetchone()
        return None if row is None else self._action_from_row(row)

    def cancel_queued_actions(self, session_id: str) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                "update actions set status='canceled', error='canceled by operator' where session_id=? and status='queued'",
                (session_id,),
            )
            return cursor.rowcount

    def due_actions(self, now: float) -> list[ScheduledAction]:
        with self.connect() as conn:
            rows = conn.execute(
                "select * from actions where status='queued' and due_at <= ? order by due_at asc",
                (now,),
            ).fetchall()
        return [self._action_from_row(row) for row in rows]

    def queued_actions(self, session_id: str) -> list[ScheduledAction]:
        with self.connect() as conn:
            rows = conn.execute(
                "select * from actions where session_id=? and status in ('queued', 'running') order by due_at asc",
                (session_id,),
            ).fetchall()
        return [self._action_from_row(row) for row in rows]

    def list_actions(self, session_id: str, limit: int = 100) -> list[ScheduledAction]:
        with self.connect() as conn:
            rows = conn.execute(
                "select * from actions where session_id=? order by created_at desc limit ?",
                (session_id, limit),
            ).fetchall()
        return [self._action_from_row(row) for row in rows]

    def add_calibration_point(self, point: CalibrationPoint) -> CalibrationPoint:
        with self.connect() as conn:
            conn.execute(
                """
                insert into calibration_points(
                    id, session_id, believed_x, believed_y, believed_z, actual_x, actual_y, actual_z, note, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    point.id,
                    point.session_id,
                    point.believed_x,
                    point.believed_y,
                    point.believed_z,
                    point.actual_x,
                    point.actual_y,
                    point.actual_z,
                    point.note,
                    point.created_at.isoformat(),
                ),
            )
        return point

    def list_calibration_points(self, session_id: str) -> list[CalibrationPoint]:
        with self.connect() as conn:
            rows = conn.execute(
                "select * from calibration_points where session_id=? order by created_at asc",
                (session_id,),
            ).fetchall()
        return [self._calibration_from_row(row) for row in rows]

    def clear_calibration_points(self, session_id: str) -> int:
        with self.connect() as conn:
            cursor = conn.execute("delete from calibration_points where session_id=?", (session_id,))
            return cursor.rowcount

    @staticmethod
    def _session_from_row(row: sqlite3.Row) -> SessionRecord:
        return SessionRecord(
            id=row["id"],
            title=row["title"],
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            model=row["model"],
        )

    @staticmethod
    def _message_from_row(row: sqlite3.Row) -> ChatMessage:
        return ChatMessage(
            id=row["id"],
            role=row["role"],
            content=row["content"],
            created_at=datetime.fromisoformat(row["created_at"]),
            metadata=json.loads(row["metadata"]),
        )

    @staticmethod
    def _action_from_row(row: sqlite3.Row) -> ScheduledAction:
        return ScheduledAction(
            id=row["id"],
            session_id=row["session_id"],
            tool_name=row["tool_name"],
            args=json.loads(row["args"]),
            due_at=row["due_at"],
            created_at=row["created_at"],
            status=row["status"],
            result=json.loads(row["result"]) if row["result"] else None,
            error=row["error"],
        )

    @staticmethod
    def _calibration_from_row(row: sqlite3.Row) -> CalibrationPoint:
        return CalibrationPoint(
            id=row["id"],
            session_id=row["session_id"],
            believed_x=row["believed_x"],
            believed_y=row["believed_y"],
            believed_z=row["believed_z"],
            actual_x=row["actual_x"],
            actual_y=row["actual_y"],
            actual_z=row["actual_z"],
            note=row["note"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
