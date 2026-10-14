# Prompt: migrar grib_viewer de Tkinter a PyQt6 usando la base gráfica de `base_gui/`

## Cómo lanzar la sesión (instrucciones para Luis, no se pegan)

**Qué hay preparado en esta carpeta**

- `grib_viewer.py`, `README.md`: la app Tkinter original, sin tocar.
- `base_gui/`: kit con la base gráfica PyQt6 y su `README.md`.
- `requirements.txt`: dependencias completas (app + interfaz + empaquetado).
- `.python-version`: fija el entorno pyenv `Grib` (Python 3.14.3), ya creado y con todo instalado.
- Este archivo: el prompt.

**Paso 1: abrir una terminal parada en esta carpeta**

```
cd /Users/luis/Documents/Programacion/Claude/grib
python --version        # debe decir Python 3.14.3 (entorno Grib, activado solo por .python-version)
python -c "import PyQt6, eccodes, cartopy, matplotlib; print('ok')"
```

Si `python --version` no dice 3.14.3, el shell no tiene pyenv inicializado:

```
eval "$(pyenv init -)"
```

y repetir. Si git protesta por la licencia de Xcode:

```
export DEVELOPER_DIR=/Library/Developer/CommandLineTools
```

**Paso 2: lanzar Claude Code en esta carpeta, sin directorios extra**

```
claude
```

No usar `--add-dir`. La sesión no necesita ni debe leer nada fuera de esta carpeta.

**Paso 3: pegar el prompt**

Copiar desde la línea `## Contexto` (más abajo) hasta el final del archivo, y pegarlo como primer mensaje. Una forma cómoda:

```
sed -n '/^## Contexto/,$p' PROMPT_MIGRACION_PYQT6.md | pbcopy
```

y luego Cmd+V en la sesión. No hace falta pegar esta sección de instrucciones ni el título.

**Paso 4: qué esperar**

La sesión primero lee `base_gui/README.md`, el kit y `grib_viewer.py`, y te muestra el plan de la Fase 1 antes de escribir código. Después avanza por cuatro fases con un commit cada una y te avisa al terminar cada fase. No va a mergear a `main` ni a crear tags o releases: eso queda para vos después de pasar el plan de pruebas manual.

**Detalle del entorno que conviene saber**

- El Python 3.14.3 de pyenv **no trae `tkinter`**, así que la app vieja no se puede ejecutar en el entorno `Grib`. No hace falta: la Fase 1 se valida con tests y la app PyQt6 es la que se prueba desde la Fase 3. Si querés correr la versión Tk para comparar, usá otro intérprete con tkinter, por ejemplo `/Users/luis/.pyenv/versions/3.13.4/bin/python3`, instalándole antes numpy, matplotlib y eccodes.
- Para empaquetar con py2app al final, el `python` del entorno `Grib` ya tiene py2app instalado.

---

## Contexto

Quiero portar `grib_viewer.py` (app de escritorio Python + Tkinter + matplotlib, un solo archivo de ~1.500 líneas, en esta carpeta) a **PyQt6**, reutilizando la base gráfica y de presentación que está en la carpeta `base_gui/` de este mismo proyecto. Esa carpeta es un kit autocontenido que viene de otra app mía de escritorio; su `README.md` explica cada archivo, el contrato del stylesheet, las reglas y las trampas conocidas. **Todo lo necesario está en esta carpeta: no busques ni leas nada fuera de ella.**

El objetivo es que el visor GRIB quede con la misma apariencia e infraestructura: ventana translúcida con desenfoque nativo en macOS (opaca en Windows/Linux), tema generado a partir de un color de acento, diálogos "glass", configuración persistente, hoja de atajos, zoom de fuente, captura de errores a log y empaquetado para macOS.

