import filecmp
import os
import re
import sqlite3
import shutil
import tempfile
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import (
    CNES_FILE,
    DATA_DIR,
    DATABASE_STORAGE_DIR,
    HOSPITAL_CNES_FILE,
    HOSPITAL_DATA_DIR,
    HOSPITAL_UPLOAD_DIR,
    PROJECT_DIR,
)
from .cnes import load_cnes_registry
from .database import (
    active_database_path,
    connect,
    initialize_database,
    prune_unlisted_units,
    select_database,
)
from .ingest import DEMOGRAPHICS_VERSION, FILE_PATTERN, discover_files, import_directory
from .hospital_ingest import FILE_PATTERN as HOSPITAL_FILE_PATTERN
from .hospital_ingest import discover_files as discover_hospital_files
from .hospital_ingest import import_directory as import_hospital_directory

IMPORT_LOCK = threading.Lock()
IMPORT_STATE = {"running": False, "current": 0, "total": 0, "file": None, "status": "idle", "message": None, "result": None}
HOSPITAL_IMPORT_STATE = {"running": False, "current": 0, "total": 0, "file": None, "status": "idle", "message": None, "result": None}
MONTH_RE = re.compile(r"(\d{4})-(\d{2})")
MONTH_NAMES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
MAX_MONTHS = 36
REPORT_SQL = (
    "SELECT competence, procedure_code, SUM(approved_quantity) AS qty, "
    "SUM(submitted_quantity) AS submitted, SUM(approved_value_cents) AS value_cents, "
    "SUM(submitted_value_cents) AS submitted_value_cents "
    "FROM production WHERE cnes = ? AND competence BETWEEN ? AND ? "
    "GROUP BY competence, procedure_code"
)


class UnitEntry(BaseModel):
    cnes: str
    name: str


class UnitSettings(BaseModel):
    ambulatory: list[UnitEntry]
    hospital: list[UnitEntry]


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield

