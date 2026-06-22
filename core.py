# -*- coding: utf-8 -*-
"""Ядро РМКО: схема БД, импорт из xlsx, бизнес-логика статусов.

Логика статусов и правил перенесена из листа «ИнструкцияДляMain»:
- Текущий статус (авто): Удалён (ПометкаУдаления=Да) / Выдан (Проведен=Да,
  Резерв=Нет) / Резерв (иначе).
- Этап сделки ведёт менеджер: Счет отправлен → Оплата есть → Закрыто,
  либо Не состоялась (инициатива клиента) / Удалён (инициатива компании).
- Корректное закрытие: Закрыто = ✔товар в наличии + дата закрытия;
  Удалён = причина удаления + дата; Не состоялась = причина отказа + дата.
- Сроки считаются в РАБОЧИХ днях (сб/вс не считаются) — пожелание из листа
  «Вопросы».
"""
import os
import re
import sqlite3
try:
    import libsql_client
    _HAS_LIBSQL = True
except ImportError:
    libsql_client = None  # type: ignore
    _HAS_LIBSQL = False
from datetime import date, datetime, timedelta
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

class _DummyCursor:
    def __init__(self, rs):
        self.rs = rs
        self._rows = []
        if rs:
            if hasattr(rs, 'rows') and hasattr(rs, 'columns'):
                columns = rs.columns
                for row in rs.rows:
                    d = {columns[i]: row[i] for i in range(len(columns))}
                    self._rows.append(d)
            elif hasattr(rs, 'description') and rs.description:
                columns = [col[0] for col in rs.description]
                for row in rs.fetchall():
                    d = {columns[i]: row[i] for i in range(len(columns))}
                    self._rows.append(d)
        self._idx = 0

    def fetchone(self):
        if self._idx < len(self._rows):
            res = self._rows[self._idx]
            self._idx += 1
            return res
        return None

    def fetchall(self):
        res = self._rows[self._idx:]
        self._idx = len(self._rows)
        return res

    def __iter__(self):
        return iter(self._rows)


def _split_sql_script(sql_script):
    return [stmt.strip() for stmt in sql_script.split(";") if stmt.strip()]


class _DbWrapper:
    def __init__(self, url, auth_token):
        if url.startswith("file:"):
            self.con = sqlite3.connect(url.replace("file:", ""))
            self.con.row_factory = sqlite3.Row
            self.is_sqlite = True
        else:
            if not _HAS_LIBSQL:
                raise RuntimeError("libsql_client is required for remote database URLs")
            remote_url = url.replace("libsql://", "https://")
            self.client = libsql_client.create_client_sync(
                remote_url,
                auth_token=auth_token,
            )
            self.is_sqlite = False
    
    def cursor(self):
        if self.is_sqlite:
            return self.con.cursor()
        return self

    def execute(self, sql, params=None):
        if self.is_sqlite:
            if params is not None:
                return self.con.execute(sql, params)
            return self.con.execute(sql)
        else:
            args = params if params is not None else []
            result = self.client.execute(sql, args)
            return _DummyCursor(result)

    def executescript(self, sql_script):
        if self.is_sqlite:
            self.con.executescript(sql_script)
        else:
            statements = _split_sql_script(sql_script)
            if statements:
                self.client.batch(statements)
    
    def execute_batch(self, statements_list):
        """Отправляет список (sql, params) батчами по 500 — минимум HTTP round-trips."""
        if not statements_list:
            return
        if self.is_sqlite:
            for sql, params in statements_list:
                if params is not None:
                    self.con.execute(sql, params)
                else:
                    self.con.execute(sql)
            self.con.commit()
        else:
            batch_size = 500
            for i in range(0, len(statements_list), batch_size):
                chunk = statements_list[i : i + batch_size]
                parts = []
                for sql, params in chunk:
                    if params is None:
                        parts.append(sql)
                    elif isinstance(params, dict):
                        parts.append(libsql_client.Statement(sql, params))
                    else:
                        parts.append(libsql_client.Statement(sql, params))
                self.client.batch(parts)
    
    def commit(self):
        if self.is_sqlite:
            self.con.commit()
            
    def close(self):
        if self.is_sqlite:
            self.con.close()
        else:
            self.client.close()

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "rmko.db")
XLSX_PATH = os.path.join(os.path.dirname(BASE), "Рабочее место Корпоративного отдела .xlsx")

