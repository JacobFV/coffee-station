from coffee_station.hardware import diagnose_hardware, list_serial_ports
from coffee_station.settings import Settings


def test_hardware_diagnostics_shape(tmp_path):
    diagnostics = diagnose_hardware(Settings(data_dir=tmp_path, camera_indices=""))

    assert "serial_ports" in diagnostics
    assert "usb_serial_ports" in diagnostics
    assert "ready_for_lerobot" in diagnostics


def test_serial_ports_returns_list():
    assert isinstance(list_serial_ports(), list)
