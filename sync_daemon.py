# -*- coding: utf-8 -*-
"""Автосинхронизация 1С → SQLite Cloud.

Скрипт мониторит файл выгрузки из 1С (CSV) в сетевой папке в реальном времени,
и при появлении обновленного файла — импортирует данные в облачную БД SQLite Cloud.

Использует watchdog для реального мониторинга файловой системы.
Запускается как Windows Service для непрерывной работы.
Использование:  python sync_daemon.py
"""
import os
import sys
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from dotenv import load_dotenv

# Загружаем переменные окружения из .env
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

# ─── Настройки ───────────────────────────────────────────────────────────────
NETWORK_PATH = os.getenv(
    "SYNC_NETWORK_PATH",
    r"\\kz-srv1.lan.dns-shop.kz\kazakhstan\Отдел функционального развития\B2B\РМКО"
)
FILE_NAME = os.getenv("SYNC_FILE_NAME", "РМКО_выгрузка.csv")
CSV_ENCODING = os.getenv("SYNC_CSV_ENCODING", "utf-8")
_raw_sep = os.getenv("SYNC_CSV_SEPARATOR", ";")
# Интерпретация escape-последовательностей: "\t" → табуляция, "\n" → перенос строки
CSV_SEPARATOR = _raw_sep.encode().decode("unicode_escape") if _raw_sep else ";"

# Файл для отслеживания последней синхронизации
STATE_FILE = os.path.join(BASE_DIR, ".sync_state.json")
LOG_FILE = os.path.join(BASE_DIR, "sync.log")

# Задержка перед синхронизацией (сек) после обнаружения изменения файла
# Нужно чтобы файл полностью записался 1С
SYNC_DELAY = 5

# Размер батча для импорта в SQLite Cloud
BATCH_SIZE = 1000

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


def validate_csv_structure(file_path):
    """Валидация структуры CSV файла перед импортом.
    
    Проверяет:
    - Файл существует и доступен для чтения
    - Файл не пустой
    - Есть обязательные колонки
    
    Returns:
        tuple: (is_valid, error_message)
    """
    try:
        import csv
        with open(file_path, 'r', encoding=CSV_ENCODING) as f:
            reader = csv.reader(f, delimiter=CSV_SEPARATOR)
            header = next(reader, None)
            
            if not header:
                return False, "Файл пуст или не содержит заголовков"
            
            # Проверка обязательных колонок
            required_cols = ["НомерДокумента", "ДатаСоздания"]
            header_clean = [str(c).strip().lstrip('\ufeff') for c in header]
            missing = [col for col in required_cols if col not in header_clean]
            
            if missing:
                return False, f"Отсутствуют обязательные колонки: {', '.join(missing)}"
            
            # Проверяем что есть хотя бы одна строка данных
            first_row = next(reader, None)
            if not first_row:
                return False, "Файл не содержит данных"
            
            return True, None
            
    except UnicodeDecodeError as e:
        return False, f"Ошибка кодировки: {e}"
    except Exception as e:
        return False, f"Ошибка валидации: {e}"


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
    3. Валидирует структуру CSV
    4. Если да — импортирует в облако через core.import_csv()
    5. Сохраняет состояние
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

    # 4. Валидация структуры CSV
    log.info("Валидация структуры CSV...")
    is_valid, error_msg = validate_csv_structure(file_path)
    if not is_valid:
        log.error("Валидация не пройдена: %s", error_msg)
        log.error("Импорт отменён для защиты базы данных от некорректных данных.")
        return False
    log.info("Валидация пройдена успешно.")

    # 5. Импортируем данные в БД
    try:
        import core
        log.info("Запускаю импорт CSV → SQLite Cloud (batch size=%d)...", BATCH_SIZE)
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
        log.error("Импорт не завершён. База данных осталась в консистентном состоянии.")
        return False

    # 6. Сохраняем состояние
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


# ─── Watchdog обработчик событий ──────────────────────────────────────────────

