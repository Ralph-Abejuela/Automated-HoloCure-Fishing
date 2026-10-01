import argparse
import json
import sys
import time
from math import floor

import cv2
import numpy as np
from imgproc import templates, masks
from telemetry import (
    STATE_RUNNING,
    STATE_WAITING,
    Dot,
    Match,
    Rect,
    Telemetry,
)
from timings import TimingError, Timings, SPECS, parse_value
DEBUG = False

#: Region of Interest - we only need this area of the screen, in 360p
#: coordinates. It is multiplied by the window's scale factor later.
FISHING_ROI = (276, 242, 133, 38)  # left, top, width, height
MINING_ROI = (203, 251, 216, 44)
#: top, bottom, start_x_offset, end_x_offset of the strip the pointer is in
MINING_SCAN_REGION = (24, 30, -3, 33)

#: Arbitrary magic numbers a template match has to stay under. They are rough
#: because hovering the mouse over a button changes the pixels without
#: changing what the game wants, which is what makes the loops get stuck.
ARROW_THRESHOLD = 1000
OK_THRESHOLD = 60_000_000
POINTER_THRESHOLD = 100

#: Colours the monitor window draws on, in RGB.
ARROW_COLOR = (0, 200, 255)
OK_COLOR = (255, 96, 96)
POINTER_COLOR = (0, 255, 0)
RED_AREA_COLOR = (255, 0, 255)


def load_timings(path=None, overrides=None, platform_name=None) -> Timings:
    """Build the timing table, reporting a bad file or override as CLI text."""
    settings = Timings(path=path, platform=platform_name)
    for item in overrides or []:
        name, separator, value = item.partition("=")
        name = name.strip()
        if not separator or name not in SPECS:
            raise SystemExit(
                f"Error: --set wants NAME=VALUE for a known timing, got {item!r}.\n"
                f"Known timings: {', '.join(SPECS)}"
            )
        settings[name] = parse_value(SPECS[name], value)
    return settings


