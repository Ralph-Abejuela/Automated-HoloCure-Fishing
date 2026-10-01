import argparse
import json
import sys
import time
from math import floor

import cv2
import numpy as np
from imgproc import templates, masks
from timings import TimingError, Timings, SPECS, parse_value
DEBUG = False


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


def fishing_mode(platform, settings: Timings) -> None:
    # first time config load, but we check every second to see if it's changed
    keybinds = get_config(platform.config_file_path())
    one_second_timer = time.perf_counter()
    counter = 0
    # Region of Interest - we only need this area of the screen
    BASE_ROI = (276, 242, 133, 38)  # left, top, width, height
    # Big loopy boi:
    while True:
        #   1. Use computer vision to get information about the game
        #   2. Use OpenCV template matching to check which button to press
        #   3. Send the inputs to the game
        last_time = time.perf_counter()
        # pick up timings edited by the GUI or CLI while we run
        settings.reload_if_changed()
        # update the config once a second :)
        if last_time - one_second_timer > settings["config_poll_interval"]:
            keybinds = get_config(platform.config_file_path())
            one_second_timer = last_time
        # find the window every loop - a bit ugly, but we can handle the game
        # closing and opening this way (there's probably a better way though)
        platform.wait_until_application_handle()
        # capture only the area we need for image processing
        left, top, width, height = platform.get_holocure_bounds()
        if width == 0 or height == 0:  # skip if window minimised
            continue
        scale = round(height / 360)
        roi = np.multiply(scale, BASE_ROI)
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
        if DEBUG:
            cv2.namedWindow("Source", cv2.WINDOW_NORMAL)
            cv2.imshow("Source", img_src)
            cv2.resizeWindow("Source", img_src.shape[1] * 2, img_src.shape[0] * 2)

        # maths time
        # look for rhythm game arrows first
        for key in ("space", "left", "right", "up", "down"):
            h, w, _ = templates[key].shape
            # offset so all templates line up properly
            h_offset = 10 - floor(h / 2)
            w_offset = 10 - floor(w / 2)
            a = img_src[h_offset: h_offset + h, 103 + w_offset + platform.offset(counter): 133 + platform.offset(counter)]
            res = cv2.matchTemplate(
                img_src[h_offset: h_offset + h, 103 + w_offset + platform.offset(counter): 133 + platform.offset(counter)],
                templates[key],
                cv2.TM_SQDIFF,
                mask=masks[key],
            )
            min_val, _, _, _ = cv2.minMaxLoc(res)
            # arbitrary magic number, gets stuck if mouse hovering over button
            if min_val < 1000:
                platform.press_key(keybinds[key])
                time.sleep(settings["fishing_key_delay"])
                break

        # look for "ok" button and press enter if so
        h, w, _ = templates["ok"].shape
        res = cv2.matchTemplate(
            img_src[9: 9 + h, 0:w],
            templates["ok"],
            cv2.TM_SQDIFF,
            mask=masks["ok"],
        )
        min_val, _, _, _ = cv2.minMaxLoc(res)
        # arbitrary magic number, handles the mouse hovering over the OK button
        if min_val < 60_000_000:
            for _ in range(settings["fishing_ok_presses"]):
                platform.press_key("enter")
                time.sleep(settings["fishing_ok_gap"])
            counter += 1
            print("Fishing count: ", counter)

        elapsed = time.perf_counter() - last_time
        # debug to see how fast the loop runs
        if DEBUG:
            fps = 1 / elapsed
            print(f"FPS: {round(fps, 2):06.2f}" + "-" * round(fps / 10))
            cv2.waitKey(1)

        # slow the loop down to fishing_loop_interval (100Hz by default)
        loop_interval = settings["fishing_loop_interval"]
        if elapsed < loop_interval:
            time.sleep(loop_interval - elapsed)
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
def pick_axe_mode(platform, settings: Timings) -> None:
    # first time config load, but we check every second to see if it's changed  
    keybinds = get_config(platform.config_file_path())
    one_second_timer = time.perf_counter()
    counter = 0
    BASE_ROI = (203, 251, 216, 44)  # left, top, width, height
    SCAN_REGION = (24, 30, -3, 33) # top, bottom, start_x_offset, end_x_offset
    # Big loopy boi:
    while True:
        #   1. Use computer vision to get information about the game
        #   2. Use OpenCV template matching to check which button to press
        #   3. Send the inputs to the game
        last_time = time.perf_counter()
        # pick up timings edited by the GUI or CLI while we run
        settings.reload_if_changed()
        # update the config once a second :)
        if last_time - one_second_timer > settings["config_poll_interval"]:
            keybinds = get_config(platform.config_file_path())
            one_second_timer = last_time
        # find the window every loop - a bit ugly, but we can handle the game
        # closing and opening this way (there's probably a better way though)
        platform.wait_until_application_handle()
        # capture only the area we need for image processing
        left, top, width, height = platform.get_holocure_bounds()
        if width == 0 or height == 0:  # skip if window minimised
            continue
        scale = round(height / 360)
        roi = np.multiply(scale, BASE_ROI)
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
        ran_checker = False

        if not ran_checker:
            area_start_x, area_end_x = check_red_area(img_src)
        ran_checker = True
        if area_end_x - area_start_x > 0:
            detection_area = img_src[SCAN_REGION[0]:SCAN_REGION[1],area_start_x+SCAN_REGION[2]:area_end_x+SCAN_REGION[3]]
            res = cv2.matchTemplate(
                detection_area,
                templates["pointer"],
                cv2.TM_SQDIFF,
                mask=masks["pointer"],
            )

            min_val, _, _, _ = cv2.minMaxLoc(res)
            # print(min_val)

            if min_val < 100:
                platform.press_key("enter")
                time.sleep(settings["mining_enter_delay"])

        if DEBUG:
            cv2.namedWindow("Source", cv2.WINDOW_NORMAL)
            sourceImg = cv2.rectangle(img_src, (area_start_x+SCAN_REGION[2], SCAN_REGION[0]), (area_end_x+SCAN_REGION[3], SCAN_REGION[1]), (0, 0, 255), 1)
            cv2.imshow("Source", sourceImg)
            cv2.resizeWindow("Source", sourceImg.shape[1] * 2, sourceImg.shape[0] * 2)
            if area_end_x - area_start_x > 0:
                cv2.namedWindow("Detection Area", cv2.WINDOW_NORMAL)    
                cv2.imshow("Detection Area", img_src[SCAN_REGION[0]:SCAN_REGION[1],area_start_x+SCAN_REGION[2]:area_end_x+SCAN_REGION[3]])
                cv2.resizeWindow("Detection Area", detection_area.shape[0] * 2, detection_area.shape[1] * 2)
            
        a = img_src[23:img_src.shape[0], 0:img_src.shape[1]]
        # look for "ok" button and press enter if so
        h, w, _ = templates["ok"].shape
        res = cv2.matchTemplate(
            img_src[0:29, 69: 69+89],
            templates["ok"],
            cv2.TM_SQDIFF,
            mask=masks["ok"],
        )
        min_val, _, _, _ = cv2.minMaxLoc(res)
        # arbitrary magic number, handles the mouse hovering over the OK button
        if min_val < 60_000_000:
            for _ in range(settings["mining_ok_presses"]):
                platform.press_key("enter")
                time.sleep(settings["mining_ok_gap"])
            counter += 1
            print("Mining count: ", counter)
            ran_checker = False

        elapsed = time.perf_counter() - last_time
        # debug to see how fast the loop runs
        if DEBUG:
            fps = 1 / elapsed
            print(f"FPS: {round(fps, 2):06.2f}" + "-" * round(fps / 10))
            cv2.waitKey(1)

        # slow the loop down to 100Hz max
        # if elapsed < 0.001:
        #     time.sleep(0.001 - elapsed)
    # Region of Interest - we only need this area of the screen


def main(argv=None) -> None:
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
    arguments = parser.parse_args(argv)

    platform_name = sys.platform
    if platform_name == "win32":
        from platform_windows import Windows
        platform = Windows()
    elif platform_name == "linux":
        from platform_linux import Linux
        platform = Linux()
    else:
        raise OSError("Unsupported operating system!")

    try:
        settings = load_timings(
            arguments.timings_file, arguments.set, platform_name
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
    main(sys.argv[1:])
