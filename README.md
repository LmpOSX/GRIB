# Visor GRIB – Viento y temperatura GRIB2 (GFS)

Aplicación de escritorio (Python 3.14 + PyQt6 + matplotlib + cartopy
opcional) para visualizar archivos GRIB2 con componentes de viento
(UGRD/VGRD) y temperatura (TMP) en niveles de presión, con un panel de
controles al estilo de un sistema ATC: selección de paso (Current / Next /
Advanced), nivel de vuelo (F050…F530 convertido a presión ISA e interpolado
en ln p), barbas coloreadas por velocidad, contornos de temperatura, "Extra
Info", grilla, zoom/pan y exportación a PNG/CSV.

La interfaz usa la base gráfica compartida con otras apps del autor: ventana
translúcida con desenfoque nativo en macOS (opaca en Windows/Linux), tema
generado a partir de un color de acento, diálogos "glass", configuración
persistente, hoja de atajos, zoom de fuente y captura de errores a log.

## Estructura

```
main.py                     arranque (QApplication, FileOpen de macOS, argv)
app/
  grib_reader.py            lectura GRIB2 (ecCodes), inventario, cache, ISA, ln(p)
  wind_plot.py              mapa matplotlib (QtAgg) + cartopy opcional
  main_window.py            ventana principal: mapa, panel, menús, atajos
  config.py, theme.py, platform_blur.py, crash_guard.py, utils.py
  widgets/                  control_panel, inventory_panel, welcome_widget
  dialogs/                  glass_dialog, settings_dialog, shortcuts_dialog, about_dialog
tests/                      unittest (lector, ventana y mapa en offscreen)
docs/PLAN_PRUEBAS_2_0_0.md  plan de pruebas manual
scripts/build.sh, setup.py  .app + DMG con py2app (macOS)
```

Módulos del esquema de fuentes: `app/sources/base.py` (clase `Source`,
descarga genérica), `app/sources/gfs.py`, `app/sources/cache.py`,
`app/sources/credentials.py`, `app/regrid.py` (submuestreo, promedio de
área, recorte), `app/widgets/params_form.py` (formulario por parámetros),
`app/dialogs/source_config_dialog.py` y `app/dialogs/download_dialog.py`.

## Instalación

### Entorno `Grib` (pyenv, Python 3.14)

El archivo `.python-version` fija el entorno `Grib`. Si todavía no existe:

```bash
pyenv install 3.14.3
pyenv virtualenv 3.14.3 Grib
cd /ruta/al/proyecto         # .python-version activa el entorno solo
python --version             # Python 3.14.3
pip install --upgrade pip
pip install -r requirements.txt
python -c "import PyQt6, eccodes, cartopy, matplotlib; print('ok')"
```

Si el shell no reconoce el entorno, inicializar pyenv primero:

```bash
eval "$(pyenv init -)"
```

### Dependencias nativas

* **ecCodes**: `pip install eccodes` trae la biblioteca en las ruedas
  recientes. Si no la encuentra ("Cannot find the ecCodes library"):

  ```bash
  # macOS
  brew install eccodes && pip install eccodes
  export ECCODES_DIR=$(brew --prefix eccodes)     # si aún no la encuentra

  # Debian / Ubuntu
  sudo apt install libeccodes0 libeccodes-dev && pip install eccodes

  # Alternativa: conda / mamba
  conda create -n grib python=3.12 -c conda-forge eccodes python-eccodes \
      cartopy matplotlib numpy pyqt certifi
  ```

* **cartopy** es opcional: sin él el mapa se dibuja sin costas ni fronteras y
  la app lo avisa. La primera vez que se dibuja un mapa descarga las costas de
  Natural Earth a 50 m (hace falta conexión). Si aparece
  `CERTIFICATE_VERIFY_FAILED`, instalar `certifi` (ya está en
  `requirements.txt`) o ejecutar `Install Certificates.command` del Python
  de python.org.

* **macOS**: `pyobjc-framework-Cocoa` (en `requirements.txt`) da el desenfoque
  nativo y el nombre de la app en la barra de menú. Sin él la ventana queda
  opaca.

