@echo off
title Jarvis - voice mode
cd /d "%~dp0"
echo.
echo   JARVIS - VOICE MODE
echo   Wait for "Hello, I am Jarvis", then say:  "Hey Jarvis, what is the time?"
echo   Close the Jarvis window app first, so only one Jarvis is listening.
echo   Press Ctrl+C to stop.
echo.
".venv\Scripts\python.exe" agent.py
pause
