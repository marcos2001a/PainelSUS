import re
import threading
from contextlib import asynccontextmanager
from pathlib import Path
import shutil

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import DATA_DIR, HOSPITAL_DATA_DIR, PROJECT_DIR
from .database import connect, initialize_database
from .ingest import FILE_PATTERN, discover_files, import_directory
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
    "SUM(submitted_quantity) AS submitted, SUM(approved_value_cents) AS value_cents "
    "FROM production WHERE cnes = ? AND competence BETWEEN ? AND ? "
    "GROUP BY competence, procedure_code"
)

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

def _run_hospital_import() -> None:
    try:
        result = import_hospital_directory(on_progress=_hospital_progress)
        HOSPITAL_IMPORT_STATE.update(running=False, status="done", result=result)
    except Exception as exc:
        HOSPITAL_IMPORT_STATE.update(running=False, status="error", message=str(exc))

def _start_hospital_import() -> dict:
    with IMPORT_LOCK:
        if IMPORT_STATE["running"] or HOSPITAL_IMPORT_STATE["running"]:
            raise HTTPException(status_code=409, detail="Já existe uma importação em andamento.")
        HOSPITAL_IMPORT_STATE.update(
            running=True, status="running", current=0, total=0,
            file=None, message=None, result=None,
        )
    threading.Thread(target=_run_hospital_import, daemon=True).start()
    return dict(HOSPITAL_IMPORT_STATE)

@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(PROJECT_DIR / "static" / "index.html")

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
def units(q: str = Query(default="", max_length=80)) -> list[dict]:
    term = q.strip()
    with connect() as connection:
        rows = connection.execute(
            "SELECT cnes, COALESCE(name, '') AS name FROM facilities "
            "WHERE cnes LIKE ? OR name LIKE ? "
            "ORDER BY name COLLATE NOCASE LIMIT 100",
            (f"%{term}%", f"%{term}%"),
        ).fetchall()
    return [{"cnes": row["cnes"], "name": row["name"]} for row in rows]

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
def start_hospital_import() -> dict:
    return _start_hospital_import()

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
        competence(ym): {"admissions": 0, "previous_admissions": 0, "deaths": 0, "stay_days": 0, "value_cents": 0}
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
        competence(ym): {"exam": 0, "procedure": 0, "prev_exam": 0, "prev_procedure": 0}
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
        item(code)["prev_qty"] += qty

    monthly_rows = []
    for ym in months:
        key = competence(ym)
        bucket = monthly[key]
        total = bucket["exam"] + bucket["procedure"]
        prev_total = bucket["prev_exam"] + bucket["prev_procedure"]
        monthly_rows.append({
            "competence": key,
            "label": month_label(ym),
            "exam_qty": bucket["exam"],
            "procedure_qty": bucket["procedure"],
            "total_qty": total,
            "prev_total_qty": prev_total,
            "diff": total - prev_total,
            "pct": pct(total, prev_total),
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
            "submitted": sum(data["submitted"] for data in items.values()),
            "value_cents": sum(data["value_cents"] for data in items.values()),
            "pct": pct(total_qty, prev_total_qty),
        },
        "monthly": monthly_rows,
        "exam_items": build("exam"),
        "procedure_items": build("procedure"),
    }
