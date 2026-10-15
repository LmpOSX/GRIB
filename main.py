import sys
import os
import platform

# pyproj (PROJ, que trae sus propias libcurl, libtiff y libsqlite3) tiene que
# cargarse antes que PyQt6 y ecCodes: en Linux, si se carga después, la
# finalización del intérprete aborta ("double free" / "corrupted size").
try:
    import pyproj  # noqa: F401
except ImportError:
    pass

# Permite ejecutar desde cualquier directorio
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# macOS: que la barra de menú diga el nombre de la app y no "Python"
if platform.system() == "Darwin":
    try:
        from Foundation import NSBundle
        info = NSBundle.mainBundle().infoDictionary()
        info["CFBundleName"] = "Visor GRIB"
    except Exception:
        pass

from PyQt6.QtWidgets import QApplication, QStyleFactory
from PyQt6.QtCore import Qt, QEvent, QTimer, QTranslator, QLibraryInfo
from PyQt6.QtGui import QFont, QFontDatabase

from app.main_window import MainWindow

FILE_EXTENSIONS = (".grib2", ".grb2", ".grib", ".grb")


class GribViewerApp(QApplication):
    """QApplication que atiende los eventos FileOpen de macOS.

    Cuando el usuario abre un .grib2 desde el Finder, macOS manda un Apple
    Event (no un argumento de línea de comandos); Qt lo traduce a un
    QEvent.Type.FileOpen que se captura acá.
    """

    def __init__(self, argv):
        super().__init__(argv)
        self._pending_file: str | None = None
        self._window: MainWindow | None = None

    def set_window(self, window: MainWindow):
        self._window = window
        # Si el FileOpen llegó antes de que existiera la ventana, abrirlo ahora
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
    # HiDPI
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

    # Excepciones no controladas: registrar y avisar, en vez de abortar
    from app import crash_guard
    crash_guard.install()

    app = GribViewerApp(sys.argv)
    app.setApplicationName("Visor GRIB")

    # Textos estándar de Qt en español (Sí / No / Cancelar / Aceptar, diálogos
    # de archivo, etc.).  El traductor debe vivir mientras viva la app.
    app._qt_translator = QTranslator(app)
    if app._qt_translator.load(
            "qtbase_es", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(app._qt_translator)
    app.setOrganizationName("VisorGRIB")
    app.setApplicationDisplayName("Visor GRIB")

    # Estilo Fusion en lugar del nativo de macOS
    app.setStyle(QStyleFactory.create("Fusion"))

    # Fuente por defecto: la del sistema (en macOS es SF Pro; pedirla por
    # nombre "SF Pro Display" no la encuentra y Qt avisa en consola).
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
    font.setPointSize(13)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    app.setFont(font)

    window = MainWindow()
    window.show()
    app.set_window(window)

    # Archivo por línea de comandos: `python main.py archivo.grib2`
    file_arg = next((a for a in sys.argv[1:] if os.path.isfile(a)), None)
    if file_arg:
        QTimer.singleShot(300, lambda p=file_arg: window.open_file(p))

    # Prueba de humo del empaquetado (scripts/build*.sh): con VISOR_GRIB_SMOKE=<seg>
    # la app se cierra sola; código 0 si la ventana se mostró y el archivo
    # pedido quedó cargado (ecCodes, matplotlib y cartopy dentro del paquete).
    smoke = os.environ.get("VISOR_GRIB_SMOKE")
    if smoke:
        try:
            wait_ms = int(float(smoke) * 1000)
        except ValueError:
            wait_ms = 6000

        def _smoke_exit():
            ok = window.isVisible() and (not file_arg or window._reader is not None)
            print("smoke:", "ok" if ok else "FALLO", flush=True)
            app.exit(0 if ok else 3)
        QTimer.singleShot(wait_ms, _smoke_exit)

    # Desenfoque nativo directamente sobre la ventana principal. Si no hay
    # desenfoque (Windows sin acrílico, Linux), la ventana queda opaca con el
    # fondo del tema en vez de translúcida sobre el escritorio.
    from app.platform_blur import apply_blur

    from app.platform_blur import disable_native_fullscreen

    def _blur_or_opaque():
        if not apply_blur(window):
            from app.theme import opaque_window_css
            window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
            window.setStyleSheet(opaque_window_css(window._cfg["accent_color"]))
        else:
            # Con desenfoque, el botón verde maximiza (la pantalla completa
            # nativa dejaría la ventana opaca sobre un Space negro)
            disable_native_fullscreen(window)
    QTimer.singleShot(50, _blur_or_opaque)

    rc = app.exec()

    # Salida ordenada: el mapa (matplotlib) y la ventana se destruyen antes
    # que QApplication
    window.close()
    window.deleteLater()
    app.processEvents()
    del window
    sys.exit(rc)


if __name__ == "__main__":
    main()