# --- справочники (ИнструкцияДляMain + бэклог листа «Вопросы») ---
STAGES = ["Счет отправлен", "Оплата есть", "Закрыто", "Не состоялась", "Удалён",
          "Заменена", "Сервис"]
NEXT_STEPS = [
    "Связаться по счету", "Напомнить об оплате", "Уточнить решение по счету",
    "Отправить КП", "Обновить счет", "Согласовать договор", "Подтвердить оплату",
    "Уточнить наличие товара", "Предложить аналог", "Сообщить о поступлении товара",
    "Согласовать доставку", "Напомнить о заборе товара", "Уточнить причину отказа",
]
REJECT_REASONS = ["высокая цена", "выбрали другого поставщика", "клиент передумал",
                  "нет обратной связи от клиента", "не выделили средства",
                  "не оплатили", "нет новых РН", "другое"]
DELETE_REASONS = ["счет создан ошибочно", "замена счета", "пересоздан документ",
                  "дубль", "другое"]
CHECK_STATUSES = ["Новая", "Отработано", "Закрыто автоматически"]
GOODS_CHECK = ["Ожидает проверки", "Проверено", "Товар есть"]

CLOSED_STAGES = {"Закрыто", "Не состоялась", "Удалён", "Заменена"}

# поля, которые редактирует менеджер (разрешены в PATCH)
EDITABLE = {
    "stage", "last_contact", "close_date",
    "reject_reason", "delete_reason", "notes", "in_stock",
    "closing_docs", "delivery", "contract_num", "lead_source", "mgr_comment",
}

SCHEMA = """
DROP TABLE IF EXISTS tasks;
CREATE TABLE IF NOT EXISTS deals (
    key TEXT PRIMARY KEY,
    territory TEXT, city TEXT, branch TEXT, author TEXT,
    doc TEXT, doc_num TEXT, created_at TEXT, doc_date TEXT,
    client TEXT, amount REAL, contacts TEXT, comment_1c TEXT,
    deleted INTEGER DEFAULT 0, posted INTEGER DEFAULT 0, reserved INTEGER DEFAULT 0,
    status_1c TEXT,
    payment_amount REAL, payment_source TEXT, payment_date TEXT,
    has_payment INTEGER DEFAULT 0, invoice_basis TEXT,
    stage TEXT, next_step TEXT, plan_contact TEXT, last_contact TEXT,
    close_date TEXT, reject_reason TEXT, delete_reason TEXT, notes TEXT,
    check_status TEXT, in_stock TEXT DEFAULT 'Ожидает проверки', closing_docs INTEGER, delivery TEXT,
    contract_num TEXT, lead_source TEXT, mgr_comment TEXT,
    flag TEXT DEFAULT '', fixed_at TEXT, processed_at TEXT,
    updated_at TEXT, updated_by TEXT
);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_key TEXT, field TEXT, old_val TEXT, new_val TEXT,
    user TEXT, ts TEXT
);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS specialists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    city TEXT
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    needs_password_change INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS verification_codes (
    email TEXT PRIMARY KEY,
    code TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS allowed_emails (
    email TEXT PRIMARY KEY
);
CREATE INDEX IF NOT EXISTS ix_deals_city ON deals(city);
CREATE INDEX IF NOT EXISTS ix_hist_key ON history(deal_key);
"""

# Миграции для добавления новых колонок в существующую БД
_MIGRATIONS = [
    "ALTER TABLE deals ADD COLUMN status_1c TEXT",
    "ALTER TABLE deals ADD COLUMN payment_amount REAL",
    "ALTER TABLE deals ADD COLUMN payment_source TEXT",
    "ALTER TABLE deals ADD COLUMN payment_date TEXT",
    "ALTER TABLE deals ADD COLUMN has_payment INTEGER DEFAULT 0",
    "ALTER TABLE deals ADD COLUMN invoice_basis TEXT",
]