def fishing_mode(platform, settings: Timings, telemetry: Telemetry = None) -> None:
    """Fish until the loop is told to stop.

    Every iteration is reported to ``telemetry``: what was captured, which
    templates matched and how well, which keys were sent and how long the
    pass took. A ``telemetry`` of None just records into the void, so the
    command line run behaves exactly as it did before.
    """
    telemetry = telemetry or Telemetry()
    telemetry.set_mode("fishing")
    # first time config load, but we check every second to see if it's changed
    keybinds = get_config(platform.config_file_path())
    one_second_timer = time.perf_counter()
    counter = 0
    telemetry.update(keybinds=keybinds)
    telemetry.log(f"Keybinds: {keybinds}")
    BASE_ROI = FISHING_ROI
    # Big loopy boi:
    while not telemetry.should_stop():
        #   1. Use computer vision to get information about the game
        #   2. Use OpenCV template matching to check which button to press
        #   3. Send the inputs to the game
        last_time = time.perf_counter()
        # pick up timings edited by the GUI or CLI while we run
        if settings.reload_if_changed():
            telemetry.set_timings(settings.values, str(settings.path))
            telemetry.log(f"Timings reloaded from {settings.path.name}.")
        # update the config once a second :)
        if last_time - one_second_timer > settings["config_poll_interval"]:
            keybinds = get_config(platform.config_file_path())
            one_second_timer = last_time
            telemetry.update(keybinds=keybinds)
            telemetry.log(f"Keybinds re-read: {keybinds}")
        # find the window every loop - a bit ugly, but we can handle the game
        # closing and opening this way (there's probably a better way though)
        platform.wait_until_application_handle()
        if telemetry.should_stop():
            break
        # capture only the area we need for image processing
        left, top, width, height = platform.get_holocure_bounds()
        if width == 0 or height == 0:  # skip if window minimised
            telemetry.set_state(
                STATE_WAITING, "HoloCure is minimised, there is nothing to read."
            )
            continue
        scale = round(height / 360)
        roi = np.multiply(scale, BASE_ROI)

        capture_start = time.perf_counter()
        img_src = platform.holocure_screenshot(roi)

        # resize the image down to 360p equivalent
        # so the rest of the code is resolution-invariant
        img_src = cv2.resize(
            img_src,
            dsize=None,
            fx=1 / scale,
            fy=1 / scale,
            interpolation=cv2.INTER_NEAREST,
        )
        capture_ms = (time.perf_counter() - capture_start) * 1000
        if DEBUG:
            cv2.namedWindow("Source", cv2.WINDOW_NORMAL)
            cv2.imshow("Source", img_src)
            cv2.resizeWindow("Source", img_src.shape[1] * 2, img_src.shape[0] * 2)

        # maths time
        # look for rhythm game arrows first
        match_start = time.perf_counter()
        rects = []
        dots = []
        matches = []
        arrow = None
        offset_pixels = platform.offset(counter)
        for key in ("space", "left", "right", "up", "down"):
            h, w, _ = templates[key].shape
            # offset so all templates line up properly
            h_offset = 10 - floor(h / 2)
            w_offset = 10 - floor(w / 2)
            window_x = 103 + w_offset + offset_pixels
            window = img_src[
                h_offset: h_offset + h, window_x: 133 + offset_pixels
            ]
            res = cv2.matchTemplate(
                window,
                templates[key],
                cv2.TM_SQDIFF,
                mask=masks[key],
            )
            min_val, _, min_loc, _ = cv2.minMaxLoc(res)
            matched = min_val < ARROW_THRESHOLD
            matches.append(Match(key, min_val, ARROW_THRESHOLD, matched, min_loc))
            rects.append(
                Rect(
                    window_x,
                    h_offset,
                    window.shape[1],
                    window.shape[0],
                    ARROW_COLOR,
                    key,
                )
            )
            # arbitrary magic number, gets stuck if mouse hovering over button
            if matched:
                arrow = key
                dots.append(
                    Dot(window_x + min_loc[0], h_offset + min_loc[1], ARROW_COLOR, key)
                )
                platform.press_key(keybinds[key])
                telemetry.key(keybinds[key], f"rhythm arrow '{key}' matched")
                time.sleep(settings["fishing_key_delay"])
                break

        # look for "ok" button and press enter if so
        h, w, _ = templates["ok"].shape
        ok_y = 9
        res = cv2.matchTemplate(
            img_src[ok_y: ok_y + h, 0:w],
            templates["ok"],
            cv2.TM_SQDIFF,
            mask=masks["ok"],
        )
        min_val, _, min_loc, _ = cv2.minMaxLoc(res)
        # arbitrary magic number, handles the mouse hovering over the OK button
        ok_matched = min_val < OK_THRESHOLD
        matches.append(Match("ok", min_val, OK_THRESHOLD, ok_matched, min_loc))
        rects.append(Rect(0, ok_y, w, h, OK_COLOR, "ok"))
        if ok_matched:
            dots.append(Dot(min_loc[0], ok_y + min_loc[1], OK_COLOR, "ok"))
            presses = int(settings["fishing_ok_presses"])
            for press in range(1, presses + 1):
                telemetry.key(
                    "enter", f"dismissing the prompt {press} of {presses}"
                )
                platform.press_key("enter")
                time.sleep(settings["fishing_ok_gap"])
            counter += 1
            telemetry.log(f"Fishing count: {counter}", level="good")

        match_ms = (time.perf_counter() - match_start) * 1000
        if arrow is not None:
            message = f"Arrow '{arrow}' matched, pressed {keybinds[arrow]!r}."
        elif ok_matched:
            message = f"'ok' matched, {presses} x Enter. Fishing count {counter}."
        else:
            message = "No template matched, watching the buttons."

        elapsed = time.perf_counter() - last_time
        # debug to see how fast the loop runs
        if DEBUG:
            fps = 1 / elapsed
            print(f"FPS: {round(fps, 2):06.2f}" + "-" * round(fps / 10))
            cv2.waitKey(1)

        # slow the loop down to fishing_loop_interval (100Hz by default)
        loop_interval = settings["fishing_loop_interval"]
        sleep_for = loop_interval - elapsed if elapsed < loop_interval else 0.0

        telemetry.update(
            state=STATE_RUNNING,
            message=message,
            image=img_src,
            rects=rects,
            dots=dots,
            matches=matches,
            bounds=(left, top, width, height),
            roi=tuple(int(value) for value in roi),
            scale=scale,
            keybinds=keybinds,
            counter=counter,
            capture_ms=capture_ms,
            match_ms=match_ms,
            loop_ms=elapsed * 1000,
            sleep_ms=sleep_for * 1000,
        )
        telemetry.loop_done(elapsed)

        if sleep_for > 0:
            time.sleep(sleep_for)
    telemetry.finish("Fishing stopped.")


