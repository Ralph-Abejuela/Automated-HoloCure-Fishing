import math
import re
import subprocess
import time
from pathlib import Path

import numpy as np

from platform_UNF import Platform

from Xlib import X, XK, protocol
from Xlib.display import Display

keycodes = {
    "0": XK.XK_0,
    "1": XK.XK_1,
    "2": XK.XK_2,
    "3": XK.XK_3,
    "4": XK.XK_4,
    "5": XK.XK_5,
    "6": XK.XK_6,
    "7": XK.XK_7,
    "8": XK.XK_8,
    "9": XK.XK_9,
    "a": XK.XK_a,
    "b": XK.XK_b,
    "c": XK.XK_c,
    "d": XK.XK_d,
    "e": XK.XK_e,
    "f": XK.XK_f,
    "g": XK.XK_g,
    "h": XK.XK_h,
    "i": XK.XK_i,
    "j": XK.XK_j,
    "k": XK.XK_k,
    "l": XK.XK_l,
    "m": XK.XK_m,
    "n": XK.XK_n,
    "o": XK.XK_o,
    "p": XK.XK_p,
    "q": XK.XK_q,
    "r": XK.XK_r,
    "s": XK.XK_s,
    "t": XK.XK_t,
    "u": XK.XK_u,
    "v": XK.XK_v,
    "w": XK.XK_w,
    "x": XK.XK_x,
    "y": XK.XK_y,
    "z": XK.XK_z,
    "space": XK.XK_space,
    "enter": XK.XK_Return,
    "left": XK.XK_Left,
    "up": XK.XK_Up,
    "right": XK.XK_Right,
    "down": XK.XK_Down,
    "shift": XK.XK_Shift_L,
    "ctrl": XK.XK_Control_L,
    "alt": XK.XK_Alt_L
}
possible_paths = {
    Path(f"{Path.home()}/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/compatdata/2420510/pfx/drive_c/users/steamuser/AppData/Local/HoloCure/settings.json"),
    Path(f"{Path.home()}/.local/share/Steam/steamapps/compatdata/2420510/pfx/drive_c/users/steamuser/AppData/Local/HoloCure/settings.json"),
    Path(f"{Path.home()}/.var/app/io.itch.itch/data/wine/drive_c/users/ggg/AppData/Local/HoloCure/settings.json")
}

class Linux(Platform):

    def __init__(self):
        # initialized in wait_until_application_handle
        self._window = None

        # initialized in get_config_file_path
        self._config_path = "no"

    def wait_until_application_handle(self):
        # This function gets called every frame to check whether the window handle is still valid (i.e. if the
        #  program has been closed) to handle closing & reopening of Holocure.
        # This is not necessarily the smartest idea on Linux because we have to recursive loop over all windows to find
        #  the correct one.
        # So assume the window will be valid indefinitely.
        if self._window:
            return
        if self.stopping():
            return

        # The actual visible Holocure window might be nested in any number of parent windows depending on the
        # compositor. We henceforth have to search recursively.
        disp = Display()

        def search_holocure_window(window):
            name = window.get_wm_name()
            classs = window.get_wm_class()
            if name == "HoloCure" and classs == ("steam_app_2420510", "steam_app_2420510"):
                self._window = window
                return

            for child in window.query_tree().children:
                search_holocure_window(child)

        search_holocure_window(disp.screen().root)

    def get_holocure_bounds(self):
        # Absolute position of the window doesn't matter because we can screenshot HoloCure seperately. We only store
        #  width and height
        geometry = self._window.get_geometry()
        w, h = geometry.width, geometry.height
        return 0, 0, w, h

    def press_key(self, key):
        if key not in keycodes:
            print(f"key {key} not supported, not pressing")
            return

        disp = Display()
        the_root = disp.screen().root

        event = protocol.event.KeyPress(
            time=X.CurrentTime,
            root=the_root, window=self._window, same_screen=0, child=X.NONE,
            root_x=0, root_y=0, event_x=0, event_y=0,
            state=0, detail=disp.keysym_to_keycode(keycodes[key])
        )
        disp.send_event(self._window, event, propagate=True)
        disp.sync()

        # we need to wait at least a frame between press and release to make sure holocure picks up the input
        time.sleep(self.timing("keypress_gap"))

        event = protocol.event.KeyRelease(
            time=X.CurrentTime,
            root=the_root, window=self._window, same_screen=0, child=X.NONE,
            root_x=0, root_y=0, event_x=0, event_y=0,
            state=0, detail=disp.keysym_to_keycode(keycodes[key])
        )
        disp.send_event(self._window, event, propagate=True)
        disp.sync()

    def holocure_screenshot(self, roi=None):
        raw = self._window.get_image(*roi, X.ZPixmap, 0xffffffff)
        return np.frombuffer(raw.data, dtype=np.uint8).reshape((roi[3], roi[2], 4))[:, :, :3]

    def config_file_path(self):
        # If you have custom keybinds, uncomment the following line, replacing the string with the path to your
        # settings.json file
        # return "/path/to/settings.json"

        if not self._config_path == "no":
            return self._config_path

        ok_path = next(path for path in possible_paths if path.exists())

        if not ok_path:
            print("Could not find keybinds file, take a look in the readme file how to specifiy that location")
            self._config_path = None
            return None

        return ok_path

    def offset(self, fish_count):
        # 0 pixels at 0 fish, -15 pixels at speed 7
        return math.floor(-15 * min(fish_count, 70) / 70)