app = FastAPI(title="Painel de Produção Ambulatorial", version="0.3.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=PROJECT_DIR / "static"), name="static")
app.mount("/img", StaticFiles(directory=PROJECT_DIR / "img"), name="img")

def parse_month(value: str) -> tuple[int, int]:
    match = MONTH_RE.fullmatch(value or "")
    if not match:
        raise HTTPException(status_code=400, detail="Use o formato AAAA-MM.")
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        raise HTTPException(status_code=400, detail="Mês inválido.")
    return year, month

def competence(ym: tuple[int, int]) -> str:
    return f"{ym[0]:04d}{ym[1]:02d}"

def month_label(ym: tuple[int, int]) -> str:
    return f"{MONTH_NAMES[ym[1] - 1]}/{str(ym[0])[2:]}"

def months_between(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    months = []
    year, month = start
    while (year, month) <= end:
        months.append((year, month))
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return months

def kind_of(code: str) -> str:
    return "exam" if code.startswith("02") else "procedure"

def pct(current: int, previous: int) -> float | None:
    if not previous:
        return None
    return round((current - previous) * 100 / previous, 1)

def rate(numerator: int, denominator: int) -> float | None:
    return round(numerator * 100 / denominator, 1) if denominator else None

def _progress(event: dict) -> None:
    IMPORT_STATE.update(
        current=event.get("current", 0),
        total=event.get("total", 0),
        file=event.get("file"),
        message=event.get("error"),
    )

def _run_import() -> None:
    try:
        result = import_directory(on_progress=_progress)
        IMPORT_STATE.update(running=False, status="done", result=result)
    except Exception as exc:
        IMPORT_STATE.update(running=False, status="error", message=str(exc))

def _start_import() -> dict:
    with IMPORT_LOCK:
        if IMPORT_STATE["running"] or HOSPITAL_IMPORT_STATE["running"]:
            raise HTTPException(status_code=409, detail="Já existe uma importação em andamento.")
        IMPORT_STATE.update(running=True, status="running", current=0, total=0, file=None, message=None, result=None)
    threading.Thread(target=_run_import, daemon=True).start()
    return dict(IMPORT_STATE)

def _hospital_progress(event: dict) -> None:
    HOSPITAL_IMPORT_STATE.update(
        current=event.get("current", 0), total=event.get("total", 0),
        file=event.get("file"), message=event.get("error"),
    )

def _run_hospital_import(files: list[Path] | None = None, data_dir: Path = HOSPITAL_DATA_DIR) -> None:
    try:
        result = import_hospital_directory(data_dir=data_dir, files=files, on_progress=_hospital_progress)
        HOSPITAL_IMPORT_STATE.update(running=False, status="done", result=result)
    except Exception as exc:
        HOSPITAL_IMPORT_STATE.update(running=False, status="error", message=str(exc))

def _start_hospital_import_locked(
    files: list[Path] | None = None,
    data_dir: Path = HOSPITAL_DATA_DIR,
) -> dict:
    if IMPORT_STATE["running"] or HOSPITAL_IMPORT_STATE["running"]:
        raise HTTPException(status_code=409, detail="Já existe uma importação em andamento.")
    HOSPITAL_IMPORT_STATE.update(
        running=True, status="running", current=0, total=0,
        file=None, message=None, result=None,
    )
    threading.Thread(target=_run_hospital_import, args=(files, data_dir), daemon=True).start()
    return dict(HOSPITAL_IMPORT_STATE)

def _start_hospital_import() -> dict:
    with IMPORT_LOCK:
        return _start_hospital_import_locked()

def _save_hospital_upload(upload: UploadFile) -> Path:
    name = Path(upload.filename or "").name
    if not HOSPITAL_FILE_PATTERN.fullmatch(name):
        raise HTTPException(status_code=400, detail=f"Nome de arquivo RDSP inválido: {name or 'sem nome'}.")
    HOSPITAL_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    destination = HOSPITAL_UPLOAD_DIR / name
    fd, temporary_name = tempfile.mkstemp(dir=HOSPITAL_UPLOAD_DIR, suffix=".uploading")
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as target:
            shutil.copyfileobj(upload.file, target)
        if destination.is_file() and filecmp.cmp(temporary_path, destination, shallow=False):
            temporary_path.unlink()
        else:
            temporary_path.replace(destination)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return destination


def _validate_unit_entries(entries: list[UnitEntry]) -> list[tuple[str, str]]:
    if not entries:
        raise HTTPException(status_code=400, detail="Cada lista deve conter ao menos uma unidade.")

    validated = []
    seen = set()
    for entry in entries:
        cnes = entry.cnes.strip()
        name = entry.name.strip()
        if not re.fullmatch(r"\d{7}", cnes):
            raise HTTPException(status_code=400, detail=f"CNES inválido: {cnes or '(vazio)'}.")
        if not name or any(character in name for character in "\t\r\n"):
            raise HTTPException(status_code=400, detail=f"Nome inválido para o CNES {cnes}.")
        if cnes in seen:
            raise HTTPException(status_code=400, detail=f"CNES duplicado: {cnes}.")
        seen.add(cnes)
        validated.append((cnes, name))
    return validated


def _write_unit_registry(path: Path, entries: list[tuple[str, str]]) -> None:
    content = "CNES\tNome da Unidade\n" + "".join(
        f"{cnes}\t{name}\n" for cnes, name in entries
    )
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        temporary_path.replace(path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(PROJECT_DIR / "static" / "index.html")


@app.get("/api/settings/units")
def get_unit_settings() -> dict:
    return {
        "ambulatory": [
            {"cnes": cnes, "name": name}
            for cnes, name in load_cnes_registry(CNES_FILE).items()
        ],
        "hospital": [
            {"cnes": cnes, "name": name}
            for cnes, name in load_cnes_registry(HOSPITAL_CNES_FILE).items()
        ],
    }


@app.put("/api/settings/units")
def save_unit_settings(settings: UnitSettings) -> dict:
    ambulatory = _validate_unit_entries(settings.ambulatory)
    hospital = _validate_unit_entries(settings.hospital)
    _write_unit_registry(CNES_FILE, ambulatory)
    _write_unit_registry(HOSPITAL_CNES_FILE, hospital)
    removed = prune_unlisted_units(
        {cnes for cnes, _ in ambulatory},
        {cnes for cnes, _ in hospital},
    )
    return {
        "message": (
            "Unidades salvas. Limpeza do banco: "
            f"{removed['ambulatory']} registros ambulatoriais, "
            f"{removed['hospital']} hospitalares e "
            f"{removed['facilities']} cadastros de unidades removidos."
        ),
        "removed": removed,
    }


@app.get("/api/settings/database")
def get_database_settings() -> dict:
    return {"name": active_database_path().name}


@app.post("/api/settings/database")
def upload_database(file: UploadFile = File(...)) -> dict:
    filename = Path(file.filename or "").name
    if not filename.lower().endswith(".sqlite3"):
        raise HTTPException(status_code=400, detail="Selecione um arquivo com extensão .sqlite3.")

    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).stem).strip("._-")
    stored_name = f"{stem or 'banco'}-{uuid.uuid4().hex[:8]}.sqlite3"
    temporary_path = None

    with IMPORT_LOCK:
        if IMPORT_STATE["running"] or HOSPITAL_IMPORT_STATE["running"]:
            raise HTTPException(status_code=409, detail="Não é possível trocar o banco durante uma importação.")

        DATABASE_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=DATABASE_STORAGE_DIR, suffix=".uploading"
        )
        temporary_path = Path(temporary_name)
        destination = DATABASE_STORAGE_DIR / stored_name
        try:
            with os.fdopen(descriptor, "wb") as target:
                shutil.copyfileobj(file.file, target)

            with temporary_path.open("rb") as source:
                if source.read(16) != b"SQLite format 3\x00":
                    raise HTTPException(status_code=400, detail="O arquivo selecionado não é um banco SQLite válido.")

            connection = sqlite3.connect(temporary_path)
            try:
                integrity = connection.execute("PRAGMA quick_check").fetchone()
            finally:
                connection.close()
            if integrity is None or integrity[0] != "ok":
                raise HTTPException(status_code=400, detail="O banco SQLite selecionado está corrompido.")

            initialize_database(temporary_path)
            temporary_path.replace(destination)
            select_database(stored_name)
        except sqlite3.DatabaseError as exc:
            raise HTTPException(status_code=400, detail=f"Não foi possível abrir o banco SQLite: {exc}") from exc
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        finally:
            temporary_path.unlink(missing_ok=True)

    return {"name": stored_name, "message": "Banco de dados selecionado com sucesso."}


