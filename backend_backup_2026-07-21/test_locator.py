from app.tools.screenshot import take_screenshot
from app.vision.ui_locator import locate_object

image = take_screenshot()

point = locate_object(image, "tv")

print(point)