import cv2


def find_template(screen_path, template_path, threshold=0.40):

    screen = cv2.imread(str(screen_path))
    template = cv2.imread(str(template_path))

    if screen is None:
        print("Screen image not found.")
        return None

    if template is None:
        print("Template image not found:", template_path)
        return None

    result = cv2.matchTemplate(
        screen,
        template,
        cv2.TM_CCOEFF_NORMED,
    )

    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    print(f"Match Confidence: {max_val:.3f}")

    if max_val < threshold:
        return None

    h, w = template.shape[:2]

    center = (
        max_loc[0] + w // 2,
        max_loc[1] + h // 2,
    )

    return center