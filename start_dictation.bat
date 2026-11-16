@echo off
rem Double-click to start dictation in the background (no console window).
start "" "%~dp0Jarvis-v1\Scripts\pythonw.exe" "%~dp0app.py" --child