@app.get("/api/status")
def status() -> dict:
    with connect() as connection:
        summary = connection.execute(
            "SELECT (SELECT COUNT(*) FROM source_files) AS imported_files, "
            "(SELECT COALESCE(SUM(record_count), 0) FROM source_files) AS source_records, "
            "COUNT(DISTINCT production.cnes) AS units, COUNT(production.procedure_code) AS groups, "
            "MIN(production.competence) AS first_competence, MAX(production.competence) AS last_competence "
            "FROM production"
        ).fetchone()
        file_count = len(discover_files(DATA_DIR)) if DATA_DIR.is_dir() else 0
    return {
        "data_directory_exists": DATA_DIR.is_dir(),
        "available_files": file_count,
        "imported_files": summary["imported_files"],
        "source_records": summary["source_records"],
        "units": summary["units"],
        "groups": summary["groups"],
        "first_competence": summary["first_competence"],
        "last_competence": summary["last_competence"],
        "import": dict(IMPORT_STATE),
    }

@app.post("/api/import")
def start_import(files: list[UploadFile] = File(default=[])) -> dict:
    if IMPORT_STATE["running"] or HOSPITAL_IMPORT_STATE["running"]:
        raise HTTPException(status_code=409, detail="Já existe uma importação em andamento.")
    if files:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        saved = 0
        for upload in files:
            name = Path(upload.filename or "").name
            if not FILE_PATTERN.fullmatch(name):
                continue
            with (DATA_DIR / name).open("wb") as target:
                shutil.copyfileobj(upload.file, target)
            saved += 1
        if not saved:
            raise HTTPException(status_code=400, detail="Nenhum arquivo no padrão PASPaamm[a-d].dbc.")
    return _start_import()

@app.get("/api/import/status")
def import_status() -> dict:
    return dict(IMPORT_STATE)

@app.get("/api/units")
def units(
    q: str = Query(default="", max_length=80),
    scope: str = Query(default="overview", pattern="^(overview|hospital)$"),
) -> list[dict]:
    term = q.strip().casefold()
    registry_path = CNES_FILE if scope == "overview" else HOSPITAL_CNES_FILE
    registry = load_cnes_registry(registry_path)
    return [
        {"cnes": cnes, "name": name}
        for cnes, name in sorted(
            registry.items(), key=lambda item: (item[1].casefold(), item[0])
        )
        if term in cnes or term in name.casefold()
    ][:100]

@app.get("/api/hospital/status")
def hospital_status() -> dict:
    with connect() as connection:
        summary = connection.execute(
            "SELECT (SELECT COUNT(*) FROM hospital_source_files) AS imported_files, "
            "(SELECT COALESCE(SUM(record_count), 0) FROM hospital_source_files) AS source_records, "
            "MIN(hospital_production.competence) AS first_competence, "
            "MAX(hospital_production.competence) AS last_competence "
            "FROM hospital_production"
        ).fetchone()
        file_count = len(discover_hospital_files(HOSPITAL_DATA_DIR)) if HOSPITAL_DATA_DIR.is_dir() else 0
        if HOSPITAL_UPLOAD_DIR.is_dir():
            file_count += len(discover_hospital_files(HOSPITAL_UPLOAD_DIR))
    return {
        "data_directory_exists": HOSPITAL_DATA_DIR.is_dir(),
        "available_files": file_count,
        "imported_files": summary["imported_files"],
        "source_records": summary["source_records"],
        "first_competence": summary["first_competence"],
        "last_competence": summary["last_competence"],
        "import": dict(HOSPITAL_IMPORT_STATE),
    }

