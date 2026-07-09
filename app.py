# -*- coding: utf-8 -*-
"""РМКО — рабочее место корпоративного отдела (Flask + SQLite).

Запуск:  python app.py            (порт 8000, доступен по сети)
Импорт:  python core.py           (или кнопка «Обновить из 1С» в интерфейсе)
"""
import os
import sys
import time
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
    now_ts = time.time()
    # Потокобезопасное чтение кэша
    with core._cache_lock:
        cached = core._meta_cache
        if cached["data"] and now_ts - cached["ts"] < core.META_TTL:
            result = dict(cached["data"])
        else:
            result = None
    if result is None:
        con = core.db()
        cities_rows = con.execute("SELECT DISTINCT city FROM deals WHERE city IS NOT NULL")
        cities = sorted({r["city"] for r in cities_rows})
        li = con.execute("SELECT v FROM meta WHERE k='last_import'").fetchone()
        specialists = core.load_specialists(con)
        result = {
            "cities": cities,
            "specialists": specialists,
            "stages": core.STAGES, "next_steps": core.NEXT_STEPS,
            "reject_reasons": core.REJECT_REASONS, "delete_reasons": core.DELETE_REASONS,
            "check_statuses": core.CHECK_STATUSES, "goods_check": core.GOODS_CHECK,
            "last_import": li["v"] if li else None,
        }
        with core._cache_lock:
            cached["data"] = result
            cached["ts"] = now_ts
        result = dict(result)
    # Per-request данные (не кэшируются)
    result["user"] = {"name": session.get("username"), "needs_password_change": session.get("needs_password_change")}
    result["now"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    return jsonify(result)


@app.get("/api/deals")
@login_required
def deals():
    con = core.db()
    
    user_name = session.get("username", "")
    zone_cities = []
    if user_name:
        specialists = core.load_specialists(con)
        for s in specialists:
            if s["name"] == user_name and s["city"]:
                zone_cities.append(s["city"])
                
    where_sql, params = core.build_filters_sql(request.args, zone_cities=zone_cities)
    
    sort_col = request.args.get("sortCol", "amount")
    sort_dir = int(request.args.get("sortDir", "-1"))
    
    order_by = sort_col
    if sort_col == "status":
        order_by = f"({core.SQL_LEVEL})"
    elif sort_col not in ("amount", "client", "doc_date", "stage", "city", "doc_num", "in_stock", "plan_contact", "notes", "author"):
        order_by = "amount"
        
    direction = "DESC" if sort_dir == -1 else "ASC"
    order_clause = f"ORDER BY {order_by} {direction}"
    
    page = int(request.args.get("page", "0"))
    limit = 50
    offset = page * limit
    
    query = f"SELECT * FROM deals WHERE {where_sql} {order_clause} LIMIT {limit} OFFSET {offset}"
    rows = [dict(r) for r in con.execute(query, params)]
    
    count_res = list(con.execute(f"SELECT COUNT(*) as c FROM deals WHERE {where_sql}", params))
    total = count_res[0]["c"] if count_res else 0
    
    sum_res = list(con.execute(f"SELECT SUM(amount) as s FROM deals WHERE {where_sql}", params))
    total_sum = sum_res[0]["s"] if sum_res and sum_res[0]["s"] is not None else 0
    
    user_action_keys = {r["deal_key"] for r in con.execute("SELECT DISTINCT deal_key FROM history WHERE user != '1С-импорт'")}
    
    out = []
    for d in rows:
        d.update(core.derive(d, user_action_keys=user_action_keys))
        out.append(d)
        
    return jsonify({
        "items": out,
        "total": total,
        "sum": total_sum
    })


@app.get("/api/stats")
@login_required
def stats():
    try:
        con = core.db()
        
        user_name = session.get("username", "")
        zone_cities = []
        if user_name:
            specialists = core.load_specialists(con)
            for s in specialists:
                if s["name"] == user_name and s["city"]:
                    zone_cities.append(s["city"])
                    
        where_sql, params = core.build_filters_sql(request.args, zone_cities=zone_cities)
        
        kpi_sql = f'''
        SELECT 
            SUM(CASE WHEN NOT ({core.SQL_IS_CLOSED}) THEN 1 ELSE 0 END) as act_count,
            SUM(CASE WHEN NOT ({core.SQL_IS_CLOSED}) THEN amount ELSE 0 END) as act_sum,
            
            SUM(CASE WHEN NOT ({core.SQL_IS_CLOSED}) AND ({core.SQL_LEVEL}) = 'risk' THEN 1 ELSE 0 END) as risk_count,
            SUM(CASE WHEN NOT ({core.SQL_IS_CLOSED}) AND ({core.SQL_LEVEL}) = 'risk' THEN amount ELSE 0 END) as risk_sum,
            
            SUM(CASE WHEN NOT ({core.SQL_IS_CLOSED}) AND ({core.SQL_LEVEL}) = 'ready' THEN 1 ELSE 0 END) as ready_count,
            SUM(CASE WHEN NOT ({core.SQL_IS_CLOSED}) AND ({core.SQL_LEVEL}) = 'ready' THEN amount ELSE 0 END) as ready_sum,
            
            SUM(CASE WHEN NOT ({core.SQL_IS_CLOSED}) AND ({core.SQL_OVERDUE}) = 1 THEN 1 ELSE 0 END) as over_count,
            
            SUM(CASE WHEN ({core.SQL_LEVEL}) = 'error' THEN 1 ELSE 0 END) as err_count,
            
            SUM(CASE WHEN ({core.SQL_LEVEL}) = 'done' THEN 1 ELSE 0 END) as done_count,
            SUM(CASE WHEN ({core.SQL_LEVEL}) = 'done' THEN amount ELSE 0 END) as done_sum,
            
            SUM(CASE WHEN ({core.SQL_IS_CLOSED}) AND ({core.SQL_LEVEL}) != 'done' THEN 1 ELSE 0 END) as lost_count,
            SUM(CASE WHEN ({core.SQL_IS_CLOSED}) AND ({core.SQL_LEVEL}) != 'done' THEN amount ELSE 0 END) as lost_sum
        FROM deals WHERE {where_sql}
        '''
        kpi_row = list(con.execute(kpi_sql, params))[0]
        kpi = dict(kpi_row)
        for k, v in kpi.items():
            if v is None: kpi[k] = 0
            
        funnel_sql = f"SELECT COALESCE(stage, '(нет этапа)') as s, SUM(amount) as a FROM deals WHERE {where_sql} GROUP BY s"
        funnel_rows = list(con.execute(funnel_sql, params))
        funnel = {r["s"]: r["a"] or 0 for r in funnel_rows}
        
        lost_sql = f"SELECT COALESCE(NULLIF(reject_reason, ''), NULLIF(delete_reason, ''), '(без причины)') as r, SUM(amount) as a FROM deals WHERE {where_sql} AND ({core.SQL_IS_CLOSED} AND ({core.SQL_LEVEL}) != 'done') GROUP BY r"
        lost_rows = list(con.execute(lost_sql, params))
        lost = {r["r"]: r["a"] or 0 for r in lost_rows}
        
        week_sql = f"SELECT strftime('%Y-W%W', substr(COALESCE(doc_date, created_at), 1, 19)) as w, SUM(amount) as a FROM deals WHERE {where_sql} GROUP BY w"
        week_rows = list(con.execute(week_sql, params))
        weeks = {r["w"]: r["a"] or 0 for r in week_rows if r["w"]}
        
        city_sql = f'''
        SELECT COALESCE(city, '(пусто)') as c, 
               SUM(CASE WHEN NOT ({core.SQL_IS_CLOSED}) THEN amount ELSE 0 END) as act_sum,
               SUM(CASE WHEN ({core.SQL_LEVEL}) = 'done' THEN amount ELSE 0 END) as done_sum
        FROM deals WHERE {where_sql} GROUP BY c
        '''
        city_rows = list(con.execute(city_sql, params))
        cities = {r["c"]: [r["act_sum"] or 0, r["done_sum"] or 0] for r in city_rows}
        
        mgr_sql = f'''
        SELECT COALESCE(author, '(пусто)') as a,
               COUNT(*) as n,
               SUM(amount) as sum,
               SUM(CASE WHEN NOT ({core.SQL_IS_CLOSED}) THEN 1 ELSE 0 END) as act,
               SUM(CASE WHEN NOT ({core.SQL_IS_CLOSED}) AND ({core.SQL_LEVEL}) = 'risk' THEN 1 ELSE 0 END) as risk,
               SUM(CASE WHEN ({core.SQL_LEVEL}) = 'error' THEN 1 ELSE 0 END) as err,
               SUM(CASE WHEN NOT ({core.SQL_IS_CLOSED}) AND ({core.SQL_OVERDUE}) = 1 THEN 1 ELSE 0 END) as over,
               SUM(CASE WHEN ({core.SQL_LEVEL}) = 'done' THEN 1 ELSE 0 END) as done
        FROM deals WHERE {where_sql} GROUP BY a
        '''
        mgr_rows = list(con.execute(mgr_sql, params))
        mgrs = {r["a"]: dict(r) for r in mgr_rows}
        
        return jsonify({
            "kpi": kpi,
            "funnel": funnel,
            "lost": lost,
            "weeks": weeks,
            "cities": cities,
            "mgrs": mgrs
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


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
