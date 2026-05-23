from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-flash-latest", alias="GEMINI_MODEL")
    agent_step_interval_s: float = Field(default=1.0, alias="AGENT_STEP_INTERVAL_S")
    agent_max_tool_rounds: int = Field(default=2, alias="AGENT_MAX_TOOL_ROUNDS")

    robot_backend: Literal["sim", "lerobot"] = Field(default="sim", alias="ROBOT_BACKEND")
    lerobot_port: str | None = Field(default=None, alias="LEROBOT_PORT")
    lerobot_id: str = Field(default="coffee_station_arm", alias="LEROBOT_ID")
    lerobot_type: str = Field(default="so100_follower", alias="LEROBOT_TYPE")
    lerobot_action_keys: str | None = Field(default=None, alias="LEROBOT_ACTION_KEYS")
    robot_joint_limits_json: str | None = Field(default=None, alias="ROBOT_JOINT_LIMITS_JSON")
    robot_min_command_interval_s: float = Field(default=0.05, alias="ROBOT_MIN_COMMAND_INTERVAL_S")

    camera_indices: str = Field(default="0", alias="CAMERA_INDICES")
    camera_discovery_max_index: int = Field(default=6, alias="CAMERA_DISCOVERY_MAX_INDEX")
    camera_width: int = Field(default=1280, alias="CAMERA_WIDTH")
    camera_height: int = Field(default=720, alias="CAMERA_HEIGHT")
    camera_fps: int = Field(default=30, alias="CAMERA_FPS")

    data_dir: Path = Field(default=Path.home() / ".coffee-station", alias="COFFEE_STATION_DATA_DIR")
    host: str = Field(default="127.0.0.1", alias="HOST")
    port: int = Field(default=8765, alias="PORT")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "sessions.sqlite3"

    def parsed_camera_indices(self) -> list[int]:
        indices: list[int] = []
        for part in self.camera_indices.split(","):
            part = part.strip()
            if not part:
                continue
            indices.append(int(part))
        return indices or [0]
