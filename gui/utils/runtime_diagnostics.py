"""Keep Python exceptions and native Qt failures available after exit."""

import faulthandler
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
import threading

_fault_file = None
_qt_handler = None


def install_diagnostics(log_dir):
    global _fault_file, _qt_handler
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    handler = RotatingFileHandler(log_dir / "runtime.log", maxBytes=3_000_000,
                                  backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(message)s"))
    root.addHandler(handler)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    _fault_file = open(log_dir / "crash.log", "a", encoding="utf-8")
    faulthandler.enable(file=_fault_file, all_threads=True)

    def exception_hook(kind, value, traceback):
        logging.critical("Unhandled Python exception", exc_info=(kind, value, traceback))
        sys.__excepthook__(kind, value, traceback)

    sys.excepthook = exception_hook

    def thread_hook(args):
        exception_hook(args.exc_type, args.exc_value, args.exc_traceback)

    threading.excepthook = thread_hook
    from PyQt5.QtCore import qInstallMessageHandler, QtCriticalMsg, QtFatalMsg

    def qt_handler(kind, context, message):
        level = logging.ERROR if kind in (QtCriticalMsg, QtFatalMsg) else logging.WARNING
        logging.log(level, "Qt: %s", message)
        if sys.__stderr__:
            print(message, file=sys.__stderr__)

    _qt_handler = qt_handler
    qInstallMessageHandler(_qt_handler)
    logging.info("GUI started; Python %s", sys.version.split()[0])


def log_task_error(message):
    logging.error("Task failed: %s", message)
