# Visor GRIB – Viento y temperatura GRIB2 (GFS)

Aplicación de escritorio (Python 3.14 + PyQt6 + matplotlib + cartopy
opcional) para visualizar archivos GRIB2 con componentes de viento
(UGRD/VGRD) y temperatura (TMP) en niveles de presión, con un panel de
controles al estilo de un sistema ATC: selección de paso (Current / Next /
Advanced), nivel de vuelo (16 botones F050…F530 convertidos a presión ISA e interpolados
en ln p), barbas coloreadas por velocidad, contornos de temperatura, "Extra
Info", grilla, zoom/pan y exportación a PNG/CSV.

El **formato interno único es el WAFS** (producto OACI de viento y
temperatura en altura: niveles de vuelo cada 1000 ft codificados como la
presión ISA en Pa). Todo lo que se descarga de una fuente de altura y todo
archivo local en niveles de presión se convierte a ese formato antes de
mostrarse, y lo cargado se puede exportar como WAFS (ver «Formato WAFS»).

La interfaz usa la base gráfica compartida con otras apps del autor: ventana
translúcida con desenfoque nativo en macOS (opaca en Windows/Linux), tema
generado a partir de un color de acento, diálogos "glass", configuración
persistente, hoja de atajos, zoom de fuente y captura de errores a log.

## Estructura

