import sqlite3
from contextlib import contextmanager
from .config import DATABASE_PATH
@contextmanager
def connect():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()
def initialize_database():
    with connect() as c:
        c.executescript("CREATE TABLE IF NOT EXISTS production (cnes TEXT, competence TEXT, procedure_code TEXT, approved_quantity INTEGER, approved_value_cents INTEGER);")
