#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -r /etc/os-release ]]; then
  echo "Erro: não foi possível identificar a distribuição Linux." >&2
  exit 1
fi

# shellcheck disable=SC1091
source /etc/os-release

install_system_packages() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    if ! command -v sudo >/dev/null 2>&1; then
      echo "Erro: instale sudo ou execute como root para instalar dependências." >&2
      exit 1
    fi
    sudo "$@"
  fi
}

DISTRO=" ${ID:-} ${ID_LIKE:-} "
PYTHON_BIN=""

if [[ "$DISTRO" == *" debian "* || "$DISTRO" == *" ubuntu "* ]]; then
  echo "Distribuição detectada: ${PRETTY_NAME:-Debian/Ubuntu}"
  install_system_packages apt-get update

  if apt-cache show python3.12 2>/dev/null | grep -q '^Package: python3.12$'; then
    install_system_packages apt-get install -y --no-install-recommends \
      build-essential ca-certificates python3.12 python3.12-dev python3.12-venv
    PYTHON_BIN="$(command -v python3.12)"
  else
    install_system_packages apt-get install -y --no-install-recommends \
      build-essential ca-certificates python3 python3-dev python3-venv
    PYTHON_BIN="$(command -v python3)"
  fi
elif [[ "$DISTRO" == *" fedora "* || "$DISTRO" == *" rhel "* || "$DISTRO" == *" centos "* ]]; then
  echo "Distribuição detectada: ${PRETTY_NAME:-Fedora/RHEL}"
  install_system_packages dnf install -y ca-certificates gcc make

  if command -v python3.12 >/dev/null 2>&1; then
    install_system_packages dnf install -y python3.12-devel
    PYTHON_BIN="$(command -v python3.12)"
  elif command -v python3 >/dev/null 2>&1 &&
       python3 -c 'import sys; raise SystemExit(sys.version_info[:2] not in ((3, 12), (3, 13)))'; then
    install_system_packages dnf install -y python3-devel
    PYTHON_BIN="$(command -v python3)"
  else
    install_system_packages dnf install -y python3.12 python3.12-devel
    PYTHON_BIN="$(command -v python3.12)"
  fi
elif [[ "$DISTRO" == *" arch "* || "$DISTRO" == *" archlinux "* || "$DISTRO" == *" manjaro "* ]]; then
  echo "Distribuição detectada: ${PRETTY_NAME:-Arch Linux}"
  install_system_packages pacman -S --needed --noconfirm ca-certificates base-devel python
  PYTHON_BIN="$(command -v python3)"
else
  echo "Erro: distribuição não suportada: ${PRETTY_NAME:-${ID:-desconhecida}}." >&2
  echo "Distribuições suportadas: Debian/Ubuntu e derivados, Fedora/RHEL e Arch Linux." >&2
  exit 1
fi

if [[ -z "$PYTHON_BIN" ]] || ! "$PYTHON_BIN" -c \
  'import sys; raise SystemExit(sys.version_info[:2] not in ((3, 12), (3, 13)))'; then
  echo "Erro: é necessário Python 3.12 ou 3.13. A distribuição não forneceu uma versão compatível." >&2
  echo "Em Debian/Ubuntu, habilite um repositório que forneça python3.12 e execute novamente." >&2
  exit 1
fi

echo "Usando $("$PYTHON_BIN" --version)."
cd "$PROJECT_DIR"
if [[ -x ".venv/bin/python" ]]; then
  if ! .venv/bin/python -c \
    'import sys; raise SystemExit(sys.version_info[:2] not in ((3, 12), (3, 13)))'; then
    echo "Erro: .venv existente não usa Python 3.12 ou 3.13." >&2
    echo "Renomeie ou remova .venv manualmente e execute o instalador novamente." >&2
    exit 1
  fi
else
  echo "Criando ambiente virtual Python..."
  "$PYTHON_BIN" -m venv .venv
fi

echo "Instalando dependências da aplicação..."
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

mkdir -p data

echo
echo "Instalação concluída."
echo "Inicie a aplicação com: bash install/start.sh"
echo "Para parar ou reiniciar: bash install/stop.sh ou bash install/restart.sh"
echo "Depois, acesse http://127.0.0.1:8000"
