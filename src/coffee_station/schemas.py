from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def new_id() -> str:
    return uuid4().hex


class JointPose(BaseModel):
    joints: list[float] = Field(min_length=1, description="Joint positions in degrees, including gripper if present.")


class WorldPose(BaseModel):
    x: float
    y: float
    z: float
    roll: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0
    gripper: float | None = None


class ToolEnvelope(BaseModel):
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    offset_s: float = Field(default=0.0, ge=0.0)


class ScheduledAction(BaseModel):
    id: str = Field(default_factory=new_id)
    session_id: str
    tool_name: str
    args: dict[str, Any]
    due_at: float
    created_at: float
    status: Literal["queued", "running", "done", "failed", "canceled"] = "queued"
    result: dict[str, Any] | None = None
    error: str | None = None


class CameraConfig(BaseModel):
    camera_id: int
    enabled: bool = True
    auto_include: bool = True
    frequency_hz: float = Field(default=1.0, ge=0.0, le=30.0)
    label: str | None = None
    source_url: str | None = None
    serial_port: str | None = None
    kind: Literal["physical", "virtual"] = "physical"
    agent_visible: bool = True


class FrameInfo(BaseModel):
    camera_id: int
    timestamp: float
    width: int
    height: int
    jpeg_base64: str | None = None


class CalibrationPoint(BaseModel):
    id: str = Field(default_factory=new_id)
    session_id: str
    believed_x: float
    believed_y: float
    believed_z: float
    actual_x: float
    actual_y: float
    actual_z: float
    note: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ChatMessage(BaseModel):
    id: str = Field(default_factory=new_id)
    role: Literal["system", "user", "agent", "tool"]
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionRecord(BaseModel):
    id: str = Field(default_factory=new_id)
    title: str = "Untitled session"
    status: Literal["running", "paused", "stopped"] = "paused"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    model: str


class SessionSnapshot(BaseModel):
    session: SessionRecord
    messages: list[ChatMessage]
    camera_configs: list[CameraConfig]
    robot_state: dict[str, Any]
    queued_actions: list[ScheduledAction]
    recent_actions: list[ScheduledAction]
