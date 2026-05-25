from fastapi.testclient import TestClient

from coffee_station.server import create_app
from coffee_station.settings import Settings


def test_session_api_lifecycle(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, camera_indices=""))

    with TestClient(app) as client:
        sessions = client.get("/api/sessions").json()
        assert sessions["active_session_id"]

        created = client.post("/api/sessions", json={"title": "API test"}).json()
        session_id = created["session"]["id"]

        message = client.post(f"/api/sessions/{session_id}/messages", json={"content": "watch the cup"}).json()
        assert message["message"]["content"] == "watch the cup"

        paused = client.post(f"/api/sessions/{session_id}/status", json={"status": "paused"}).json()
        assert paused["session"]["status"] == "paused"

        cameras = client.get("/api/cameras").json()
        assert "camera" in cameras["cameras"][0]
        assert any(item["camera"]["kind"] == "virtual" and item["camera"]["agent_visible"] is False for item in cameras["cameras"])
        assert client.get("/api/cameras/999/stream").status_code == 404
        assert client.post("/api/cameras/configure", json={"camera_id": -101, "enabled": True}).status_code == 400

        actions = client.get(f"/api/sessions/{session_id}/actions").json()
        assert actions["queued_actions"] == []

        skills = client.get("/api/skills").json()
        assert any(skill["name"] == "pose-table-6dof" for skill in skills["skills"])

        self_calibration = client.get("/api/self-calibration").json()
        assert self_calibration["enabled"] is False
        gated = client.post(f"/api/self-calibration/start/{session_id}").json()
        assert "SELF_CALIBRATION_ENABLED" in gated["detail"]

        hardware = client.get("/api/hardware/diagnostics").json()
        assert "serial_ports" in hardware
        scan = client.get("/api/hardware/feetech-scan", params={"port": "/dev/does-not-exist"}).json()
        assert scan["ok"] is False