## Uso

```bash
python main.py                        # abre la bienvenida
python main.py FDP_MULTI.grib2        # abre directamente un archivo
```

También se abre un `.grib2` con doble clic en el Finder cuando la app está
empaquetada (`scripts/build.sh`).

### Obtener datos (fuentes)

El visor obtiene datos de **fuentes** intercambiables. La fuente se elige en
el selector `Fuente` de la barra de acciones (sólo aparecen las habilitadas;
`✓ FL` marca las que publican los niveles isobáricos OACI por nivel de
vuelo) y `Obtener datos…` (⌘⇧D) abre el diálogo de descarga de esa fuente:

* **Corrida y plazos**: el combo de corrida lista las últimas doce que la
  fuente debería tener publicadas; los plazos se validan contra los que la
  fuente ofrece (el GFS: cada hora hasta +120, cada 3 h hasta +384).
* **Variables** y **niveles** de la fuente (sin selector de nivel en las
  fuentes de superficie), con atajos "Los del visor", "Todos" y "Ninguno".
* **Opciones de la fuente**: formulario generado a partir de sus parámetros
  (para el GFS: resolución, "bajar siempre 0,25° y regrillar", suavizado y
  niveles intermedios).
* **Zona**: lat norte/sur y lon oeste/este o todo el globo; con un archivo
  abierto, "Dominio del archivo abierto" copia su recuadro. Si el servidor
  filtra por zona se le pide recortado; si no, se recorta localmente.
* **Destino**: carpeta y nombre; un archivo por plazo o uno con todos;
  abrir al terminar.

La descarga corre en un hilo con progreso y cancelación, no deja archivos a
medias, reintenta tres veces ante cortes de red o errores 5xx, y comprueba
que lo recibido sea realmente GRIB2/NetCDF (una página HTML porque el plazo
aún no se publicó se informa con la sugerencia de probar la corrida
anterior; un 401/403 avisa que revises las credenciales). Lo bajado queda en
una **caché local** (`~/Library/Caches/Visor GRIB/descargas` en macOS) y no
se vuelve a pedir; el tamaño máximo y los días a conservar se fijan en
Preferencias ▸ Descarga, donde también se vacía.

Junto a cada archivo se escribe `archivo.grib2.json` con la **procedencia**
(fuente, modelo, corrida, plazos, parámetros, resolución efectiva). Al
abrirlo, el panel STATUS muestra `FUENTE: …` con fuente, modelo, corrida,
plazo y, si se regrilló, desde qué resolución y con qué método. Un archivo
sin ese JSON se muestra como "archivo local (sin procedencia)".

#### Fuentes disponibles

| Fuente | Modelo / producto | Tipo | Resolución y zona | Credenciales | Niveles por FL | Documentación |
|---|---|---|---|---|---|---|
| NOAA GFS | GFS de NCEP vía NOMADS grib filter (`pgrb2` + `pgrb2b`) | altura: T, U, V, HGT, RH en 42 niveles isobáricos; 4 corridas/día; +0…+384 h | 0,25° / 0,50° / 1,00°, recorte por zona en el servidor | no | no (pero con los intermedios ofrece los mismos niveles que WAFS) | <https://nomads.ncep.noaa.gov/> |

Las fuentes previstas para las próximas etapas (NOAA WAFS 0,25° ✓ FL, ECMWF
Open Data, DWD ICON, SMN Argentina WRF, fuente genérica con URL
configurable) se suman implementando una subclase de `sources.base.Source`
y registrándola en `sources/__init__.py`; los diálogos se arman solos.

#### Fuente NOAA GFS: resolución y suavizado

Los productos de 0,50° y 1,00° del GFS son muestras puntuales del campo de
0,25° (verificado: tomar un punto cada dos o cuatro reproduce el producto
real salvo la cuantización del empaquetado). Por eso la fuente ofrece:

