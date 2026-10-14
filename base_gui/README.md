# base_gui: base gráfica y de presentación (PyQt6)

Kit autocontenido copiado de otra app de escritorio del mismo autor. Es el punto
de partida para la interfaz PyQt6 del visor GRIB. Todo lo que hay acá está
probado en macOS y Windows; no depende de nada fuera de esta carpeta.

## Contenido

| Archivo | Qué es | Uso en el visor |
|---|---|---|
| `app/theme.py` | Paleta generada desde un color de acento, `build_stylesheet(accent, font_size, opacity)`, `opaque_window_css`, `opaque_base_css`, pila de fuentes | Copiar sin cambios |
| `app/platform_blur.py` | `apply_blur(widget)`: desenfoque nativo macOS (pyobjc) y Windows; devuelve `False` si falla | Copiar sin cambios |
| `app/dialogs/glass_dialog.py` | `GlassDialog(QDialog)`: barra de título nativa transparente, blur y arreglo del alto con FullSizeContentView | Copiar sin cambios |
| `app/dialogs/settings_dialog.py` | Preferencias: color de acento, opacidad y tamaño de fuente. Firma `SettingsDialog(parent, current_color, ...)` | Copiar; quitar lo que no aplique |
| `app/dialogs/shortcuts_dialog.py` | Hoja de atajos; tabla `SHORTCUTS` de tuplas (grupo, acción, atajo) | Copiar; reemplazar la tabla |
| `app/widgets/welcome_widget.py` | Pantalla vacía con acciones y archivos recientes | Copiar; adaptar textos y señales |
| `app/config.py` | `config.json` en Application Support / APPDATA / XDG; `DEFAULTS`, límites de opacidad y fuente, recientes, directorio de trabajo | Copiar; cambiar `APP_NAME` y `DEFAULTS` |
| `app/crash_guard.py` | `sys.excepthook` que escribe `errores.log` junto al config | Copiar sin cambios |
| `app/utils.py` | `MOD_KEY`, `IS_MAC`, `IS_WINDOWS` y formato numérico español | Copiar la parte de plataforma |
| `main.py` | `QApplication` subclass: nombre de la app en la barra de menú de macOS vía `NSBundle`, evento `FileOpen` del Finder, archivo por argv, traductor de Qt al español, estilo Fusion, blur o fallback opaco | Copiar y adaptar (quitar `database`, cambiar nombre y extensión) |
| `setup.py` | py2app: bundle, icono, asociación de extensión | Copiar y adaptar |
| `scripts/build.sh` | `.app` + DMG con AppleScript para la ventana del instalador | Copiar y adaptar nombres |
| `scripts/make_icon.py`, `scripts/make_ico.py` | Icono generado por código → `.icns` / `.ico` | Reemplazar el dibujo |
| `resources/app_icon.png` | Icono de ejemplo | Reemplazar |
| `windows/` | Workflow de GitHub Actions (PyInstaller + Inno Setup) y sus archivos `.spec` / `.iss` | Opcional, fase final |
| `.gitignore` | Python, venv, build, config local, log | Copiar y ajustar |
| `referencia/main_window.py` | Ventana principal de la app de origen. **Solo lectura, no copiar**: tiene lógica de otro dominio | Ver el esqueleto: `_apply_theme`, `_register_shortcuts`, zoom de fuente, `_build_ui`, menús, `_restore_geometry`, `closeEvent` |

## Contrato del stylesheet

`build_stylesheet` estiliza por `objectName`. Usar estos nombres tal cual:
`MainContainer`, `AppMenuBar`, `ContentPanel`, `ActionBar`, `ActionSep`,
`DropdownBtn`, `SearchField`, `GlassPanel`, `WelcomeWidget`.

## Reglas

1. Todo diálogo hereda de `GlassDialog`. Nunca `QDialog` a secas.
2. Los colores salen solo de `build_stylesheet`; no se escriben colores a mano en widgets Qt.
3. El tema se aplica con `QApplication.instance().setStyleSheet(...)` desde un único `_apply_theme(accent, font_size, opacity)` en la ventana principal. Si `apply_blur` devuelve `False`, quitar `WA_TranslucentBackground` y sumar `opaque_window_css`.
4. Atajos declarados con `"Ctrl+..."` (Qt los traduce a ⌘ en macOS); en textos de ayuda usar `utils.MOD_KEY`.
5. Zoom de fuente con Ctrl + / Ctrl − / Ctrl 0, persistido en config.
6. Un solo `QShortcut("Escape")` en la ventana principal; otro en un hijo lo vuelve ambiguo y no corre ninguno.
7. Geometría de ventana restaurada desde config al abrir.

## Trampas conocidas

- `GlassDialog.show()` hace **segfault** con `QT_QPA_PLATFORM=offscreen` por el blur nativo. En tests: `glass_dialog._apply_dialog_blur = lambda w: None` antes de mostrar cualquier diálogo.
- Con FullSizeContentView el layout recibe un alto 28 px menor que el widget; `GlassDialog` lo corrige en `resizeEvent` y `LayoutRequest`. No tocar.
- Fuera de macOS la ventana y los diálogos deben ser opacos (ya contemplado).
- Todo widget creado en un test debe guardarse en `self.w` o cerrarse; huérfano, el GC lo destruye y Qt hace segfault.
- `_font_stack()` consulta `QFontDatabase`: hace falta una `QApplication` viva antes de `build_stylesheet`.
- `config.CONFIG_PATH` cae a la carpeta del código si la app no está empaquetada; en tests aislar `app.config.CONFIG_PATH` a un directorio temporal.

## Verificación rápida

Con el entorno `Grib` (Python 3.14.3) activo, parado en esta carpeta:

```
QT_QPA_PLATFORM=offscreen python -c "
from PyQt6.QtWidgets import QApplication; app = QApplication([])
from app.theme import build_stylesheet; app.setStyleSheet(build_stylesheet('#4A90D9'))
from app.dialogs import glass_dialog; glass_dialog._apply_dialog_blur = lambda w: None
from app.dialogs.settings_dialog import SettingsDialog; d = SettingsDialog(None, '#4A90D9'); d.show(); print('OK')"
```
