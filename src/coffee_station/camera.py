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
        self.capture_lock = threading.Lock()
        self.frame_ready = threading.Condition(self.lock)
        self.capture_thread: threading.Thread | None = None
        self.stop_event = threading.Event()
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
            self.config.enabled = False
            cap.release()
            with self.lock:
                self.frame_ready.notify_all()
            return
        self.capture = cap
        self.open_error = None

    def close(self) -> None:
        self.stop_capture_loop()
        with self.capture_lock:
            if self.capture is not None:
                self.capture.release()
                self.capture = None

    def start_capture_loop(self) -> None:
        if not self.config.enabled:
            return
        if self.capture_thread is not None and self.capture_thread.is_alive():
            return
        self.stop_event.clear()
        self.capture_thread = threading.Thread(
            target=self._capture_loop,
            name=f"camera-{self.config.camera_id}-capture",
            daemon=True,
        )
        self.capture_thread.start()

    def stop_capture_loop(self) -> None:
        self.stop_event.set()
        if (
            self.capture_thread is not None
            and self.capture_thread.is_alive()
            and threading.current_thread() is not self.capture_thread
        ):
            self.capture_thread.join(timeout=2.0)
        self.capture_thread = None

    def _capture_loop(self) -> None:
        fps = max(1.0, float(self.settings.camera_fps))
        interval_s = 1.0 / fps
        while not self.stop_event.is_set() and self.config.enabled:
            started_at = time.time()
            self.read()
            elapsed = time.time() - started_at
            wait_s = max(0.0, interval_s - elapsed)
            if wait_s:
                self.stop_event.wait(wait_s)

    def read(self) -> CapturedFrame | None:
        if not self.config.enabled:
            return self.latest
        with self.capture_lock:
            self.open()
            if self.capture is None:
                return self.latest
            ok, frame = self.capture.read()
        if not ok:
            self.open_error = f"camera {self.config.camera_id} read failed"
            self.config.enabled = False
            with self.lock:
                self.frame_ready.notify_all()
            return self.latest
        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not ok:
            self.open_error = f"camera {self.config.camera_id} jpeg encode failed"
            self.config.enabled = False
            with self.lock:
                self.frame_ready.notify_all()
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
            self.frame_ready.notify_all()
        return captured

    def wait_for_frame(self, last_timestamp: float | None = None, timeout_s: float = 1.0) -> CapturedFrame | None:
        self.start_capture_loop()
        with self.lock:
            if self.latest is not None and (last_timestamp is None or self.latest.timestamp > last_timestamp):
                return self.latest
            self.frame_ready.wait(timeout=timeout_s)
            if self.latest is not None and (last_timestamp is None or self.latest.timestamp > last_timestamp):
                return self.latest
            return self.latest


class CameraManager:
    VIRTUAL_SO101_CAMERA_ID = -101

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

    def list_agent_configs(self) -> list[CameraConfig]:
        return [config for config in self.list_configs() if config.agent_visible]

    def display_status(self) -> list[dict[str, Any]]:
        return [
            *self.status(agent_visible_only=False),
            {
                "camera": CameraConfig(
                    camera_id=self.VIRTUAL_SO101_CAMERA_ID,
                    enabled=True,
                    auto_include=False,
                    frequency_hz=0.0,
                    label="Virtual SO-101 believed pose",
                    kind="virtual",
                    agent_visible=False,
                ).model_dump(),
                "open": True,
                "open_error": None,
                "latest_frame": None,
            },
        ]

    def discover(self) -> list[dict[str, Any]]:
        discovered: list[dict[str, Any]] = []
        max_index = max(self.settings.camera_discovery_max_index, max(self.devices.keys(), default=0))
        for camera_id in range(max_index + 1):
            cap = cv2.VideoCapture(camera_id)
            opened = cap.isOpened()
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) if opened else 0
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) if opened else 0
            cap.release()
            if opened and camera_id not in self.devices:
                self.devices[camera_id] = CameraDevice(CameraConfig(camera_id=camera_id, enabled=False), self.settings)
            discovered.append(
                {
                    "camera_id": camera_id,
                    "available": opened,
                    "configured": camera_id in self.devices,
                    "width": width,
                    "height": height,
                }
            )
        return discovered

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
                else:
                    device.open_error = None
                    device.start_capture_loop()
            if auto_include is not None:
                device.config.auto_include = auto_include
            if frequency_hz is not None:
                device.config.frequency_hz = frequency_hz
            if label is not None:
                device.config.label = label
            return {"camera": device.config.model_dump(), "open_error": device.open_error}

    def status(self, agent_visible_only: bool = True) -> list[dict[str, Any]]:
        statuses: list[dict[str, Any]] = []
        for device in self.devices.values():
            if agent_visible_only and not device.config.agent_visible:
                continue
            latest = device.latest.info(include_bytes=False).model_dump() if device.latest else None
            statuses.append(
                {
                    "camera": device.config.model_dump(),
                    "open": device.capture is not None,
                    "open_error": device.open_error,
                    "latest_frame": latest,
                }
            )
        return statuses

    def latest_frame(self, camera_id: int, include_bytes: bool = True, refresh: bool = True) -> FrameInfo | None:
        device = self.devices.get(camera_id)
        if device is None or not device.config.agent_visible:
            return None
        frame = device.read() if refresh else device.latest
        if frame is None:
            return None
        return frame.info(include_bytes=include_bytes)

    def latest_jpeg(self, camera_id: int, refresh: bool = True) -> bytes | None:
        device = self.devices.get(camera_id)
        if device is None or not device.config.agent_visible:
            return None
        frame = device.read() if refresh else device.latest
        return None if frame is None else frame.jpeg

    def raw_frame(self, camera_id: int, refresh: bool = True) -> CapturedFrame | None:
        device = self.devices.get(camera_id)
        if device is None or not device.config.agent_visible:
            return None
        return device.read() if refresh else device.latest

    def stream_frames(self, camera_id: int, max_fps: float | None = None):
        device = self.devices.get(camera_id)
        if device is None:
            return
        target_fps = max(1.0, min(float(max_fps or self.settings.camera_fps), float(self.settings.camera_fps)))
        min_interval_s = 1.0 / target_fps
        last_sent_at = 0.0
        last_timestamp: float | None = None
        while device.config.enabled:
            frame = device.wait_for_frame(last_timestamp=last_timestamp, timeout_s=1.0)
            if frame is None:
                frame = device.read()
            if frame is None:
                time.sleep(0.1)
                continue
            now = time.time()
            if now - last_sent_at < min_interval_s:
                time.sleep(min_interval_s - (now - last_sent_at))
            last_timestamp = frame.timestamp
            last_sent_at = time.time()
            yield frame

    def frames_for_agent_step(self) -> list[CapturedFrame]:
        now = time.time()
        frames: list[CapturedFrame] = []
        for camera_id, device in self.devices.items():
            config = device.config
            if not config.enabled or not config.auto_include or not config.agent_visible:
                continue
            frequency = config.frequency_hz
            if frequency <= 0:
                continue
            interval = 1.0 / frequency
            last = self.last_auto_sent.get(camera_id, 0.0)
            if now - last < interval:
                continue
            frame = device.latest if device.capture_thread and device.capture_thread.is_alive() else device.read()
            if frame is not None:
                frames.append(frame)
                self.last_auto_sent[camera_id] = now
        return frames

    def shutdown(self) -> None:
        for device in self.devices.values():
            device.close()
