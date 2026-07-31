"""Deterministic gesture recognition from a normalized 21-point hand frame."""

from __future__ import annotations

from dataclasses import dataclass

from app.gestures.geometry import (
    extended_fingers,
    normalized_distance,
    palm_center,
    palm_scale,
)
from app.gestures.models import (
    Gesture,
    GestureObservation,
    HandFrame,
    HandLandmark,
)


@dataclass(frozen=True)
class RecognitionThresholds:
    pinch_distance: float = 0.34
    minimum_palm_scale: float = 0.035

    def __post_init__(self) -> None:
        if self.pinch_distance <= 0:
            raise ValueError("pinch_distance must be positive.")
        if self.minimum_palm_scale <= 0:
            raise ValueError("minimum_palm_scale must be positive.")


class GestureRecognizer:
    def __init__(self, thresholds: RecognitionThresholds | None = None) -> None:
        self.thresholds = thresholds or RecognitionThresholds()

    def recognize(self, frame: HandFrame) -> GestureObservation:
        scale = palm_scale(frame)
        center = palm_center(frame)
        fingers = extended_fingers(frame)
        index_pinch = normalized_distance(
            frame,
            HandLandmark.THUMB_TIP,
            HandLandmark.INDEX_TIP,
        )
        middle_pinch = normalized_distance(
            frame,
            HandLandmark.THUMB_TIP,
            HandLandmark.MIDDLE_TIP,
        )
        ring_pinch = normalized_distance(
            frame,
            HandLandmark.THUMB_TIP,
            HandLandmark.RING_TIP,
        )

        gesture = Gesture.NONE
        if scale >= self.thresholds.minimum_palm_scale:
            if index_pinch <= self.thresholds.pinch_distance:
                gesture = Gesture.PINCH_INDEX
            elif middle_pinch <= self.thresholds.pinch_distance:
                gesture = Gesture.PINCH_MIDDLE
            elif ring_pinch <= self.thresholds.pinch_distance:
                gesture = Gesture.PINCH_RING
            elif fingers == (True, True, True, False):
                gesture = Gesture.THREE_FINGER
            elif fingers == (False, False, False, False):
                gesture = Gesture.FIST
            elif fingers == (True, True, True, True):
                gesture = Gesture.OPEN_PALM
            elif fingers == (True, True, False, False):
                gesture = Gesture.TWO_FINGER
            elif fingers == (True, False, False, False):
                gesture = Gesture.POINT

        confidence = min(
            frame.confidence,
            max(0.0, min(1.0, scale / 0.12)),
        )
        return GestureObservation(
            gesture=gesture,
            timestamp=frame.timestamp,
            confidence=confidence,
            cursor_point=frame.point(HandLandmark.INDEX_TIP),
            palm_center=center,
            palm_scale=scale,
            extended_fingers=fingers,
            metrics={
                "index_pinch": index_pinch,
                "middle_pinch": middle_pinch,
                "ring_pinch": ring_pinch,
            },
        )