Trabajá en **español rioplatense** (vos), con comentarios y mensajes de commit en español. Los commits terminan con la línea `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Entorno

- Python y paquetes: entorno pyenv `Grib` (Python 3.14.3), fijado por `.python-version`. Verificar con `python -c "import PyQt6, eccodes, cartopy, matplotlib; print('ok')"`. No crear otro entorno ni instalar nada fuera de `requirements.txt`; si falta algo, agregarlo ahí y avisar.
- Este Python **no tiene `tkinter`**: la app Tk original no se ejecuta en este entorno. No intentes instalarlo ni cambiar de intérprete; la Fase 1 se valida con tests unitarios y `python -m py_compile grib_viewer.py`, y la app que se ejecuta es la PyQt6 a partir de la Fase 3.
- Si `git` falla con "You have not agreed to the Xcode license", exportar `DEVELOPER_DIR=/Library/Developer/CommandLineTools` antes de usarlo.
- Tests: `QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -p "test_*.py"`.

## Paso 0: leer antes de tocar nada

1. `base_gui/README.md` completo, y después cada archivo de `base_gui/` (los de `app/`, `main.py`, `setup.py`, `scripts/`). `base_gui/referencia/main_window.py` se lee solo para copiar el esqueleto de la ventana principal; tiene lógica de otro dominio que no va.
2. `grib_viewer.py` y `README.md` de esta carpeta, enteros.

## Reglas de la base gráfica (no negociables)

Son las del `base_gui/README.md`; las repito porque son el contrato:

1. Todo diálogo hereda de `GlassDialog`. Nunca `QDialog` a secas.
2. Todos los colores de la interfaz salen de `build_stylesheet`. Las constantes `UI_BG`, `UI_FG`, `UI_ACCENT`, `UI_TITLE`, etc. del archivo Tk desaparecen. Excepción: la escala de colores de las barbas (cian / azul / verde / amarillo / naranja / rojo) es del dominio y se conserva en `speed_color`.
3. Un único `_apply_theme(accent, font_size, opacity)` en la ventana principal; fallback opaco si `apply_blur` devuelve `False`.
4. Atajos con `"Ctrl+..."`; en textos de ayuda, `utils.MOD_KEY`.
5. Zoom de fuente Ctrl + / Ctrl − / Ctrl 0 persistido en config.
6. Un solo `QShortcut("Escape")`.
7. Nombres de objeto del stylesheet tal cual: `MainContainer`, `AppMenuBar`, `ContentPanel`, `ActionBar`, `ActionSep`, `DropdownBtn`, `GlassPanel`, `WelcomeWidget`.
8. En tests, parchear `glass_dialog._apply_dialog_blur = lambda w: None` y aislar `app.config.CONFIG_PATH` a un directorio temporal.

## Arquitectura destino

Separar el archivo único en un paquete. La lógica sin interfaz se mueve **sin cambios de comportamiento**:

```
grib/
  main.py                      # adaptado de base_gui/main.py: nombre, extensión .grib2, sin database
  app/
    __init__.py                # __version__ = "2.0.0"
    config.py, crash_guard.py, theme.py, platform_blur.py, utils.py   # desde base_gui/
    grib_reader.py             # GribMessage, GribStep, GribReader, fl_to_hpa,
                               # speed_dir_from_uv, speed_color, fmt_dt  (sin Qt ni Tk)
    wind_plot.py               # WindPlot con backend QtAgg (sin Tk)
    main_window.py             # MainWindow(QMainWindow), esqueleto de base_gui/referencia
    widgets/
      control_panel.py         # panel derecho: STATUS, TIME, LEVEL, VARIABLE, CONFIG, RECUADRO
      inventory_panel.py       # QPlainTextEdit solo lectura, fuente monoespaciada
      welcome_widget.py        # desde base_gui/
    dialogs/
      glass_dialog.py, settings_dialog.py, shortcuts_dialog.py   # desde base_gui/
      about_dialog.py
  tests/
  docs/PLAN_PRUEBAS_2_0_0.md
  scripts/build.sh, setup.py, scripts/make_icon.py   # desde base_gui/, adaptados
  resources/
  requirements.txt             # ya actualizado, no tocar salvo que falte algo
```

`base_gui/` se borra en la última fase, cuando todo lo útil ya esté en `app/`.

### matplotlib dentro de Qt

- `matplotlib.use("QtAgg")` antes de cualquier otro import de matplotlib; `from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT`.
- El fondo de la figura y de los ejes toma colores de `theme.generate_palette(accent)` (`bg_data` para la figura, `text_bright` para textos y ejes) y se actualiza cuando cambia el tema. El canvas es opaco: no intentar hacerlo translúcido. Va dentro de un `QFrame` con `objectName("GlassPanel")`.
- `NavigationToolbar2QT` trae íconos negros que no se ven sobre fondo oscuro: ocultarla y reemplazarla por botones propios (Inicio, Zoom, Pan, Guardar PNG) en la `ActionBar`, conectados a `toolbar.home()`, `toolbar.zoom()`, `toolbar.pan()` y `export_png`. Mantener la instancia de la toolbar aunque esté oculta porque es la que implementa zoom y pan.
- Conservar los eventos `motion_notify_event` (lat/lon/velocidad/dirección/T bajo el cursor, en la `QStatusBar`) y `draw_event` (sincronizar las entradas del recuadro con la vista).

### Equivalencias Tk → Qt

| Tkinter | Qt |
|---|---|
| `ttk.Frame` / `LabelFrame` con título | `QFrame#GlassPanel` con `QLabel` de título en negrita |
| `Radiobutton` (Current / Next / Advanced; Viento / Temperatura / Ambas) | `QRadioButton` en `QButtonGroup` |
| Botones F050…F530 con estilo `Sel.FL.TButton` | `QPushButton` `checkable` en un `QButtonGroup` exclusivo, grilla de 4 columnas |
| `ttk.Combobox` readonly | `QComboBox` |
| `Checkbutton` (Extra Info, Grilla, Fondo de velocidad) | `QCheckBox` |
| `Spinbox` Densidad | `QSpinBox` |
| `Entry` lat/lon | `QLineEdit` con `QDoubleValidator` y `returnPressed` → aplicar |
| `ScrolledText` inventario | `QPlainTextEdit` solo lectura |
| `Status.TLabel` (texto verde monoespaciado) | `QLabel` con `objectName("StatusMono")`, fuente monoespaciada, color de la paleta |
| `filedialog` / `messagebox` | `QFileDialog` / `QMessageBox` (padre = ventana principal) |
| barra inferior | `QStatusBar` |
| `after(...)` | `QTimer.singleShot` |

