"""
imgproc.py

Contains constants and functions for image processing.
"""

import cv2

from resources import resource_dir

#: Where the templates are read from. Resolved through resources rather than
#: a "./img/..." relative path, because a relative path is relative to the
#: current directory: it works from the project folder and nowhere else, so
#: the built executable would start with every template missing.
TEMPLATE_DIR = resource_dir() / "img" / "360p"

raw = dict(
    ok=cv2.imread(str(TEMPLATE_DIR / "ok.png"), cv2.IMREAD_UNCHANGED),
    # box=cv2.imread(str(TEMPLATE_DIR / "box.png"), cv2.IMREAD_UNCHANGED),  # unused
    space=cv2.imread(str(TEMPLATE_DIR / "space.png"), cv2.IMREAD_UNCHANGED),
    left=cv2.imread(str(TEMPLATE_DIR / "left.png"), cv2.IMREAD_UNCHANGED),
    right=cv2.imread(str(TEMPLATE_DIR / "right.png"), cv2.IMREAD_UNCHANGED),
    up=cv2.imread(str(TEMPLATE_DIR / "up.png"), cv2.IMREAD_UNCHANGED),
    down=cv2.imread(str(TEMPLATE_DIR / "down.png"), cv2.IMREAD_UNCHANGED),
    pointer=cv2.imread(str(TEMPLATE_DIR / "pointer.png"), cv2.IMREAD_UNCHANGED),
)

templates = {}
for name, img in raw.items():
    templates[name] = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

masks = {}
for name, img in raw.items():
    masks[name] = cv2.extractChannel(img, 3)
