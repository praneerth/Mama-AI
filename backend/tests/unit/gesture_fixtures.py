from __future__ import annotations

from app.gestures.models import HandFrame, HandLandmark, Point3D


_FINGER_GROUPS = {
    "index": (
        HandLandmark.INDEX_MCP,
        HandLandmark.INDEX_PIP,
        HandLandmark.INDEX_DIP,
        HandLandmark.INDEX_TIP,
    ),
    "middle": (
        HandLandmark.MIDDLE_MCP,
        HandLandmark.MIDDLE_PIP,
        HandLandmark.MIDDLE_DIP,
        HandLandmark.MIDDLE_TIP,
    ),
    "ring": (
        HandLandmark.RING_MCP,
        HandLandmark.RING_PIP,
        HandLandmark.RING_DIP,
        HandLandmark.RING_TIP,
    ),
    "pinky": (
        HandLandmark.PINKY_MCP,
        HandLandmark.PINKY_PIP,
        HandLandmark.PINKY_DIP,
        HandLandmark.PINKY_TIP,
    ),
}


def make_hand_frame(
    extended: tuple[bool, bool, bool, bool],
    *,
    timestamp: float = 0.0,
    confidence: float = 1.0,
    pinch: str | None = None,
    shift_x: float = 0.0,
    shift_y: float = 0.0,
) -> HandFrame:
    points = [Point3D(0.5, 0.8, 0.0) for _ in range(21)]
    points[HandLandmark.WRIST] = Point3D(0.50, 0.82, 0.0)
    points[HandLandmark.THUMB_CMC] = Point3D(0.43, 0.68, 0.0)
    points[HandLandmark.THUMB_MCP] = Point3D(0.37, 0.61, 0.0)
    points[HandLandmark.THUMB_IP] = Point3D(0.32, 0.55, 0.0)
    points[HandLandmark.THUMB_TIP] = Point3D(0.27, 0.50, 0.0)

    x_values = (0.42, 0.49, 0.56, 0.63)
    for state, (name, indexes), x in zip(extended, _FINGER_GROUPS.items(), x_values):
        mcp, pip, dip, tip = indexes
        points[mcp] = Point3D(x, 0.63, 0.0)
        if state:
            points[pip] = Point3D(x, 0.48, 0.0)
            points[dip] = Point3D(x, 0.34, 0.0)
            points[tip] = Point3D(x, 0.20, 0.0)
        else:
            points[pip] = Point3D(x, 0.55, 0.0)
            points[dip] = Point3D(x + 0.025, 0.60, 0.0)
            points[tip] = Point3D(x + 0.045, 0.64, 0.0)

    if pinch == "index":
        index_tip = points[HandLandmark.INDEX_TIP]
        points[HandLandmark.THUMB_TIP] = Point3D(
            index_tip.x - 0.005,
            index_tip.y + 0.005,
            0.0,
        )
    elif pinch == "middle":
        middle_tip = points[HandLandmark.MIDDLE_TIP]
        points[HandLandmark.THUMB_TIP] = Point3D(
            middle_tip.x - 0.005,
            middle_tip.y + 0.005,
            0.0,
        )
    elif pinch == "ring":
        ring_tip = points[HandLandmark.RING_TIP]
        points[HandLandmark.THUMB_TIP] = Point3D(
            ring_tip.x - 0.005,
            ring_tip.y + 0.005,
            0.0,
        )

    shifted = tuple(
        Point3D(point.x + shift_x, point.y + shift_y, point.z)
        for point in points
    )
    return HandFrame(
        landmarks=shifted,
        timestamp=timestamp,
        confidence=confidence,
        handedness="right",
        source_width=1280,
        source_height=720,
    )
