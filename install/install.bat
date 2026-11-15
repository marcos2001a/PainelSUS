@echo off
setlocal
for %%I in ("%~dp0..") do set "PROJECT_DIR=%%~fI"
pushd "%PROJECT_DIR%"
if errorlevel 1 (
  echo Nao foi possivel acessar a pasta do projeto.
  pause
  exit /b 1
)

set "PYTHON_CMD="
py -3.12 --version >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=py -3.12"

if not defined PYTHON_CMD (
  py -3.13 --version >nul 2>nul
  if not errorlevel 1 set "PYTHON_CMD=py -3.13"
)

if not defined PYTHON_CMD (
  python -c "import sys; raise SystemExit(sys.version_info[:2] not in ((3, 12), (3, 13)))" >nul 2>nul
  if not errorlevel 1 set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
  if not exist "%~dp0python-3.13.12-amd64.exe" (
    echo Python 3.12 ou 3.13 nao foi encontrado e o instalador incluido esta ausente.
    popd
    pause
    exit /b 1
  )

  echo Instalando Python 3.13.12 e adicionando-o ao PATH...
  "%~dp0python-3.13.12-amd64.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_pip=1 Include_test=0 TargetDir="%LOCALAPPDATA%\Programs\Python\Python313"
  if errorlevel 1 (
    echo Nao foi possivel instalar o Python.
    popd
    pause
    exit /b 1
  )
  if not exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
    echo O instalador terminou, mas o executavel do Python nao foi encontrado.
    popd
    pause
    exit /b 1
  )
  set "PYTHON_CMD="%LOCALAPPDATA%\Programs\Python\Python313\python.exe""
)

if not exist ".venv\Scripts\python.exe" (
  call %PYTHON_CMD% -m venv .venv
  if errorlevel 1 (
    echo Nao foi possivel criar o ambiente virtual Python.
    popd
    pause
    exit /b 1
  )
) else (
  ".venv\Scripts\python.exe" -c "import sys; raise SystemExit(sys.version_info[:2] not in ((3, 12), (3, 13)))"
  if errorlevel 1 (
    echo O ambiente .venv existente nao usa Python 3.12 ou 3.13.
    echo Remova ou renomeie .venv e execute este instalador novamente.
    popd
    pause
    exit /b 1
  )
)

".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (
  echo Falha ao atualizar o pip.
  popd
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo Falha ao instalar as dependencias da aplicacao.
  popd
  pause
  exit /b 1
)

if not exist "data" mkdir "data"

echo.
echo Instalacao concluida. Inicie o painel com run.bat na pasta do projeto.
popd
endlocal
