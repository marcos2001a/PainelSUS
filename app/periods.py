import re
from datetime import date

MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
MONTH_NAMES = (
    "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
    "Jul", "Ago", "Set", "Out", "Nov", "Dez",
)


def validate_month(value: str) -> str:
    if not MONTH_PATTERN.fullmatch(value):
        raise ValueError("Formato inválido.")
    return value.replace("-", "")


def month_sequence(start: str, end: str) -> list[str]:
    start_value = validate_month(start)
    end_value = validate_month(end)
    if start_value > end_value:
        raise ValueError("O início do período deve ser anterior ao fim.")

    start_date = date(int(start_value[:4]), int(start_value[4:]), 1)
    end_date = date(int(end_value[:4]), int(end_value[4:]), 1)
    months = []
    current = start_date
    while current <= end_date:
        months.append(f"{current.year:04d}{current.month:02d}")
        next_month = current.month + 1
        current = date(
            current.year + (1 if next_month == 13 else 0),
            1 if next_month == 13 else next_month,
            1,
        )
    return months


def previous_year_month(month: str) -> str:
    if not re.fullmatch(r"\d{6}", month):
        raise ValueError("Competência inválida.")
    return f"{int(month[:4]) - 1:04d}{month[4:]}"


def display_month(month: str) -> str:
    return f"{MONTH_NAMES[int(month[4:]) - 1]}/{month[:4]}"
