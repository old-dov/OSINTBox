@echo off
setlocal

if "%~1"=="" (
  set "PYTHON=python"
) else (
  set "PYTHON=%~1"
)

echo [1/3] Installing dependencies...
"%PYTHON%" -m pip install --upgrade pip
if errorlevel 1 (
  echo [ERREUR] Echec mise a jour pip.
  exit /b 1
)
"%PYTHON%" -m pip install -r requirements-dev.txt
if errorlevel 1 (
  echo [ERREUR] Echec installation dependances.
  exit /b 1
)

echo [2/3] Building EXE with PyInstaller...
"%PYTHON%" -m PyInstaller --clean --noconfirm --onefile --windowed --name OSINTBox --icon "pictures\osint_box.ico" --add-data "pictures\osint_box.ico;pictures" --add-data "osintbox\catalog.yaml;osintbox" osintbox_app.py
if errorlevel 1 (
  echo [ERREUR] Echec compilation EXE.
  exit /b 1
)

echo [3/3] Done.
echo EXE generated at: dist\OSINTBox.exe
echo.
echo NOTE: OSINTBox.exe orchestre 4 outils externes (Sherlock/Maigret/Holehe/theHarvester)
echo via sous-processus. Ils doivent etre pip-installes et accessibles sur le PATH systeme
echo (ou un venv active) pour que l'exe les trouve -- voir README.md.

endlocal
