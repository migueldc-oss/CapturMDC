@echo off
REM Build CapturMDC.exe (Windows, single file, no console window).
cd /d "%~dp0"

".\.venv\Scripts\python.exe" make_icon.py

".\.venv\Scripts\python.exe" -m PyInstaller ^
  --noconfirm --clean --onefile --windowed --name CapturMDC --icon app.ico ^
  --collect-data customtkinter ^
  --exclude-module numpy --exclude-module asyncio --exclude-module multiprocessing ^
  --hidden-import pynput.keyboard._win32 ^
  --hidden-import pynput.mouse._win32 ^
  --hidden-import pynput._util.win32 ^
  --hidden-import pystray._win32 ^
  __main__.py

echo.
echo Executable: dist\CapturMDC.exe
