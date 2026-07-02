# -*- coding: utf-8 -*-
"""РМКО — рабочее место корпоративного отдела (Flask + SQLite).

Запуск:  python app.py            (порт 8000, доступен по сети)
Импорт:  python core.py           (или кнопка «Обновить из 1С» в интерфейсе)
"""
import os
import sys
from datetime import datetime, timedelta
import random
import string
import smtplib
from email.message import EmailMessage
from functools import wraps
from urllib.parse import unquote

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from flask import Flask, jsonify, request, send_from_directory, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash

import core

app = Flask(__name__, static_folder="static")
app.secret_key = os.getenv("SECRET_KEY", "super-secret-rmko-key-12345")

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Unauthorized"}), 401
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function

@app.get("/")
@login_required
def index():
    return send_from_directory(os.path.join(core.BASE, "templates"), "index.html")


@app.get("/api/meta")
@login_required
def meta():
    con = core.db()
    deals = [dict(r) for r in con.execute("SELECT DISTINCT city FROM deals")]
    li = con.execute("SELECT v FROM meta WHERE k='last_import'").fetchone()
    con.close()
    cities = sorted({d["city"] for d in deals if d["city"]})
    return jsonify({
        "user": {"name": session.get("username"), "needs_password_change": session.get("needs_password_change")},
        "cities": cities,
        "specialists": core.load_specialists(),
        "stages": core.STAGES, "next_steps": core.NEXT_STEPS,
        "reject_reasons": core.REJECT_REASONS, "delete_reasons": core.DELETE_REASONS,
        "check_statuses": core.CHECK_STATUSES, "goods_check": core.GOODS_CHECK,
        "last_import": li["v"] if li else None,
        "now": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })


@app.get("/api/deals")
@login_required
def deals():
    con = core.db()
    # Оптимизированный запрос - получаем deals и user_action_keys одним соединением
    rows = [dict(r) for r in con.execute("SELECT * FROM deals")]
    # Кэшируем результат запроса истории для ускорения
    history_rows = con.execute("SELECT DISTINCT deal_key FROM history WHERE user != '1С-импорт'").fetchall()
    user_action_keys = {r["deal_key"] for r in history_rows}
    con.close()
    out = []
    for d in rows:
        d.update(core.derive(d, user_action_keys=user_action_keys))
        out.append(d)
    return jsonify(out)


@app.patch("/api/deal/<path:key>")
@login_required
def patch_deal(key):
    selected_user = (request.headers.get("X-User") or "").strip()
    user = unquote(selected_user) if selected_user else session.get("username", "аноним")
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
        if f == "closing_docs" and v is not None:
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
    has_action = con.execute("SELECT 1 FROM history WHERE deal_key=? AND user != '1С-импорт' LIMIT 1", (key,)).fetchone() is not None
    con.close()
    fresh.update(core.derive(fresh, user_action_keys={key} if has_action else set()))
    return jsonify(fresh)


@app.get("/api/history/<path:key>")
@login_required
def history(key):
    con = core.db()
    rows = [dict(r) for r in con.execute(
        "SELECT field, old_val, new_val, user, ts FROM history WHERE deal_key=? ORDER BY ts DESC LIMIT 100",
        (key,))]
    con.close()
    return jsonify(rows)


@app.post("/api/import")
@login_required
def do_import():
    try:
        stats = core.import_xlsx()
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/specialists")
@login_required
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
@login_required
def delete_specialist(sid):
    con = core.db()
    con.execute("DELETE FROM specialists WHERE id = ?", (sid,))
    con.commit()
    con.close()
    return jsonify({"success": True})


def send_code_email(to_email, code):
    sender = os.getenv("SMTP_SENDER") or os.getenv("SMTP_USER")
    if not sender:
        print(f"MOCK EMAIL: Sent code {code} to {to_email}")
        return True
    try:
        msg = EmailMessage()
        msg.set_content(f"Ваш код для регистрации в РМКО: {code}")
        msg["Subject"] = "Код подтверждения РМКО"
        msg["From"] = sender
        msg["To"] = to_email

        host = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        port = int(os.getenv("SMTP_PORT", 465))
        
        if port == 587:
            server = smtplib.SMTP(host, port, timeout=10)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(host, port, timeout=10)
            
        server.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASS"))
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print("SMTP ERROR:", e)
        return False

@app.route("/login")
def login_page():
    return send_from_directory(os.path.join(core.BASE, "templates"), "login.html")