```
main.py                     arranque (QApplication, FileOpen de macOS, argv)
app/
  grib_reader.py            lectura GRIB2 (ecCodes), inventario, cache, ISA, ln(p)
  wafs_format.py            formato WAFS: tabla FL↔Pa, conversión, detección, validador, .idx, exportación, CLI
  wind_plot.py              mapa matplotlib (QtAgg) + cartopy opcional
  main_window.py            ventana principal: mapa, panel, menús, atajos
  config.py, theme.py, platform_blur.py, crash_guard.py, utils.py
  widgets/                  control_panel, inventory_panel, welcome_widget
  dialogs/                  glass_dialog, settings_dialog, shortcuts_dialog, about_dialog, export_wafs_dialog
tests/                      unittest (lector, ventana y mapa en offscreen); tests/data: caso de referencia WAFS
docs/referencia/            make_wafs_like.py, conversor de referencia del formato WAFS
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

Toda fuente **de altura** (GFS, ECMWF, ICON, genérica) pasa por el
**conversor WAFS** después de bajar cada plazo y antes de escribir el
archivo: el nombre lleva el sufijo `_wafs` y la procedencia anota el rango
de FL, los niveles de origen y los FL omitidos o extrapolados. Lo que ya
viene en WAFS (WIFS, un WAFS real) se detecta y no se reconvierte; las
fuentes de superficie (SMN) no se tocan. Se desactiva en Preferencias ▸
WAFS.

Junto a cada archivo se escribe `archivo.grib2.json` con la **procedencia**
(fuente, modelo, corrida, plazos, parámetros, resolución efectiva). Al
abrirlo, la franja STATUS muestra `FUENTE: …` con fuente, modelo, corrida,
plazo y, si se regrilló, desde qué resolución y con qué método. Un archivo
sin ese JSON se muestra como "archivo local (sin procedencia)".

#### Fuentes disponibles

| Fuente | Modelo / producto | Tipo y variables | Resolución y zona | Corridas y plazos | Credenciales | Niveles por FL | Documentación |
|---|---|---|---|---|---|---|---|
| **NOAA GFS** | GFS (NCEP) vía NOMADS grib filter (`pgrb2` + `pgrb2b`) | altura: T, U, V, HGT, RH en 42 niveles isobáricos | 0,25° / 0,50° / 1,00°; recorte en el servidor; regrillado y suavizado local opcionales | 00/06/12/18; +0…+120 cada 1 h, +123…+384 cada 3 h | no | no (con los intermedios cubre los niveles OACI) | <https://nomads.ncep.noaa.gov/> |
| **NOAA WAFS 0,25° (WIFS)** ✓ FL | WAFC Washington (o Londres), producto OACI de viento y temperatura en altura | altura: U/V, T, altura geopotencial en **FL050–FL600 cada 1000 ft** (56 niveles); el nivel del archivo coincide con el FL del visor | 0,25° global; recorte local; se filtran los FL pedidos | 00/06/12/18 (sólo la última); +6…+24 cada 1 h, +27…+48 cada 3 h, +54…+120 cada 6 h (archivos de tres plazos) | **sí**: clave de API de WIFS (Token, `X-API-Key`); cuenta aprobada por la autoridad meteorológica del Estado y la FAA | **sí** | <https://aviationweather.gov/wifs/users_guide/> |
| **ECMWF Open Data** | IFS 0,25° (CC BY 4.0), librería oficial `ecmwf-opendata`; reintentos y espera ante «503 Slow Down» configurables | altura: u, v, t, gh, r en 13 niveles (1000…50 hPa) | 0,25° global; recorte local | 00/12 hasta +240 h (cada 3 h hasta +144, cada 6 h después); 06/18 hasta +90 h | no | no | <https://www.ecmwf.int/en/forecasts/datasets/open-data> |
| **DWD ICON global** | ICON ~13 km, grilla icosaédrica regrillada localmente a 0,25° con los pesos de DWD (vecino más cercano, sin cdo) | altura: U, V, T, FI, RELHUM en 18 niveles (1000…30 hPa) | 0,25° tras regrillar; recorte local | 00/12 hasta +180 h, 06/18 hasta +120 h; cada 1 h hasta +78, cada 3 h después; sólo la última corrida de cada ciclo | no | no | <https://www.dwd.de/EN/ourservices/opendata/opendata.html> |
| **SMN Argentina WRF 4 km** | WRF-ARW 4 km del SMN, NetCDF horario en AWS (`smn-ar-wrf`) | **superficie**: viento 10 m, T 2 m, HR 2 m (sin niveles: el visor oculta LEVEL) | Lambert 4 km convertido localmente a lat/lon 0,04–0,25° recortado a la zona (dominio 57S–12S / 94W–36W) | 00/06/12/18; +0…+72 cada 1 h (~38 MB por hora) | no | no | <https://odp-aws-smn.github.io/documentation_wrf_det/> |
| **Fuente genérica (URL)** | servidor propio: plantilla de URL con `{YYYY} {MM} {DD} {HH} {FFF}` | lo que publique el servidor (GRIB2 se recorta; NetCDF sólo se valida y guarda) | según el archivo | ciclos y plazos configurables | opcional: ninguna, usuario/clave (HTTP básica, FTP, SFTP) o token (HTTP Bearer) | no | — |

Las fuentes marcadas ✓ FL publican los niveles isobáricos OACI por nivel de
vuelo. WAFS y la fuente genérica vienen deshabilitadas hasta que se
configuren. Para sumar otra fuente se implementa una subclase de
`sources.base.Source` (atributos y `build_requests`; opcionalmente
`fetch_request`, `postprocess_step`, `test_connection`) y se registra en
`sources/__init__.py`; los diálogos se arman solos a partir de sus
parámetros.

Notas verificadas contra los servidores (14/10/2026): el producto WAFS de
viento y temperatura a 0,25° ya no está en NOMADS (ni en `gfs.YYYYMMDD/HH/
atmos` ni en un paquete `wafs`), por eso la fuente va contra WIFS; ECMWF
responde `Too Many Requests` si se piden los índices a mano, de ahí la
librería y el espejo AWS por defecto; ICON global sólo existe en
icosaédrica, y los pesos `ICON_GLOBAL2WORLD_025_EASY` de DWD son de vecino
más cercano con un enlace por punto, lo que permite aplicarlos con numpy.

#### Fuente ECMWF Open Data: saturación del servidor y licencia

Después de cada publicación el almacenamiento de ECMWF suele responder
`503 Slow Down` (o `429`) a los tramos de bytes que pide la librería. Ésta
trae una política de 500 reintentos cada 120 s que dejaría la descarga
colgada sin explicación; la fuente la reemplaza por dos parámetros
(Preferencias ▸ Fuentes ▸ ECMWF Open Data): **Reintentos** (10 por defecto)
y **Espera entre reintentos** (30 s; si el servidor manda `Retry-After` se
respeta). Cada reintento y la cuenta regresiva se muestran en la ventana de
avance (`servidor saturado (503 Slow Down), reintento 2 de 10`, `reintento
en 17 s`) y `Cancelar` corta la espera al instante. Si se agotan los
reintentos, el error lo dice y sugiere esperar o subir el valor.

La librería imprime por consola la barra de avance y, al terminar, el aviso
`By downloading data from the ECMWF open data dataset, you agree to the
terms: Attribution 4.0 International (CC BY 4.0)`. Es sólo informativo (no
pide respuesta): los datos son CC BY 4.0 y corresponde atribuir a ECMWF al
redistribuirlos.

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

### Franja STATUS y panel de la derecha

La franja **STATUS** va pegada arriba del mapa, porque describe lo que se
está viendo: fuente (modelo, corrida, plazo, resolución y formato WAFS),
`RUN`, `STEP`, ventana de validez en UTC y en hora local, y `LEVEL` (nivel
elegido y si es exacto del archivo, interpolado en ln(p) o extrapolado).

El panel de la derecha agrupa los controles por pregunta: *qué miro*
(TIME, LEVEL, VARIABLE), *cómo lo veo* (VIENTO) y *dónde* (MAPA). Cada
sección separa sus grupos con una línea fina y un subtítulo; nada impone
ancho (los combos recortan el texto largo y el desplegable lo muestra
entero), así que el panel nunca se corta ni necesita scroll horizontal.
Tampoco tiene scroll: las secciones son fijas y sólo el INVENTARIO, que
absorbe el alto que sobra, se desplaza por dentro (vertical y horizontal). El botón `▥` de la barra de acciones (o Vista ▸
Panel lateral, ⌘⇧P) oculta el panel y el mapa ocupa todo el ancho; la
elección se recuerda. La ventana arranca en 1600×1000 (o lo que entre en
la pantalla) y recuerda tamaño y posición.

* **TIME**: `Current (+0)`, `Next (+1)`, `Advanced (+2)` eligen el 1.°, 2.° y
  3.° paso del archivo, con su hora de validez al lado. Si hay más de tres
  pasos aparece un combo con todos.
* **LEVEL**: 16 botones F050…F530 (incluye F200 y F480). El FL se convierte a presión con la atmósfera
  estándar ISA (`p = 1013.25·(1 − 6.8756e-6·h)^5.2559` hasta 36 089 ft,
  isotérmica arriba) y U, V y T se interpolan linealmente en ln(p) entre los
  niveles del archivo. Fuera del rango se usa el nivel más cercano y STATUS
  lo marca como "extrapolado". El combo "Nivel de presión" elige un nivel
  del archivo sin interpolar. Con un archivo **WAFS** (lo normal, porque
  todo se convierte al abrir o descargar) nada de esto interpola: cada
  botón de FL es un nivel exacto del archivo, y el combo pasa a llamarse
  "Otro FL del archivo" para elegir los FL que no tienen botón (FL200,
  FL250, …).
* **VARIABLE**: Viento, Temperatura (contornos cada 2 °C) o ambas.
* **VIENTO**: `Estilo` elige la representación: **Barbas** (convención
  meteorológica, en kt), **Flechas** (de largo fijo, apuntan hacia donde
  sopla el viento; la velocidad va sólo en el color y donde hay calma no
  hay flecha) o **Curvas** (líneas de corriente del campo con una flecha
  de sentido cada pocos centímetros); las tres usan la misma escala de
  colores por velocidad. `Densidad` dibuja un punto cada N (en curvas baja
  la densidad de líneas). Capas adicionales: `Extra Info` escribe la
  velocidad (y la temperatura) junto a cada punto, con unidades
  (`12 kt  −45 °C`) o sin ellas y con el tamaño que se elija en
  Preferencias ▸ Mapa (además lo escala ⌘ +/−), raleando los rótulos para
  que no se pisen; `Fondo de velocidad` rellena el mapa con la misma
  escala de colores.
* **MAPA**: `Proyección` elige cómo se dibuja el mapa: Lat/Lon
  (PlateCarree), Estereográfica conforme centrada en el dominio del archivo,
  Estereográfica polar sur o norte, Mercator o Lambert conforme (requieren
  cartopy; la elección se guarda en la configuración); `Grilla` dibuja la
  grilla lat/lon del archivo; el recuadro lat/lon mín/máx (Enter o
  `Aplicar recuadro`) y `Todo el dominio` fijan la vista.
* **INVENTARIO**: corrida, pasos, variables, niveles y grilla del archivo.

Cualquier cambio de radio, botón de nivel, combo o casilla redibuja
automáticamente, y estilo, casillas y densidad quedan guardados como
valores iniciales (también editables en Preferencias ▸ Mapa). Las mismas
opciones de VIENTO y MAPA están en el menú **Vista** (Proyección, Viento,
Extra Info, Fondo de velocidad, Grilla), sincronizadas con el panel; las
acciones globales `Actualizar` (F5) y `Ocultar capa` / `Mostrar capa`
(⌘D) van en la barra de acciones y en Vista.

### Barra de acciones y mapa

La barra de acciones tiene tres grupos del mismo alto, separados con
aire: *datos* (`Abrir GRIB…`, el selector `Fuente` integrado en un solo
control con borde, `Obtener datos…`), *mapa* (`Inicio`, `Actualizar`,
`Ocultar capa`) y *salida* (`Guardar PNG`); a la derecha, `▥` (panel
lateral) y `⚙` (preferencias). La franja STATUS y la barra de estado
inferior usan un tamaño de letra fijo que no sigue ⌘ +/−. El mapa ocupa
el área con márgenes justos para las etiquetas de lat/lon; el título
(corrida, validez, nivel y variable) no se dibuja en pantalla, porque
STATUS ya lo muestra, pero sí en el PNG exportado. El mapa se mueve arrastrándolo con el
botón izquierdo (cursor de mano) y se acerca o aleja con la rueda del mouse
alrededor del cursor; no hay modos ni botones de zoom/pan. La vista se
conserva al cambiar paso, nivel, variable u opciones; `Inicio` o `Todo el
dominio` la reinician. La vista siempre llena el área del mapa: al fijar el
dominio o un recuadro se amplía en el sentido que haga falta.

Para que el mapa responda rápido, las barbas o flechas y los rótulos de "Extra Info"
se dibujan sólo para la zona visible. Al alejar la vista las barbas y las
flechas primero se achican (hasta la mitad del tamaño nominal) y las curvas
se afinan, para conservar la mayor cantidad posible de celdas; recién
cuando ya no entran se ralean (al acercar la vista aparecen todos;
`Densidad` fija el raleo mínimo). Mientras se arrastra el mapa se ocultan los rótulos y las etiquetas
de la grilla, que vuelven al soltar. Al mover el mouse sobre el mapa la barra inferior
muestra lat/lon y, en el punto de grilla más cercano, velocidad (kt),
dirección (°) y temperatura (°C).

En cualquier proyección las barbas y flechas se rotan a la orientación
local del mapa (las curvas se calculan sobre una grilla regular de la
proyección que cubre la vista, muestreando el campo bilinealmente y
rotando los vectores), los meridianos y paralelos cada 10° llevan etiquetas en los bordes y
la grilla del archivo (opcional) se dibuja punteada. La barra de estado
convierte la posición del cursor a lat/lon.

Escala de colores del viento (barbas, flechas y curvas): 0–9 kt cian, 10–19 azul, 20–29 verde,
30–39 amarillo, 40–49 naranja, ≥50 rojo. Conversiones: 1 m/s = 1.943844 kt;
dirección meteorológica = (270 − atan2(v, u)) mod 360; T(°C) = T(K) −
273.15. Las longitudes 0–360 se normalizan a −180…180 y las latitudes se
reordenan de sur a norte si el archivo viene de norte a sur.

### Atajos

| Acción | macOS | Windows / Linux |
|---|---|---|
| Abrir GRIB… | ⌘ O | Ctrl O |
| Obtener datos… | ⌘ ⇧ D | Ctrl Shift D |
| Exportar PNG… | ⌘ E | Ctrl E |
| Exportar CSV… | ⌘ ⇧ E | Ctrl Shift E |
| Exportar a WAFS… | ⌘ ⇧ W | Ctrl Shift W |
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

## Formato WAFS

El WAFS (World Area Forecast System) es el producto OACI de viento y
temperatura en altura que producen los centros WAFC de Washington y Londres.
El visor lo adopta como **formato interno único**: lee sólo WAFS, convierte
a WAFS lo que baja y lo que abre, y exporta WAFS. Referencia: el código con
el que NOAA produce el producto operativo,
<https://github.com/NOAA-EMC/wafs> (`scripts/exwafs_grib2_0p25.sh` y las
tablas en `fix/wafs/`).

**Qué es un archivo WAFS**

* GRIB2 en grilla regular lat/lon. El operativo es global a 0,25°
  (1440×721, 90N→90S, 0→359,75); el formato admite cualquier recorte
  regular, que es nuestro uso.
* Variables UGRD, VGRD, TMP (obligatorias), HGT y RH (RH sólo FL050–FL180),
  más campos 2D opcionales (viento máximo y tropopausa). Unidades K, m/s,
  gpm y %. Viento referido al norte/este geográfico.
* Niveles: **niveles de vuelo cada 1000 ft, FL050–FL600**, codificados como
  superficie isobárica (tipo 100) a la **presión ISA del FL en Pa redondeada
  a 0,1 hPa**. Por eso `wgrib2 -s` los lista como `843.1 mb`, `812 mb`,
  `781.9 mb`…, y ecCodes muestra `level` truncado (843): el lector usa el
  valor escalado exacto.
* Plazos operativos: +6…+24 cada 1 h, +27…+48 cada 3 h, +54…+120 cada 6 h;
  corridas 00/06/12/18. Nombre del producto: `gfs.tHHz.wafs_0p25.fFFF.grib2`.

**Fórmula ISA** (la del conversor de referencia; reproduce exactamente los
valores que figuran en las tablas de NCEP):

```
h = FL × 100 × 0,3048                              (m)
h ≤ 11 000 m:  p = 101 325 · (1 − 2,25577e-5 · h)^5,25588        (troposfera)
h > 11 000 m:  p = 22 632,06 · exp(−(h − 11 000) / 6 341,62)      (estratosfera isotérmica)
Pa del nivel = round(p / 10) · 10
```

**Tabla FL ↔ Pa** (completa, FL000–FL600; en negrita los que NCEP lista
literalmente):

| FL | Pa | FL | Pa | FL | Pa | FL | Pa |
|---|---|---|---|---|---|---|---|
| FL000 | 101320 | FL160 | 54920 | FL320 | 27450 | **FL480** | **12770** |
| FL010 | 97720 | FL170 | 52720 | FL330 | 26200 | FL490 | 12170 |
| FL020 | 94210 | **FL180** | **50600** | **FL340** | **25000** | FL500 | 11600 |
| FL030 | 90810 | FL190 | 48550 | FL350 | 23840 | FL510 | 11050 |
| FL040 | 87510 | FL200 | 46560 | **FL360** | **22730** | FL520 | 10530 |
| **FL050** | **84310** | FL210 | 44650 | FL370 | 21660 | **FL530** | **10040** |
| FL060 | 81200 | FL220 | 42790 | FL380 | 20650 | FL540 | 9570 |
| FL070 | 78190 | FL230 | 41000 | **FL390** | **19680** | FL550 | 9120 |
| FL080 | 75260 | **FL240** | **39270** | FL400 | 18750 | FL560 | 8690 |
| FL090 | 72430 | FL250 | 37600 | **FL410** | **17870** | FL570 | 8280 |
| **FL100** | **69680** | FL260 | 35990 | FL420 | 17040 | FL580 | 7900 |
| FL110 | 67020 | FL270 | 34430 | FL430 | 16240 | FL590 | 7520 |
| FL120 | 64440 | FL280 | 32930 | FL440 | 15470 | FL600 | 7170 |
| FL130 | 61940 | FL290 | 31480 | **FL450** | **14750** |  |  |
| FL140 | 59520 | **FL300** | **30090** | FL460 | 14060 |  |  |
| FL150 | 57180 | FL310 | 28740 | FL470 | 13400 |  |  |

**Conversión** (`app/wafs_format.py`, sin interfaz; reestructura el
conversor de referencia `docs/referencia/make_wafs_like.py` sin cambiar su
aritmética: con las opciones por defecto reproduce byte a byte su salida):

* Para cada plazo y variable se apilan los niveles de presión del origen y
  se interpola **linealmente en ln(p)** a la presión ISA de cada FL.
* FL fuera del rango de niveles del origen: se **omiten** (no se
  extrapola); con «extrapolar» se usa el nivel más cercano y queda anotado
  en la procedencia (`wafs.extrapolados`) y en el log de la descarga.
* Rango configurable (Preferencias ▸ WAFS): por defecto FL050–FL530, lo que
  cubre el GFS entre 850 y 100 hPa; «ampliar» lo extiende hacia abajo si el
  origen trae niveles por debajo de 850 hPa y hacia arriba (hasta FL600) si
  trae niveles por encima de 100 hPa. RH se limita a FL180.
* Se conservan corrida, plazo, grilla, empaquetado y centro del origen
  (cada mensaje es un clon del original con el nivel cambiado); la
  procedencia (`.json` junto al archivo) registra fuente, modelo y archivo
  original. Los mensajes que no están en niveles de presión se descartan,
  salvo los campos 2D del WAFS, que pasan tal cual.
* Un archivo que ya está en WAFS (todos sus niveles isobáricos son
  presiones ISA de FL enteros, tolerancia 10 Pa) se detecta y no se toca.
* Dónde actúa: en la descarga (cada plazo, antes de escribir; sufijo
  `_wafs`), al **abrir un archivo local** en niveles de presión (se escribe
  `<nombre>_wafs.grib2` con su `.json` y `.idx` junto al original, o en la
  caché si la carpeta no es escribible, y se abre ese), en la exportación si
  lo cargado todavía no es WAFS, y por línea de comandos:

```bash
python -m app.wafs_format entrada.grib2 salida.grib2 [--fl-min 50 --fl-max 530] \
    [--sin-extender] [--extrapolar] [--tabla 25] [--centro N] [--sin-idx]
