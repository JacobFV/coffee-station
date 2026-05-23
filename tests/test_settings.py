from coffee_station.settings import Settings


def test_settings_accept_field_name_overrides(tmp_path):
    settings = Settings(data_dir=tmp_path, camera_indices="", robot_backend="lerobot", lerobot_port="/dev/test")

    assert settings.data_dir == tmp_path
    assert settings.parsed_camera_indices() == [0]
    assert settings.robot_backend == "lerobot"
    assert settings.lerobot_port == "/dev/test"
