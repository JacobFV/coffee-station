from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from importlib import resources
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .calibration.solver import CalibrationSolverError
from .calibration.service import SelfCalibrationService
from .agent import AgentHarness
from .camera import CameraManager
from .hardware import diagnose_hardware, scan_feetech_motors
from .robot import build_robot
from .schemas import ChatMessage, SessionSnapshot
from .settings import Settings
from .skills import SkillLibrary
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
    args: dict[str, Any] = Field(default_factory=dict)


class AppState:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.storage = Storage(settings.db_path)
        self.cameras = CameraManager(settings)
        self.robot = build_robot(settings, self.storage.get_arm_calibration(settings.lerobot_id if settings.robot_backend == "lerobot" else "sim"))
        self.skills = SkillLibrary()
        self.self_calibration = SelfCalibrationService(settings, self.storage, self.robot, self.cameras)
        self.tools = ToolRegistry(
            self.robot,
            self.cameras,
            self.storage,
            self.settings,
            self.skills,
            self.self_calibration,
        )
        self.agent = AgentHarness(settings, self.storage, self.cameras, self.tools, self.skills)


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
            recent_actions=state.storage.list_actions(session_id, limit=50),
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
        return {"cameras": state.cameras.status()}

    @app.post("/api/cameras/discover")
    def discover_cameras() -> dict[str, Any]:
        discovered = state.cameras.discover()
        if state.agent.active_session_id:
            for config in state.cameras.list_configs():
                state.storage.upsert_camera_config(state.agent.active_session_id, config)
        return {"discovered": discovered, "cameras": state.cameras.status()}

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

    @app.get("/api/cameras/{camera_id}/stream")
    def camera_stream(camera_id: int, fps: float | None = None) -> StreamingResponse:
        if camera_id not in state.cameras.devices:
            raise HTTPException(status_code=404, detail="camera not configured")

        def generate():
            for frame in state.cameras.stream_frames(camera_id, max_fps=fps):
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    + f"X-Camera-Timestamp: {frame.timestamp:.6f}\r\n".encode("ascii")
                    + f"Content-Length: {len(frame.jpeg)}\r\n\r\n".encode("ascii")
                    + frame.jpeg
                    + b"\r\n"
                )

        return StreamingResponse(
            generate(),
            media_type="multipart/x-mixed-replace; boundary=frame",
            headers={"Cache-Control": "no-store"},
        )

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

    @app.get("/api/skills")
    def list_skills() -> dict[str, Any]:
        return {"skills": [{"name": skill.name, "description": skill.description} for skill in state.skills.list()]}

    @app.get("/api/skills/{name}")
    def get_skill(name: str) -> dict[str, Any]:
        skill = state.skills.get(name)
        if skill is None:
            raise HTTPException(status_code=404, detail="skill not found")
        return {"skill": {"name": skill.name, "description": skill.description, "instructions": skill.body.strip()}}

    @app.get("/api/self-calibration")
    def get_self_calibration(camera_id: int = 0) -> dict[str, Any]:
        return state.self_calibration.status(camera_id)

    @app.post("/api/self-calibration/start/{session_id}")
    def start_self_calibration(session_id: str, camera_id: int = 0, duration_s: float = 0.35) -> dict[str, Any]:
        if not state.storage.get_session(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        try:
            result = state.self_calibration.start_markerless_calibration(session_id, camera_id, duration_s)
        except CalibrationSolverError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"result": result.model_dump()}

    @app.post("/api/self-calibration/fit/{session_id}")
    def fit_self_calibration(session_id: str, camera_id: int = 0) -> dict[str, Any]:
        if not state.storage.get_session(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        try:
            result = state.self_calibration.fit_from_session_samples(session_id, camera_id)
        except CalibrationSolverError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"result": result.model_dump()}

    @app.get("/api/sessions/{session_id}/actions")
    def list_actions(session_id: str) -> dict[str, Any]:
        if not state.storage.get_session(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        return {
            "queued_actions": [action.model_dump() for action in state.storage.queued_actions(session_id)],
            "recent_actions": [action.model_dump() for action in state.storage.list_actions(session_id, limit=100)],
        }

    @app.post("/api/sessions/{session_id}/actions/{action_id}/cancel")
    def cancel_action(session_id: str, action_id: str) -> dict[str, Any]:
        if not state.storage.get_session(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        action = state.storage.cancel_action(action_id)
        if action is None:
            raise HTTPException(status_code=404, detail="action not found")
        return {"action": action.model_dump()}

    @app.post("/api/sessions/{session_id}/actions/cancel-queued")
    def cancel_queued_actions(session_id: str) -> dict[str, Any]:
        if not state.storage.get_session(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        return {"canceled": state.storage.cancel_queued_actions(session_id)}

    @app.post("/api/robot/stop/{session_id}")
    def stop_robot(session_id: str) -> dict[str, Any]:
        if not state.storage.get_session(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        return state.tools.stop_robot(session_id)

    @app.get("/api/hardware/diagnostics")
    def hardware_diagnostics() -> dict[str, Any]:
        return diagnose_hardware(state.settings)

    @app.get("/api/hardware/feetech-scan")
    def hardware_feetech_scan(port: str) -> dict[str, Any]:
        return scan_feetech_motors(port)

    @app.post("/api/agent/step/{session_id}")
    async def manual_step(session_id: str) -> dict[str, Any]:
        if not state.storage.get_session(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        await asyncio.to_thread(state.agent.step, session_id)
        return {"ok": True}

    return app
