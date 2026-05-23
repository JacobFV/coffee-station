from __future__ import annotations

import platform
import subprocess
from typing import Any

from .settings import Settings


def list_serial_ports() -> list[dict[str, Any]]:
    try:
        from serial.tools import list_ports
    except Exception as exc:
        return [{"error": f"pyserial unavailable: {exc}"}]
    ports: list[dict[str, Any]] = []
    for port in list_ports.comports():
        ports.append(
            {
                "device": port.device,
                "name": port.name,
                "description": port.description,
                "hwid": port.hwid,
                "vid": port.vid,
                "pid": port.pid,
                "serial_number": port.serial_number,
                "manufacturer": port.manufacturer,
                "product": port.product,
            }
        )
    return ports


def usb_summary() -> dict[str, Any]:
    if platform.system() != "Darwin":
        return {"platform": platform.system(), "summary": "USB summary is only implemented for macOS."}
    try:
        result = subprocess.run(
            ["system_profiler", "SPUSBDataType", "-json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:
        return {"platform": "Darwin", "error": str(exc)}
    return {
        "platform": "Darwin",
        "returncode": result.returncode,
        "has_output": bool(result.stdout.strip()),
        "raw_excerpt": result.stdout[:2000],
        "stderr": result.stderr[:1000],
    }


def diagnose_hardware(settings: Settings) -> dict[str, Any]:
    ports = list_serial_ports()
    usb = usb_summary()
    usb_serial_ports = [
        port for port in ports
        if isinstance(port.get("device"), str)
        and ("/cu.usb" in port["device"] or "/tty.usb" in port["device"] or "usb" in (port.get("description") or "").lower())
    ]
    return {
        "robot_backend": settings.robot_backend,
        "configured_lerobot_port": settings.lerobot_port,
        "serial_ports": ports,
        "usb_serial_ports": usb_serial_ports,
        "usb_summary": usb,
        "ready_for_lerobot": bool(settings.lerobot_port and any(port["device"] == settings.lerobot_port for port in ports)),
        "guidance": (
            "Set ROBOT_BACKEND=lerobot and LEROBOT_PORT to a visible /dev/cu.usb* device."
            if not usb_serial_ports
            else "Use one visible usb serial port as LEROBOT_PORT, then restart."
        ),
    }