python -m app.wafs_format --validar archivo.grib2
```

En el visor, con un WAFS abierto cada botón de FL cae en un **nivel exacto
del archivo** (STATUS: `LEVEL: F300 = 30090 Pa (WAFS, nivel exacto)`), el
combo «Otro FL del archivo» lista los 49 niveles como `FL300 · 300.9 hPa`
(su primera opción es «el FL del botón elegido», sin interpolación), el
inventario dice `FORMATO: WAFS …` y FUENTE agrega `WAFS FL050–FL530
(convertido)`.

**Exportar a WAFS…** (Archivo, ⌘⇧W) toma lo cargado y escribe GRIB2 WAFS:
todos los plazos y niveles o una selección (plazos, rango de FL), sólo
UGRD/VGRD/TMP o todas las variables, recorte geográfico opcional (el
recuadro visible como valor inicial), regrillado bilineal a 0,25° (como el
operativo) o a 1,00° (para el FDP), un archivo por plazo con el nombre
`gfs.tHHz.wafs_0p25.fFFF.grib2` (prefijo del modelo editable) o un único
archivo multi-plazo, `tablesVersion 25` en los mensajes y el inventario
`.idx` (formato `wgrib2 -s`: `1:0:d=2026101318:TMP:843.1 mb:6 hour fcst:`)
junto a cada archivo. Al terminar **reabre lo escrito** y comprueba cantidad
de mensajes, niveles y que los valores coincidan con lo que había en
memoria dentro de la precisión del empaquetado; el resultado se muestra
junto con los avisos del validador.

**Validador** (`validate_wafs`, usado por la conversión, la exportación y
`--validar`): niveles = presión ISA de FL enteros (tolerancia 10 Pa),
variables y unidades esperadas, RH sólo hasta FL180, grilla regular lat/lon
única, viento en componentes geográficas (`uvRelativeToGrid = 0`),
UGRD/VGRD/TMP presentes en cada plazo. **Avisa, no bloquea.**

**Qué reproduce y qué no respecto del producto oficial.** El WAFS operativo
sale de los niveles del modelo (híbridos) vía UPP, con interpolación
vertical propia y regrillado bilineal a 0,25°; el nuestro sale de los
niveles de presión publicados (GFS 850–100 hPa cada 50 hPa, o cada 25 con
los intermedios), así que habrá pequeñas diferencias de interpolación
vertical, mayores donde el perfil es curvo entre niveles (chorro,
tropopausa). Coinciden la codificación de niveles (tipo 100, Pa redondeados
a 0,1 hPa, mismos valores de la tabla), las variables y unidades, la grilla
regular y el nombre de archivo. No se generan los campos 2D de viento
máximo y tropopausa ni ICAHT, y el centro/subcentro queda el del origen
(NCEP en los GFS) salvo que se indique otro (`--centro`); `tablesVersion`
se pone en 25 al exportar.

## Preferencias

`⚙` en la barra de acciones o Vista ▸ Preferencias… (⌘,) abre un diálogo
con seis pestañas:

* **Apariencia**: color de acento (presets o personalizado, con vista previa
  en vivo) y transparencia de la ventana.
* **Mapa**: proyección, valores iniciales de VIENTO y MAPA (viento, Extra Info, grilla,
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
* **WAFS**: convertir a WAFS al descargar y al abrir archivos locales,
  rango de FL (por defecto FL050–FL530), ampliar el rango si la fuente trae
  niveles por debajo de 850 o por encima de 100 hPa, y extrapolar con el
  nivel más cercano en vez de omitir (ver «Formato WAFS»).
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
llavero en memoria, formulario y diálogos de fuente), cada fuente con
servidores simulados (WAFS con ítems JSON y plazos agrupados, ECMWF con un
cliente falso, SMN con un NetCDF sintético convertido a GRIB2, ICON con
pesos sintéticos, la genérica contra un servidor HTTP local con
autenticación básica), la descarga con niveles intermedios, el formato
WAFS (`tests/test_wafs.py`: la tabla FL↔Pa contra los valores de NCEP;
convertir `tests/data/FDP_MULTI.grib2` reproduce byte a byte
`tests/data/WAFS_like_test.grib2`, generado por el conversor de referencia;
ida y vuelta exportar → reabrir sin pérdida; un origen con niveles por
debajo de 850 o por encima de 100 hPa amplía el rango de FL; un archivo ya
en WAFS pasa sin cambios; extrapolación, validador, `.idx`, regrillado
bilineal, recorte, CLI, lector con niveles exactos y conversión en la
descarga), la ventana y los diálogos en offscreen, y
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