# Миграция in_stock INTEGER → TEXT (0 → 'Ожидает проверки', 1 → 'Проверено')
_MIGRATE_IN_STOCK = """
UPDATE deals SET in_stock = CASE
    WHEN in_stock = 1 OR in_stock = '1' THEN 'Проверено'
    WHEN in_stock = 0 OR in_stock = '0' THEN 'Ожидает проверки'
    WHEN in_stock IS NULL OR in_stock = '' THEN 'Ожидает проверки'
    ELSE in_stock
END
"""


def _run_migrations(con):
    """Добавить новые колонки в существующую таблицу deals (игнорирует дубли)."""
    for sql in _MIGRATIONS:
        try:
            con.execute(sql)
        except Exception:
            pass  # колонка уже существует
    # Конвертация in_stock: INTEGER 0/1 → TEXT
    try:
        con.execute(_MIGRATE_IN_STOCK)
    except Exception:
        pass
    try:
        con.commit()
    except Exception:
        pass


_schema_applied = False


def db():
    global _schema_applied
    url = os.getenv("TURSO_DATABASE_URL", f"file:{DB_PATH}").replace("libsql://", "https://")
    auth_token = os.getenv("TURSO_AUTH_TOKEN", "")
    con = _DbWrapper(url, auth_token)
    if not _schema_applied:
        con.executescript(SCHEMA)
        _run_migrations(con)
        _schema_applied = True
    return con


# ---------------- утилиты ----------------

def clean_text(v):
    if v is None:
        return None
    s = str(v).replace("\t", " ").replace(" ", " ").strip()
    if s.lower() in ("nan", "nat", "none", ""):
        return None
    return s


def parse_amount(v):
    s = clean_text(v)
    if s is None:
        return None
    s = s.replace("₸", "").replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _is_nat(v):
    try:
        return v != v  # NaN / NaT
    except Exception:
        return False


def parse_date(v):
    """Вернуть YYYY-MM-DD или None."""
    if v is None or _is_nat(v):
        return None
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, date):
        return v.strftime("%Y-%m-%d")
    s = clean_text(v)
    if not s:
        return None
    s = s.split()[0]
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def parse_dt(v):
    if v is None or _is_nat(v):
        return None
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    s = clean_text(v)
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:19], fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return parse_date(s)


def yes(v):
    s = clean_text(v)
    return 1 if s in ("Да", "True", "true", "1", "Есть") else 0


def opt_bool(v):
    """True/False/None для чекбоксов из xlsx (бывают bool, 1.0/0.0, текст)."""
    s = clean_text(v)
    if s is None:
        return None
    if s in ("True", "true", "Да", "1", "1.0", "Есть", "TRUE", "ИСТИНА"):
        return 1
    if s in ("False", "false", "Нет", "0", "0.0", "FALSE", "ЛОЖЬ"):
        return 0
    return None


def workdays_between(d_from, d_to):
    """Рабочие дни (без сб/вс) между датами, минимум 0."""
    if not d_from:
        return 0
    try:
        a = datetime.strptime(d_from[:10], "%Y-%m-%d").date()
    except ValueError:
        return 0
    b = d_to
    if a >= b:
        return 0
    days, cur = 0, a
    while cur < b:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            days += 1
    return days


