"""Quote calculations from frame size, moulding code and optional extras."""

from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCALES_PATH = ROOT / "data" / "scales.json"


def load_scales() -> dict:
    return json.loads(SCALES_PATH.read_text(encoding="utf-8"))


def money(value: float) -> float:
    return round(value + 1e-9, 2)


def billed_metres(width_mm: float, height_mm: float) -> dict:
    """Perimeter plus 0.5 m waste, then always round up to the next whole metre."""
    perimeter_metres = (2 * (width_mm + height_mm)) / 1000
    cut_metres = perimeter_metres + 0.5
    billed = float(math.ceil(cut_metres - 1e-9))
    rounded_up = not math.isclose(cut_metres, billed, rel_tol=0, abs_tol=1e-9)
    return {
        "perimeter_metres": round(perimeter_metres, 4),
        "cut_metres": round(cut_metres, 4),
        "billed_metres": billed,
        "rounded_up": rounded_up,
    }


def board_usage(frame_w: float, frame_h: float, board_w: int, board_h: int) -> dict:
    fits = (frame_w <= board_w and frame_h <= board_h) or (
        frame_w <= board_h and frame_h <= board_w
    )
    frame_area = frame_w * frame_h
    board_area = board_w * board_h
    percent = frame_area / board_area if board_area else 0
    return {
        "fits": fits,
        "percent_used": percent,
        "frame_area_mm2": frame_area,
        "board_area_mm2": board_area,
    }


def band_price(area_m2: float, bands: list[dict]) -> dict:
    for band in bands:
        max_area = band.get("max_area_m2")
        if max_area is None or area_m2 <= max_area:
            return {
                "price_excl": band["price_excl"],
                "max_area_m2": max_area,
            }
    last = bands[-1]
    return {"price_excl": last["price_excl"], "max_area_m2": last.get("max_area_m2")}


def lerp(start: float, end: float, t: float) -> float:
    return start + (end - start) * t


def glass_size_factor(area_m2: float, glass: dict) -> float:
    """1.0 at the reference sheet. Higher for small jobs, slightly lower for large."""
    ref = glass["reference"]
    ref_area = (ref["width_mm"] / 1000) * (ref["height_mm"] / 1000)
    small_area = float(glass["small_area_m2"])
    small_factor = float(glass["small_factor"])
    large_area = float(glass["large_area_m2"])
    large_factor = float(glass["large_factor"])

    if area_m2 <= small_area:
        return small_factor
    if area_m2 <= ref_area:
        t = (area_m2 - small_area) / (ref_area - small_area)
        return lerp(small_factor, 1.0, t)
    if area_m2 >= large_area:
        return large_factor
    t = (area_m2 - ref_area) / (large_area - ref_area)
    return lerp(1.0, large_factor, t)


def accessory_price(area_m2: float, accessories: dict) -> dict:
    threshold = float(accessories.get("large_area_m2", 1.0))
    base = float(accessories["base_excl"])
    large = float(accessories["large_excl"])
    if area_m2 > threshold:
        return {
            "price_excl": large,
            "tier": "large",
            "threshold_m2": threshold,
        }
    return {
        "price_excl": base,
        "tier": "base",
        "threshold_m2": threshold,
    }


def glass_price(area_m2: float, glass: dict) -> dict:
    ref = glass["reference"]
    ref_area = (ref["width_mm"] / 1000) * (ref["height_mm"] / 1000)
    base_rate = ref["price_excl"] / ref_area
    factor = glass_size_factor(area_m2, glass)
    raw = area_m2 * base_rate * factor
    minimum = float(glass["minimum_excl"])
    applied_min = raw < minimum
    return {
        "price_excl": max(minimum, raw),
        "base_rate": round(base_rate, 4),
        "size_factor": round(factor, 4),
        "effective_rate": round(base_rate * factor, 4),
        "minimum_applied": applied_min,
        "minimum_excl": minimum,
        "thickness_mm": glass.get("thickness_mm", 2),
        "label": glass.get("label", "2mm glass"),
    }


def line_totals(amount: float, vat_rate: float = 0.15, vat_inclusive: bool = False) -> dict:
    if vat_inclusive:
        price = money(amount)
        return {"excl": price, "vat": 0.0, "incl": price, "vat_inclusive": True}
    vat = money(amount * vat_rate)
    incl = money(amount + vat)
    return {
        "excl": money(amount),
        "vat": vat,
        "incl": incl,
        "vat_inclusive": False,
    }


def get_moulding(conn: sqlite3.Connection, code: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM mouldings WHERE code = ?",
        (code.strip().upper(),),
    ).fetchone()
    return dict(row) if row else None


def get_board(conn: sqlite3.Connection, code: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM boards WHERE code = ?",
        (code.strip().upper(),),
    ).fetchone()
    return dict(row) if row else None


def search_mouldings(conn: sqlite3.Connection, query: str, limit: int = 12) -> list[dict]:
    needle = f"%{query.strip().upper()}%"
    rows = conn.execute(
        """
        SELECT code, description, base, width_mm, material
        FROM mouldings
        WHERE code LIKE ? OR UPPER(description) LIKE ?
        ORDER BY
            CASE WHEN code LIKE ? THEN 0 ELSE 1 END,
            code
        LIMIT ?
        """,
        (needle, needle, f"{query.strip().upper()}%", limit),
    ).fetchall()
    return [dict(row) for row in rows]


