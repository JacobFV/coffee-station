from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class TrackedPoint:
    u: float
    v: float
    confidence: float


class MarkerlessMotionTracker:
    """Track a coherent motion region, preferring the FK-projected gripper."""

    def __init__(self) -> None:
        self.previous_gray: np.ndarray | None = None
        self.previous_point: TrackedPoint | None = None

    def reset(self) -> None:
        self.previous_gray = None
        self.previous_point = None

    def observe(self, jpeg: bytes, expected_uv: tuple[float, float] | None = None) -> TrackedPoint | None:
        array = np.frombuffer(jpeg, dtype=np.uint8)
        frame = cv2.imdecode(array, cv2.IMREAD_COLOR)
        if frame is None:
            return None
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if self.previous_gray is None:
            self.previous_gray = gray
            return None

        flow = cv2.calcOpticalFlowFarneback(
            self.previous_gray,
            gray,
            None,
            pyr_scale=0.5,
            levels=3,
            winsize=25,
            iterations=3,
            poly_n=5,
            poly_sigma=1.2,
            flags=0,
        )
        self.previous_gray = gray
        magnitude, _angle = cv2.cartToPolar(flow[..., 0], flow[..., 1])
        threshold = max(1.0, float(np.percentile(magnitude, 97.0)))
        mask = (magnitude >= threshold).astype("uint8")
        components, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
        if components <= 1:
            return self.previous_point

        best_index = 1
        best_score = float("-inf")
        diagonal = float(np.hypot(gray.shape[1], gray.shape[0]))
        for index in range(1, components):
            area = float(stats[index, cv2.CC_STAT_AREA])
            if area < 8:
                continue
            motion_score = area * float(np.mean(magnitude[labels == index]))
            if expected_uv is None:
                score = motion_score
            else:
                centroid = centroids[index]
                distance = float(np.hypot(centroid[0] - expected_uv[0], centroid[1] - expected_uv[1]))
                proximity = 1.0 - min(1.0, distance / max(diagonal * 0.35, 1.0))
                score = proximity * 1000000.0 + motion_score
            if score > best_score:
                best_score = score
                best_index = index

        if best_score <= 0:
            return self.previous_point
        centroid = centroids[best_index]
        frame_area = float(gray.shape[0] * gray.shape[1])
        confidence = min(1.0, max(0.05, best_score / max(frame_area * 4.0, 1.0)))
        point = TrackedPoint(u=float(centroid[0]), v=float(centroid[1]), confidence=confidence)
        self.previous_point = point
        return point
