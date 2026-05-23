import socket

from coffee_station.desktop import find_available_port, renderer_bridge_config
from coffee_station.settings import Settings


def test_find_available_port_uses_preferred_when_free():
    port = find_available_port("127.0.0.1", 0)

    assert isinstance(port, int)
    assert port > 0


def test_renderer_bridge_binds_to_loopback(tmp_path):
    settings = Settings(data_dir=tmp_path, camera_indices="")

    bridge = renderer_bridge_config(settings)

    assert bridge.host == "127.0.0.1"
    assert bridge.port > 0
    assert bridge.loopback_url == f"http://127.0.0.1:{bridge.port}"


def test_renderer_bridge_picks_free_port(tmp_path):
    settings = Settings(data_dir=tmp_path, camera_indices="")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        busy_port = sock.getsockname()[1]

        bridge = renderer_bridge_config(settings)

    assert bridge.port != busy_port