def search_boards(conn: sqlite3.Connection, query: str, limit: int = 12) -> list[dict]:
    needle = f"%{query.strip().upper()}%"
    rows = conn.execute(
        """
        SELECT code, description, category, width_mm, height_mm, price, board_type
        FROM boards
        WHERE code LIKE ? OR UPPER(description) LIKE ? OR UPPER(category) LIKE ?
        ORDER BY
            CASE WHEN code LIKE ? THEN 0 ELSE 1 END,
            code
        LIMIT ?
        """,
        (needle, needle, needle, f"{query.strip().upper()}%", limit),
    ).fetchall()
    return [dict(row) for row in rows]


def calculate_quote(conn: sqlite3.Connection, payload: dict) -> dict:
    scales = load_scales()
    vat_rate = float(scales.get("vat_rate", 0.15))
    width_mm = float(payload["width_mm"])
    height_mm = float(payload["height_mm"])
    errors = []

    if width_mm <= 0 or height_mm <= 0:
        errors.append("Frame dimensions must be greater than zero.")

    moulding = get_moulding(conn, payload.get("frame_code", ""))
    if not moulding:
        errors.append(f"Frame code '{payload.get('frame_code', '')}' was not found in the price lists.")

    mount = None
    if payload.get("mount_needed"):
        mount = get_board(conn, payload.get("mount_code", ""))
        if not mount:
            errors.append(f"Mount board code '{payload.get('mount_code', '')}' was not found.")

    if errors:
        return {"ok": False, "errors": errors}

    length = billed_metres(width_mm, height_mm)
    frame_excl = length["billed_metres"] * moulding["base"]
    frame_line = {
        "type": "frame",
        "code": moulding["code"],
        "description": moulding["description"],
        "material": moulding["material"],
        "width_mm": moulding["width_mm"],
        "base_per_m": moulding["base"],
        "cut_metres": length["cut_metres"],
        "billed_metres": length["billed_metres"],
        "rounded_up": length["rounded_up"],
        "perimeter_metres": length["perimeter_metres"],
        **line_totals(frame_excl, vat_rate),
    }

    lines = [frame_line]
    area_m2 = (width_mm * height_mm) / 1_000_000

    if mount:
        usage = board_usage(width_mm, height_mm, mount["width_mm"], mount["height_mm"])
        if not usage["fits"]:
            return {
                "ok": False,
                "errors": [
                    f"{mount['code']} is {mount['width_mm']} × {mount['height_mm']} mm, "
                    f"which is too small for a {width_mm:g} × {height_mm:g} mm frame."
                ],
            }
        board_excl = mount["price"] if usage["percent_used"] > 0.5 else usage["percent_used"] * mount["price"]
        full_sheet = usage["percent_used"] > 0.5
        lines.append(
            {
                "type": "mount_board",
                "code": mount["code"],
                "description": mount["description"],
                "category": mount["category"],
                "sheet_w_mm": mount["width_mm"],
                "sheet_h_mm": mount["height_mm"],
                "sheet_price": mount["price"],
                "percent_used": round(usage["percent_used"], 6),
                "full_sheet": full_sheet,
                **line_totals(board_excl, vat_rate),
            }
        )

    if payload.get("glass_needed"):
        priced = glass_price(area_m2, scales["glass"])
        lines.append(
            {
                "type": "glass",
                "description": priced["label"],
                "status": scales["glass"]["status"],
                "area_m2": round(area_m2, 4),
                "thickness_mm": priced["thickness_mm"],
                "base_rate": priced["base_rate"],
                "size_factor": priced["size_factor"],
                "effective_rate": priced["effective_rate"],
                "minimum_applied": priced["minimum_applied"],
                "minimum_excl": priced["minimum_excl"],
                **line_totals(priced["price_excl"], vat_inclusive=True),
            }
        )

    if payload.get("accessories_needed"):
        priced = accessory_price(area_m2, scales["accessories"])
        lines.append(
            {
                "type": "accessories",
                "description": "Accessories",
                "status": scales["accessories"]["status"],
                "area_m2": round(area_m2, 4),
                "tier": priced["tier"],
                "threshold_m2": priced["threshold_m2"],
                **line_totals(priced["price_excl"], vat_inclusive=True),
            }
        )

    materials = money(sum(line["incl"] for line in lines))
    multiplier = float(scales.get("job_multiplier", {}).get("factor", 2.85))
    quote_total = money(materials * multiplier)

    return {
        "ok": True,
        "vat_rate": vat_rate,
        "frame": {
            "width_mm": width_mm,
            "height_mm": height_mm,
            "area_m2": round(area_m2, 4),
        },
        "lines": lines,
        "totals": {
            "materials": materials,
            "multiplier": multiplier,
            "quote": quote_total,
        },
        "notes": {
            "glass": scales["glass"]["note"],
            "accessories": scales["accessories"]["note"],
            "job_multiplier": scales.get("job_multiplier", {}).get("note", ""),
        },
    }
