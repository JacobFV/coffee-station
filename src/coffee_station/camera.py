from __future__ import annotations

import base64
import threading
import time
from dataclasses import dataclass
from typing import Any

import cv2

from .schemas import CameraConfig, FrameInfo
from .settings import Settings


@dataclass
class CapturedFrame:
    camera_id: int
    timestamp: float
    width: int
    height: int
    jpeg: bytes

    def info(self, include_bytes: bool = False) -> FrameInfo:
        return FrameInfo(
            camera_id=self.camera_id,
            timestamp=self.timestamp,
            width=self.width,
            height=self.height,
            jpeg_base64=base64.b64encode(self.jpeg).decode("ascii") if include_bytes else None,
        )


class CameraDevice:
    def __init__(self, config: CameraConfig, settings: Settings) -> None:
        self.config = config
        self.settings = settings
        self.capture: cv2.VideoCapture | None = None
        self.latest: CapturedFrame | None = None
        self.lock = threading.Lock()
        self.open_error: str | None = None

    def open(self) -> None:
        if self.capture is not None:
            return
        cap = cv2.VideoCapture(self.config.camera_id)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.settings.camera_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.settings.camera_height)
        cap.set(cv2.CAP_PROP_FPS, self.settings.camera_fps)
        if not cap.isOpened():
            self.open_error = f"camera {self.config.camera_id} could not be opened"
            cap.release()
            return
        self.capture = cap
        self.open_error = None

    def close(self) -> None:
        if self.capture is not None:
            self.capture.release()
            self.capture = None

    def read(self) -> CapturedFrame | None:
        if not self.config.enabled:
            return self.latest
        self.open()
        if self.capture is None:
            return self.latest
        ok, frame = self.capture.read()
        if not ok:
            self.open_error = f"camera {self.config.camera_id} read failed"
            return self.latest
        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not ok:
            self.open_error = f"camera {self.config.camera_id} jpeg encode failed"
            return self.latest
        height, width = frame.shape[:2]
        captured = CapturedFrame(
            camera_id=self.config.camera_id,
            timestamp=time.time(),
            width=width,
            height=height,
            jpeg=encoded.tobytes(),
        )
        with self.lock:
            self.latest = captured
        return captured


class CameraManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.devices: dict[int, CameraDevice] = {
            camera_id: CameraDevice(CameraConfig(camera_id=camera_id), settings)
            for camera_id in settings.parsed_camera_indices()
        }
        self.last_auto_sent: dict[int, float] = {}
        self.lock = threading.Lock()

    def list_configs(self) -> list[CameraConfig]:
        return [device.config for device in self.devices.values()]

    def configure(self, camera_id: int, enabled: bool | None = None, auto_include: bool | None = None,
                  frequency_hz: float | None = None, label: str | None = None) -> dict[str, Any]:
        with self.lock:
            device = self.devices.get(camera_id)
            if device is None:
                device = CameraDevice(CameraConfig(camera_id=camera_id), self.settings)
                self.devices[camera_id] = device
            if enabled is not None:
                device.config.enabled = enabled
                if not enabled:
                    device.close()
            if auto_include is not None:
                device.config.auto_include = auto_include
            if frequency_hz is not None:
                device.config.frequency_hz = frequency_hz
            if label is not None:
                device.config.label = label
            return {"camera": device.config.model_dump(), "open_error": device.open_error}

    def latest_frame(self, camera_id: int, include_bytes: bool = True, refresh: bool = True) -> FrameInfo | None:
        device = self.devices.get(camera_id)
        if device is None:
            return None
        frame = device.read() if refresh else device.latest
        if frame is None:
            return None
        return frame.info(include_bytes=include_bytes)

    def latest_jpeg(self, camera_id: int, refresh: bool = True) -> bytes | None:
        device = self.devices.get(camera_id)
        if device is None:
            return None
        frame = device.read() if refresh else device.latest
        return None if frame is None else frame.jpeg

    def frames_for_agent_step(self) -> list[CapturedFrame]:
        now = time.time()
        frames: list[CapturedFrame] = []
        for camera_id, device in self.devices.items():
            config = device.config
            if not config.enabled or not config.auto_include:
                continue
            frequency = config.frequency_hz
            if frequency <= 0:
                continue
            interval = 1.0 / frequency
            last = self.last_auto_sent.get(camera_id, 0.0)
            if now - last < interval:
                continue
            frame = device.read()
            if frame is not None:
                frames.append(frame)
                self.last_auto_sent[camera_id] = now
        return frames

    def shutdown(self) -> None:
        for device in self.devices.values():
            device.close()