def check_red_area(img_src):
        area_start_x = 0
        area_end_x = 0
        t__ = False
        img_src2 = img_src[0:img_src.shape[0], 0:img_src.shape[1]]
        temp_ing = img_src[34:35, 14:img_src.shape[1]]
        data = np.array(temp_ing).tolist()
        for i in range(len(data[0])):
            # print(data[0][i])
            if data[0][i][2] == 255 and data[0][i][1] == 0 and data[0][i][0] == 0:
                if not t__:
                    area_start_x = i
                    area_end_x = i
                    t__ = True
                area_end_x += 1
        return area_start_x, area_end_x
def pick_axe_mode(platform, settings: Timings, telemetry: Telemetry = None) -> None:
    """Mine until the loop is told to stop, reporting as fishing_mode does."""
    telemetry = telemetry or Telemetry()
    telemetry.set_mode("mining")
    # first time config load, but we check every second to see if it's changed  
    keybinds = get_config(platform.config_file_path())
    one_second_timer = time.perf_counter()
    counter = 0
    telemetry.update(keybinds=keybinds)
    telemetry.log(f"Keybinds: {keybinds}")
    BASE_ROI = MINING_ROI
    SCAN_REGION = MINING_SCAN_REGION
    # Big loopy boi:
    while not telemetry.should_stop():
        #   1. Use computer vision to get information about the game
        #   2. Use OpenCV template matching to check which button to press
        #   3. Send the inputs to the game
        last_time = time.perf_counter()
        # pick up timings edited by the GUI or CLI while we run
        if settings.reload_if_changed():
            telemetry.set_timings(settings.values, str(settings.path))
            telemetry.log(f"Timings reloaded from {settings.path.name}.")
        # update the config once a second :)
        if last_time - one_second_timer > settings["config_poll_interval"]:
            keybinds = get_config(platform.config_file_path())
            one_second_timer = last_time
            telemetry.update(keybinds=keybinds)
            telemetry.log(f"Keybinds re-read: {keybinds}")
        # find the window every loop - a bit ugly, but we can handle the game
        # closing and opening this way (there's probably a better way though)
        platform.wait_until_application_handle()
        if telemetry.should_stop():
            break
        # capture only the area we need for image processing
        left, top, width, height = platform.get_holocure_bounds()
        if width == 0 or height == 0:  # skip if window minimised
            telemetry.set_state(
                STATE_WAITING, "HoloCure is minimised, there is nothing to read."
            )
            continue
        scale = round(height / 360)
        roi = np.multiply(scale, BASE_ROI)

        capture_start = time.perf_counter()
        img_src = platform.holocure_screenshot(roi)

        # resize the image down to 360p equivalent
        # so the rest of the code is resolution-invariant
        img_src = cv2.resize(
            img_src,
            dsize=None,
            fx=1 / scale,
            fy=1 / scale,
            interpolation=cv2.INTER_NEAREST,
        )
        capture_ms = (time.perf_counter() - capture_start) * 1000
        ran_checker = False

        if not ran_checker:
            area_start_x, area_end_x = check_red_area(img_src)
        ran_checker = True

        match_start = time.perf_counter()
        rects = []
        dots = []
        matches = []
        pointer_matched = False
        scan_x = area_start_x + SCAN_REGION[2]
        scan_right = area_end_x + SCAN_REGION[3]
        detection_area = None
        if area_end_x - area_start_x > 0:
            rects.append(
                Rect(
                    scan_x,
                    SCAN_REGION[0],
                    scan_right - scan_x,
                    SCAN_REGION[1] - SCAN_REGION[0],
                    RED_AREA_COLOR,
                    "red bar",
                )
            )
            detection_area = img_src[
                SCAN_REGION[0]: SCAN_REGION[1], scan_x: scan_right
            ]
            res = cv2.matchTemplate(
                detection_area,
                templates["pointer"],
                cv2.TM_SQDIFF,
                mask=masks["pointer"],
            )

            min_val, _, min_loc, _ = cv2.minMaxLoc(res)
            pointer_matched = min_val < POINTER_THRESHOLD
            matches.append(
                Match("pointer", min_val, POINTER_THRESHOLD, pointer_matched, min_loc)
            )
            rects.append(
                Rect(
                    scan_x,
                    SCAN_REGION[0],
                    detection_area.shape[1],
                    detection_area.shape[0],
                    POINTER_COLOR,
                    "pointer scan",
                )
            )
            if pointer_matched:
                dots.append(
                    Dot(
                        scan_x + min_loc[0],
                        SCAN_REGION[0] + min_loc[1],
                        POINTER_COLOR,
                        "pointer",
                    )
                )
                platform.press_key("enter")
                telemetry.key("enter", "pointer matched, swung the axe")
                time.sleep(settings["mining_enter_delay"])

        # look for "ok" button and press enter if so
        # the window the "ok" template is searched in, not the template size
        ok_x, ok_y, ok_width, ok_height = 69, 0, 89, 29
        res = cv2.matchTemplate(
            img_src[ok_y: ok_y + ok_height, ok_x: ok_x + ok_width],
            templates["ok"],
            cv2.TM_SQDIFF,
            mask=masks["ok"],
        )
        min_val, _, min_loc, _ = cv2.minMaxLoc(res)
        # arbitrary magic number, handles the mouse hovering over the OK button
        ok_matched = min_val < OK_THRESHOLD
        matches.append(Match("ok", min_val, OK_THRESHOLD, ok_matched, min_loc))
        rects.append(Rect(ok_x, ok_y, ok_width, ok_height, OK_COLOR, "ok"))
        if ok_matched:
            dots.append(
                Dot(ok_x + min_loc[0], ok_y + min_loc[1], OK_COLOR, "ok")
            )
            presses = int(settings["mining_ok_presses"])
            for press in range(1, presses + 1):
                telemetry.key(
                    "enter", f"dismissing the prompt {press} of {presses}"
                )
                platform.press_key("enter")
                time.sleep(settings["mining_ok_gap"])
            counter += 1
            telemetry.log(f"Mining count: {counter}", level="good")
            ran_checker = False
        match_ms = (time.perf_counter() - match_start) * 1000

        if DEBUG:
            cv2.namedWindow("Source", cv2.WINDOW_NORMAL)
            sourceImg = cv2.rectangle(img_src, (scan_x, SCAN_REGION[0]), (area_end_x+SCAN_REGION[3], SCAN_REGION[1]), (0, 0, 255), 1)
            cv2.imshow("Source", sourceImg)
            cv2.resizeWindow("Source", sourceImg.shape[1] * 2, sourceImg.shape[0] * 2)
            if area_end_x - area_start_x > 0:
                cv2.namedWindow("Detection Area", cv2.WINDOW_NORMAL)    
                cv2.imshow("Detection Area", img_src[SCAN_REGION[0]:SCAN_REGION[1],area_start_x+SCAN_REGION[2]:area_end_x+SCAN_REGION[3]])
                cv2.resizeWindow("Detection Area", detection_area.shape[0] * 2, detection_area.shape[1] * 2)

        if pointer_matched:
            message = "Pointer matched, pressed Enter."
        elif ok_matched:
            message = f"'ok' matched, {presses} x Enter. Mining count {counter}."
        else:
            message = "No template matched, watching the pointer."

        elapsed = time.perf_counter() - last_time
        # debug to see how fast the loop runs
        if DEBUG:
            fps = 1 / elapsed
            print(f"FPS: {round(fps, 2):06.2f}" + "-" * round(fps / 10))
            cv2.waitKey(1)

        # slow the loop down to 100Hz max
        # if elapsed < 0.001:
        #     time.sleep(0.001 - elapsed)

        telemetry.update(
            state=STATE_RUNNING,
            message=message,
            image=img_src,
            rects=rects,
            dots=dots,
            matches=matches,
            bounds=(left, top, width, height),
            roi=tuple(int(value) for value in roi),
            scale=scale,
            keybinds=keybinds,
            counter=counter,
            capture_ms=capture_ms,
            match_ms=match_ms,
            loop_ms=elapsed * 1000,
            sleep_ms=0.0,
        )
        telemetry.loop_done(elapsed)
    telemetry.finish("Mining stopped.")


