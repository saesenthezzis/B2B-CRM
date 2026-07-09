# -*- coding: utf-8 -*-
"""Windows Service для автоматической синхронизации 1С → SQLite Cloud.

Запускается как фоновый сервис Windows и мониторит сетевую папку
с файлом выгрузки из 1С в реальном времени.

Установка:
    python sync_service.py install
    python sync_service.py start

Удаление:
    python sync_service.py stop
    python sync_service.py remove
"""
import os
import sys
import time
import logging
from pathlib import Path

# Добавляем путь к sync_daemon.py для импорта
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

try:
    import win32service
    import win32serviceutil
    import win32event
    import servicemanager
    _HAS_WIN32 = True
except ImportError:
    _HAS_WIN32 = False
    print("WARNING: pywin32 не установлен. Установите: pip install pywin32")


class RMKOSyncService(win32serviceutil.ServiceFramework):
    """Windows Service для мониторинга синхронизации РМКО."""
    
    _svc_name_ = "RMKOSyncService"
    _svc_display_name_ = "РМКО Автосинхронизация 1С-SQLiteCloud"
    _svc_description_ = "Мониторит сетевую папку с выгрузкой из 1С и автоматически синхронизирует данные в облачную БД SQLite Cloud"
    
    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        self.is_alive = True
        self.monitor_thread = None
        
    def SvcStop(self):
        """Остановка сервиса."""
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self.is_alive = False
        win32event.SetEvent(self.hWaitStop)
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STOPPED,
            (self._svc_name_, '')
        )
        
    def SvcDoRun(self):
        """Основной рабочий цикл сервиса."""
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, '')
        )
        
        self.run_monitor()
        
    def run_monitor(self):
        """Запуск мониторинга в отдельном потоке."""
        try:
            # Импортируем sync_daemon только при запуске
            import sync_daemon
            
            # Настраиваем логирование для сервиса
            log = logging.getLogger("sync")
            log.setLevel(logging.INFO)
            
            # Лог в файл
            log_file = os.path.join(BASE_DIR, "sync.log")
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setFormatter(logging.Formatter(
                "%(asctime)s  %(levelname)-7s  %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            ))
            log.addHandler(file_handler)
            
            # Лог в Windows Event Log
            event_handler = logging.Handler()
            event_handler.emit = lambda record: servicemanager.LogInfoMsg(
                f"{record.levelname}: {record.getMessage()}"
            )
            log.addHandler(event_handler)
            
            log.info("=" * 60)
            log.info("Запуск Windows Service для синхронизации РМКО")
            log.info("Сетевая папка: %s", sync_daemon.NETWORK_PATH)
            log.info("Имя файла: %s", sync_daemon.FILE_NAME)
            
            # Импортируем классы мониторинга из sync_daemon
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
            
            class CSVHandler(FileSystemEventHandler):
                """Обработчик событий файловой системы."""
                
                def __init__(self, sync_function):
                    self.sync_function = sync_function
                    self.last_sync = 0
                    
                def on_modified(self, event):
                    """При изменении файла."""
                    if event.is_directory:
                        return
                    
                    file_path = event.src_path
                    file_name = os.path.basename(file_path)
                    
                    # Проверяем что это нужный файл
                    target_name = sync_daemon.FILE_NAME.lower()
                    if not file_name.lower().startswith(target_name.replace('.csv', '')):
                        return
                    
                    # Проверяем задержку между синхронизациями
                    now = time.time()
                    if now - self.last_sync < sync_daemon.SYNC_DELAY:
                        return
                    
                    log.info("Обнаружено изменение файла: %s", file_name)
                    self.last_sync = now
                    
                    # Задержка для завершения записи файла
                    time.sleep(sync_daemon.SYNC_DELAY)
                    
                    # Запускаем синхронизацию
                    try:
                        self.sync_function()
                    except Exception as e:
                        log.error("Ошибка при синхронизации: %s", e)
            
            # Создаём обработчик
            handler = CSVHandler(sync_daemon.run_sync)
            
            # Настраиваем наблюдателя
            observer = Observer()
            observer.schedule(handler, sync_daemon.NETWORK_PATH, recursive=False)
            
            # Запускаем наблюдение
            observer.start()
            log.info("Мониторинг запущен. Ожидание изменений...")
            
            # Основной цикл сервиса
            while self.is_alive:
                # Проверяем состояние сервиса
                win32event.WaitForSingleObject(self.hWaitStop, 1000)
                
                # Периодическая проверка доступности сетевой папки
                if not os.path.isdir(sync_daemon.NETWORK_PATH):
                    log.warning("Сетевая папка недоступна: %s", sync_daemon.NETWORK_PATH)
                    time.sleep(30)
                    continue
                
                # Проверяем файл (может пропустить события watchdog)
                try:
                    file_path = sync_daemon.find_export_file()
                    if file_path:
                        state = sync_daemon.load_state()
                        if sync_daemon.file_has_changed(file_path, state):
                            log.info("Проверка: файл изменён, запускаем синхронизацию")
                            sync_daemon.run_sync()
                except Exception as e:
                    log.error("Ошибка при периодической проверке: %s", e)
            
            # Останавливаем наблюдателя
            observer.stop()
            observer.join()
            log.info("Мониторинг остановлен")
            
        except Exception as e:
            servicemanager.LogErrorMsg(f"Критическая ошибка сервиса: {e}")
            log.critical("Критическая ошибка: %s", e)


if __name__ == '__main__':
    if not _HAS_WIN32:
        print("ERROR: pywin32 не установлен")
        print("Установите: pip install pywin32")
        sys.exit(1)
    
    if len(sys.argv) == 1:
        # Если запущен без аргументов - для тестирования
        print("Запуск в тестовом режиме (не как сервис)")
        print("Для установки сервиса:")
        print("  python sync_service.py install")
        print("  python sync_service.py start")
        print()
        
        # Тестовый запуск
        service = RMKOSyncService(None)
        service.run_monitor()
    else:
        # Команды управления сервисом
        win32serviceutil.HandleCommandLine(RMKOSyncService)