@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    set "GALAXY_PYTHON=py -3"
) else (
    set "GALAXY_PYTHON=python"
)

%GALAXY_PYTHON% -c "import sys, fastapi, uvicorn, webview; from importlib.metadata import version; release=lambda name: tuple(int(part) for part in version(name).split('.')[:2]); sys.exit(0 if (0, 115) <= release('fastapi') < (1,) and (0, 30) <= release('uvicorn') < (1,) and (6,) <= release('pywebview') < (7,) else 1)" >nul 2>nul
if errorlevel 1 (
    echo Installing Galaxy desktop web runtime...
    %GALAXY_PYTHON% -m pip install -r requirements-web.txt
    if errorlevel 1 (
        echo Galaxy desktop web runtime installation failed.
        pause
        exit /b 1
    )
)

%GALAXY_PYTHON% -c "import edge_tts, sys; sys.exit(0 if edge_tts.__version_info__[0] == 7 and edge_tts.__version_info__ >= (7, 2, 8) else 1)" >nul 2>nul
if errorlevel 1 (
    echo Installing Edge TTS voice engine...
    %GALAXY_PYTHON% -m pip install -r requirements-voice.txt
    if errorlevel 1 (
        echo Edge TTS installation failed. Starting with Windows SAPI available as the offline fallback.
    )
)

%GALAXY_PYTHON% run.py

if errorlevel 1 pause
