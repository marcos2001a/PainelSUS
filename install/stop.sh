#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$PROJECT_DIR/data/dashboard.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "A aplicação não está em execução (arquivo PID ausente)."
  exit 0
fi

PID="$(cat "$PID_FILE")"
if [[ ! "$PID" =~ ^[0-9]+$ ]]; then
  echo "Erro: arquivo PID inválido: $PID_FILE." >&2
  exit 1
fi

if ! kill -0 "$PID" 2>/dev/null; then
  rm -f "$PID_FILE"
  echo "PID antigo removido; a aplicação não estava em execução."
  exit 0
fi

COMMAND="$(ps -p "$PID" -o args= 2>/dev/null || true)"
if [[ "$COMMAND" != *"-m uvicorn app.main:app --host 127.0.0.1 --port 8000"* ]]; then
  echo "Erro: o PID registrado ($PID) não corresponde ao servidor desta aplicação." >&2
  echo "O processo não foi encerrado; verifique $PID_FILE." >&2
  exit 1
fi

kill -TERM "$PID"
for _ in {1..20}; do
  if ! kill -0 "$PID" 2>/dev/null; then
    rm -f "$PID_FILE"
    echo "Aplicação parada."
    exit 0
  fi
  sleep 1
done

echo "Erro: o processo $PID não encerrou após SIGTERM. O arquivo PID foi mantido." >&2
exit 1
