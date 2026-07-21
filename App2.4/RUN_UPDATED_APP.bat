@echo off
cd /d "%~dp0"
python -m streamlit run app2.4.py
if errorlevel 1 (
    echo.
    echo The app did not start. If dependencies are missing, run INSTALL_DEPENDENCIES.bat first.
    pause
)