@app.post("/api/hospital/import")
def start_hospital_import(files: list[UploadFile] = File(default=[])) -> dict:
    if not files:
        return _start_hospital_import()
    names = [Path(upload.filename or "").name for upload in files]
    if any(not HOSPITAL_FILE_PATTERN.fullmatch(name) for name in names):
        raise HTTPException(status_code=400, detail="Selecione somente arquivos no padrão RDSPaaaa.dbc.")
    if len(set(name.upper() for name in names)) != len(names):
        raise HTTPException(status_code=400, detail="A seleção contém arquivos com nomes repetidos.")
    with IMPORT_LOCK:
        if IMPORT_STATE["running"] or HOSPITAL_IMPORT_STATE["running"]:
            raise HTTPException(status_code=409, detail="Já existe uma importação em andamento.")
        selected_files = [_save_hospital_upload(upload) for upload in files]
        return _start_hospital_import_locked(selected_files, HOSPITAL_UPLOAD_DIR)

@app.get("/api/hospital/import/status")
def hospital_import_status() -> dict:
    return dict(HOSPITAL_IMPORT_STATE)

@app.get("/api/hospital/report")
def get_hospital_report(
    cnes: str = Query(pattern=r"^\d{7}$"),
    start: str = Query(max_length=7),
    end: str = Query(max_length=7),
    compare: bool = False,
) -> dict:
    if cnes not in load_cnes_registry(HOSPITAL_CNES_FILE):
        raise HTTPException(status_code=404, detail="CNES não cadastrado para a produção hospitalar.")
    start_ym, end_ym = parse_month(start), parse_month(end)
    months = months_between(start_ym, end_ym)
    if not months or len(months) > MAX_MONTHS:
        raise HTTPException(status_code=400, detail=f"Escolha um período de 1 a {MAX_MONTHS} meses, com início antes do fim.")
    prev_start = (start_ym[0] - 1, start_ym[1])
    prev_end = (end_ym[0] - 1, end_ym[1])
    query = (
        "SELECT competence, procedure_code, SUM(admissions) AS admissions, "
        "SUM(deaths) AS deaths, SUM(length_of_stay_days) AS stay_days, "
        "SUM(total_value_cents) AS value_cents FROM hospital_production "
        "WHERE cnes = ? AND competence BETWEEN ? AND ? GROUP BY competence, procedure_code"
    )
    with connect() as connection:
        facility = connection.execute("SELECT name FROM facilities WHERE cnes = ?", (cnes,)).fetchone()
        rows = connection.execute(query, (cnes, competence(start_ym), competence(end_ym))).fetchall()
        previous_rows = connection.execute(query, (cnes, competence(prev_start), competence(prev_end))).fetchall() if compare else []
        descriptions = {
            row["code"]: row["description"]
            for row in connection.execute("SELECT code, description FROM procedures").fetchall()
        }

    monthly = {
        competence(ym): {
            "admissions": 0, "previous_admissions": 0, "deaths": 0,
            "stay_days": 0, "value_cents": 0, "previous_value_cents": 0,
        }
        for ym in months
    }
    items = {}
    def item(code: str) -> dict:
        return items.setdefault(code, {
            "code": code, "name": descriptions.get(code, ""), "admissions": 0,
            "previous_admissions": 0, "deaths": 0, "stay_days": 0, "value_cents": 0,
        })

    for row in rows:
        bucket = monthly.get(row["competence"])
        if bucket is None:
            continue
        code = row["procedure_code"]
        target = item(code)
        for key, source in (("admissions", "admissions"), ("deaths", "deaths"), ("stay_days", "stay_days"), ("value_cents", "value_cents")):
            value = row[source] or 0
            bucket[key] += value
            target[key] += value
    for row in previous_rows:
        key = f"{int(row['competence'][:4]) + 1}{row['competence'][4:]}"
        if key in monthly:
            monthly[key]["previous_admissions"] += row["admissions"] or 0
            monthly[key]["previous_value_cents"] += row["value_cents"] or 0
            item(row["procedure_code"])["previous_admissions"] += row["admissions"] or 0

    monthly_rows = []
    for ym in months:
        key = competence(ym)
        row = monthly[key]
        row["competence"] = key
        row["label"] = month_label(ym)
        row["difference"] = row["admissions"] - row["previous_admissions"]
        row["percentage"] = pct(row["admissions"], row["previous_admissions"])
        monthly_rows.append(row)
    current_total = sum(row["admissions"] for row in monthly_rows)
    previous_total = sum(row["previous_admissions"] for row in monthly_rows)
    procedure_items = sorted(items.values(), key=lambda row: (-row["admissions"], row["code"]))
    for row in procedure_items:
        row["difference"] = row["admissions"] - row["previous_admissions"]
        row["percentage"] = pct(row["admissions"], row["previous_admissions"])
        row["mortality_rate"] = rate(row["deaths"], row["admissions"])
        row["average_stay"] = round(row["stay_days"] / row["admissions"], 1) if row["admissions"] else None

    return {
        "facility": {"cnes": cnes, "name": facility["name"] if facility else ""},
        "period": {"start": competence(start_ym), "end": competence(end_ym), "label": f"{month_label(start_ym)} a {month_label(end_ym)}"},
        "compare": compare,
        "summary": {
            "admissions": current_total,
            "previous_admissions": previous_total,
            "deaths": sum(row["deaths"] for row in monthly_rows),
            "stay_days": sum(row["stay_days"] for row in monthly_rows),
            "average_stay": round(sum(row["stay_days"] for row in monthly_rows) / current_total, 1) if current_total else 0,
            "value_cents": sum(row["value_cents"] for row in monthly_rows),
            "previous_value_cents": sum(row["previous_value_cents"] for row in monthly_rows),
            "average_value_cents": round(sum(row["value_cents"] for row in monthly_rows) / current_total) if current_total else None,
            "previous_average_value_cents": round(sum(row["previous_value_cents"] for row in monthly_rows) / previous_total) if previous_total else None,
            "average_value_difference_cents": (
                round(sum(row["value_cents"] for row in monthly_rows) / current_total)
                - round(sum(row["previous_value_cents"] for row in monthly_rows) / previous_total)
            ) if current_total and previous_total else None,
            "average_value_percentage": pct(
                round(sum(row["value_cents"] for row in monthly_rows) / current_total),
                round(sum(row["previous_value_cents"] for row in monthly_rows) / previous_total),
            ) if current_total and previous_total else None,
            "difference": current_total - previous_total,
            "percentage": pct(current_total, previous_total),
        },
        "monthly": monthly_rows,
        "procedure_items": procedure_items,
    }