def make_platform(platform_name: str = None):
    """Return the platform adapter for this machine, or for ``platform_name``."""
    platform_name = sys.platform if platform_name is None else platform_name
    if platform_name == "win32":
        from platform_windows import Windows

        return Windows()
    if platform_name == "linux":
        from platform_linux import Linux

        return Linux()
    raise OSError("Unsupported operating system!")


def main(argv=None) -> int:
    """Entry point for the program."""
    parser = argparse.ArgumentParser(
        description="Automate the HoloCure fishing and mining minigames.",
        epilog="Change the delays with timings_cli.py or timings_gui.py.",
    )
    parser.add_argument(
        "--timings-file",
        metavar="PATH",
        help="timings JSON file to use instead of timings.json next to the scripts",
    )
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="override one timing for this run only, e.g. --set fishing_key_delay=250ms "
        "(repeatable, not written to disk)",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="open a window that shows the capture region, the template matches, "
        "the keypresses and the timings, instead of asking for a mode on the console",
    )
    arguments = parser.parse_args(argv)

    platform = make_platform()

    try:
        settings = load_timings(
            arguments.timings_file, arguments.set, sys.platform
        )
    except TimingError as error:
        raise SystemExit(f"Error: {arguments.timings_file or 'timings.json'}\n{error}")
    platform.timings = settings

    if arguments.set:
        print(f"Using {settings.path} plus command line overrides.")
    elif settings.path.is_file():
        print(f"Using timings from {settings.path}.")
    else:
        print(f"No {settings.path.name} found, using built-in default timings.")

    print("Welcome to Automated HoloCure Fishing!")
    print("Please open HoloCure, go to Holo House, and start fishing!")
    print("You can do other tasks as long as the HoloCure window isn't minimised.")
    print("It works even if the game is in the background!")

    if arguments.gui:
        try:
            import monitor_gui
        except ImportError as error:
            raise SystemExit(f"Error: this Python has no tkinter ({error}).\nDrop --gui to pick a mode on the console instead.")
        return monitor_gui.launch(settings=settings, platform=platform)

    # first time config load, but we check every second to see if it's changed
    while True:
        mode = input("Enter 1 for Fishing Mode, 2 for AutoMining mode, or 3 to exit: ")
        if mode == "1":
            fishing_mode(platform, settings)
        elif mode == "2":
            pick_axe_mode(platform, settings)
        elif mode == "3":
            break
        else:
            print("Invalid input, please try again.")
    return 0



def get_config(path):
    """Load game configuration and return a table."""
    # TODO: maybe only read if the file is modified

    defaults = {
        "space": "space",
        "left": "a",
        "right": "d",
        "up": "w",
        "down": "s",
    }

    if not path:
        return defaults

    with open(path) as config_file:
        config = json.load(config_file)
        keybinds = config.get("theButtons")
        if keybinds:
            return {
                "space": keybinds[0].lower(),
                "left": keybinds[2].lower(),
                "right": keybinds[3].lower(),
                "up": keybinds[4].lower(),
                "down": keybinds[5].lower(),
            }
        return {
            "space": "space",
            "left": "a",
            "right": "d",
            "up": "w",
            "down": "s",
        }


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
