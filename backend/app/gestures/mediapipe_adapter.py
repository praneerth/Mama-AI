"""Optional OpenCV/MediaPipe camera adapter for the native gesture agent."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

from app.gestures.config import GestureAgentConfig
from app.gestures.models import HandFrame, Point3D


class GestureDependencyError(RuntimeError):
    pass


@dataclass
class CameraResult:
    frame: HandFrame | None
    image: Any
    landmarks: Any = None


class MediaPipeHandCamera:
    def __init__(self, config: GestureAgentConfig) -> None:
        self.config = config
        try:
            import cv2
            import mediapipe as mp
        except Exception as exc:
            raise GestureDependencyError(
                "OpenCV and MediaPipe are required. Install "
                "backend/requirements-gesture.txt in the Windows venv."
            ) from exc
        self.cv2 = cv2
        self.mp = mp
        if not hasattr(mp, "solutions"):
            version = str(getattr(mp, "__version__", "unknown"))
            raise GestureDependencyError(
                "Installed MediaPipe "
                f"{version} does not provide the legacy Solutions API "
                "required by Mama AI Hand Gesture Phase 1. Install the "
                "supported Windows version with: python -m pip install "
                "--force-reinstall --no-cache-dir mediapipe==0.10.21"
            )

        self.capture = self._open_capture(config.camera_index)
        if not self.capture.isOpened():
            self.capture.release()
            raise RuntimeError(
                f"Unable to open camera index {config.camera_index}."
            )
        self._configure_capture()
        self.hands = mp.solutions.hands.Hands(
            static_image_mode=False,
            # Detect a second hand so Phase 1 can fail closed instead of
            # silently choosing one of multiple visible hands.
            max_num_hands=2,
            model_complexity=config.model_complexity,
            min_detection_confidence=config.minimum_detection_confidence,
            min_tracking_confidence=config.minimum_tracking_confidence,
        )
        self.drawer = mp.solutions.drawing_utils
        self.connections = mp.solutions.hands.HAND_CONNECTIONS

    def _open_capture(self, camera_index: int) -> Any:
        if sys.platform == "win32" and hasattr(self.cv2, "CAP_DSHOW"):
            capture = self.cv2.VideoCapture(camera_index, self.cv2.CAP_DSHOW)
            if capture.isOpened():
                return capture
            capture.release()
        return self.cv2.VideoCapture(camera_index)

    def _configure_capture(self) -> None:
        properties = (
            ("CAP_PROP_FRAME_WIDTH", float(self.config.camera_width)),
            ("CAP_PROP_FRAME_HEIGHT", float(self.config.camera_height)),
            ("CAP_PROP_FPS", float(self.config.camera_fps)),
            ("CAP_PROP_BUFFERSIZE", float(self.config.camera_buffer_size)),
        )
        for name, value in properties:
            property_id = getattr(self.cv2, name, None)
            if property_id is not None:
                self.capture.set(property_id, value)

    def read(self, timestamp: float) -> CameraResult:
        ok, image = self.capture.read()
        if not ok or image is None:
            return CameraResult(frame=None, image=image)
        rgb = self.cv2.cvtColor(image, self.cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False
        result = self.hands.process(rgb)
        rgb.flags.writeable = True
        if (
            not result.multi_hand_landmarks
            or len(result.multi_hand_landmarks) != self.config.maximum_hands
        ):
            return CameraResult(frame=None, image=image)
        hand = result.multi_hand_landmarks[0]
        handedness = "unknown"
        confidence = 1.0
        if result.multi_handedness:
            classification = result.multi_handedness[0].classification[0]
            handedness = str(classification.label).lower()
            confidence = float(classification.score)
        height, width = image.shape[:2]
        frame = HandFrame(
            landmarks=tuple(
                Point3D(float(point.x), float(point.y), float(point.z))
                for point in hand.landmark
            ),
            timestamp=timestamp,
            confidence=confidence,
            handedness=handedness,
            source_width=int(width),
            source_height=int(height),
        )
        return CameraResult(frame=frame, image=image, landmarks=hand)

    def annotate(
        self,
        result: CameraResult,
        *,
        gesture: str,
        armed: bool,
        profile: str,
        message: str = "",
    ) -> Any:
        image = result.image
        if image is None:
            return image
        if result.landmarks is not None:
            self.drawer.draw_landmarks(
                image,
                result.landmarks,
                self.connections,
            )
        if self.config.mirror_camera:
            image = self.cv2.flip(image, 1)
        status = "ARMED" if armed else "SAFE / DISARMED"
        self.cv2.putText(
            image,
            f"Mama AI Gestures: {status}",
            (15, 30),
            self.cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 0, 255) if armed else (0, 180, 0),
            2,
        )
        self.cv2.putText(
            image,
            f"Gesture: {gesture} | Profile: {profile}",
            (15, 60),
            self.cv2.FONT_HERSHEY_SIMPLEX,
            0.58,
            (255, 255, 255),
            2,
        )
        self.cv2.putText(
            image,
            "Hold 3 fingers to toggle | Ctrl+Alt+G emergency | Q exits",
            (15, 90),
            self.cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (255, 255, 255),
            1,
        )
        if message:
            self.cv2.putText(
                image,
                message[:90],
                (15, 120),
                self.cv2.FONT_HERSHEY_SIMPLEX,
                0.48,
                (0, 230, 230),
                1,
            )
        return image

    def show(self, image: Any) -> bool:
        if image is None:
            return True
        self.cv2.imshow("Mama AI Hand Gestures", image)
        key = self.cv2.waitKey(1) & 0xFF
        return key not in {ord("q"), 27}

    def close(self) -> None:
        try:
            self.hands.close()
        finally:
            self.capture.release()
            self.cv2.destroyAllWindows()