* **Resolución**: la grilla objetivo (0,25° / 0,50° / 1,00°).
* **Bajar siempre 0,25° y regrillar localmente**: pide el producto fino y
  lo submuestrea a la resolución objetivo (el archivo resulta igual al
  producto grueso de NOAA). Sirve también para tener niveles intermedios a
  1,00°, que NOMADS no filtra.
* **Suavizado**: `Promedio de área` reemplaza el submuestreo por el promedio
  ponderado de las celdas de 0,25° que cubre cada celda gruesa (los bordes
  pesan la mitad); da un campo más representativo de la celda pero distinto
  del publicado, con diferencias locales de hasta 15–30 kt en bordes de
  chorro y cordillera. Activa la bajada a 0,25° automáticamente. No actúa
  si la resolución objetivo es 0,25°.
* **Niveles intermedios cada 25 hPa** (875 … 125; pgrb2b a 0,25°,
  incluidos en pgrb2full a 0,50°). Ningún nivel del GFS coincide
  exactamente con la presión ISA de un FL salvo F340 (250 hPa) y F530
  (100 hPa); con los intermedios cada FL del visor queda a menos de 8 hPa
  de un nivel del archivo (F320 ≈ 275, F360 ≈ 225, F410 ≈ 175).

### Panel de la derecha

* **STATUS**: corrida, paso, ventana de validez en UTC y en hora local, nivel
  elegido y si fue interpolado en ln(p) o extrapolado (nivel más cercano).
* **TIME**: `Current (+0)`, `Next (+1)`, `Advanced (+2)` eligen el 1.°, 2.° y
  3.° paso del archivo, con su hora de validez al lado. Si hay más de tres
  pasos aparece un combo con todos.
* **LEVEL**: botones F050…F530. El FL se convierte a presión con la atmósfera
  estándar ISA (`p = 1013.25·(1 − 6.8756e-6·h)^5.2559` hasta 36 089 ft,
  isotérmica arriba) y U, V y T se interpolan linealmente en ln(p) entre los
  niveles del archivo. Fuera del rango se usa el nivel más cercano y STATUS
  lo marca como "extrapolado". El combo "Nivel de presión" elige un nivel
  del archivo sin interpolar.
* **VARIABLE**: Viento (barbas), Temperatura (contornos cada 2 °C) o ambas.
* **CONFIG**: `Proyección` elige cómo se dibuja el mapa: Lat/Lon
  (PlateCarree), Estereográfica conforme centrada en el dominio del archivo,
  Estereográfica polar sur o norte, Mercator o Lambert conforme (requieren
  cartopy; la elección se guarda en la configuración). `Extra Info` escribe
  la velocidad en kt (y la temperatura en °C) junto a cada barba; `Grilla` dibuja la grilla lat/lon del archivo;
  `Fondo de velocidad` rellena el mapa con la misma escala de colores;
  `Densidad` submuestrea las barbas cada N puntos; `Update` redibuja y
  `Disable`/`Enable` oculta o muestra la capa de datos. Cualquier cambio de
  radio, botón de nivel, combo o casilla redibuja automáticamente, y las
  casillas y la densidad quedan guardadas como valores iniciales (también
  editables en Preferencias ▸ Mapa).
* **RECUADRO**: lat/lon mín/máx (Enter aplica) y `Todo el dominio`.
* **INVENTARIO**: corrida, pasos, variables, niveles y grilla del archivo.

### Barra de acciones y mapa

`Abrir GRIB…`, `Inicio` (vista inicial), `Guardar PNG` y `⚙` (preferencias:
color de acento y transparencia). El mapa se mueve arrastrándolo con el
botón izquierdo (cursor de mano) y se acerca o aleja con la rueda del mouse
alrededor del cursor; no hay modos ni botones de zoom/pan. La vista se
conserva al cambiar paso, nivel, variable u opciones; `Inicio` o `Todo el
dominio` la reinician. La vista siempre llena el área del mapa: al fijar el
dominio o un recuadro se amplía en el sentido que haga falta.