@app.get("/api/report")
def get_report(
    cnes: str = Query(pattern=r"^\d{7}$"),
    start: str = Query(max_length=7),
    end: str = Query(max_length=7),
    compare: bool = False,
    exams: bool = True,
    procedures: bool = True,
) -> dict:
    if cnes not in load_cnes_registry(CNES_FILE):
        raise HTTPException(status_code=404, detail="CNES não cadastrado para a visão geral.")
    start_ym, end_ym = parse_month(start), parse_month(end)
    months = months_between(start_ym, end_ym)
    if not months or len(months) > MAX_MONTHS:
        raise HTTPException(
            status_code=400,
            detail=f"Escolha um período de 1 a {MAX_MONTHS} meses, com início antes do fim.",
        )
    prev_start = (start_ym[0] - 1, start_ym[1])
    prev_end = (end_ym[0] - 1, end_ym[1])

    def wanted(code: str) -> bool:
        kind = kind_of(code)
        return (kind == "exam" and exams) or (kind == "procedure" and procedures)

    with connect() as conn:
        facility = conn.execute("SELECT name FROM facilities WHERE cnes = ?", (cnes,)).fetchone()
        cur_rows = conn.execute(REPORT_SQL, (cnes, competence(start_ym), competence(end_ym))).fetchall()
        prev_rows = []
        if compare:
            prev_rows = conn.execute(REPORT_SQL, (cnes, competence(prev_start), competence(prev_end))).fetchall()
        names = {
            row["code"]: row["description"]
            for row in conn.execute("SELECT code, description FROM procedures").fetchall()
        }

    monthly = {
        competence(ym): {
            "exam": 0, "procedure": 0, "prev_exam": 0, "prev_procedure": 0,
            "submitted": 0, "value_cents": 0, "submitted_value_cents": 0,
            "previous_submitted": 0, "previous_value_cents": 0,
            "previous_submitted_value_cents": 0,
        }
        for ym in months
    }
    items: dict[str, dict] = {}

    def item(code: str) -> dict:
        if code not in items:
            items[code] = {
                "name": names.get(code, ""),
                "kind": kind_of(code),
                "qty": 0,
                "prev_qty": 0,
                "submitted": 0,
                "value_cents": 0,
            }
        return items[code]

    for row in cur_rows:
        code = row["procedure_code"]
        bucket = monthly.get(row["competence"])
        if bucket is None or not wanted(code):
            continue
        qty = row["qty"] or 0
        bucket[kind_of(code)] += qty
        bucket["submitted"] += row["submitted"] or 0
        bucket["value_cents"] += row["value_cents"] or 0
        bucket["submitted_value_cents"] += row["submitted_value_cents"] or 0
        found = item(code)
        found["qty"] += qty
        found["submitted"] += row["submitted"] or 0
        found["value_cents"] += row["value_cents"] or 0

    for row in prev_rows:
        code = row["procedure_code"]
        key = f"{int(row['competence'][:4]) + 1}{row['competence'][4:]}"
        bucket = monthly.get(key)
        if bucket is None or not wanted(code):
            continue
        qty = row["qty"] or 0
        bucket["prev_" + kind_of(code)] += qty
        bucket["previous_submitted"] += row["submitted"] or 0
        bucket["previous_value_cents"] += row["value_cents"] or 0
        bucket["previous_submitted_value_cents"] += row["submitted_value_cents"] or 0
        item(code)["prev_qty"] += qty

    monthly_rows = []
    for ym in months:
        key = competence(ym)
        bucket = monthly[key]
        total = bucket["exam"] + bucket["procedure"]
        prev_total = bucket["prev_exam"] + bucket["prev_procedure"]
        quantity_rate = rate(total, bucket["submitted"])
        previous_quantity_rate = rate(prev_total, bucket["previous_submitted"]) if compare else None
        value_rate = rate(bucket["value_cents"], bucket["submitted_value_cents"])
        previous_value_rate = rate(bucket["previous_value_cents"], bucket["previous_submitted_value_cents"]) if compare else None
        monthly_rows.append({
            "competence": key,
            "label": month_label(ym),
            "exam_qty": bucket["exam"],
            "procedure_qty": bucket["procedure"],
            "total_qty": total,
            "prev_total_qty": prev_total,
            "diff": total - prev_total,
            "pct": pct(total, prev_total),
            "submitted": bucket["submitted"],
            "previous_submitted": bucket["previous_submitted"],
            "value_cents": bucket["value_cents"],
            "previous_value_cents": bucket["previous_value_cents"],
            "submitted_value_cents": bucket["submitted_value_cents"],
            "previous_submitted_value_cents": bucket["previous_submitted_value_cents"],
            "quantity_approval_rate": quantity_rate,
            "previous_quantity_approval_rate": previous_quantity_rate,
            "quantity_approval_rate_change": round(quantity_rate - previous_quantity_rate, 1)
                if quantity_rate is not None and previous_quantity_rate is not None else None,
            "value_approval_rate": value_rate,
            "previous_value_approval_rate": previous_value_rate,
            "value_approval_rate_change": round(value_rate - previous_value_rate, 1)
                if value_rate is not None and previous_value_rate is not None else None,
        })

    def build(kind: str) -> list[dict]:
        rows = [
            {
                "code": code,
                "name": data["name"],
                "qty": data["qty"],
                "prev_qty": data["prev_qty"],
                "diff": data["qty"] - data["prev_qty"],
                "pct": pct(data["qty"], data["prev_qty"]),
                "submitted": data["submitted"],
                "value_cents": data["value_cents"],
            }
            for code, data in items.items()
            if data["kind"] == kind
        ]
        return sorted(rows, key=lambda r: (-r["qty"], r["code"]))

    total_qty = sum(r["total_qty"] for r in monthly_rows)
    prev_total_qty = sum(r["prev_total_qty"] for r in monthly_rows)
    total_submitted = sum(r["submitted"] for r in monthly_rows)
    previous_submitted = sum(r["previous_submitted"] for r in monthly_rows)
    total_value_cents = sum(r["value_cents"] for r in monthly_rows)
    previous_value_cents = sum(r["previous_value_cents"] for r in monthly_rows)
    total_submitted_value_cents = sum(r["submitted_value_cents"] for r in monthly_rows)
    previous_submitted_value_cents = sum(r["previous_submitted_value_cents"] for r in monthly_rows)
    quantity_approval_rate = rate(total_qty, total_submitted)
    previous_quantity_approval_rate = rate(prev_total_qty, previous_submitted) if compare else None
    value_approval_rate = rate(total_value_cents, total_submitted_value_cents)
    previous_value_approval_rate = rate(previous_value_cents, previous_submitted_value_cents) if compare else None

    return {
        "facility": {"cnes": cnes, "name": facility["name"] if facility else ""},
        "period": {
            "start": competence(start_ym),
            "end": competence(end_ym),
            "label": f"{month_label(start_ym)} a {month_label(end_ym)}",
        },
        "compare": compare,
        "exams": exams,
        "procedures": procedures,
        "summary": {
            "quantity": total_qty,
            "previous_quantity": prev_total_qty,
            "submitted": total_submitted,
            "previous_submitted": previous_submitted,
            "value_cents": total_value_cents,
            "previous_value_cents": previous_value_cents,
            "submitted_value_cents": total_submitted_value_cents,
            "previous_submitted_value_cents": previous_submitted_value_cents,
            "pct": pct(total_qty, prev_total_qty),
            "quantity_approval_rate": quantity_approval_rate,
            "previous_quantity_approval_rate": previous_quantity_approval_rate,
            "quantity_approval_rate_change": round(
                quantity_approval_rate - previous_quantity_approval_rate, 1
            ) if quantity_approval_rate is not None and previous_quantity_approval_rate is not None else None,
            "value_approval_rate": value_approval_rate,
            "previous_value_approval_rate": previous_value_approval_rate,
            "value_approval_rate_change": round(
                value_approval_rate - previous_value_approval_rate, 1
            ) if value_approval_rate is not None and previous_value_approval_rate is not None else None,
        },
        "monthly": monthly_rows,
        "exam_items": build("exam"),
        "procedure_items": build("procedure"),
    }

