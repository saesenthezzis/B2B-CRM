# -*- coding: utf-8 -*-
"""Автосинхронизация 1С → Turso.

Скрипт проверяет файл выгрузки из 1С (CSV) в сетевой папке,
и если файл обновился — импортирует данные в облачную БД Turso.

Запускается через Windows Task Scheduler каждый час (9:00 — 20:00).
Использование:  python sync_daemon.py
"""
import os
import sys
import json
import logging
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# Загружаем переменные окружения из .env
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

# ─── Настройки ───────────────────────────────────────────────────────────────
NETWORK_PATH = os.getenv(
    "SYNC_NETWORK_PATH",
    r"\\kz-srv1.lan.dns-shop.kz\kazakhstan\Администрация\Отдел Альтернативных продаж"
)
FILE_NAME = os.getenv("SYNC_FILE_NAME", "РМКО_выгрузка.csv")
CSV_ENCODING = os.getenv("SYNC_CSV_ENCODING", "utf-8")
_raw_sep = os.getenv("SYNC_CSV_SEPARATOR", ";")
# Интерпретация escape-последовательностей: "\t" → табуляция, "\n" → перенос строки
CSV_SEPARATOR = _raw_sep.encode().decode("unicode_escape") if _raw_sep else ";"

# Файл для отслеживания последней синхронизации
STATE_FILE = os.path.join(BASE_DIR, ".sync_state.json")
LOG_FILE = os.path.join(BASE_DIR, "sync.log")

# ─── Логирование ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("sync")


# ─── Функции состояния ───────────────────────────────────────────────────────

def load_state():
    """Загрузить состояние последней синхронизации."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state):
    """Сохранить состояние синхронизации."""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ─── Основная логика ─────────────────────────────────────────────────────────

def find_export_file():
    """Найти файл выгрузки в сетевой папке.

    Returns:
        str: полный путь к файлу или None, если не найден.
    """
    file_path = os.path.join(NETWORK_PATH, FILE_NAME)

    if os.path.isfile(file_path):
        return file_path

    # Если точное имя не найдено — ищем по паттерну (1С может добавлять дату)
    try:
        base_name = Path(FILE_NAME).stem
        for f in os.listdir(NETWORK_PATH):
            if f.startswith(base_name) and f.lower().endswith(".csv"):
                return os.path.join(NETWORK_PATH, f)
    except (OSError, PermissionError) as e:
        log.error("Не удалось прочитать сетевую папку %s: %s", NETWORK_PATH, e)
    return None


def file_has_changed(file_path, state):
    """Проверить, изменился ли файл с момента последней синхронизации."""
    try:
        mtime = os.path.getmtime(file_path)
        fsize = os.path.getsize(file_path)
    except OSError as e:
        log.error("Не удалось получить атрибуты файла %s: %s", file_path, e)
        return False

    last_mtime = state.get("last_mtime", 0)
    last_fsize = state.get("last_fsize", 0)

    if mtime != last_mtime or fsize != last_fsize:
        return True
    return False


def run_sync():
    """Главная функция синхронизации.

    1. Находит файл выгрузки в сетевой папке
    2. Проверяет, обновился ли он
    3. Если да — импортирует в Turso через core.import_csv()
    4. Сохраняет состояние
    """
    log.info("=" * 60)
    log.info("Запуск синхронизации")
    log.info("Сетевая папка: %s", NETWORK_PATH)
    log.info("Имя файла: %s", FILE_NAME)

    # 1. Проверяем доступность сетевой папки
    if not os.path.isdir(NETWORK_PATH):
        log.error("Сетевая папка недоступна: %s", NETWORK_PATH)
        log.error("Проверьте подключение к сети и правильность пути.")
        return False

    # 2. Ищем файл выгрузки
    file_path = find_export_file()
    if not file_path:
        log.warning("Файл выгрузки не найден: %s", FILE_NAME)
        return False

    log.info("Найден файл: %s", file_path)

    # 3. Проверяем, обновился ли файл
    state = load_state()
    if not file_has_changed(file_path, state):
        log.info("Файл не изменился с последней синхронизации — пропускаем.")
        return True

    mtime = os.path.getmtime(file_path)
    fsize = os.path.getsize(file_path)
    log.info("Файл обновлён: размер=%d байт, время=%s",
             fsize, datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S"))

    # 4. Импортируем данные в Turso
    try:
        import core
        log.info("Запускаю импорт CSV → Turso...")
        stats = core.import_csv(
            csv_path=file_path,
            encoding=CSV_ENCODING,
            separator=CSV_SEPARATOR,
        )
        log.info("Импорт завершён: новых=%d, обновлено=%d, без изменений=%d, пропущено=%d",
                 stats["new"], stats["updated"], stats["unchanged"], stats["skipped"])
    except FileNotFoundError as e:
        log.error("Файл не найден: %s", e)
        return False
    except Exception as e:
        log.error("Ошибка при импорте: %s", e, exc_info=True)
        return False

    # 5. Сохраняем состояние
    state.update({
        "last_mtime": mtime,
        "last_fsize": fsize,
        "last_file": file_path,
        "last_sync": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_stats": stats,
    })
    save_state(state)
    log.info("Синхронизация завершена успешно.")
    return True


# ─── Точка входа ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        success = run_sync()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        log.info("Прервано пользователем.")
        sys.exit(0)
    except Exception as e:
        log.critical("Критическая ошибка: %s", e, exc_info=True)
        sys.exit(2)
