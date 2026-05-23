from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from importlib import resources
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agent import AgentHarness
from .camera import CameraManager
from .robot import build_robot
from .schemas import ChatMessage, SessionSnapshot
from .settings import Settings
from .storage import Storage
from .tools import ToolRegistry


class CreateSessionRequest(BaseModel):
    title: str = "Untitled session"


class UserMessageRequest(BaseModel):
    content: str


class SessionStatusRequest(BaseModel):
    status: str


class CameraConfigureRequest(BaseModel):
    camera_id: int
    enabled: bool | None = None
    auto_include: bool | None = None
    frequency_hz: float | None = None
    label: str | None = None


class ToolCallRequest(BaseModel):
    session_id: str
    tool_name: str
    args: dict[str, Any] = {}


class AppState:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.storage = Storage(settings.db_path)
        self.cameras = CameraManager(settings)
        self.robot = build_robot(settings)
        self.tools = ToolRegistry(self.robot, self.cameras, self.storage)
        self.agent = AgentHarness(settings, self.storage, self.cameras, self.tools)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    state = AppState(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        sessions = state.storage.list_sessions()
        if sessions:
            state.agent.set_active_session(sessions[0].id)
        else:
            state.agent.create_session("Default session")
        state.agent.start_background_loop()
        yield
        await state.agent.shutdown()
        state.cameras.shutdown()
        state.robot.disconnect()

    app = FastAPI(title="Coffee Station", lifespan=lifespan)
    app.state.core = state

    static_root = resources.files("coffee_station").joinpath("static")
    app.mount("/static", StaticFiles(directory=str(static_root)), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(static_root.joinpath("index.html"))

    @app.get("/api/sessions")
    def list_sessions() -> dict[str, Any]:
        return {
            "active_session_id": state.agent.active_session_id,
            "sessions": [session.model_dump() for session in state.storage.list_sessions()],
        }

    @app.post("/api/sessions")
    def create_session(request: CreateSessionRequest) -> dict[str, Any]:
        session = state.agent.create_session(request.title)
        return {"session": session.model_dump()}

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str) -> SessionSnapshot:
        session = state.storage.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        return SessionSnapshot(
            session=session,
            messages=state.storage.list_messages(session_id),
            camera_configs=state.storage.list_camera_configs(session_id) or state.cameras.list_configs(),
            robot_state=state.robot.state(),
            queued_actions=state.storage.queued_actions(session_id),
        )

    @app.post("/api/sessions/{session_id}/activate")
    def activate_session(session_id: str) -> dict[str, Any]:
        session = state.agent.set_active_session(session_id)
        return {"session": session.model_dump()}

    @app.post("/api/sessions/{session_id}/messages")
    def add_message(session_id: str, request: UserMessageRequest) -> dict[str, Any]:
        if not state.storage.get_session(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        message = state.agent.add_user_message(session_id, request.content)
        state.agent.resume(session_id)
        return {"message": message.model_dump()}

    @app.post("/api/sessions/{session_id}/status")
    def update_session_status(session_id: str, request: SessionStatusRequest) -> dict[str, Any]:
        if not state.storage.get_session(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        if request.status == "running":
            state.agent.resume(session_id)
        elif request.status in {"paused", "stopped"}:
            state.storage.update_session_status(session_id, request.status)
        else:
            raise HTTPException(status_code=400, detail="status must be running, paused, or stopped")
        return {"session": state.storage.get_session(session_id).model_dump()}

    @app.get("/api/cameras")
    def list_cameras() -> dict[str, Any]:
        return {"cameras": [camera.model_dump() for camera in state.cameras.list_configs()]}

    @app.post("/api/cameras/configure")
    def configure_camera(request: CameraConfigureRequest) -> dict[str, Any]:
        result = state.cameras.configure(
            request.camera_id,
            enabled=request.enabled,
            auto_include=request.auto_include,
            frequency_hz=request.frequency_hz,
            label=request.label,
        )
        if state.agent.active_session_id:
            config = next(c for c in state.cameras.list_configs() if c.camera_id == request.camera_id)
            state.storage.upsert_camera_config(state.agent.active_session_id, config)
        return result

    @app.get("/api/cameras/{camera_id}/frame")
    def camera_frame(camera_id: int) -> Response:
        jpeg = state.cameras.latest_jpeg(camera_id, refresh=True)
        if jpeg is None:
            return Response(status_code=204)
        return Response(content=jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.get("/api/cameras/{camera_id}/latest")
    def latest_frame(camera_id: int) -> dict[str, Any]:
        frame = state.cameras.latest_frame(camera_id, include_bytes=True, refresh=True)
        if frame is None:
            raise HTTPException(status_code=404, detail="frame unavailable")
        return {"frame": frame.model_dump()}

    @app.post("/api/tools/call")
    def call_tool(request: ToolCallRequest) -> dict[str, Any]:
        if not state.storage.get_session(request.session_id):
            raise HTTPException(status_code=404, detail="session not found")
        result = state.tools.dispatch(request.session_id, request.tool_name, dict(request.args))
        state.storage.add_message(
            request.session_id,
            ChatMessage(role="tool", content=f"{request.tool_name}: {result}", metadata={"manual": True, "result": result}),
        )
        return {"result": result}

    @app.post("/api/agent/step/{session_id}")
    async def manual_step(session_id: str) -> dict[str, Any]:
        if not state.storage.get_session(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        await asyncio.to_thread(state.agent.step, session_id)
        return {"ok": True}

    return app