def add_workdays(d_from, days):
    if not d_from:
        return None
    try:
        cur = datetime.strptime(d_from[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    added = 0
    while added < days:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            added += 1
    return cur


def phones(contacts):
    """Достать телефоны для ссылок WhatsApp (wa.me)."""
    if not contacts:
        return []
    found = re.findall(r"\+?\d[\d\-\s()]{8,}", contacts)
    out = []
    for f in found:
        digits = re.sub(r"\D", "", f)
        if len(digits) == 11 and digits.startswith("8"):
            digits = "7" + digits[1:]
        if len(digits) == 10:
            digits = "7" + digits
        if len(digits) == 11 and digits.startswith("7"):
            if digits not in out:
                out.append(digits)
    return out[:3]


# ---------------- бизнес-логика статусов ----------------

# Маппинг из нового поля «Статус» 1С → внутренние флаги (deleted, posted, reserved)
STATUS_FROM_1C = {
    "Выдан":  {"deleted": 0, "posted": 1, "reserved": 0},
    "Резерв": {"deleted": 0, "posted": 1, "reserved": 1},
    "Удален": {"deleted": 1, "posted": 0, "reserved": 0},
    "Прочее": {"deleted": 0, "posted": 0, "reserved": 0},
}

# Лист «Статусы»: текущий статус определяется флагами 1С
# (ПометкаУдаления / Проведен / Резерв). Порядок — как в таблице.
STATUS_RULES = [
    ("Выдан",  {"deleted": 0, "posted": 1, "reserved": 0}),
    ("Резерв", {"deleted": 0, "posted": 1, "reserved": 1}),
    ("Удален", {"deleted": 1, "posted": 0, "reserved": 0}),
]
STATUS_DELETED = "Удален"  # написание статуса — как в листе «Статусы» (не «Удалён»-этап)


def cur_status(d):
    # Новый формат: если есть прямой статус из 1С — используем его
    status_1c = d.get("status_1c")
    if status_1c and status_1c in STATUS_FROM_1C:
        return status_1c
    # Старый формат: вычисляем из флагов deleted/posted/reserved
    deleted, posted, reserved = int(bool(d["deleted"])), int(bool(d["posted"])), int(bool(d["reserved"]))
    for name, c in STATUS_RULES:
        if c["deleted"] == deleted and c["posted"] == posted and c["reserved"] == reserved:
            return name
    # комбинации вне таблицы: помеченные на удаление -> Удален, иначе -> Резерв
    if deleted:
        return STATUS_DELETED
    if posted and not reserved:
        return "Выдан"
    return "Резерв"


def derive(d, today=None, user_action_keys=None):
    """Вычислить производные поля сделки по правилам ИнструкцииДляMain."""
    today = today or date.today()
    st = cur_status(d)
    stage = d["stage"] or ""
    
    in_stock_val = d.get("in_stock") or "Ожидает проверки"
    in_stock_ok = in_stock_val in ("Проверено", "Товар есть")
    
    wd = workdays_between(d["doc_date"] or d["created_at"], today)

    # 1. Автоматический План конт. = дата документа + 2 рабочих дня
    doc_date_str = d.get("doc_date") or d.get("created_at")
    plan_contact = None
    plan_color = ""
    if doc_date_str:
        due = add_workdays(doc_date_str, 2)
        if due:
            plan_contact = due.strftime("%Y-%m-%d")
            today_str = today.strftime("%Y-%m-%d")
            plan_contact_str = plan_contact[:10]
            if today_str < plan_contact_str:
                plan_color = "green"
            elif today_str == plan_contact_str:
                plan_color = "yellow"
            else:
                plan_color = "red"

    # 2. Автоматический статус Проверка
    has_user_action = False
    if user_action_keys is not None:
        has_user_action = d["key"] in user_action_keys
    
    is_issued = st == "Выдан" or (
        bool(d.get("posted")) and not bool(d.get("reserved")) and not bool(d.get("deleted"))
    )
    if is_issued:
        chk_status = "Закрыто" if has_user_action else "Закрыто автоматически"
    else:
        chk_status = "В работе" if has_user_action else "Новая"

    errors = []
    if stage == "Закрыто" and (not in_stock_ok or not d["close_date"]):
        need = []
        if not in_stock_ok:
            need.append("✔ товар в наличии (Проверено / Товар есть)")
        if not d["close_date"]:
            need.append("дата закрытия")
        errors.append("Закрыто оформлено неверно: нет " + ", ".join(need))
    if stage == "Удалён":
        if not d["delete_reason"]:
            errors.append("Удалён: не указана причина удаления")
        if not d["close_date"]:
            errors.append("Удалён: не указана дата удаления")
    if stage == "Не состоялась":
        if not d["reject_reason"]:
            errors.append("Не состоялась: не указана причина отказа")
        if not d["close_date"]:
            errors.append("Не состоялась: не указана дата")
    if st in ("Удалён", "Удален") and stage not in ("Удалён", "Не состоялась", "Заменена"):
        errors.append("РН удалена в 1С — выбрать этап «Удалён» или «Не состоялась» и причину")

    # подсказка (что происходит со сделкой и что делать)
    if errors:
        if st in ("Удалён", "Удален"):
            hint = "Указать причину"
        else:
            hint = "Исправить данные"
        level = "error"
    elif st in ("Удалён", "Удален") or stage in ("Удалён", "Не состоялась"):
        hint, level = "Без продажи", "closed"
    elif stage == "Заменена":
        hint, level = "Сделка заменена", "closed"
    elif st == "Выдан" or (stage == "Закрыто" and in_stock_ok):
        hint, level = "Товар выдан", "done"
    elif stage == "Оплата есть" and in_stock_ok:
        hint, level = "Выдать товар", "ready"
    elif stage == "Оплата есть":
        hint, level = "Проверить товар", "paid"
    elif stage == "Счет отправлен" and wd >= 3:
        hint, level = "Позвонить клиенту", "risk"
    elif (stage == "Счет отправлен" or st == "Резерв") and wd >= 2:
        hint, level = "Проверить статус", "warn"
    elif stage == "Сервис":
        hint, level = "Сервис", "info"
    elif not stage and st == "Резерв":
        hint, level = "Выбрать этап", "new"
    else:
        hint, level = "В работе", "info"

    # Сверяем overdue по plan_contact
    overdue = bool(plan_contact and plan_contact[:10] < today.strftime("%Y-%m-%d")
                   and level not in ("done", "closed"))
    closed = level in ("done", "closed") and not errors
    return {
        "cur_status": st, "hint": hint, "level": level, "errors": errors,
        "workdays": wd, "overdue_contact": overdue, "is_closed": closed,
        "phones": phones(d["contacts"]),
        "plan_contact": plan_contact,
        "plan_color": plan_color,
        "check_status": chk_status,
    }


# ---------------- зоны ответственности ----------------

def load_specialists():
    con = db()
    rows = [dict(r) for r in con.execute("SELECT id, name, city FROM specialists ORDER BY name")]
    con.close()
    return rows


# ---------------- импорт из xlsx ----------------

COLMAP_1C = {
    "Территория": "territory", "Город": "city", "Филиал": "branch", "Автор": "author",
    "Документ": "doc", "НомерДокумента": "doc_num", "Контрагент": "client",
    "Контакты": "contacts", "Комментарий": "comment_1c",
    "СчетОснование": "invoice_basis", "ИсточникОплаты": "payment_source",
}
def parse_in_stock(v):
    s = clean_text(v)
    if not s:
        return "Ожидает проверки"
    if s in ("Да", "1", "1.0", "Есть", "True", "true", "ИСТИНА", "Товар есть"):
        return "Товар есть"
    if s in ("Проверено", "проверено"):
        return "Проверено"
    if s in ("Ожидает проверки", "ожидает проверки"):
        return "Ожидает проверки"
    return "Ожидает проверки"

COLMAP_MGR = {
    "Этап сделки": ("stage", clean_text),
    "Дата посл. контакта": ("last_contact", parse_date),
    "Дата закрытия|удаления": ("close_date", parse_date),
    "Причина отказа": ("reject_reason", clean_text),
    "Причина удаления": ("delete_reason", clean_text),
    "Примечания": ("notes", clean_text),
    "Товар в наличии": ("in_stock", parse_in_stock),
    "Закрывающие документы": ("closing_docs", opt_bool),
    "Доставка": ("delivery", clean_text),
    "Номер договора": ("contract_num", clean_text),
    "Источник лида": ("lead_source", clean_text),
}
TRACKED_1C = ["amount", "doc_date", "contacts", "comment_1c", "deleted", "posted",
              "reserved", "client", "status_1c", "payment_amount", "has_payment",
              "payment_source", "payment_date", "invoice_basis"]

# Колонки, загружаемые при старте импорта — только те, что нужны в _process_import_df
_EXISTING_COLS = (
    "key, territory, city, branch, author, doc, amount, doc_date, "
    "contacts, comment_1c, deleted, posted, reserved, client, status_1c, "
    "payment_amount, payment_source, payment_date, has_payment, "
    "invoice_basis, stage, last_contact, close_date, reject_reason, "
    "delete_reason, notes, in_stock, closing_docs, delivery, "
    "contract_num, lead_source, flag"
)


def _normalize(v):
    """Нормализация значения для сравнения: убирает различия в типах (float vs str и т.д.)."""
    if v is None:
        return None
    s = str(v).strip()
    if s in ("", "None", "nan", "NaT", "none", "nat"):
        return None
    try:
        f = float(s)
        # Если число целое — сравниваем как int, чтобы "1500.0" == 1500
        return int(f) if f == int(f) else f
    except (ValueError, OverflowError):
        return s


def _sheet_rows(xlsx_path, sheet):
    import pandas as pd
    df = pd.read_excel(xlsx_path, sheet_name=sheet, header=0)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _process_import_df(df, con, existing, stats, now, first, seen):
    """Обработка одного DataFrame сделок (общая логика для xlsx и csv)."""
    if "НомерДокумента" not in df.columns:
        return
    
    stmts = []
    
    for _, r in df.iterrows():
        num = clean_text(r.get("НомерДокумента"))
        created = parse_dt(r.get("ДатаСоздания"))
        if not num or not created:
            stats["skipped"] += 1
            continue
        key = f"{num}|{created[:10]}"
        if key in seen:  # дубли в выгрузке игнорируем («Что нового» 30.03)
            continue
        seen.add(key)

        vals = {c: clean_text(r.get(src)) for src, c in COLMAP_1C.items()}
        vals.update({
            "key": key, "doc_num": num, "created_at": created,
            "doc_date": parse_dt(r.get("ДатаДокумента")),
            "amount": parse_amount(r.get("Сумма")),
        })

        # Новый формат 1С: поле «Статус» вместо трёх флагов
        status_raw = clean_text(r.get("Статус"))
        if status_raw and status_raw in STATUS_FROM_1C:
            flags = STATUS_FROM_1C[status_raw]
            vals["status_1c"] = status_raw
            vals["deleted"] = flags["deleted"]
            vals["posted"] = flags["posted"]
            vals["reserved"] = flags["reserved"]
        else:
            # Старый формат: три отдельных флага
            vals["deleted"] = yes(r.get("ПометкаУдаления"))
            vals["posted"] = yes(r.get("Проведен"))
            vals["reserved"] = yes(r.get("Резерв"))

        # Поля оплаты (новый формат)
        if "Оплата" in df.columns:
            vals["payment_amount"] = parse_amount(r.get("Оплата"))
        if "ДатаОплаты" in df.columns:
            vals["payment_date"] = parse_dt(r.get("ДатаОплаты"))
        if "ЕстьОплата" in df.columns:
            vals["has_payment"] = yes(r.get("ЕстьОплата"))
        mgr_vals = {}
        for src, (cl, fn) in COLMAP_MGR.items():
            if src in df.columns:
                mgr_vals[cl] = fn(r.get(src))

        old = existing.get(key)
        if old is None:
            row = dict(vals)
            row.update({k: v for k, v in mgr_vals.items() if v is not None})
            row.setdefault("check_status", "Новая")
            row["flag"] = "" if first else "NEW"
            row["fixed_at"] = now
            cols = ", ".join(row)
            stmts.append((f"INSERT INTO deals ({cols}) VALUES ({', '.join(':'+c for c in row)})", row))
            stats["new"] += 1
        else:
            changes = {}
            for c in TRACKED_1C + ["territory", "city", "branch", "author", "doc"]:
                raw_nv = vals.get(c)
                raw_ov = old.get(c)
                # Нормализуем перед сравнением — устраняет ложные UPDATE из-за типов
                if _normalize(raw_nv) != _normalize(raw_ov):
                    if raw_nv is not None:
                        changes[c] = raw_nv
            # менеджерские поля — только если в БД пусто
            for c, nv in mgr_vals.items():
                if nv is not None and (old.get(c) is None or old.get(c) == ""):
                    changes[c] = nv
            if changes:
                tracked_changed = any(c in TRACKED_1C for c in changes)
                if tracked_changed and old.get("flag") != "NEW":
                    changes["flag"] = "UPDATE"
                    changes["fixed_at"] = now
                    for c in changes:
                        if c in TRACKED_1C:
                            stmts.append((
                                "INSERT INTO history (deal_key, field, old_val, new_val, user, ts) "
                                "VALUES (?,?,?,?,?,?)",
                                (key, c, str(old.get(c)), str(changes[c]), "1С-импорт", now)))
                sets = ", ".join(f"{c}=:{c}" for c in changes)
                changes["key"] = key
                stmts.append((f"UPDATE deals SET {sets} WHERE key=:key", changes))
                stats["updated"] += 1
            else:
                stats["unchanged"] += 1

    con.execute_batch(stmts)


def _finalize_import(con, now):
    """Автозаполнение для выданных накладных + обновление meta.
    
    Все 4 запроса отправляются одним батчем — один HTTP round-trip вместо четырёх.
    """
    con.execute_batch([
        (
            """UPDATE deals SET close_date = substr(COALESCE(doc_date, created_at),1,10)
               WHERE close_date IS NULL AND posted=1 AND reserved=0 AND deleted=0""",
            None,
        ),
        (
            """UPDATE deals SET next_step='Закрыто автоматически'
               WHERE (next_step IS NULL OR next_step='')
                 AND posted=1 AND reserved=0 AND deleted=0""",
            None,
        ),
        (
            """UPDATE deals SET stage='Закрыто', in_stock='Товар есть',
                      check_status='Закрыто автоматически'
               WHERE posted=1 AND reserved=0 AND deleted=0""",
            None,
        ),
        ("INSERT OR REPLACE INTO meta (k, v) VALUES ('last_import', ?)", (now,)),
    ])
    con.commit()


def import_xlsx(xlsx_path=None, first=False):
    """Импорт/обновление сделок из xlsx. Возвращает статистику."""
    import pandas as pd
    xlsx_path = xlsx_path or XLSX_PATH
    if not os.path.exists(xlsx_path):
        raise FileNotFoundError("Файл выгрузки из 1С не найден. Пожалуйста, запустите 'Обновить данные из 1С.bat' локально на вашем компьютере.")

    con = db()
    existing = {
        r["key"]: dict(r)
        for r in con.execute(f"SELECT {_EXISTING_COLS} FROM deals")
    }
    first = first or not existing

    stats = {"new": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    sheets = []
    xl = pd.ExcelFile(xlsx_path)
    # Новый формат: один лист «Лист1»
    if "Лист1" in xl.sheet_names:
        sheets.append("Лист1")
    # Старый формат: листы «main» и «Import»
    if "main" in xl.sheet_names:
        sheets.append("main")
    if "Import" in xl.sheet_names:
        sheets.append("Import")

    seen = set()
    for sheet in sheets:
        df = _sheet_rows(xlsx_path, sheet)
        _process_import_df(df, con, existing, stats, now, first, seen)

    _finalize_import(con, now)
    con.close()
    return stats


def import_csv(csv_path, encoding='utf-8', separator=';', first=False):
    """Импорт/обновление сделок из CSV (автовыгрузка 1С). Возвращает статистику.

    Параметры:
        csv_path:  путь к CSV-файлу
        encoding:  кодировка файла (utf-8, cp1251, и т.д.)
        separator: разделитель полей (точка с запятой по умолчанию)
        first:     True при первом импорте (не помечает записи как NEW)
    """
    import pandas as pd
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV файл не найден: {csv_path}")

    con = db()
    existing = {
        r["key"]: dict(r)
        for r in con.execute(f"SELECT {_EXISTING_COLS} FROM deals")
    }
    first = first or not existing

    stats = {"new": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    seen = set()
    import csv
    rows = []
    with open(csv_path, 'r', encoding=encoding) as f:
        reader = csv.reader(f, delimiter=separator)
        header = next(reader)
        # Убираем BOM из первой колонки
        header = [str(c).strip().lstrip('\ufeff') for c in header]
        h_len = len(header)
        for i, row in enumerate(reader):
            if not row:
                continue
            if len(row) == h_len:
                rows.append(row)
            elif len(row) > h_len:
                L = len(row) - h_len
                contacts = separator.join(row[11 : 12 + L])
                comment = row[12 + L]
                new_row = row[0:11] + [contacts, comment] + row[-5:]
                rows.append(new_row)
            else:
                continue
    df = pd.DataFrame(rows, columns=header)
    _process_import_df(df, con, existing, stats, now, first, seen)

    _finalize_import(con, now)
    con.close()
    return stats


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print("Импорт из:", XLSX_PATH)
    print(import_xlsx())