@app.post("/api/auth/send-code")
def auth_send_code():
    data = request.json
    email = data.get("email", "").strip().lower()
    if not email:
        return jsonify({"error": "Email обязателен"}), 400
    
    con = core.db()
    allowed = con.execute("SELECT email FROM allowed_emails").fetchall()
    if allowed:
        if email not in [r["email"].lower() for r in allowed]:
            con.close()
            return jsonify({"error": "Этот email не добавлен в белый список"}), 403
            
    code = "".join(random.choices(string.digits, k=6))
    expires = (datetime.now() + timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
    
    con.execute("INSERT OR REPLACE INTO verification_codes (email, code, expires_at) VALUES (?, ?, ?)",
                (email, code, expires))
    con.commit()
    con.close()
    
    if send_code_email(email, code):
        return jsonify({"success": True})
    return jsonify({"error": "Ошибка отправки письма. Убедитесь, что SMTP настроен."}), 500

@app.post("/api/auth/register")
def auth_register():
    data = request.json
    email = data.get("email", "").strip().lower()
    code = data.get("code", "").strip()
    username = data.get("username", "").strip()
    
    if not email or not code or not username:
        return jsonify({"error": "Заполните все поля"}), 400
        
    con = core.db()
    row = con.execute("SELECT * FROM verification_codes WHERE email=? AND code=?", (email, code)).fetchone()
    if not row or row["expires_at"] < datetime.now().strftime("%Y-%m-%d %H:%M:%S"):
        con.close()
        return jsonify({"error": "Неверный или просроченный код"}), 400
        
    try:
        pw_hash = generate_password_hash("1")
        con.execute("INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)", 
                    (username, email, pw_hash))
        con.execute("DELETE FROM verification_codes WHERE email=?", (email,))
        con.commit()
        
        user = con.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        session["user_id"] = user["id"]
        session["username"] = username
        session["needs_password_change"] = 1
    except Exception as e:
        con.close()
        return jsonify({"error": "Имя пользователя или email уже заняты"}), 400
        
    con.close()
    return jsonify({"success": True})

@app.post("/api/auth/login")
def auth_login():
    data = request.json
    username = data.get("username", "").strip()
    password = data.get("password", "")
    
    con = core.db()
    user = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    con.close()
    
    if user and check_password_hash(user["password_hash"], password):
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["needs_password_change"] = user["needs_password_change"]
        return jsonify({"success": True})
        
    return jsonify({"error": "Неверный логин или пароль"}), 401

@app.post("/api/auth/change-password")
@login_required
def auth_change_password():
    data = request.json
    new_password = data.get("new_password", "")
    if len(new_password) < 4:
        return jsonify({"error": "Пароль должен быть длиннее 3 символов"}), 400
        
    con = core.db()
    con.execute("UPDATE users SET password_hash=?, needs_password_change=0 WHERE id=?", 
                (generate_password_hash(new_password), session["user_id"]))
    con.commit()
    con.close()
    
    session["needs_password_change"] = 0
    return jsonify({"success": True})

@app.post("/api/auth/logout")
def auth_logout():
    session.clear()
    return jsonify({"success": True})


@app.get("/api/dashboard/data")
@login_required
def dashboard_data():
    import pandas as pd
    view = request.args.get("view", "trend")
    period = request.args.get("period", "month")
    group_by = request.args.get("groupBy", "city")

    con = core.db()
    rows = [dict(r) for r in con.execute(
        "SELECT doc_date, created_at, amount, client, city, author, stage, "
        "deleted, posted, reserved FROM deals"
    )]
    con.close()

    if not rows:
        return jsonify({"labels": [], "values": [], "series": []})

    df = pd.DataFrame(rows)
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
    df["date"] = pd.to_datetime(
        df["doc_date"].fillna(df["created_at"]), errors="coerce"
    )
    df = df.dropna(subset=["date"])

    # period filter
    now = pd.Timestamp.now()
    if period == "week":
        df = df[df["date"] >= now - pd.Timedelta(days=7)]
    elif period == "month":
        df = df[df["date"] >= now - pd.Timedelta(days=30)]
    elif period == "quarter":
        df = df[df["date"] >= now - pd.Timedelta(days=90)]
    elif period == "year":
        df = df[df["date"] >= now - pd.Timedelta(days=365)]

    if df.empty:
        return jsonify({"labels": [], "values": [], "series": []})

    if view == "trend":
        # candlestick-style OHLC by day
        df = df.set_index("date").sort_index()
        freq = "D" if period == "week" else "W" if period in ("month", "quarter") else "ME"
        ohlc = df["amount"].resample(freq).agg(
            open="first", high="max", low="min", close="last"
        ).dropna()
        series = []
        for ts, row in ohlc.iterrows():
            series.append({
                "time": ts.strftime("%Y-%m-%d"),
                "open": round(row["open"], 2),
                "high": round(row["high"], 2),
                "low": round(row["low"], 2),
                "close": round(row["close"], 2),
            })
        return jsonify({"series": series})

    elif view == "structure":
        col_map = {"city": "city", "author": "author", "stage": "stage"}
        col = col_map.get(group_by, "city")
        grp = df.groupby(df[col].fillna("(не указано)"))["amount"].sum()
        grp = grp.sort_values(ascending=False).head(12)
        return jsonify({
            "labels": grp.index.tolist(),
            "values": [round(v, 2) for v in grp.values.tolist()],
        })

    elif view == "rating":
        grp = df.groupby(df["client"].fillna("(не указано)"))["amount"].sum()
        grp = grp.sort_values(ascending=False).head(10)
        return jsonify({
            "labels": grp.index.tolist(),
            "values": [round(v, 2) for v in grp.values.tolist()],
        })

    elif view == "plan":
        # cumulative daily sum for current month
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        mdf = df[df["date"] >= month_start].copy()
        if mdf.empty:
            return jsonify({"series": []})
        daily = mdf.set_index("date").resample("D")["amount"].sum().fillna(0)
        cumulative = daily.cumsum()
        series = [
            {"x": ts.strftime("%Y-%m-%d"), "y": round(v, 2)}
            for ts, v in cumulative.items()
        ]
        return jsonify({"series": series})

    return jsonify({"error": "unknown view"}), 400


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if not os.path.exists(core.DB_PATH):
        print("Первый запуск: импортирую данные из xlsx...")
        print(core.import_xlsx(first=True))
    print("РМКО запущено: http://localhost:8000 (по сети — http://<ip-компьютера>:8000)")
    app.run(host="0.0.0.0", port=8000, debug=False)
