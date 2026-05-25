from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from google import genai
from google.genai import types

from .camera import CameraManager
from .schemas import ChatMessage, SessionRecord
from .settings import Settings
from .skills import SkillLibrary
from .storage import Storage
from .tools import ToolRegistry

LOGGER = logging.getLogger(__name__)

SYSTEM_PROMPT = """You control a USB LeRobot follower arm through tools.
Use direct joint-pose tools only when a joint-space command is explicit.
Use world-space IK tools for object- or camera-grounded movement.
Prefer small, reversible movements, and schedule multi-step motion with bundle_tool_calls when timing matters.
A camera frame is normally included on each loop step according to camera feed settings.
Report concise observations and tool decisions. Never claim a movement happened unless a tool result confirms it.
You have high-level AgentSkills-style procedures. Use the skills index to decide what to activate, and follow activated skill instructions exactly.
"""


class AgentHarness:
    def __init__(self, settings: Settings, storage: Storage, cameras: CameraManager, tools: ToolRegistry,
                 skills: SkillLibrary | None = None) -> None:
        self.settings = settings
        self.storage = storage
        self.cameras = cameras
        self.tools = tools
        self.skills = skills or SkillLibrary()
        self.client = genai.Client(api_key=settings.gemini_api_key) if settings.gemini_api_key else None
        self.active_session_id: str | None = None
        self.task: asyncio.Task[None] | None = None
        self.stop_event = asyncio.Event()
        self.step_lock = threading.Lock()

    def create_session(self, title: str = "Untitled session") -> SessionRecord:
        session = self.storage.create_session(model=self.settings.gemini_model, title=title)
        for config in self.cameras.list_configs():
            self.storage.upsert_camera_config(session.id, config)
        self.storage.add_message(session.id, ChatMessage(role="system", content=SYSTEM_PROMPT))
        self.active_session_id = session.id
        return session

    def set_active_session(self, session_id: str) -> SessionRecord:
        session = self.storage.get_session(session_id)
        if session is None:
            raise ValueError(f"session not found: {session_id}")
        self.active_session_id = session.id
        configs = self.storage.list_camera_configs(session.id)
        for config in configs:
            self.cameras.configure(
                config.camera_id,
                enabled=config.enabled,
                auto_include=config.auto_include,
                frequency_hz=config.frequency_hz,
                label=config.label,
            )
        return session

    def add_user_message(self, session_id: str, content: str) -> ChatMessage:
        message = ChatMessage(role="user", content=content)
        return self.storage.add_message(session_id, message)

    def pause(self, session_id: str) -> None:
        self.storage.update_session_status(session_id, "paused")

    def resume(self, session_id: str) -> None:
        self.storage.update_session_status(session_id, "running")
        self.active_session_id = session_id

    def start_background_loop(self) -> None:
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._loop())

    async def shutdown(self) -> None:
        self.stop_event.set()
        if self.task is not None:
            await self.task

    async def _loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.tools.run_due_actions()
                if self.active_session_id:
                    session = self.storage.get_session(self.active_session_id)
                    if session and session.status == "running":
                        await asyncio.to_thread(self.step, session.id)
            except Exception:
                LOGGER.exception("agent loop step failed")
            await asyncio.sleep(self.settings.agent_step_interval_s)

    def step(self, session_id: str) -> None:
        if not self.step_lock.acquire(blocking=False):
            return
        try:
            self._step_locked(session_id)
        finally:
            self.step_lock.release()

    def _step_locked(self, session_id: str) -> None:
        if self.client is None:
            self.storage.add_message(
                session_id,
                ChatMessage(
                    role="agent",
                    content="GEMINI_API_KEY is not configured; autonomous model steps are disabled.",
                    metadata={"error": "missing_api_key"},
                ),
            )
            self.storage.update_session_status(session_id, "paused")
            return

        contents = self._build_contents(session_id)
        config = types.GenerateContentConfig(
            tools=[types.Tool(function_declarations=self.tools.declarations)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        text_parts: list[str] = []
        all_function_results: list[dict[str, Any]] = []
        for _round in range(max(1, self.settings.agent_max_tool_rounds)):
            response = self.client.models.generate_content(
                model=self.settings.gemini_model,
                contents=contents,
                config=config,
            )
            model_content = self._first_content(response)
            if model_content is None:
                break
            contents.append(model_content)
            function_response_parts: list[types.Part] = []
            for part in model_content.parts or []:
                if getattr(part, "text", None):
                    text_parts.append(part.text)
                call = getattr(part, "function_call", None)
                if not call:
                    continue
                args = dict(call.args or {})
                try:
                    result = self.tools.dispatch(session_id, call.name, args)
                except Exception as exc:
                    result = {"error": str(exc)}
                all_function_results.append({"name": call.name, "result": result})
                function_response_parts.append(types.Part.from_function_response(name=call.name, response=result))
                self.storage.add_message(
                    session_id,
                    ChatMessage(role="tool", content=f"{call.name}: {result}", metadata={"tool": call.name, "result": result}),
                )
            if not function_response_parts:
                break
            contents.append(types.Content(role="user", parts=function_response_parts))
        if text_parts or all_function_results:
            self.storage.add_message(
                session_id,
                ChatMessage(
                    role="agent",
                    content="\n".join(text_parts) if text_parts else "Tool calls executed.",
                    metadata={"function_results": all_function_results},
                ),
            )

    @staticmethod
    def _first_content(response: Any) -> types.Content | None:
        for candidate in response.candidates or []:
            if candidate.content:
                return candidate.content
        return None

    def _build_contents(self, session_id: str) -> list[types.Content]:
        messages = self.storage.list_messages(session_id, limit=50)
        contents: list[types.Content] = []
        conversation_text = "\n".join(f"{message.role}: {message.content}" for message in messages[-12:])
        active_skills = self.skills.activate_for_text(conversation_text)
        skill_index = "\n".join(skill.index_line() for skill in self.skills.list())
        skill_context = "Available skills:\n" + skill_index
        if active_skills:
            skill_context += "\n\nActivated skill instructions:\n" + "\n\n".join(skill.prompt_block() for skill in active_skills)
        contents.append(types.Content(role="user", parts=[types.Part(text=skill_context)]))
        for message in messages:
            if message.role == "system":
                contents.append(types.Content(role="user", parts=[types.Part(text=f"System instruction: {message.content}")]))
            elif message.role == "agent":
                contents.append(types.Content(role="model", parts=[types.Part(text=message.content)]))
            elif message.role in {"user", "tool"}:
                contents.append(types.Content(role="user", parts=[types.Part(text=f"{message.role}: {message.content}")]))

        frame_parts: list[types.Part] = []
        for frame in self.cameras.frames_for_agent_step():
            if self.tools.calibration is not None:
                try:
                    self.tools.calibration.observe_agent_frame(session_id, frame)
                except Exception:
                    LOGGER.exception("self-calibration online observation failed")
            frame_parts.append(types.Part(text=f"Camera {frame.camera_id} frame at {frame.timestamp:.3f}"))
            frame_parts.append(types.Part.from_bytes(data=frame.jpeg, mime_type="image/jpeg"))
        status = self.tools.get_robot_state(session_id)
        step_parts = [
            types.Part(text=f"Agent loop step. Robot state: {status}. Decide whether to call tools or wait.")
        ] + frame_parts
        contents.append(types.Content(role="user", parts=step_parts))
        return contents
