@echo off
setlocal
cd /d "%~dp0"

py -3.12 --version >nul 2>nul
if errorlevel 1 (
  set PYTHON_VERSION=3.13
) else (
  set PYTHON_VERSION=3.12
)

if not exist ".venv\Scripts\python.exe" (
  py -%PYTHON_VERSION% -m venv .venv
  if errorlevel 1 (
    echo Nao foi possivel criar o ambiente Python. Verifique a instalacao do Python.
    exit /b 1
  )
)

".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

echo.
echo Instalacao concluida. Inicie o painel com run.bat.
endlocal