Comportamientos a conservar exactamente: redibujo automático al cambiar radio, botón de nivel, combo o checkbox; combo de pasos solo si hay más de tres; interpolación ISA / ln(p) y aviso "extrapolado" en STATUS; `Todo el dominio`; exportar PNG y CSV con el nombre por defecto actual; abrir archivo desde argv; aviso cuando cartopy no está.

### Menús y atajos

- Archivo: Abrir GRIB… (Ctrl+O), Recientes, Exportar PNG… (Ctrl+E), Exportar CSV… (Ctrl+Shift+E), Cerrar archivo (Ctrl+W), Salir.
- Vista: Todo el dominio (Ctrl+Shift+0; Ctrl+0 queda para la fuente), Actualizar (F5), Capa de datos activada/desactivada (Ctrl+D), Preferencias… (Ctrl+,).
- Ayuda: Atajos de teclado, Acerca de.
- `WelcomeWidget` cuando no hay archivo abierto, con "Abrir GRIB…" y recientes; al abrir, se reemplaza por el mapa.

## Forma de trabajo

1. Esta carpeta no es un repo: `git init`, commit inicial con el estado actual tal cual (incluida `base_gui/`), y rama `FEAT-PYQT6` desde `main`.
2. Fases con commit al final de cada una, en este orden:
   - **Fase 1**: extraer `app/grib_reader.py` y `app/wind_plot.py` del archivo Tk sin tocar la lógica; `grib_viewer.py` queda importándolos (solo verificable con `py_compile`, ver Entorno). Tests unitarios de `fl_to_hpa`, `speed_dir_from_uv`, `speed_color`, normalización de longitudes y reordenamiento de latitudes, e interpolación en ln(p) con arreglos sintéticos (no hace falta un `.grib2` real; si hay uno en la carpeta, sumar un test de inventario que se salte si no existe).
   - **Fase 2**: copiar la base gráfica de `base_gui/` a `app/`, adaptar `main.py`, y `MainWindow` vacía con tema, menús, preferencias, atajos, bienvenida, geometría. Test offscreen de que la ventana y cada diálogo abren y cierran.
   - **Fase 3**: mapa Qt + panel de controles + inventario + barra de estado, con todos los comportamientos de la lista. Test offscreen de que cambiar nivel, paso o variable dispara el redibujo sobre un `GribReader` falso.
   - **Fase 4**: borrar `grib_viewer.py`, los imports de Tk y `base_gui/`; actualizar `README.md` (instalación con el entorno `Grib`, uso, atajos), `scripts/build.sh` y `setup.py`. Plan de pruebas manual `docs/PLAN_PRUEBAS_2_0_0.md` con casos numerados.
3. **No commitear con tests en rojo**: no usar `tests | grep ... && git commit` (grep devuelve 0 aunque haya FAIL); commitear solo tras verificar la línea `OK`.
4. No mergear a `main` ni crear tag ni release: eso lo decido yo después de pasar el plan de pruebas en la app real.
5. Si algo de la base no encaja con una app de un solo documento sin "proyectos" (por ejemplo `last_project_id` en `DEFAULTS`, o `remove_session_db` en `main.py`), quitalo y anotalo en el resumen final; no inventes equivalentes.
6. Avisame al terminar cada fase con un resumen corto de lo hecho, los tests que corren y lo que quedó pendiente. No preguntes antes de las decisiones de rutina; preguntá solo si dos lecturas del pedido llevan a trabajo materialmente distinto.

Empezá por el Paso 0 y, antes de escribir código, mostrame en pocas líneas el plan de la Fase 1 y qué partes de `grib_viewer.py` van a cada módulo.
