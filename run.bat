@echo off
REM VRChat Asset Vault — double-click to run. No commands needed.
REM First run installs the app (PySide6) if it is not installed yet.
cd /d "%~dp0"
python -c "import vrchat_asset_vault" 2>nul
if errorlevel 1 (
    echo Installing VRChat Asset Vault, one moment...
    pip install -e .[gui]
    if errorlevel 1 (
        echo.
        echo Install failed. Make sure Python 3.11 or newer is installed
        echo from python.org and added to PATH, then double-click again.
        pause
        exit /b 1
    )
)
python -m vrchat_asset_vault gui
if errorlevel 1 (
    echo.
    echo The program closed with an error. See the message above.
    pause
)