@app.get("/api/report/general")
def get_general_report(
    start: str = Query(max_length=7),
    end: str = Query(max_length=7),
    compare: bool = False,
    exams: bool = True,
    procedures: bool = True,
) -> dict:
    if not exams and not procedures:
        raise HTTPException(status_code=400, detail="Selecione exames, procedimentos ou ambos.")
    registry = load_cnes_registry(CNES_FILE)
    start_ym, end_ym = parse_month(start), parse_month(end)
    months = months_between(start_ym, end_ym)
    if not months or len(months) > MAX_MONTHS:
        raise HTTPException(
            status_code=400,
            detail=f"Escolha um período de 1 a {MAX_MONTHS} meses, com início antes do fim.",
        )

    query = (
        "SELECT cnes, procedure_code, SUM(approved_quantity) AS qty "
        "FROM production WHERE competence BETWEEN ? AND ? "
        "GROUP BY cnes, procedure_code"
    )
    previous_start = (start_ym[0] - 1, start_ym[1])
    previous_end = (end_ym[0] - 1, end_ym[1])
    with connect() as connection:
        current_rows = connection.execute(
            query, (competence(start_ym), competence(end_ym))
        ).fetchall()
        previous_rows = connection.execute(
            query, (competence(previous_start), competence(previous_end))
        ).fetchall() if compare else []
        facility_names = {
            row["cnes"]: row["name"]
            for row in connection.execute("SELECT cnes, name FROM facilities").fetchall()
        }

    totals: dict[str, dict[str, int]] = {}

    def add_rows(source_rows, prefix: str = "") -> None:
        for row in source_rows:
            cnes = row["cnes"]
            if cnes not in registry:
                continue
            category = "exams" if kind_of(row["procedure_code"]) == "exam" else "procedures"
            if (category == "exams" and not exams) or (category == "procedures" and not procedures):
                continue
            bucket = totals.setdefault(cnes, {
                "exams": 0, "procedures": 0,
                "previous_exams": 0, "previous_procedures": 0,
            })
            bucket[f"{prefix}{category}"] += row["qty"] or 0

    add_rows(current_rows)
    add_rows(previous_rows, "previous_")

    result_rows = []
    summary = {
        "exams": 0, "procedures": 0, "total": 0,
        "previous_exams": 0, "previous_procedures": 0, "previous_total": 0,
    }
    for cnes, values in totals.items():
        exam_qty = values["exams"]
        procedure_qty = values["procedures"]
        previous_exams = values["previous_exams"]
        previous_procedures = values["previous_procedures"]
        total = exam_qty + procedure_qty
        previous_total = previous_exams + previous_procedures
        if total == 0 and (not compare or previous_total == 0):
            continue
        row = {
            "cnes": cnes,
            "name": registry[cnes] or facility_names.get(cnes, ""),
            "exams": exam_qty,
            "procedures": procedure_qty,
            "total": total,
            "previous_exams": previous_exams,
            "previous_procedures": previous_procedures,
            "previous_total": previous_total,
        }
        for key in ("exams", "procedures", "total"):
            previous = row[f"previous_{key}"]
            difference = row[key] - previous
            row[f"{key}_difference"] = difference
            row[f"{key}_percentage"] = pct(row[key], previous)
            summary[key] += row[key]
            summary[f"previous_{key}"] += previous
        result_rows.append(row)

    for key in ("exams", "procedures", "total"):
        previous = summary[f"previous_{key}"]
        summary[f"{key}_difference"] = summary[key] - previous
        summary[f"{key}_percentage"] = pct(summary[key], previous)

    result_rows.sort(key=lambda row: (-row["total"], row["name"].casefold(), row["cnes"]))
    return {
        "period": {
            "start": competence(start_ym),
            "end": competence(end_ym),
            "label": f"{month_label(start_ym)} a {month_label(end_ym)}",
        },
        "compare": compare,
        "exams": exams,
        "procedures": procedures,
        "rows": result_rows,
        "summary": summary,
    }


