from types import SimpleNamespace

from google.genai import types

from coffee_station.agent import AgentHarness
from coffee_station.camera import CameraManager
from coffee_station.robot import RobotController, SimRobot
from coffee_station.settings import Settings
from coffee_station.storage import Storage
from coffee_station.tools import ToolRegistry


class FakeModels:
    def __init__(self):
        self.requests = []

    def generate_content(self, model, contents, config):
        self.requests.append(contents)
        if len(self.requests) == 1:
            content = types.Content(
                role="model",
                parts=[types.Part.from_function_call(name="get_robot_state", args={})],
            )
        else:
            assert any(
                getattr(part, "function_response", None)
                for content_item in contents
                for part in (content_item.parts or [])
            )
            content = types.Content(role="model", parts=[types.Part(text="state observed")])
        return SimpleNamespace(candidates=[SimpleNamespace(content=content)])


class FakeClient:
    def __init__(self):
        self.models = FakeModels()


def test_agent_continues_after_tool_response(tmp_path):
    settings = Settings(data_dir=tmp_path, camera_indices="", gemini_api_key="test", agent_max_tool_rounds=2)
    storage = Storage(tmp_path / "sessions.sqlite3")
    robot = RobotController(SimRobot())
    robot.connect()
    cameras = CameraManager(settings)
    tools = ToolRegistry(robot, cameras, storage)
    agent = AgentHarness(settings, storage, cameras, tools)
    agent.client = FakeClient()
    session = agent.create_session("agent")

    agent.step(session.id)

    messages = storage.list_messages(session.id)
    assert any(message.role == "tool" and "get_robot_state" in message.content for message in messages)
    assert messages[-1].role == "agent"
    assert messages[-1].content == "state observed"
