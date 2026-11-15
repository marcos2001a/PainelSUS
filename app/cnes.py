import hashlib
import re
from pathlib import Path


def load_cnes_registry(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise FileNotFoundError(f"Arquivo de CNES não encontrado: {path}")

    registry = {}
    with path.open(encoding="utf-8-sig") as source:
        for line_number, line in enumerate(source, start=1):
            fields = line.rstrip("\r\n").split("\t", 1)
            cnes = fields[0].strip()
            if not cnes or cnes.upper() == "CNES":
                continue
            if not re.fullmatch(r"\d{7}", cnes):
                raise ValueError(f"{path}:{line_number}: CNES inválido: {cnes}")
            registry[cnes] = fields[1].strip() if len(fields) > 1 else ""

    if not registry:
        raise ValueError(f"Arquivo de CNES sem unidades cadastradas: {path}")
    return registry


def cnes_filter_signature(registry: dict[str, str]) -> str:
    codes = "\n".join(sorted(registry))
    return hashlib.sha256(codes.encode("ascii")).hexdigest()
