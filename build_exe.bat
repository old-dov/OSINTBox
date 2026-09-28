@echo off
setlocal

if "%~1"=="" (
  set "PYTHON=python"
) else (
  set "PYTHON=%~1"
)

echo [1/4] Installing dependencies...
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

echo [2/4] Building Rust companion CLI...
cargo build --release --locked --manifest-path rust\Cargo.toml -p osintbox-core --bin osintbox-rs
if errorlevel 1 (
  echo [ERREUR] Echec compilation Rust.
  exit /b 1
)

echo [3/4] Building EXE with PyInstaller...
"%PYTHON%" -m PyInstaller --clean --noconfirm --onefile --windowed --name OSINTBox --icon "pictures\osint_box.ico" --add-data "pictures\osint_box.ico;pictures" --add-data "osintbox\catalog.yaml;osintbox" osintbox_app.py
if errorlevel 1 (
  echo [ERREUR] Echec compilation EXE.
  exit /b 1
)

copy /Y "rust\target\release\osintbox-rs.exe" "dist\osintbox-rs.exe" >nul
if errorlevel 1 (
  echo [ERREUR] Impossible de copier la CLI Rust dans dist.
  exit /b 1
)

echo [4/4] Done.
echo EXE generated at: dist\OSINTBox.exe
echo Rust CLI generated at: dist\osintbox-rs.exe
echo.
echo NOTE: OSINTBox.exe orchestre 4 outils externes (Sherlock/Maigret/Holehe/theHarvester)
echo via sous-processus. Ils doivent etre pip-installes et accessibles sur le PATH systeme
echo (ou un venv active) pour que l'exe les trouve -- voir README.md.

endlocal
