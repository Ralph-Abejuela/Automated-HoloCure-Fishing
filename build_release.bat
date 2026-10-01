@echo off
REM Build the Windows binary that goes in the release.
REM
REM Produces dist\Automated-HoloCure-Fishing\ with holocure_fishing.exe at the
REM top of it, zipped as dist\Automated-HoloCure-Fishing-vX.Y.Z.zip. It is a
REM folder rather than a single file: it starts faster, and when something
REM goes wrong the templates and timings.json it is reading are right there.
REM
REM Needs the dev dependencies: uv sync --group dev.

setlocal

REM The version in the asset name is what the README tells people to look for.
set VERSION=v0.1.0

if not exist ".venv\Scripts\python.exe" (
    echo Error: no .venv here. Run "uv sync --group dev" first.
    exit /b 1
)

echo Building Automated HoloCure Fishing for Windows x64...
uv run --group dev python -m nuitka ^
    --standalone ^
    --assume-yes-for-downloads ^
    --windows-console-mode=force ^
    --enable-plugin=tk-inter ^
    --output-filename=holocure_fishing.exe ^
    --output-dir=dist ^
    --include-data-dir=img=img ^
    --include-data-files=timings.json=timings.json ^
    --include-data-files=LICENSE=LICENSE ^
    --include-data-files=README.md=README.md ^
    --jobs=4 ^
    holocure_fishing.py
if errorlevel 1 (
    echo Error: the build failed.
    exit /b 1
)

REM Nuitka leaves the program in dist\holocure_fishing.dist next to a
REM dist\holocure_fishing.build of intermediates. The build folder is worth
REM deleting - it is most of the size and nothing needs it - and the dist
REM folder is renamed to the name the release zip is named after, so the exe
REM ends up at the top of the zip instead of a folder down.
if exist "dist\Automated-HoloCure-Fishing" rmdir /s /q "dist\Automated-HoloCure-Fishing"
if exist "dist\holocure_fishing.build" rmdir /s /q "dist\holocure_fishing.build"
move "dist\holocure_fishing.dist" "dist\Automated-HoloCure-Fishing" >nul
if errorlevel 1 (
    echo Error: could not put the build folder where the zip expects it.
    exit /b 1
)

echo Zipping...
powershell -NoProfile -Command ^
    "Compress-Archive -Path 'dist\Automated-HoloCure-Fishing' -DestinationPath 'dist\Automated-HoloCure-Fishing-%VERSION%.zip' -Force"
if errorlevel 1 (
    echo Error: the zip failed.
    exit /b 1
)

echo Done: dist\Automated-HoloCure-Fishing-%VERSION%.zip
endlocal