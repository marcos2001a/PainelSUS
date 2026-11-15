#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$PROJECT_DIR/data/dashboard.pid"
LOG_FILE="$PROJECT_DIR/data/dashboard.log"
PYTHON="$PROJECT_DIR/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  echo "Erro: ambiente .venv não encontrado. Execute bash install/install.sh primeiro." >&2
  exit 1
fi

if ! "$PYTHON" -c 'import uvicorn' >/dev/null 2>&1; then
  echo "Erro: uvicorn não está instalado em .venv. Execute bash install/install.sh." >&2
  exit 1
fi

mkdir -p "$PROJECT_DIR/data"

if [[ -f "$PID_FILE" ]]; then
  PID="$(cat "$PID_FILE")"
  if [[ ! "$PID" =~ ^[0-9]+$ ]]; then
    echo "Erro: arquivo PID inválido: $PID_FILE." >&2
    exit 1
  fi

  if kill -0 "$PID" 2>/dev/null; then
    COMMAND="$(ps -p "$PID" -o args= 2>/dev/null || true)"
    if [[ "$COMMAND" == *"-m uvicorn app.main:app --host 127.0.0.1 --port 8000"* ]]; then
      echo "A aplicação já está em execução (PID $PID)."
      exit 0
    fi
    echo "Erro: o PID registrado ($PID) pertence a outro processo; não será encerrado." >&2
    exit 1
  fi

  rm -f "$PID_FILE"
fi

cd "$PROJECT_DIR"
nohup "$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 \
  >>"$LOG_FILE" 2>&1 </dev/null &
PID=$!
printf '%s\n' "$PID" > "$PID_FILE"

sleep 1
if ! kill -0 "$PID" 2>/dev/null; then
  rm -f "$PID_FILE"
  echo "Erro: a aplicação não iniciou. Consulte $LOG_FILE." >&2
  exit 1
fi

echo "Aplicação iniciada (PID $PID)."
echo "Acesse http://127.0.0.1:8000"
echo "Log: $LOG_FILE"
