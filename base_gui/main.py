import sys
import os
import platform

# Allow running from any directory
sys.path.insert(0, os.path.dirname(__file__))

# Fix macOS native menu bar showing "Python" instead of app name
if platform.system() == "Darwin":
    try:
        from Foundation import NSBundle
        info = NSBundle.mainBundle().infoDictionary()
        info["CFBundleName"] = "Presupuestador Pro"
    except Exception:
        pass

from PyQt6.QtWidgets import QApplication, QStyleFactory
from PyQt6.QtCore import Qt, QEvent, QTimer, QTranslator, QLocale, QLibraryInfo
from PyQt6.QtGui import QFont, QFontDatabase

from app.main_window import MainWindow

FILE_EXTENSION = ".ppto"


class PresupuestadorApp(QApplication):
    """QApplication subclass that handles macOS FileOpen events.

    When the user double-clicks a .ppto file in Finder, macOS sends an
    Apple Event (not a command-line argument).  Qt translates that into a
    QEvent.Type.FileOpen which we catch here.
    """

    def __init__(self, argv):
        super().__init__(argv)
        self._pending_file: str | None = None
        self._window: MainWindow | None = None

    def set_window(self, window: MainWindow):
        self._window = window
        # If a FileOpen arrived before the window was ready, open it now
        if self._pending_file:
            QTimer.singleShot(300, lambda: self._open(self._pending_file))
            self._pending_file = None

    def event(self, event):
        if event.type() == QEvent.Type.FileOpen:
            path = event.file()
            if path and os.path.isfile(path):
                if self._window:
                    QTimer.singleShot(100, lambda: self._open(path))
                else:
                    self._pending_file = path
                return True
        return super().event(event)

    def _open(self, path: str):
        if self._window:
            self._window.open_file(path)


def main():
    # Enable HiDPI
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

    # Excepciones no controladas: registrar y avisar, en vez de abortar
    from app import crash_guard
    crash_guard.install()
    import atexit
    from app import database as _db
    atexit.register(_db.remove_session_db)

    app = PresupuestadorApp(sys.argv)
    app.setApplicationName("Presupuestador Pro")

    # Textos estándar de Qt en español (Sí / No / Cancelar / Aceptar, diálogos
    # de archivo, etc.).  El traductor debe vivir mientras viva la app.
    app._qt_translator = QTranslator(app)
    if app._qt_translator.load(
            "qtbase_es", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(app._qt_translator)
    app.setOrganizationName("PresupuestadorPro")
    app.setApplicationDisplayName("Presupuestador Pro")

    # Usar estilo Fusion en lugar del nativo de macOS.
    app.setStyle(QStyleFactory.create("Fusion"))

    # Default font: la del sistema (en macOS es SF Pro; pedirla por nombre
    # "SF Pro Display" no la encuentra y Qt avisa en consola).
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
    font.setPointSize(13)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    app.setFont(font)

    window = MainWindow()
    window.show()
    app.set_window(window)

    # Also handle command-line argument (e.g. `open file.ppto` from terminal)
    for arg in sys.argv[1:]:
        if os.path.isfile(arg):
            QTimer.singleShot(300, lambda p=arg: window.open_file(p))
            break

    # Apply native blur directly to the main window (no companion window).
    # Si no hay desenfoque (Windows sin acrílico, Linux), la ventana queda
    # opaca con el fondo del tema en vez de translúcida sobre el escritorio.
    from app.platform_blur import apply_blur

    def _blur_or_opaque():
        if not apply_blur(window):
            from app.theme import opaque_window_css
            window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
            window.setStyleSheet(opaque_window_css(window._cfg["accent_color"]))
    QTimer.singleShot(50, _blur_or_opaque)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