@app.get("/api/report/diverse")
def get_diverse_report(
    start: str = Query(max_length=7),
    end: str = Query(max_length=7),
    cnes: str | None = Query(default=None, pattern=r"^\d{7}$"),
) -> dict:
    registry = load_cnes_registry(CNES_FILE)
    if cnes and cnes not in registry:
        raise HTTPException(status_code=404, detail="CNES não cadastrado para a visão geral.")

    start_ym, end_ym = parse_month(start), parse_month(end)
    months = months_between(start_ym, end_ym)
    if not months or len(months) > MAX_MONTHS:
        raise HTTPException(
            status_code=400,
            detail=f"Escolha um período de 1 a {MAX_MONTHS} meses, com início antes do fim.",
        )

    filters = ["competence BETWEEN ? AND ?", "approved_quantity > 0"]
    parameters: list[str] = [competence(start_ym), competence(end_ym)]
    if cnes:
        filters.append("cnes = ?")
        parameters.append(cnes)
    where_clause = " AND ".join(filters)

    def groups(
        connection: sqlite3.Connection,
        columns: tuple[str, ...],
        labeler,
        limit: int | None = None,
    ) -> dict:
        selected = ", ".join(columns)
        query = (
            f"SELECT {selected}, SUM(approved_quantity) AS quantity "
            f"FROM production_demographics WHERE {where_clause} "
            f"GROUP BY {selected} ORDER BY quantity DESC, {selected}"
        )
        rows = connection.execute(query, parameters).fetchall()
        total = sum(row["quantity"] or 0 for row in rows)
        visible_rows = rows if limit is None else rows[:limit]
        items = []
        for row in visible_rows:
            values = tuple(row[column] or "" for column in columns)
            quantity = row["quantity"] or 0
            items.append(
                {
                    "label": labeler(values),
                    "quantity": quantity,
                    "percentage": rate(quantity, total),
                }
            )
        return {
            "items": items,
            "total": total,
            "truncated": limit is not None and len(rows) > limit,
        }

    race_labels = {
        "01": "Branca",
        "02": "Preta",
        "03": "Parda",
        "04": "Amarela",
        "05": "Indígena",
        "99": "Sem informação (99)",
    }
    sex_labels = {"F": "Feminino", "M": "Masculino"}

    def code_label(value: str, labels: dict[str, str], empty_label: str) -> str:
        if not value:
            return empty_label
        return labels.get(value, f"Não classificado ({value})")

    with connect() as connection:
        totals = connection.execute(
            "SELECT COALESCE(SUM(approved_quantity), 0) AS quantity, "
            "COUNT(DISTINCT cnes) AS units "
            f"FROM production_demographics WHERE {where_clause}",
            parameters,
        ).fetchone()
        pending_reimport_files = connection.execute(
            "SELECT COUNT(*) FROM source_files WHERE demographics_version < ?",
            (DEMOGRAPHICS_VERSION,),
        ).fetchone()[0]
        dimensions = {
            "age": groups(
                connection,
                ("age_flag", "age_value"),
                lambda values: (
                    f"{values[1]} (PA_FLIDADE {values[0]})"
                    if values[1] and values[0]
                    else values[1] or "Não informado"
                ),
            ),
            "sex": groups(
                connection,
                ("sex",),
                lambda values: code_label(values[0], sex_labels, "Não informado"),
            ),
            "race": groups(
                connection,
                ("race",),
                lambda values: code_label(values[0], race_labels, "Não informado"),
            ),
            "cid_primary": groups(
                connection,
                ("cid_primary",),
                lambda values: (
                    "Sem CID informado (0000)"
                    if values[0] == "0000"
                    else values[0] or "Não informado"
                ),
                limit=100,
            ),
            "cid_secondary": groups(
                connection,
                ("cid_secondary",),
                lambda values: (
                    "Sem CID informado (0000)"
                    if values[0] == "0000"
                    else values[0] or "Não informado"
                ),
                limit=100,
            ),
            "cid_associated": groups(
                connection,
                ("cid_associated",),
                lambda values: (
                    "Sem CID informado (0000)"
                    if values[0] == "0000"
                    else values[0] or "Não informado"
                ),
                limit=100,
            ),
        }

    return {
        "period": {
            "start": competence(start_ym),
            "end": competence(end_ym),
            "label": f"{month_label(start_ym)} a {month_label(end_ym)}",
        },
        "unit": {
            "cnes": cnes,
            "name": registry.get(cnes, "") if cnes else "Todas as unidades",
        },
        "total_approved_quantity": totals["quantity"],
        "units": totals["units"],
        "pending_reimport_files": pending_reimport_files,
        "dimensions": dimensions,
    }
