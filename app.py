# -*- coding: utf-8 -*-
"""РМКО — рабочее место корпоративного отдела (Flask + SQLite).

Запуск:  python app.py            (порт 8000, доступен по сети)
Импорт:  python core.py           (или кнопка «Обновить из 1С» в интерфейсе)
"""
import os
import sys
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, jsonify, request, send_from_directory

import core

app = Flask(__name__, static_folder="static")


@app.get("/")
def index():
    return send_from_directory(os.path.join(core.BASE, "templates"), "index.html")


@app.get("/api/meta")
def meta():
    con = core.db()
    deals = [dict(r) for r in con.execute("SELECT DISTINCT city FROM deals")]
    li = con.execute("SELECT v FROM meta WHERE k='last_import'").fetchone()
    con.close()
    cities = sorted({d["city"] for d in deals if d["city"]})
    return jsonify({
        "cities": cities,
        "specialists": core.load_specialists(),
        "stages": core.STAGES, "next_steps": core.NEXT_STEPS,
        "reject_reasons": core.REJECT_REASONS, "delete_reasons": core.DELETE_REASONS,
        "check_statuses": core.CHECK_STATUSES,
        "last_import": li["v"] if li else None,
        "now": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })


@app.get("/api/deals")
def deals():
    con = core.db()
    rows = [dict(r) for r in con.execute("SELECT * FROM deals")]
    con.close()
    out = []
    for d in rows:
        d.update(core.derive(d))
        out.append(d)
    return jsonify(out)


@app.patch("/api/deal/<path:key>")
def patch_deal(key):
    user = request.headers.get("X-User") or "аноним"
    data = request.get_json(force=True) or {}
    fields = {k: v for k, v in data.items() if k in core.EDITABLE}
    if not fields:
        return jsonify({"error": "нет допустимых полей"}), 400
    con = core.db()
    old = con.execute("SELECT * FROM deals WHERE key=?", (key,)).fetchone()
    if old is None:
        con.close()
        return jsonify({"error": "сделка не найдена"}), 404
    old = dict(old)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    changes = {}
    for f, v in fields.items():
        v = v if v not in ("", None) else None
        if f in ("in_stock", "closing_docs") and v is not None:
            v = 1 if v in (1, True, "1", "true", "Да") else 0
        if v != old.get(f):
            changes[f] = v
            con.execute(
                "INSERT INTO history (deal_key, field, old_val, new_val, user, ts) VALUES (?,?,?,?,?,?)",
                (key, f, str(old.get(f) or ""), str(v or ""), user, now))
    if changes:
        changes["updated_at"] = now
        changes["updated_by"] = user
        changes["flag"] = ""  # менеджер отработал строку — снимаем NEW/UPDATE
        if not old.get("processed_at"):
            changes["processed_at"] = now
        # автодата закрытия при выборе закрывающего этапа
        if changes.get("stage") in core.CLOSED_STAGES and not (old.get("close_date") or changes.get("close_date")):
            changes["close_date"] = now[:10]
        sets = ", ".join(f"{c}=:{c}" for c in changes)
        params = dict(changes)
        params["key"] = key
        con.execute(f"UPDATE deals SET {sets} WHERE key=:key", params)
        con.commit()
    fresh = dict(con.execute("SELECT * FROM deals WHERE key=?", (key,)).fetchone())
    con.close()
    fresh.update(core.derive(fresh))
    return jsonify(fresh)


@app.get("/api/history/<path:key>")
def history(key):
    con = core.db()
    rows = [dict(r) for r in con.execute(
        "SELECT field, old_val, new_val, user, ts FROM history WHERE deal_key=? ORDER BY ts DESC LIMIT 100",
        (key,))]
    con.close()
    return jsonify(rows)


@app.post("/api/import")
def do_import():
    try:
        stats = core.import_xlsx()
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/specialists")
def add_specialist():
    data = request.json
    name = (data.get("name") or "").strip()
    city = (data.get("city") or "").strip()
    if not name or not city:
        return jsonify({"error": "Имя и город обязательны"}), 400
    
    con = core.db()
    con.execute("INSERT INTO specialists (name, city) VALUES (?, ?)", (name, city))
    con.commit()
    con.close()
    return jsonify({"success": True})


@app.delete("/api/specialists/<int:sid>")
def delete_specialist(sid):
    con = core.db()
    con.execute("DELETE FROM specialists WHERE id = ?", (sid,))
    con.commit()
    con.close()
    return jsonify({"success": True})


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if not os.path.exists(core.DB_PATH):
        print("Первый запуск: импортирую данные из xlsx...")
        print(core.import_xlsx(first=True))
    print("РМКО запущено: http://localhost:8000 (по сети — http://<ip-компьютера>:8000)")
    app.run(host="0.0.0.0", port=8000, debug=False)
