"""Local web app for framing quotations."""

from __future__ import annotations

from flask import Flask, jsonify, request, send_from_directory

from import_prices import connect, ensure_database
from pricing import calculate_quote, get_board, get_moulding, search_boards, search_mouldings

app = Flask(__name__, static_folder="static", static_url_path="/static")


def db():
    ensure_database()
    return connect()


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/health")
def health():
    conn = db()
    mouldings = conn.execute("SELECT COUNT(*) FROM mouldings").fetchone()[0]
    boards = conn.execute("SELECT COUNT(*) FROM boards").fetchone()[0]
    conn.close()
    return jsonify({"ok": True, "mouldings": mouldings, "boards": boards})


@app.get("/api/mouldings")
def mouldings():
    query = request.args.get("q", "").strip()
    conn = db()
    if len(query) < 1:
        conn.close()
        return jsonify([])
    rows = search_mouldings(conn, query)
    conn.close()
    return jsonify(rows)


@app.get("/api/boards")
def boards():
    query = request.args.get("q", "").strip()
    conn = db()
    if len(query) < 1:
        conn.close()
        return jsonify([])
    rows = search_boards(conn, query)
    conn.close()
    return jsonify(rows)


@app.get("/api/mouldings/<code>")
def moulding_detail(code: str):
    conn = db()
    row = get_moulding(conn, code)
    conn.close()
    if not row:
        return jsonify({"error": "not found"}), 404
    return jsonify(row)


@app.get("/api/boards/<code>")
def board_detail(code: str):
    conn = db()
    row = get_board(conn, code)
    conn.close()
    if not row:
        return jsonify({"error": "not found"}), 404
    return jsonify(row)


@app.post("/api/quote")
def quote():
    payload = request.get_json(force=True, silent=True) or {}
    try:
        payload["width_mm"] = float(payload.get("width_mm") or 0)
        payload["height_mm"] = float(payload.get("height_mm") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "errors": ["Frame dimensions must be numbers."]}), 400

    conn = db()
    result = calculate_quote(conn, payload)
    conn.close()
    status = 200 if result["ok"] else 400
    return jsonify(result), status


if __name__ == "__main__":
    ensure_database()
    app.run(host="127.0.0.1", port=5055, debug=True)
