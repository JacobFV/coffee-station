import socket

from coffee_station.desktop import desktop_launch_config, find_available_port
from coffee_station.settings import Settings


def test_find_available_port_uses_preferred_when_free():
    port = find_available_port("127.0.0.1", 0)

    assert isinstance(port, int)
    assert port > 0


def test_desktop_launch_config_moves_off_busy_port(tmp_path):
    settings = Settings(data_dir=tmp_path, camera_indices="")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        busy_port = sock.getsockname()[1]

        launch = desktop_launch_config(settings, host="127.0.0.1", port=busy_port)

    assert launch.port != busy_port
    assert launch.url == f"http://127.0.0.1:{launch.port}"
