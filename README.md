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
2. Install [uv](https://docs.astral.sh/uv/getting-started/installation/) (it manages the Python version and the environment for you, so you do not contaminate your system wide python installation).
3. Execute [prepare.bat](prepare.bat) or run `uv sync` in your console (this creates the .venv environment with all dependencies).
4. Execute [launch_python.bat](launch_python.bat) to open a console using the environment or copy the content to your console or skip this step and
5. Open HoloCure.
6. Start fishing by opening holocure_fishing.py or in your console "uv run holocure_fishing.py" or by any other means you want.
7. Select if you want to fish or mine.
8. Go to Holo House and start fishing or mining.
9. Enjoy!

# Getting Started on Linux

1. Make sure you have [uv](https://docs.astral.sh/uv/getting-started/installation/) installed.
2. Clone or download this repo.
3. Open HoloCure and head to the fishing area.
4. Execute the run.sh script. (on some systems you might have to make the script executable first)
```shell
$ chmod +x run.sh
$ ./run.sh
```
5. Start fishing!

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


# Building from source
This project uses [uv](https://docs.astral.sh/uv/). Dependencies are declared in
`pyproject.toml` and pinned in `uv.lock`.

* Install uv, then run:
`uv sync`

or

* python 3.11 or 3.12
* numpy (`pip install numpy`)
* opencv-python (`pip install opencv-python`)
* pywin32 on Windows (`pip install pywin32`)
* python-xlib on Linux (`pip install python-xlib`)

## Building exe from source
[//]: <> (TODO: Make a setup.py)
run:
`uv sync --group dev`
(the `dev` group installs nuitka)

then run:
```powershell
uv run python -m nuitka --include-data-files="img/360p/*.png=img/360p/" --onefile .\holocure_fishing.py
```
> make sure you are in the **Automated-Holocure-Fishing** folder

finally zip the **holocure_fishing.exe** and **img/** folder together

# License

This project is licensed under the GNU General Public License version 3.0. For the complete license text, see the file [LICENSE](LICENSE). This license applies to all files in this distribution.