Para que el mapa responda rápido, las barbas y los rótulos de "Extra Info"
se dibujan sólo para la zona visible y se ralean automáticamente cuando hay
demasiados (al acercar la vista aparecen todos; `Densidad` fija el raleo
mínimo). Mientras se arrastra el mapa se ocultan los rótulos y las etiquetas
de la grilla, que vuelven al soltar. Al mover el mouse sobre el mapa la barra inferior
muestra lat/lon y, en el punto de grilla más cercano, velocidad (kt),
dirección (°) y temperatura (°C).

En cualquier proyección las barbas se rotan a la orientación local del
mapa, los meridianos y paralelos cada 10° llevan etiquetas en los bordes y
la grilla del archivo (opcional) se dibuja punteada. La barra de estado
convierte la posición del cursor a lat/lon.

Escala de colores de las barbas: 0–9 kt cian, 10–19 azul, 20–29 verde,
30–39 amarillo, 40–49 naranja, ≥50 rojo. Conversiones: 1 m/s = 1.943844 kt;
dirección meteorológica = (270 − atan2(v, u)) mod 360; T(°C) = T(K) −
273.15. Las longitudes 0–360 se normalizan a −180…180 y las latitudes se
reordenan de sur a norte si el archivo viene de norte a sur.

### Atajos

| Acción | macOS | Windows / Linux |
|---|---|---|
| Abrir GRIB… | ⌘ O | Ctrl O |
| Descargar GFS… | ⌘ ⇧ D | Ctrl Shift D |
| Exportar PNG… | ⌘ E | Ctrl E |
| Exportar CSV… | ⌘ ⇧ E | Ctrl Shift E |
| Cerrar archivo | ⌘ W | Ctrl W |
| Salir | ⌘ Q | Ctrl Q |
| Todo el dominio | ⌘ ⇧ 0 | Ctrl Shift 0 |
| Actualizar | F5 | F5 |
| Capa de datos activada / desactivada | ⌘ D | Ctrl D |
| Preferencias… | ⌘ , | Ctrl , |
| Agrandar / achicar / restablecer fuente | ⌘ + / ⌘ − / ⌘ 0 | Ctrl + / Ctrl − / Ctrl 0 |
| Desplazar el mapa | Arrastrar | Arrastrar |
| Acercar / alejar alrededor del cursor | Rueda | Rueda |
| Atajos de teclado | ⌘ / | Ctrl / |

En macOS el botón verde maximiza la ventana sobre el escritorio en lugar
de entrar en el modo de pantalla completa nativo: en ese modo el sistema
pone la ventana sola sobre un fondo negro y el desenfoque "detrás de la
ventana" no tiene nada que mostrar. Sin desenfoque (Windows, Linux o si
falla en macOS) el botón verde conserva su comportamiento habitual.

La configuración (color, transparencia, tamaño de fuente, geometría,
recientes) se guarda en `config.json` junto al código en desarrollo y en
`~/Library/Application Support/Visor GRIB/` (macOS), `%APPDATA%\Visor GRIB`
(Windows) o `~/.config/Visor GRIB` (Linux) cuando está empaquetada. Los
errores no controlados se registran en `errores.log` en la misma carpeta.

## Preferencias

`⚙` en la barra de acciones o Vista ▸ Preferencias… (⌘,) abre un diálogo
con cuatro pestañas:

* **Apariencia**: color de acento (presets o personalizado, con vista previa
  en vivo) y transparencia de la ventana.
* **Mapa**: proyección y valores iniciales de CONFIG (Extra Info, grilla,
  fondo de velocidad, densidad).
* **Fuentes**: lista de fuentes con su casilla de habilitación, tipo y
  `✓ FL`; `Configurar…` abre la fuente: parámetros por defecto (el mismo
  formulario que el diálogo de descarga), credenciales si las exige
  (usuario/clave o token, guardadas con `keyring` en el llavero del sistema,
  nunca en `config.json`, con botón para borrarlas) y `Probar conexión`, que
  responde `Conexión OK`, `Sin red`, `Credenciales inválidas` o `Dato
  todavía no publicado`.
