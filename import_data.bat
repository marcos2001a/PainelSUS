@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Execute install.bat antes de importar os arquivos.
  exit /b 1
)

".venv\Scripts\python.exe" -m app.ingest %*
endlocal
