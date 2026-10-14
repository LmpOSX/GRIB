"""Último recurso ante excepciones no controladas en slots de Qt.

PyQt6 llama a qFatal() (abort del proceso, sin guardar nada) cuando una
excepción de Python escapa de un slot o de un método virtual reimplementado
**y** sys.excepthook es el original.  Con un hook propio la excepción se
registra en un archivo, se muestra al usuario y el programa sigue vivo.
"""
import logging
import os
import sys
import traceback

LOG_NAME = "errores.log"
_log = logging.getLogger("presupuestador.crash")
_installed_path: str | None = None


def default_log_path() -> str:
    from .config import CONFIG_PATH
    return os.path.join(os.path.dirname(CONFIG_PATH), LOG_NAME)


def _show_dialog(summary: str, details: str, log_path: str | None):
    """Aviso al usuario (reemplazable en tests)."""
    from PyQt6.QtWidgets import QApplication, QMessageBox
    if QApplication.instance() is None:
        return
    box = QMessageBox(QMessageBox.Icon.Critical, "Error inesperado",
                      "Ocurrió un error inesperado. El programa sigue funcionando, "
                      "pero conviene guardar el presupuesto y volver a abrirlo.\n\n" + summary)
    if log_path:
        box.setInformativeText(f"Detalle registrado en:\n{log_path}")
    box.setDetailedText(details)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.exec()


def handle_exception(etype, value, tb):
    if issubclass(etype, KeyboardInterrupt):
        sys.__excepthook__(etype, value, tb)
        return
    details = "".join(traceback.format_exception(etype, value, tb))
    summary = "".join(traceback.format_exception_only(etype, value)).strip()
    try:
        _log.error("Excepción no controlada:\n%s", details)
    except Exception:
        pass
    try:
        sys.stderr.write(details)
    except Exception:
        pass
    try:
        _show_dialog(summary, details, _installed_path)
    except Exception:
        pass


def install(log_path: str | None = None) -> str:
    """Instala el hook y el log a archivo.  Devuelve la ruta del log."""
    global _installed_path
    path = log_path or default_log_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        for h in list(_log.handlers):
            _log.removeHandler(h)
        _log.addHandler(handler)
        _log.setLevel(logging.ERROR)
        _log.propagate = False
    except OSError:
        path = ""
    _installed_path = path or None
    sys.excepthook = handle_exception
    return path
