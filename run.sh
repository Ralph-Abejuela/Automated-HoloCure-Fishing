#!/bin/bash

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "Error: uv is not installed. See https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
fi

# Check if x11 session
if [ "$XDG_SESSION_TYPE" != "x11" ]; then
    echo "Warning: Couldn't determine if running on X11. Wayland and other compositors are not suppported."
fi

setup_env(){
    echo "Info: Installing dependencies with uv (this creates/updates .venv/)."
    uv sync

   remove_xlib_bad_file
}

remove_xlib_bad_file(){
    echo "Info: Removing line in Xlib dependency that breaks certain Linux systems"
    python_lib_dir=$(uv run python -c "import sysconfig; print(sysconfig.get_paths()['purelib'])")
    unix_connect_file="$python_lib_dir/Xlib/support/unix_connect.py"
    if [ -f "$unix_connect_file" ]; then
        sed -i '31,35d' "$unix_connect_file"
    else
        echo "Error: failed, $unix_connect_file not found."
        echo "Error: Please report this bug on github."
        rm -rf .venv
        exit 1
    fi

    uv run python -c "from Xlib.display import Display; Display()"
    return_code=$?

    if [ $return_code -eq 0 ]; then
        echo "Info: Line removal OK."
    else
        echo "Error: Removing the line didn't fix the issue"
        echo "Error: Please report this bug on github."
        rm -rf .venv
        exit 1
    fi
}

if [ ! -d ".venv" ]; then
    setup_env
else
    echo "Info: Using existing virtual environment .venv directory."
    uv sync
fi

echo "Info: Starting main program."
uv run holocure_fishing.py
