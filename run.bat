@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Ambiente Python nao encontrado.
  echo Execute install\install.bat na pasta do projeto antes de iniciar.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
if errorlevel 1 (
  echo O painel encerrou com erro.
  pause
)
endlocal