class CSVFileHandler(FileSystemEventHandler):
    """Обработчик событий файловой системы для мониторинга CSV файла."""
    
    def __init__(self):
        self.last_event_time = 0
        self.pending_sync = False
    
    def on_modified(self, event):
        """При изменении файла — планируем синхронизацию с задержкой."""
        if event.is_directory:
            return
        
        file_name = os.path.basename(event.src_path)
        # Проверяем что это именно наш файл
        if file_name == FILE_NAME or file_name.startswith(FILE_NAME.replace('.csv', '')):
            current_time = time.time()
            self.last_event_time = current_time
            self.pending_sync = True
            log.info("Обнаружено изменение файла: %s", event.src_path)
    
    def on_created(self, event):
        """При создании файла — планируем синхронизацию с задержкой."""
        if event.is_directory:
            return
        
        file_name = os.path.basename(event.src_path)
        if file_name == FILE_NAME or file_name.startswith(FILE_NAME.replace('.csv', '')):
            current_time = time.time()
            self.last_event_time = current_time
            self.pending_sync = True
            log.info("Обнаружен новый файл: %s", event.src_path)


def run_continuous_monitor():
    """Непрерывный мониторинг папки с помощью watchdog."""
    log.info("=" * 60)
    log.info("Запуск непрерывного мониторинга")
    log.info("Сетевая папка: %s", NETWORK_PATH)
    log.info("Имя файла: %s", FILE_NAME)
    log.info("Задержка перед синхронизацией: %d сек", SYNC_DELAY)
    log.info("Нажмите Ctrl+C для остановки")
    
    # Проверяем доступность папки перед стартом
    if not os.path.isdir(NETWORK_PATH):
        log.error("Сетевая папка недоступна: %s", NETWORK_PATH)
        return False
    
    event_handler = CSVFileHandler()
    observer = Observer()
    observer.schedule(event_handler, NETWORK_PATH, recursive=False)
    
    try:
        observer.start()
        log.info("Мониторинг запущен...")
        
        while True:
            time.sleep(1)
            
            # Проверяем нужно ли выполнить синхронизацию
            if event_handler.pending_sync:
                time_since_last_event = time.time() - event_handler.last_event_time
                
                # Ждем пока файл перестанет изменяться (SYNC_DELAY)
                if time_since_last_event >= SYNC_DELAY:
                    event_handler.pending_sync = False
                    log.info("Выполняем синхронизацию...")
                    run_sync()
                    log.info("Ожидание следующих изменений...")
                    
    except KeyboardInterrupt:
        log.info("Получен сигнал остановки...")
        observer.stop()
    except Exception as e:
        log.critical("Критическая ошибка в мониторе: %s", e, exc_info=True)
        observer.stop()
        return False
    
    observer.join()
    log.info("Мониторинг остановлен.")
    return True


# ─── Точка входа ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    
    # Режим работы: one-shot (однократная синхронизация) или monitor (непрерывный)
    mode = sys.argv[1] if len(sys.argv) > 1 else "monitor"
    
    if mode == "once":
        # Однократная синхронизация (для тестирования или ручного запуска)
        try:
            success = run_sync()
            sys.exit(0 if success else 1)
        except KeyboardInterrupt:
            log.info("Прервано пользователем.")
            sys.exit(0)
        except Exception as e:
            log.critical("Критическая ошибка: %s", e, exc_info=True)
            sys.exit(2)
    elif mode == "monitor":
        # Непрерывный мониторинг (основной режим)
        try:
            success = run_continuous_monitor()
            sys.exit(0 if success else 1)
        except Exception as e:
            log.critical("Критическая ошибка: %s", e, exc_info=True)
            sys.exit(2)
    else:
        print(f"Неизвестный режим: {mode}")
        print("Использование:")
        print("  python sync_daemon.py once   - однократная синхронизация")
        print("  python sync_daemon.py monitor - непрерывный мониторинг (по умолчанию)")
        sys.exit(1)
