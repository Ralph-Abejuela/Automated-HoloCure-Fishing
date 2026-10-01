import ctypes
import os
import time
from pathlib import Path

import cv2
import numpy as np
import win32con
import win32gui
import win32ui

from platform_UNF import Platform

keycodes = {
    "0": 0x30,
    "1": 0x31,
    "2": 0x32,
    "3": 0x33,
    "4": 0x34,
    "5": 0x35,
    "6": 0x36,
    "7": 0x37,
    "8": 0x38,
    "9": 0x39,
    "a": 0x41,
    "b": 0x42,
    "c": 0x43,
    "d": 0x44,
    "e": 0x45,
    "f": 0x46,
    "g": 0x47,
    "h": 0x48,
    "i": 0x49,
    "j": 0x4A,
    "k": 0x4B,
    "l": 0x4C,
    "m": 0x4D,
    "n": 0x4E,
    "o": 0x4F,
    "p": 0x50,
    "q": 0x51,
    "r": 0x52,
    "s": 0x53,
    "t": 0x54,
    "u": 0x55,
    "v": 0x56,
    "w": 0x57,
    "x": 0x58,
    "y": 0x59,
    "z": 0x5A,
    "space": 0x20,
    "enter": 0x0D,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "shift": 0x10,
    "ctrl": 0x11,
    "alt": 0x12
}


class Windows(Platform):

    def __init__(self):
        self.handle = None,
        self.window = None

        # disable program DPI scaling - affects screen capture
        ctypes.windll.shcore.SetProcessDpiAwareness(2)

    def wait_until_application_handle(self):
        while True:
            hwndMain = win32gui.FindWindow("YYGameMakerYY", "HoloCure")
            if hwndMain != 0:
                break

            time.sleep(self.timing("window_search_interval"))

        self.handle = hwndMain
        self.window = win32ui.CreateWindowFromHandle(hwndMain)

    def config_file_path(self):
        path = f"{Path.home()}/AppData/Local/HoloCure/settings.json"
        if os.path.isfile(path):
            return path

        return None

    def get_holocure_bounds(self):
        if not self.handle:
            return None
        left, right, top, bottom = win32gui.GetClientRect(self.handle)
        return left, right, top, bottom

    def holocure_screenshot(self, roi):
        if not self.handle:
            return

        return capture_game(self.handle, *roi)

    def press_key(self, key):
        if not self.window:
            return

        if key not in keycodes:
            print(f"key {key} not supported, not pressing")
            return

        self.window.SendMessage(win32con.WM_KEYDOWN, keycodes[key], 0)
        time.sleep(self.timing("keypress_gap"))
        self.window.SendMessage(win32con.WM_KEYUP, keycodes[key], 0)

    def offset(self, fish_count):
        return 0


def capture_game(hwnd, left: int, top: int, width: int, height: int):
    """Get a screenshot of the given window.

    Works even if target hwnd is behind other windows, but not minimised.

    From https://stackoverflow.com/a/62293979
    and https://stackoverflow.com/q/40098142
    and https://stackoverflow.com/a/68310347"""
    # TODO: can probably refactor this as a class to avoid calling
    # constructors/destructors all the time
    # calculate offset (e.g. from title bar, window borders)
    offset_left, offset_top, *_ = win32gui.GetWindowRect(hwnd)
    offset_left, offset_top = win32gui.ScreenToClient(hwnd, (offset_left, offset_top))
    wDC = win32gui.GetWindowDC(hwnd)
    dcObj = win32ui.CreateDCFromHandle(wDC)
    cDC = dcObj.CreateCompatibleDC()
    dataBitMap = win32ui.CreateBitmap()
    dataBitMap.CreateCompatibleBitmap(dcObj, width, height)
    cDC.SelectObject(dataBitMap)
    cDC.BitBlt(
        (0, 0),
        (width, height),
        dcObj,
        (left - offset_left, top - offset_top),
        win32con.SRCCOPY,
    )

    im = dataBitMap.GetBitmapBits(True)
    img = np.frombuffer(im, dtype=np.uint8).reshape((height, width, 4))
    converted = cv2.cvtColor(img, cv2.COLOR_RGBA2RGB)

    dcObj.DeleteDC()
    cDC.DeleteDC()
    win32gui.ReleaseDC(hwnd, wDC)
    win32gui.DeleteObject(dataBitMap.GetHandle())
    return converted
