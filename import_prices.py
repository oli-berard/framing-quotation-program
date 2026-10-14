"""Parse Serame March 2026 PDFs into SQLite."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
PDF_DIR = DATA / "price-lists"
DB_PATH = DATA / "framing.db"
CATALOG_PATH = DATA / "catalog.json"

VAT_RATE = 0.15

MOULDING_RE = re.compile(
    r"^([A-Z0-9][A-Z0-9.\-]*)\s+(.+?)\s+"
    r"(\d+\.\d+|#VALUE!)\s+(\d+\.\d+|#VALUE!)\s+(\d+)\s*$"
)
BOARD_RE = re.compile(
    r"^([A-Z0-9][A-Z0-9.\-]*)\s+(.+?)\s+"
    r"(\d+)\s*MM\s*X\s*(\d+)\s*MM\s+"
    r"([\d,]+\.\d+)\s+([\d,]+\.\d+)",
    re.IGNORECASE,
)

SKIP_PREFIXES = (
    "CODE",
    "PRICES",
    "WWW.",
    "T'C",
    "---",
    "WOOD MOULDING",
    "SYNTHETIC MOULDING",
    "MATBOARD",
    "FOAM CORE PRICE",
    "MARCH",
    "VALID",
    "SERAME",
    "JHB",
    "CPT",
    "AVAILABLE",
    "CANVAS STRETCHER",
    "WIDTH",
    "REGULAR FOAM",
    "ARCHIVAL FOAM",
    "BLACK CORE FOAM",
    "MOULDING PRICE LIST",
    "LAMINATED",
)

BOARD_CATEGORY_PREFIXES = (
    "PETERBORO",
    "FATG CLASS",
)


def pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def should_skip(line: str) -> bool:
    upper = line.strip().upper()
    return not upper or any(upper.startswith(prefix) for prefix in SKIP_PREFIXES)


def money(value: str) -> float | None:
    if value == "#VALUE!":
        return None
    return float(value.replace(",", ""))


def parse_mouldings(text: str, material: str, source: str) -> list[dict]:
    rows = []
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if should_skip(line):
            continue
        match = MOULDING_RE.match(line)
        if not match:
            continue
        base = money(match.group(3))
        if base is None:
            continue
        rows.append(
            {
                "code": match.group(1).upper(),
                "description": match.group(2).strip(),
                "base": base,
                "base_50m": money(match.group(4)),
                "width_mm": int(match.group(5)),
                "material": material,
                "source": source,
            }
        )
    return rows


def parse_boards(text: str, board_type: str, source: str) -> list[dict]:
    rows = []
    category = "Uncategorised"
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if not line:
            continue
        upper = line.upper()
        if any(upper.startswith(prefix) for prefix in BOARD_CATEGORY_PREFIXES):
            category = line.strip()
            continue
        if should_skip(line):
            continue
        match = BOARD_RE.match(line)
        if not match:
            continue
        width_mm = int(match.group(3))
        height_mm = int(match.group(4))
        # Museum board OCR/print error: 101MM instead of 1016MM
        if width_mm == 101 and height_mm >= 1500:
            width_mm = 1016
        rows.append(
            {
                "code": match.group(1).upper(),
                "description": match.group(2).strip(),
                "category": category,
                "width_mm": width_mm,
                "height_mm": height_mm,
                "price": money(match.group(5)),
                "price_25plus": money(match.group(6)),
                "board_type": board_type,
                "source": source,
            }
        )
    return rows


def foam_category(code: str) -> str:
    if code.startswith("CC"):
        return "Regular foam core"
    if code.startswith(("AF", "AC")):
        return "Archival foam core"
    if code.startswith("BB"):
        return "Black core foam core"
    return "Foam core"


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS mouldings;
        DROP TABLE IF EXISTS boards;
        DROP TABLE IF EXISTS meta;

        CREATE TABLE mouldings (
            code TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            base REAL NOT NULL,
            base_50m REAL,
            width_mm INTEGER,
            material TEXT NOT NULL,
            source TEXT NOT NULL
        );

        CREATE TABLE boards (
            code TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            category TEXT,
            width_mm INTEGER NOT NULL,
            height_mm INTEGER NOT NULL,
            price REAL NOT NULL,
            price_25plus REAL,
            board_type TEXT NOT NULL,
            source TEXT NOT NULL
        );

        CREATE TABLE meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )


def import_catalog(db_path: Path = DB_PATH) -> dict:
    wood_pdf = PDF_DIR / "Wood Mouldings - March 2026.pdf"
    synth_pdf = PDF_DIR / "Synthetic Mouldings - March 2026.pdf"
    veneer_pdf = PDF_DIR / "Laminated Wood Veneer Mouldings - March 2026.pdf"
    mat_pdf = PDF_DIR / "Matboards - March 2026.pdf"
    foam_pdf = PDF_DIR / "Foam Core - March 2026.pdf"

    mouldings = parse_mouldings(pdf_text(wood_pdf), "wood", wood_pdf.name)
    mouldings += parse_mouldings(pdf_text(synth_pdf), "synthetic", synth_pdf.name)
    mouldings += parse_mouldings(pdf_text(veneer_pdf), "laminated veneer", veneer_pdf.name)

    boards = parse_boards(pdf_text(mat_pdf), "matboard", mat_pdf.name)
    foam = parse_boards(pdf_text(foam_pdf), "foam_core", foam_pdf.name)
    for row in foam:
        row["category"] = foam_category(row["code"])
    boards += foam

    # Keep first occurrence if a stretcher code appears on both moulding lists
    unique_mouldings = {}
    for row in mouldings:
        unique_mouldings.setdefault(row["code"], row)
    mouldings = list(unique_mouldings.values())

    unique_boards = {}
    for row in boards:
        unique_boards.setdefault(row["code"], row)
    boards = list(unique_boards.values())

    conn = connect(db_path)
    create_schema(conn)
    conn.executemany(
        """
        INSERT INTO mouldings (code, description, base, base_50m, width_mm, material, source)
        VALUES (:code, :description, :base, :base_50m, :width_mm, :material, :source)
        """,
        mouldings,
    )
    conn.executemany(
        """
        INSERT INTO boards (
            code, description, category, width_mm, height_mm,
            price, price_25plus, board_type, source
        )
        VALUES (
            :code, :description, :category, :width_mm, :height_mm,
            :price, :price_25plus, :board_type, :source
        )
        """,
        boards,
    )
    conn.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?)",
        ("price_list", "Serame March 2026"),
    )
    conn.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?)",
        ("vat_rate", str(VAT_RATE)),
    )
    conn.commit()
    conn.close()

    catalog = {
        "price_list": "Serame March 2026",
        "vat_rate": VAT_RATE,
        "mouldings": mouldings,
        "boards": boards,
    }
    CATALOG_PATH.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    static_catalog = ROOT / "static" / "catalog.json"
    static_catalog.write_text(
        json.dumps(
            {
                "mouldings": [
                    {
                        "code": row["code"],
                        "description": row["description"],
                        "base": row["base"],
                        "width_mm": row["width_mm"],
                        "material": row["material"],
                    }
                    for row in mouldings
                ],
                "boards": [
                    {
                        "code": row["code"],
                        "description": row["description"],
                        "category": row["category"],
                        "width_mm": row["width_mm"],
                        "height_mm": row["height_mm"],
                        "price": row["price"],
                        "board_type": row["board_type"],
                    }
                    for row in boards
                ],
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return {
        "mouldings": len(mouldings),
        "boards": len(boards),
        "db": str(db_path),
    }


def ensure_database(db_path: Path = DB_PATH) -> None:
    if not db_path.exists():
        import_catalog(db_path)
        return
    conn = connect(db_path)
    try:
        moulding_count = conn.execute("SELECT COUNT(*) FROM mouldings").fetchone()[0]
        board_count = conn.execute("SELECT COUNT(*) FROM boards").fetchone()[0]
    except sqlite3.Error:
        moulding_count = board_count = 0
    finally:
        conn.close()
    if moulding_count == 0 or board_count == 0:
        import_catalog(db_path)


if __name__ == "__main__":
    summary = import_catalog()
    print(
        f"Imported {summary['mouldings']} mouldings and {summary['boards']} boards into {summary['db']}"
    )