* **Descarga**: plazos, unir plazos y abrir al terminar como valores
  iniciales de `Obtener datos…`; tamaño y antigüedad máximos de la caché y
  `Vaciar caché`.
* **Motor**: cómo se leen los GRIB2. `ecCodes` usa la biblioteca Python
  incluida en `requirements.txt`; `wgrib2` ejecuta el programa de NOAA como
  proceso externo (inventario con `-s -T -VT -nxny`, grilla con `-grid` y
  valores con `-order raw -no_header -bin`), útil para contrastar o cuando
  ecCodes no puede instalarse. La ruta puede dejarse vacía (se busca en el
  PATH o en la variable `WGRIB2`) o indicarse con `Buscar…`; `Probar` muestra
  la versión. Si el motor elegido no está, abrir un archivo avisa y sigue
  con ecCodes. Ambos motores entregan los mismos campos (diferencias del
  orden de 1e-5 por el float32 de wgrib2) y el inventario indica cuál se
  usó. wgrib2 no viene en Homebrew; se compila desde
  <https://ftp.cpc.ncep.noaa.gov/wd51we/wgrib2/wgrib2.tgz> (`make` con
  `CC=clang` y las opciones USE_NETCDF3/USE_IPOLATES/USE_OPENJPEG… en 0) o se
  instala con `conda install -c conda-forge wgrib2`.

Cancelar devuelve el tema que había; Aplicar guarda todo en `config.json`.
Si cambia el motor con un archivo abierto, se reabre con el nuevo.

## Tests

```bash
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -p "test_*.py"
```

Cubren el lector (ISA, viento, colores, grilla, ln(p), lectura de un GRIB2
sintético generado con ecCodes), el parseo de la salida de wgrib2, el
esquema de fuentes (parámetros, corridas, descarga con caché, reintentos,
validación y procedencia, regrillado y recorte local, credenciales con un
llavero en memoria, formulario y diálogos de fuente), la descarga con
niveles intermedios, la ventana y los diálogos en offscreen, y
que cambiar nivel, paso, variable u opción redibuja sobre un lector
sintético. Si hay un `.grib2` real en la carpeta del proyecto se suma un
test de inventario, y si hay un `wgrib2` en el PATH (o en la variable
`WGRIB2`) se compara la lectura completa de los dos motores; ambos se saltan
si no están.

## Empaquetado macOS

```bash
scripts/build.sh      # genera iconos, "dist/Visor GRIB.app" y el DMG
```

## Verificación con wgrib2

1. Abrir el archivo: `python main.py FDP_MULTI.grib2`.
2. Elegir **Next (+1)** (segundo paso, por ejemplo +9 h) y el nivel **F100**.
   STATUS mostrará `F100 = 696.8 hPa (ISA)` interpolado entre 700 y 600 hPa;
   al estar a sólo 3 hPa de 700, los valores son prácticamente los del nivel
   de 700 mb. Para comparar exactamente, elegir `700 hPa` en el combo
   "Nivel de presión".
3. Listar los mensajes de 700 mb del archivo con wgrib2:

   ```bash
   wgrib2 -s FDP_MULTI.grib2 | grep ":700 mb:"
   ```

   Debe aparecer, para cada paso, una línea de `UGRD`, `VGRD` y `TMP`, por
   ejemplo `...:UGRD:700 mb:9 hour fcst:`; la hora de validez y el paso
   coinciden con los que muestra STATUS.
4. Extraer el valor en un punto (por ejemplo 34°S 58°W; wgrib2 usa
   longitudes 0–360, 58°W = 302°E) y compararlo con el que muestra la barra
   de estado al pasar el cursor por ese punto o con la fila correspondiente
   del CSV exportado:

   ```bash
   wgrib2 FDP_MULTI.grib2 -match ":(UGRD|VGRD|TMP):700 mb:9 hour fcst:" -lon 302 -34
   ```

   Con u y v en m/s: velocidad (kt) = √(u²+v²) × 1.943844 y dirección
   = (270 − atan2(v,u)·180/π) mod 360; T (°C) = TMP − 273.15.
