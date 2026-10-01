# Automated HoloCure fishing & mining!
![10000 combo](https://github.com/Hexus-One/Automated-HoloCure-Fishing/assets/5473838/9d92ab91-d6f2-4f1d-8d19-3885dc5a0c7a)

This project aims to automate the fishing and mining minigames in HoloCure.

This works in any **windowed** resolution, and you can move the window around, resize it or have it in the background, BUT it doesn't work when the game is minimised. Works with multi-monitor setups.

# PLEASE DISABLE FULLSCREEN OPTIMIZATION ON HOLOCURE IF IT IS NOT WORKING
Open holocure steam page > Click the gear icon (settings) > Manage... > Browse local files > Right click 'HoloCure.exe' > Click 'Compatibility' tab > Enable the 'Disable fullscreen optimizations'

# Getting Started on Windows
~~[Video Tutorial](https://drive.google.com/file/d/14Xha8OWFiv26zBD4cYjMsHLD896q8RH4/view?usp=sharing) for absolute beginners.~~ (*working on making a new one*)

## Using from release
extract the '**Automated-HoloCure-Fishing-vX.X.X.zip**' and then open **holocure_fishing.exe**

## Using from source
1. Clone this project.
2. Execute [prepare.bat](prepare.bat) or copy content to your console (this will setup a python "test_env" environment so you do not contaminate your system wide python installation).
3. Execute [launch_python.bat](launch_python.bat) to open a console using the environment or copy the content to your console or skip this step and
4. Open HoloCure.
5. Start fishing by opening holocure_fishing.py or in your console "python holocure_fishing.py" or by any other means you want.
6. Select if you want to fish or mine.
6. Go to Holo House and start fishing or mining.
7. Enjoy!

# Getting Started on Linux

1. Make sure you have Python installed.
2. Clone or download this repo.
3. Open HoloCure and head to the fishing area.
4. Execute the run.sh script. (on some systems you might have to make the script executable first)
```shell
$ chmod +x run.sh
$ ./run.sh
```
6. Start fishing!

Notes (read first before running!)
- This has only been tested on X11. On Wayland, Holocure runs under the Xwayland compatibility layer so it **might** work, but I don't have a machine to test.
- Due to privacy issues, modern Linux applications and window managers don't listen to X key events when the window isn't focused. I am looking into workarounds but for now you'll have to keep the HoloCure window focused for the script to work.
- If you have Steam installed in a non-standard location the script might not be able to pick up your custom keybinds. To
    point the program to your keybinds:
    1. Locate HoloCure's `settings.json` file. Should be located under
    ```<steam install dir>/steamapps/compatdata/2420510/pfx/drive_c/users/steamuser/AppData/Local/HoloCure/settings.json```
    2. Open `platform_linux.py` and head over to the function named *def config_file_path*. Change the line so that it points to your settings.json file path.
    3. (Re-)start the script using run.sh. 
<hr>

### [Turn off Auto HDR](https://github.com/nopeAnon/Automated-HoloCure-Fishing/issues/8#issuecomment-1685914312)

<hr>

### Recommended settings when fishing

Any setting is fine! As long as the game is windowed and not fullscreen.


# Timings
Every delay the bot waits is a named timing you can change, without editing
code. Two front ends edit the same file:

```shell
$ python timings_gui.py            # a window
$ python timings_cli.py list       # the same settings in a terminal
```

The file is `timings.json` next to the scripts. It does not exist until you
save something, and until then the built-in defaults are used.

| Timing | Default | What it does |
| --- | --- | --- |
| `keypress_gap` | 15ms (30ms on Linux) | Wait between a key going down and coming back up. |
| `window_search_interval` | 1000ms | Wait between searches for the HoloCure window while it is closed. |
| `config_poll_interval` | 1000ms | How often HoloCure's settings.json is re-read for keybinds. |
| `fishing_key_delay` | 200ms | Wait after pressing a rhythm-game arrow. |
| `fishing_ok_gap` | 10ms | Wait between the Enter presses that dismiss the fishing prompt. |
| `fishing_ok_presses` | 6 | How many times Enter is pressed to dismiss the fishing prompt. |
| `fishing_loop_interval` | 10ms | Target duration of one fishing loop, which caps it at 100 Hz. |
| `mining_enter_delay` | 400ms | Wait after pressing Enter on the mining pointer. |
| `mining_ok_gap` | 10ms | Wait between the Enter presses that dismiss the mining prompt. |
| `mining_ok_presses` | 5 | How many times Enter is pressed to dismiss the mining prompt. |

Change one from a shell:

```shell
$ python timings_cli.py set mining_enter_delay=350ms
$ python timings_cli.py set fishing_ok_presses=4 --dry-run   # show, do not write
$ python timings_cli.py reset mining_enter_delay              # back to the default
$ python timings_cli.py path                                  # which file is used
```

Delays accept `350ms`, `0.35` or `1s`; they are stored in seconds. A file
location can be overridden with `--timings-file PATH` or the
`HCF_TIMINGS_FILE` environment variable.

A game that is already running picks up a change within a second, so you can
leave the editor open next to the game and watch what works.

For a single run, without touching the file:

```shell
$ python holocure_fishing.py --set fishing_key_delay=250ms
```

# Building from source
If you have python installed, run:
`pip install -r requirements.txt`

Or

* python 3.11.4 or later
* numpy (`pip install numpy`)
* opencv-python (`pip install opencv-python`)
* pywin32 (`pip install pywin32`)

The editor window uses tkinter, which ships with python on Windows and
usually on Linux (`sudo apt install python3-tk`). The CLI needs nothing
extra. Tests are stdlib only:

```shell
$ python -m unittest discover -s tests -t .
```

## Building exe from source
[//]: <> (TODO: Make a setup.py)
run:
`pip install nuitka`

then run:
```powershell
python -m nuitka --include-data-files="img/360p/*.png=img/360p/" --onefile .\holocure_fishing.py
```
> make sure you are in the **Automated-Holocure-Fishing** folder

finally zip the **holocure_fishing.exe** and **img/** folder together

# License

This project is licensed under the GNU General Public License version 3.0. For the complete license text, see the file [LICENSE](LICENSE). This license applies to all files in this distribution.
