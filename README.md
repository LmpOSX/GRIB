# Visor GRIB – Viento y temperatura GRIB2 (GFS)

Aplicación de escritorio (Python 3.14 + PyQt6 + matplotlib + cartopy
opcional) para visualizar archivos GRIB2 con componentes de viento
(UGRD/VGRD) y temperatura (TMP) en niveles de presión, con un panel de
controles al estilo de un sistema ATC: selección de paso (Current / Next /
Advanced), nivel de vuelo (17 botones OACI F050…F530, cada uno en la presión ISA
exacta de su FL), barbas coloreadas por velocidad, contornos de temperatura, "Extra
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
  wind_plot.py              mapa matplotlib (QtAgg) + cartopy opcional; capa de límites de FIR
  fir.py, fir_aip.py        límites de FIR: carga GeoJSON/KML/SHP, extremos, cobertura, VATSpy; conversor AIP → GeoJSON (CLI)
  working_area.py           Working Area de cada FIR: plano estereográfico tangente, cuadrado en NM, contorno lat/lon, radio conforme
  main_window.py            ventana principal: mapa, panel, menús, atajos
  areas.py                  áreas de descarga por FIR: tabla, coordenadas, envolvente + margen, redondeo hacia afuera, exportar/importar
  point_query.py            consulta de punto (clic derecho): geodésico DDMM, hora YYMMDDHHMM, texto del informe
  config.py, theme.py, platform_blur.py, crash_guard.py, utils.py
  widgets/                  control_panel, inventory_panel, welcome_widget, areas_editor (tabla de áreas, CoordEdit)
  dialogs/                  glass_dialog, settings_dialog, shortcuts_dialog, about_dialog, export_wafs_dialog, fir_dialog, aip_convert_dialog, areas_dialog, fl_table_dialog, point_dialog
resources/fir/              copia filtrada de Boundaries.geojson (VATSpy, CC BY-SA 4.0)
docs/FUENTES_FIR.md         fuentes de los límites de FIR y sus licencias
tests/                      unittest (lector, ventana y mapa en offscreen); tests/data: caso de referencia WAFS
docs/referencia/            make_wafs_like.py, conversor de referencia del formato WAFS
docs/PLAN_PRUEBAS.md        plan de pruebas manual
packaging/                  spec de PyInstaller, Inno Setup (.iss), .desktop y MIME de Linux
scripts/build.sh            instalador de macOS (.app + DMG)
scripts/build_linux.sh      instaladores de Linux (.deb, AppImage, tar.gz)
scripts/build_windows.ps1   instalador de Windows (Setup.exe + zip)
.github/workflows/          tests en cada push; instaladores de los tres sistemas al etiquetar vX.Y.Z
```

Módulos del esquema de fuentes: `app/sources/base.py` (clase `Source`,
descarga genérica), `app/sources/gfs.py`, `app/sources/cache.py`,
`app/sources/credentials.py`, `app/regrid.py` (submuestreo, promedio de
área, recorte), `app/widgets/params_form.py` (formulario por parámetros),
`app/dialogs/source_config_dialog.py` y `app/dialogs/download_dialog.py`;
`app/sources/openaip_fir.py` es la fuente de límites de FIR de openAIP.

## Instalación

Para usar el programa sin instalar Python, bajar el instalador del sistema
desde la sección «Instaladores» más abajo. Lo que sigue es el entorno de
desarrollo.

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

También se abre un `.grib2` con doble clic desde el Finder o el Explorador
cuando la app está instalada (ver «Instaladores»).

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
* **Área**: dos modos excluyentes. *Manual*: lat N/S y lon W/E (grados
  decimales con signo o grados-minutos con hemisferio, p. ej. `34°02'S`),
  todo el globo, o "Dominio del archivo abierto". *Por FIR*: una casilla
  por área habilitada en Preferencias ▸ Áreas / FIR; los cuatro campos se
  recalculan solos como la **envolvente** de las marcadas (la latitud más
  al norte, la más al sur, la longitud más al oeste y la más al este) más
  el margen, y quedan bloqueados (al pasar a manual se copian como punto de
  partida). Botones `Todas` / `Ninguna`, margen, y al lado el tamaño
  resultante: grados, puntos de grilla a la resolución elegida y tamaño
  estimado. Se recuerdan el último modo y las casillas marcadas. Ver
  «Áreas de descarga por FIR».
* **Destino**: carpeta y nombre; un archivo por plazo o uno con todos;
  abrir al terminar; **Convertir a WAFS** (FL cada 1000 ft, con el rango y
  el modo de Preferencias ▸ WAFS; el botón `Preferencias WAFS…` de al lado
  abre Preferencias limitadas a esa pestaña, con las demás bloqueadas, y
  al aplicar la casilla toma el nuevo valor por defecto). La casilla arranca como «Convertir a
  WAFS por defecto» de Preferencias; sin marcar, el archivo queda en los
  niveles de presión de la fuente y sin el sufijo `_wafs`, y al abrirlo al
  terminar se muestra tal cual, en modo presión, aunque Preferencias
  convierta los archivos locales (si después lo abrís con Archivo ▸ Abrir,
  ahí sí rige esa preferencia). Queda inactiva en fuentes de superficie y
  en las que ya publican por FL.

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
(fuente, modelo, corrida, plazos, parámetros, resolución efectiva y el
bloque `area`: modo, códigos de FIR, margen, zona pedida, zona pedida al
servidor y zona obtenida). Al abrirlo, la franja STATUS muestra `FUENTE: …`
con fuente, modelo, corrida, plazo, resolución, el área (`área SAEF+SACF`
o `área MANUAL`) y, si se regrilló, desde qué resolución y con qué método.
Un archivo sin ese JSON se muestra como "archivo local (sin procedencia)".

#### Áreas de descarga por FIR

El recorte de las descargas no es fijo: se define a partir de una **tabla
de áreas** (Preferencias ▸ Áreas / FIR, o `Configurar áreas…` en el
diálogo de descarga, o Vista ▸ FIR ▸ Áreas de descarga…). Cada fila tiene
código OACI (hasta 4 letras), nombre, latitud norte y sur, longitud oeste y
este, y las casillas *Habilitada* (aparece en el bloque Área) y *A
verificar*. Las cinco FIR argentinas vienen precargadas **a verificar
contra el AIP Argentina ENR 2.1** (el visor no inventa coordenadas: estos
valores los carga y coteja el usuario):

| Código | FIR | Lat N | Lat S | Lon W | Lon E |
|---|---|---|---|---|---|
| SARR | Resistencia | −22.25 | −30.70 | −62.67 | −53.67 |
| SACF | Córdoba | −21.72 | −34.03 | −69.65 | −60.20 |
| SAMF | Mendoza | −28.50 | −38.50 | −71.21 | −64.50 |
| SAEF | Ezeiza | −30.22 | −46.00 | −71.85 | −10.00 |
| SAVF | Comodoro Rivadavia | −39.28 | −90.00 | −73.57 | −10.00 |

* Las coordenadas se cargan en grados decimales con signo (S y W negativos)
  o en grados-minutos(-segundos) con hemisferio (`22°15'S`, `06240W`,
  `221530S`, `22 15 30 S`) y se muestran siempre en el formato elegido
  (decimal o grados-minutos). Se valida que norte > sur y oeste < este, con
  aviso claro; `Aplicar` no cierra con la tabla inválida.
* `Agregar área` / `Borrar` para FIR vecinas, el área del sistema o un
  área de prueba; `Las cinco FIR por defecto` las restaura; `Extremos de
  la capa FIR` copia a la fila los extremos del polígono de esa FIR (de la
  capa de límites, VATSpy u otra: no oficial, queda "a verificar").
* **Margen de seguridad** (por defecto 1°): se suma por fuera a cada
  límite al momento de usar el área; no se guarda sumado en la tabla.
* `Exportar tabla…` / `Importar tabla…` en JSON o CSV (columnas `codigo,
  nombre, lat_norte, lat_sur, lon_oeste, lon_este, habilitada,
  a_verificar`) para compartirla.
* Todo queda en `config.json` (`areas`, `areas_margin_deg`,
  `areas_coord_format`, `download_area_mode`, `download_area_codes`,
  `download_manual_region`, `download_area_draw`).

**Cómo se usa el área al descargar.** La zona elegida reemplaza al recorte
fijo en todas las fuentes: donde el servidor recorta (filtro de NOMADS) se
pide directamente esa caja; donde no (ECMWF, ICON, WAFS, SMN, genérica) se
baja completo y se recorta localmente (`regrid.crop_grib`, la misma
función que usa la exportación WAFS). El redondeo a la grilla del modelo
se hace **hacia afuera**: nunca se achica el área pedida. Un área que llega
al polo (lat S = −90) o que cruza el meridiano de Greenwich (oeste negativo
y este positivo) se pide y se recorta correctamente, también sobre grillas
0…360. El nombre automático lleva los códigos de las FIR usadas
(`gfs_20261014_06z_0p25_SAEF+SACF_wafs.grib2`) o `MANUAL`, la procedencia
los conserva (y los archivos convertidos o exportados a WAFS heredan ese
JSON), y STATUS muestra con qué área se bajó lo que está en pantalla. Al
terminar se comprueba que la grilla obtenida contenga la caja pedida; si el
servidor recortó distinto se avisa y la procedencia anota `cubre: false`
(STATUS agrega "(incompleta)").

**En el mapa.** `Mostrar el área en el mapa` en el diálogo (o Vista ▸ FIR ▸
Rectángulos del área de descarga) dibuja en naranja el rectángulo de la
envolvente (con el margen) y, a rayas, el de cada FIR marcada con su
código, además de los contornos de la capa de FIR si está activa. El marco
acompaña al archivo abierto: con un archivo descargado es la zona pedida de
su procedencia (y las FIR con que se bajó); con un archivo sin procedencia,
el recuadro de su grilla; al abrir otro archivo se reemplaza y al cerrarlo
vuelve el de la última selección del bloque Área.

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
* **LEVEL**: una botonera fija de **17 botones, siempre los mismos**, en
  cuatro columnas: cuatro filas de cuatro y F530 solo en la quinta, con la
  lista **Otros FL** en el hueco a su derecha. Son los FL OACI17 del Anexo
  3 (F050, F080, F100, F140, F180, F210, F240, F270, F300, F320, F340,
  F360, F390, F410, F450, F480, F530). Un botón queda deshabilitado si ese FL no está en el archivo
  (F080, F210 y F480 con un archivo INDRA) o, en un archivo crudo, si su
  presión ISA cae fuera de los niveles del archivo (no se extrapola). La
  lista **Otros FL** (su rótulo «Otros FL del archivo» va en el tooltip)
  trae los demás FL disponibles que no tienen botón (en
  OACI56 o WAFS, los otros 39: F060, F070, F090 … F600) y, en archivos
  crudos, al final los niveles de presión del archivo sin interpolar; si
  todos los FL del archivo tienen botón (INDRA u OACI) la lista queda
  inactiva con «(ninguno: todos tienen botón)». Elegir en la
  lista deselecciona la botonera y viceversa. El FL activo se muestra
  siempre en el mismo lugar con sus dos presiones: `F050 · etiqueta 850 hPa
  · 843.1 hPa ISA (nivel exacto, modo OACI)` o `(interpolado en ln(p))` en
  un archivo crudo. Las presiones salen de la tabla del generador WAFS (ver
  «Formato WAFS»): el dato de cada FL corresponde siempre a su presión ISA
  exacta.
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
  (PlateCarree), Estereográfica conforme centrada en el dominio del archivo
  o tangente a la WA marcada, Estereográfica polar sur o norte, Mercator o
  Lambert conforme centrada en el dominio o tangente a la WA (requieren
  cartopy; la elección se guarda en la configuración; las variantes
  «tangente a WA» están grisadas si ninguna Working Area tiene Tangencia,
  ver «Working Area»); `Grilla de grados`
  elige los meridianos y paralelos: **10°** (sólo principales, etiquetadas
  en los bordes), **5°** (principales cada 10° y secundarias a rayas cada
  5°) o **1°** (principales cada 5°, iguales entre sí, y secundarias
  punteadas cada 1°); la casilla `+ la del archivo` (Vista ▸ Grilla
  lat/lon del archivo) agrega además la grilla fina del dato; `FIR
  Argentina`, `+ vecinas` y `FIR…` manejan la capa de límites de FIR (ver
  «Límites de FIR»); el recuadro lat/lon mín/máx (Enter o `Aplicar
  recuadro`) y `Todo el dominio` fijan la vista. Alrededor del mapa queda
  un margen reservado a las inscripciones de grados, que nunca se tapan.
* **INVENTARIO**: corrida, pasos, variables, niveles y grilla del archivo.

Cualquier cambio de radio, botón de nivel, combo o casilla redibuja
automáticamente, y estilo, casillas y densidad quedan guardados como
valores iniciales (también editables en Preferencias ▸ Mapa). Las mismas
opciones de VIENTO y MAPA están en el menú **Vista** (Proyección, Viento,
Extra Info, Fondo de velocidad, Grilla de grados, Grilla del archivo),
sincronizadas con el panel; las
acciones globales `Actualizar` (F5) y el menú `Capas` van en la barra de
acciones; `Capa de datos` (⌘D) también en Vista.

**Menú Capas.** El botón `Capas` de la barra de acciones despliega una
casilla por capa, independientes entre sí: GRIB (viento / temperatura,
⌘D), Marco del GRIB (recuadro del área de descarga o de la grilla), Fondo
de velocidad, Extra Info, Costas y fronteras, Grilla de grados (meridianos
y paralelos con rótulos), Grilla del archivo (puntos), Límites de FIR y
Working Areas de las FIR mostradas. Cada una se prende o apaga sin tocar
las demás, y queda sincronizada con las casillas del panel, el menú Vista
y la configuración (`map_coast` y `map_graticule` son nuevas; también
están en Preferencias ▸ Mapa).

### Barra de acciones y mapa

La barra de acciones tiene tres grupos del mismo alto, separados con
aire: *datos* (`Abrir GRIB…`, el selector `Fuente` integrado en un solo
control con borde, `Obtener datos…`), *mapa* (`Inicio`, `+`, `−`,
`Actualizar`, `Capas`) y *salida* (`Guardar PNG`); a la derecha, `▥` (panel
lateral) y `⚙` (preferencias). La franja STATUS y la barra de estado
inferior siguen el tamaño de fuente de la aplicación (⌘ +/−). El mapa ocupa
el área con márgenes justos para las etiquetas de lat/lon; el título
(corrida, validez, nivel y variable) no se dibuja en pantalla, porque
STATUS ya lo muestra, pero sí en el PNG exportado. El mapa se mueve arrastrándolo con el
botón izquierdo (cursor de mano) y se acerca o aleja con la rueda del mouse
alrededor del cursor; no hay modos de zoom/pan. La rueda avanza un 20 % por
muesca (Preferencias ▸ Mapa; en un trackpad cada 40 px de gesto cuentan como
una muesca y un gesto nunca pasa de una muesca por evento). **Modo fino**:
con ⌘ (Ctrl en Windows/Linux) o Shift apretados, la rueda y el arrastre se
dividen por 5 (también configurable), para ajustar la vista con precisión;
los botones `+` y `−` de la barra de acciones (Vista ▸ Acercar / Alejar
(fino), ⌘⌥= / ⌘⌥−) dan un paso fino alrededor del centro, y con Alt un paso
normal. ⌘+ y ⌘− quedan para el tamaño de fuente de toda la ventana. La vista se conserva al cambiar paso, nivel, variable u opciones;
`Inicio` o `Todo el dominio` la reinician. La vista siempre llena el área del mapa: al fijar el
dominio o un recuadro se amplía en el sentido que haga falta.

Para que el mapa responda rápido todo lo que se dibuja va en bloque, con
matrices: barbas y flechas son una colección de matplotlib; los rótulos de
"Extra Info" son una sola colección de trazados vectoriales (un artista de
texto por punto costaba cinco veces más); las líneas de corriente se
integran todas a la vez con un Runge-Kutta vectorizado en numpy sobre
una grilla regular de la proyección (`integrate_streamlines`, tres veces
más rápido que el integrador punto por punto de matplotlib) y sus flechas
de sentido son una colección de chevrones. Un cambio de nivel tarda
≈0,1 s con barbas o flechas y ≈0,15 s con curvas en un GFS de 0,50°.
Además, las barbas o flechas y los rótulos se dibujan sólo para la zona
visible. Al alejar la vista las barbas y las
flechas primero se achican (hasta la mitad del tamaño nominal) y las curvas
se afinan, para conservar la mayor cantidad posible de celdas; recién
cuando ya no entran se ralean (al acercar la vista aparecen todos;
`Densidad` fija el raleo mínimo). Mientras se arrastra el mapa se ocultan los rótulos y las etiquetas
de la grilla, que vuelven al soltar. Al mover el mouse sobre el mapa la barra inferior
muestra lat/lon y, en el punto de grilla más cercano, velocidad (kt),
dirección (°) y temperatura (°C).

**Consulta de punto (clic derecho).** Un clic con el botón derecho sobre
el mapa (o Vista ▸ Consultar punto…, ⌘ I) abre una ventana no modal, al
estilo de la consulta del FDP y con el mismo formato que la ficha del clic
izquierdo (en la ficha la consulta se edita ahí mismo), con el punto en
grados y minutos (`3125S06411W`, editable: se consulta en cuanto está
completo), la **hora de sobrevuelo** `YYMMDDHHMM` en UTC
(arranca con la validez del paso que muestra el panel; cualquier otra
elige el paso cuya ventana de validez la contiene, o el de validez más
cercana si cae fuera de todas, y lo dice) y el **nivel de sobrevuelo**
(banda, sin F: cualquier FL, arranca con el del panel). Debajo, en letra
monoespaciada alineada, van para ese paso y en ese punto la **capa
superior** y la **capa inferior**
del archivo que encierran al FL (etiqueta, FL y presión ISA real de cada
una) y el **valor en el FL**: viento en kt y grados (y `°M` si el mapa
tiene norte magnético), y temperatura en °C. El valor del FL es el de la
capa cuando el FL es un nivel exacto del archivo; si no, la interpolación
lineal en ln(p) entre ambas capas usando la presión real de cada una (en
un archivo etiquetado por FL, la ISA del FL, no la etiqueta nominal: igual
que el mapa); fuera del rango del archivo no se extrapola, se da el valor
de la capa más cercana y se avisa. El dato es el del **origen de la
celda** de la grilla que contiene al punto (su esquina suroeste), que es
la convención del FDP; la ventana lo muestra en grados y minutos y en
decimales (la barra de estado, en cambio, usa el nodo más cercano).
`Copiar` deja en el portapapeles el bloque de texto completo (geodésico,
hora, nivel, paso, origen de celda y las tres capas). Otro clic derecho
cambia el punto y conserva la hora y el FL cargados; al cerrar el archivo
la ventana queda sin datos.

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

### Límites de FIR

La capa **FIR** dibuja sobre el viento los contornos de las cinco FIR
argentinas (Resistencia SARR, Córdoba SACF, Mendoza SAMF, Ezeiza SAEF y
Comodoro Rivadavia SAVF) con su etiqueta (nombre y código OACI) dentro del
polígono, y opcionalmente las FIR limítrofes (Montevideo SUEO, Asunción
SGFA, La Paz SLLF, Santiago SCEZ, Punta Arenas SCCZ, Curitiba SBCW,
Brasilia SBBS, Atlántico SBAO y Johannesburgo Oceánico FAJO) en un estilo
más tenue y a rayas. Se activa con la casilla `FIR Argentina` del panel
(MAPA), con Vista ▸ FIR ▸ Límites de FIR (⌘⇧F) o desde el diálogo
`FIR…`; `+ vecinas` suma las limítrofes. Qué FIR están activas y el estilo
quedan en la configuración.

Las FIR se muestran **de a una o sumadas**: Vista ▸ FIR ▸ **FIR a mostrar**
tiene una entrada tildable por FIR (Argentina y vecinas) más `Todas`,
`Sólo Argentina` y `Ninguna`. Marcar una FIR con la capa apagada enciende
la capa y muestra sólo esa; marcar una vecina enciende también
`+ vecinas`. La misma elección está en la lista de la pestaña Regiones del
diálogo `FIR…`.

#### Working Area

Cada FIR puede tener, además del contorno del AIP y del recuadro lat/lon de
descarga, una **Working Area (WA)**: un cuadrado medido en millas náuticas
sobre un plano en proyección estereográfica tangente a un punto de
tangencia, con origen en el vértice suroeste y lados hacia el norte y el
este. Se define con el código de la FIR, el punto de tangencia (lat/lon),
el vértice SO (lat/lon), el ancho hacia el este y el alto hacia el norte
(NM) y el radio de la esfera conforme (km; por defecto 6371 km, y un botón
calcula √(M·N) de WGS84 en la latitud de tangencia). Los valores los cargás
vos en `FIR…` ▸ **Working Area** (también Vista ▸ FIR ▸ Working Areas…):
una fila por FIR, coordenadas en decimal con signo o grados-minutos con
hemisferio, validación (código de hasta 4 letras, rangos, lados mayores que
cero, radio entre 6000 y 6500 km, vértice a menos de 90° de la tangencia)
y, para la fila elegida, las esquinas SO y NE resultantes en lat/lon. No
vienen precargadas.

Con la casilla `WA` del panel (o Vista ▸ FIR ▸ Working Area de las FIR
mostradas, o la casilla de la pestaña) la WA de cada FIR mostrada se dibuja
junto con su contorno, en amarillo a rayas y puntos con el rótulo `WA
SAEF` en el vértice SO; si la FIR no está mostrada o su WA está
deshabilitada, no se dibuja. Los lados, rectos en el plano, se densifican
cada 5 NM y se proyectan como curvas; el viento se dibuja por encima. Color,
grosor y tamaño de etiqueta se eligen en la misma pestaña. Todo queda en la
configuración (`working_areas`, `wa_show`, `wa_color`, `wa_line_width`,
`wa_label_size`). La proyección es la estereográfica esférica estándar
(Snyder 21-2 a 21-4 y 20-14/20-15) con el radio indicado; el módulo es
`app/working_area.py` y se puede usar sin la interfaz.

**Variación magnética.** Cada WA tiene una columna `Var. mag.`: la
declinación magnética en su punto de tangencia, que gira el plano de la WA
para que el eje y apunte al norte magnético (con variación oeste, el norte
verdadero queda a la derecha). Se acepta `10W`, `7°W`, `6°55'E`,
`6°55'30"E`, `W10` y también un número sin letra, que se interpreta con la
**convención de signo** elegida en Preferencias ▸ Mapa: *este positivo*
(−10 = 10° W, la de la navegación, por defecto) u *oeste positivo* (10 =
10° W). Internamente se guarda siempre este positivo (`variation_deg`).
Para Ezeiza (34°49'S 058°32'W) el WMM-2025 da 10,0° W en octubre de 2026,
con cambio anual de 0,14° hacia el oeste; el AIP indicaba 8° W en 2015 con
variación anual 10' W, que extrapolado coincide. Verificar en el AIP
Argentina (AD 2 SAEZ) antes de usarla.

**Tangencia de la proyección.** La columna `Tangencia` marca, como mucho,
una WA (marcar otra desmarca la anterior). Con una marcada, el selector de
proyección ofrece dos variantes más: *Estereográfica conforme (tangente a
WA SAEF)* y *Lambert conforme (tangente a WA SAEF)*, además de las de
siempre, *(centro del dominio)*, que no cambian. La estereográfica tangente
se construye en el punto de tangencia de esa WA, con su radio de esfera
conforme y girada por su variación magnética: el norte magnético queda
arriba, el cuadrado de esa WA se ve con lados rectos y exactos, y las
costas, FIR, grilla de grados y barbas giran con él; la barra de estado
describe la proyección al elegirla y el cursor agrega la dirección
magnética del viento (`304.8° (314.8°M)`), mientras los números del viento
siguen siendo verdaderos. La Lambert tangente se centra en ese punto con
ese radio, sin giro (la cónica no se gira; "norte verdadero arriba"). No
hace falta que la FIR esté mostrada ni que la WA esté activa: la casilla
`WA` del panel y `Activa` sólo deciden si el cuadrado se dibuja. Sin
ninguna WA con Tangencia (o con una inválida) las dos variantes quedan
grisadas en el panel, en Vista ▸ Proyección y en Preferencias, y si estaba
en uso una de ellas el mapa pasa solo a la variante del centro del dominio.
Técnicamente PROJ no gira el plano de `stere`, así que se usa `ob_tran`
con un polo rotado a 90° del punto de tangencia en el acimut de la
variación (`working_area.tangent_projection_params`).

* **Diálogo «Límites de FIR»** (botón `FIR…`, Vista ▸ FIR ▸ Configurar
  FIR…), en cuatro pestañas (la cuarta, *Working Area*, se describe arriba). *Regiones*: casillas por FIR y estilo (color
  de las argentinas y de las vecinas, grosor, relleno semitransparente en
  %, tamaño de etiqueta; el valor por defecto es un lavanda tenue que no
  compite con la escala de las barbas ni con el magenta de la
  temperatura). *Extremos*: tabla con la latitud norte y sur y la longitud
  este y oeste máximas de cada FIR, calculadas del polígono cargado, la
  cantidad de vértices, la fuente y si la grilla meteorológica abierta
  cubre la FIR **completa**, **parcial** o **ninguna** (comparación de
  recuadros; las que llegan a 90° S siempre quedan parciales con una
  grilla regional). *Datos*: de dónde salen los límites (ver abajo).
* **Mouse**: con la capa activa la barra de estado agrega `FIR Ezeiza
  (SAEF)` cuando el cursor está dentro de una FIR y `límite SAEF · SAVF`
  cuando pasa sobre un contorno (5 px). Un clic sin arrastrar abre junto
  al mouse una **ficha** con tres secciones: *PUNTO* (la consulta de punto
  editable ahí mismo: geodésico, hora UTC y FL, que arrancan con el punto
  del clic, el paso y el FL del panel, y las tres capas alineadas; en
  archivos de superficie o en niveles de presión, el nodo más cercano con
  su viento y temperatura), *ARCHIVO* (lo que muestra STATUS) y *FIR*
  (extremos y cobertura, también en la barra de estado), con `Copiar`. Se
  cierra con un clic afuera o Escape; ⌘ I abre la misma consulta en
  ventana.
* **Dibujo**: los lados se densifican antes de proyectar, así los sectores
  oceánicos hasta 10° W y el de Comodoro Rivadavia hasta el Polo Sur se
  curvan bien en las proyecciones conformes y se recortan a la vista; los
  puntos que una proyección no puede representar (el polo en Mercator) se
  descartan. La geometría proyectada se cachea por FIR y proyección y la
  capa es una colección por grupo, así no afecta la fluidez del viento. La
  etiqueta usa el punto de etiqueta del dataset si existe y cae adentro;
  si no, un punto interior calculado por barrido de paralelos (no el
  centroide, que en polígonos cóncavos cae afuera).

**De dónde salen los contornos.** Prioridad: el archivo propio reemplaza,
para las FIR que contiene, a la fuente descargada preferida; esta
reemplaza a la copia incluida con el visor.

1. **AIP Argentina, ENR 2.1** (AIS de EANA / ANAC): la fuente oficial. Los
   límites laterales están como listas de vértices en texto. `FIR…` ▸
   Datos ▸ `Convertir texto del AIP…` (o `python -m app.fir_aip
   limites.txt --codigo SAVF -o savf.geojson`) convierte esa lista a un
   polígono GeoJSON. Reconoce `2215S06240W`, `221530S0624015W`,
   `2215.5S06240.2W`, `S2215 W06240`, `22°15'30"S 062°40'15"W`, `22 15 30 S
   062 40 15 W`, decimales con hemisferio y parejas con signo (una por
   línea), con lat y lon en cualquier orden. Los tramos descriptos con
   palabras («a lo largo del límite internacional», «siguiendo por el
   paralelo…», «por la costa», arcos) **no se inventan**: quedan unidos por
   una recta y listados en la propiedad `tramos_pendientes` (y en el
   informe del conversor) para completarlos a mano o tomarlos de otra
   fuente. El GeoJSON lleva `oficial: true` y `verificado: false`.
2. **VATSpy Data Project** (`Boundaries.geojson`,
   <https://github.com/vatsimnetwork/vatspy-data-project>, CC BY-SA 4.0):
   fuente abierta de respaldo, lista para usar, con las FIR del mundo
   identificadas por código OACI en la propiedad `id`. Una copia filtrada
   a las 14 FIR de interés viene con el visor (`resources/fir/`) y
   `Descargar límites de FIR (VATSpy)` la renueva en la carpeta de datos
   (`~/Library/Application Support/Visor GRIB/fir/`), con progreso y
   cancelación. **Estos límites son derivados de las AIP y no son
   oficiales: para uso operativo hay que verificarlos contra el AIP.**
3. **openAIP** (<https://www.openaip.net>, API Core, CC BY-NC 4.0): tercera
   fuente opcional. La API publica los espacios aéreos tipo FIR (10) y UIR
   (11) en GeoJSON y exige una clave gratuita (perfil de usuario) que se
   envía en el encabezado `x-openaip-api-key`; se guarda en el llavero
   del sistema desde Preferencias ▸ Fuentes ▸ «openAIP (límites de FIR)» ▸
   `Configurar…` (o `FIR…` ▸ Datos ▸ `Configurar clave…`), nunca en
   `config.json`, y se borra desde el mismo diálogo. `Probar conexión`
   informa cuántas FIR del país devuelve la API; la cobertura de Argentina
   no se pudo verificar sin clave. Como la API no trae el indicador OACI,
   las FIR se reconocen por nombre.

Además `Cargar archivo propio…` admite GeoJSON, KML/KMZ y Shapefile (vía
pyshp, que instala cartopy); el archivo se copia a la carpeta de datos y
reemplaza a las demás fuentes para las FIR que contiene (el código OACI
se toma de la propiedad `id`/`icao`/`code` o del nombre). Fuentes y
licencias en `docs/FUENTES_FIR.md`.

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
| Límites de FIR de Argentina | ⌘ ⇧ F | Ctrl Shift F |
| Consultar punto… | ⌘ I | Ctrl I |
| Preferencias… | ⌘ , | Ctrl , |
| Agrandar / achicar / restablecer fuente | ⌘ + / ⌘ − / ⌘ 0 | Ctrl + / Ctrl − / Ctrl 0 |
| Desplazar el mapa | Arrastrar | Arrastrar |
| Desplazar fino (÷ 5) | ⌘ o ⇧ + arrastrar | Ctrl o Shift + arrastrar |
| Acercar / alejar alrededor del cursor | Rueda | Rueda |
| Acercar / alejar fino alrededor del cursor | ⌘ o ⇧ + rueda | Ctrl o Shift + rueda |
| Acercar / alejar un paso fino (botones + y −) | ⌘⌥= / ⌘⌥− | Ctrl Alt = / Ctrl Alt − |
| Consulta de punto (capas y valor en un FL) | Clic derecho en el mapa | Clic derecho en el mapa |
| Atajos de teclado | ⌘ / | Ctrl / |

**Pantalla completa.** Vista ▸ Pantalla completa (⌃⌘F en macOS, F11 en
Windows y Linux) o el botón verde de macOS expanden la ventana a toda la
pantalla. En ese modo macOS pone la ventana sola sobre un Space sin
escritorio detrás, así que el desenfoque no tiene nada que mostrar: la
ventana pasa a opaca con el fondo del tema mientras dura, y vuelve a ser
translúcida al salir. Sin desenfoque (Windows, Linux o si falla en macOS)
la ventana es opaca siempre.

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
  superficie isobárica (tipo 100). En el producto de NOAA el nivel lleva la
  **presión ISA del FL en Pa** (`843.1 mb`, `812 mb`… en `wgrib2 -s`); en
  los modos nominales (abajo) lleva la etiqueta en hPa (`850 mb`). El
  lector usa el valor escalado exacto, no el `level` truncado de ecCodes.
* Plazos operativos: +6…+24 cada 1 h, +27…+48 cada 3 h, +54…+120 cada 6 h;
  corridas 00/06/12/18. Nombre del producto: `gfs.tHHz.wafs_0p25.fFFF.grib2`.

**La tabla de FL** (`app/fl_table.py`) es la única fuente de verdad, copiada
literal de la lista oficial de NOAA (repo NOAA-EMC/wafs) que usa el
generador de archivos WAFS del servidor; no se recalcula con la fórmula.
Para cada FL tiene dos columnas: `ISA_Pa`, la presión ISA exacta en Pa, y
`OACI56_hPa`, la etiqueta nominal en hPa: 56 etiquetas distintas y
decrecientes, con la regla del generador: los 17 OACI conservan el nominal
del Anexo 3 (Ap. 2, 1.2.2) y los demás van al múltiplo de 25 hPa más
cercano si está libre o, si colisiona, al múltiplo de 5 (no de 25) más
cercano y libre (F190 → 485 porque 475 chocaba con F200; F580 → 70 porque
75 es múltiplo de 25). **El dato de viento y temperatura de cada nivel
corresponde siempre a la presión exacta**; la etiqueta es lo que se graba
en el GRIB y lo que reconoce cada consumidor. Subconjuntos: OACI17 (050 080
100 140 180 210 240 270 300 320 340 360 390 410 450 480 530) e INDRA14
(OACI17 sin 080, 210 ni 480: los 14 botones del FDP).

| FL | ISA_Pa | Nominal | FL | ISA_Pa | Nominal | FL | ISA_Pa | Nominal | FL | ISA_Pa | Nominal |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 050 | 84310 | 850 | 190 | 48550 | 485 | 330 | 26200 | 260 | 470 | 13400 | 135 |
| 060 | 81200 | 800 | 200 | 46560 | 465 | 340 | 25000 | 250 | 480 | 12770 | 125 |
| 070 | 78190 | 775 | 210 | 44650 | 450 | 350 | 23840 | 240 | 490 | 12170 | 120 |
| 080 | 75260 | 750 | 220 | 42790 | 425 | 360 | 22730 | 225 | 500 | 11600 | 115 |
| 090 | 72430 | 725 | 230 | 41000 | 410 | 370 | 21660 | 215 | 510 | 11050 | 110 |
| 100 | 69680 | 700 | 240 | 39270 | 400 | 380 | 20650 | 205 | 520 | 10530 | 105 |
| 110 | 67020 | 675 | 250 | 37600 | 375 | 390 | 19680 | 200 | 530 | 10040 | 100 |
| 120 | 64440 | 650 | 260 | 35990 | 360 | 400 | 18750 | 190 | 540 | 9570 | 95 |
| 130 | 61940 | 625 | 270 | 34430 | 350 | 410 | 17870 | 175 | 550 | 9120 | 90 |
| 140 | 59520 | 600 | 280 | 32930 | 330 | 420 | 17040 | 170 | 560 | 8700 | 85 |
| 150 | 57180 | 575 | 290 | 31490 | 315 | 430 | 16240 | 160 | 570 | 8280 | 80 |
| 160 | 54920 | 550 | 300 | 30090 | 300 | 440 | 15470 | 155 | 580 | 7900 | 70 |
| 170 | 52720 | 525 | 310 | 28740 | 285 | 450 | 14750 | 150 | 590 | 7520 | 65 |
| 180 | 50600 | 500 | 320 | 27450 | 275 | 460 | 14060 | 140 | 600 | 7170 | 60 |

**Cuatro modos de etiquetado** (configuración y exportación; en los cuatro
el dato se interpola a `ISA_Pa`):

| Modo | Filas | Etiqueta grabada | Uso |
|---|---|---|---|
| INDRA | las 14 de INDRA14 | nominal hPa | los 14 botones del FDP |
| OACI | las 17 de OACI17 | nominal hPa | Anexo 3; **por defecto** (lo que genera el servidor) |
| OACI56 | las 56 | nominal hPa única | el FDP reconoce sus 14, el visor tiene los 56 |
| WAFS | las 56 | ISA_Pa | como codifica NOAA; el FDP sólo reconoce 300/250/100 |

El modo por defecto se elige en Preferencias ▸ WAFS (persistido,
`wafs_mode`) y vale para la conversión automática al abrir o descargar; el
diálogo Exportar a WAFS tiene su propio selector y, en los dos lugares, un
botón **Ver tabla** muestra FL, `ISA_Pa` y la etiqueta del modo elegido.

**Al leer un archivo** se mapea el nivel de cada mensaje (presión en Pa) a FL
buscándolo primero en la columna `ISA_Pa` (modo WAFS, con tolerancia de 10
Pa) y después en `OACI56_hPa`×100; lo que no está en ninguna columna queda
«no reconocido» y se muestra con su presión cruda. El inventario dice qué
modo explica todos los niveles (`FORMATO: etiquetado por FL, modo INDRA…`).
Un archivo cuenta como etiquetado por FL sólo si un modo explica todos sus
niveles y, en los modos nominales, están al menos los 14 FL de INDRA: un
GFS crudo con 850/700/500/250/100 hPa coincide con etiquetas nominales pero
no se toma por FL, se interpola. Lo que baja de una fuente en niveles de
presión se convierte siempre, aunque sus niveles coincidan con etiquetas.
Si el archivo viene en niveles de presión crudos, los FL se interpolan en
ln(p) a `ISA_Pa`, como siempre, y sólo los FL cuya presión cae dentro de los
niveles del archivo quedan disponibles (no se extrapola).

**Fórmula ISA** (la del conversor de referencia, `docs/referencia/make_wafs_like.py`;
reproduce los valores de NCEP salvo F290, que la tabla literal da 31490 Pa y
la fórmula redondeada 31480; el visor usa la tabla):

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

**Conversión** (`app/wafs_format.py`, sin interfaz; misma tabla,
interpolación y etiquetas que el generador del servidor,
`docs/referencia/gfs_to_wafs.py`, copia del paquete `gfs_wafs` que corre en
el servidor; el conversor histórico `docs/referencia/make_wafs_like.py`
queda como referencia del modo WAFS y se reproduce con tolerancia de 0,1).
La muestra `tests/data/WAFS_oaci_test.grib2` (con su `.idx`) la generó ese
paquete en modo `oaci`: el visor la lee como OACI, 17 niveles exactos, y su
inventario coincide byte a byte con el del servidor:

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
    [--modo INDRA|OACI|OACI56|WAFS] [--forzar]
python -m app.wafs_format --validar archivo.grib2
```

En el visor, con un archivo etiquetado por FL cada FL cae en un **nivel
exacto del archivo** (STATUS: `LEVEL: F300 = 30090 Pa ISA (nivel exacto,
modo OACI, etiqueta 300 hPa)`), la lista «Otros FL del archivo» trae los
FL sin botón como `FL060 · 800 hPa (812 ISA)` (su primera opción es «el FL
del botón elegido»; en INDRA u OACI no hay ninguno y queda inactiva), el
inventario dice `FORMATO: etiquetado por FL, modo …` y FUENTE agrega
`WAFS FL050–FL530 · modo OACI (convertido)`.

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
con siete pestañas:

* **Apariencia**: color de acento (presets o personalizado, con vista previa
  en vivo) y transparencia de la ventana.
* **Mapa**: proyección, valores iniciales de VIENTO y MAPA (viento, Extra Info, grilla,
  fondo de velocidad, densidad), rótulos de Extra Info, zoom y
  desplazamiento (% por paso de la rueda y divisor del modo fino) y la
  convención de signo de la variación magnética de las Working Areas.
* **Fuentes**: lista de fuentes con su casilla de habilitación, tipo y
  `✓ FL`; `Configurar…` abre la fuente: parámetros por defecto (el mismo
  formulario que el diálogo de descarga), credenciales si las exige
  (usuario/clave o token, guardadas con `keyring` en el llavero del sistema,
  nunca en `config.json`, con botón para borrarlas) y `Probar conexión`, que
  responde `Conexión OK`, `Sin red`, `Credenciales inválidas` o `Dato
  todavía no publicado`. Debajo, «Límites de FIR (capa del mapa)» con la
  fuente openAIP: su clave de API se guarda y se borra del mismo modo.
* **Descarga**: plazos, unir plazos y abrir al terminar como valores
  iniciales de `Obtener datos…`; tamaño y antigüedad máximos de la caché y
  `Vaciar caché`.
* **Áreas / FIR**: tabla de áreas de descarga (código, nombre, N/S/W/E,
  habilitada, a verificar), margen de seguridad, formato de coordenadas,
  exportar/importar (ver «Áreas de descarga por FIR»); el botón `Límites
  de FIR y Working Areas…` abre la ventana «Límites de FIR» (la misma de
  Vista ▸ FIR), donde se eligen las FIR a dibujar, su estilo, los datos de
  los límites y las Working Areas.
* **WAFS**: convertir a WAFS por defecto (valor inicial de la casilla del
  diálogo de descarga) y al abrir archivos locales,
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
QT_QPA_PLATFORM=offscreen python tests/run_tests.py     # lo mismo; es lo que corre la CI
```

En Linux, `pyproj` (PROJ con sus propias libcurl, libtiff y libsqlite3)
tiene que cargarse antes que PyQt6 y ecCodes: si no, la finalización del
intérprete aborta con un error de glibc *después* de que la suite terminó en
OK. `main.py`, `app/__init__.py` y `tests/run_tests.py` lo importan primero;
con `python -m unittest` el orden lo decide el primer test y puede terminar
en código 134 aunque todo haya pasado.

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

## Instaladores

Los instaladores de cada versión están en la página de *Releases* del
repositorio (`https://github.com/LmpOSX/GRIB/releases`):

| Sistema | Archivo | Instalación |
|---|---|---|
| macOS 12+ (Apple Silicon) | `Visor_GRIB_<ver>_macOS_arm64.dmg` | Abrir el DMG y arrastrar a Aplicaciones. La app lleva firma ad hoc, sin notarizar: al abrirla por primera vez macOS la bloquea; ir a Ajustes del Sistema ▸ Privacidad y seguridad y tocar **Abrir igualmente** (o en Terminal `xattr -cr "/Applications/Visor GRIB.app"`). Si dijera «está dañada», la firma se rompió: avisar, es un error del paquete. |
| Linux x86_64 (Debian/Ubuntu) | `Visor_GRIB_<ver>_Linux_x86_64.deb` | `sudo apt install ./Visor_GRIB_<ver>_Linux_x86_64.deb`; queda el comando `visor-grib` y la entrada en el menú. |
| Linux x86_64 (cualquier distro) | `Visor_GRIB_<ver>_Linux_x86_64.AppImage` | `chmod +x` y ejecutar. También hay un `.tar.gz` portable con la carpeta `VisorGRIB/`. |
| Windows 10/11 x64 | `Visor_GRIB_<ver>_Windows_x64_Setup.exe` | Ejecutar el instalador (SmartScreen avisa porque no está firmado: *Más información ▸ Ejecutar de todas formas*). También hay un `.zip` portable. |

La configuración del usuario queda en `~/Library/Application Support/Visor GRIB/`
(macOS), `%APPDATA%\Visor GRIB\` (Windows) o `~/.config/Visor GRIB/` (Linux).
Las costas de Natural Earth se bajan la primera vez que se dibujan, igual que
en modo desarrollo.

### Generar los instaladores

Todo sale de un único spec de PyInstaller (`packaging/visor_grib.spec`); cada
script arma el instalador propio del sistema y antes corre una prueba de humo
(abre `tests/data/WAFS_like_test.grib2` dentro del paquete con
`VISOR_GRIB_SMOKE=8` y `QT_QPA_PLATFORM=offscreen`):

```bash
scripts/build.sh              # macOS: dist/Visor GRIB.app y dist/Visor_GRIB_<ver>_macOS_<arch>.dmg
scripts/build_linux.sh        # Linux: .tar.gz, .deb (dpkg-deb) y AppImage (baja appimagetool)
pwsh scripts/build_windows.ps1   # Windows: .zip y Setup.exe (requiere Inno Setup 6)
```

PyInstaller no cruza plataformas: cada instalador se genera en su sistema.
El DMG de macOS (Apple Silicon; no hay build para Intel) se construye en
forma local y se sube a la release; el workflow
`.github/workflows/release.yml` genera los de Linux y Windows al publicar
una etiqueta `vX.Y.Z` (el job de macOS sólo corre si se lanza a mano desde
*Actions* con la casilla «macos», por si no hay un Mac a mano):

```bash
# nueva versión: cambiar app/__init__.py y CHANGELOG.md, commitear y
QT_QPA_PLATFORM=offscreen python tests/run_tests.py   # lo mismo que tests.yml
git tag v0.3.1 && git push origin main v0.3.1
gh release create v0.3.1 --title "Visor GRIB v0.3.1" --notes-file notas.md
bash scripts/build.sh && gh release upload v0.3.1 dist/Visor_GRIB_*_macOS_arm64.dmg
```

Los archivos se adjuntan a la *release* de esa etiqueta. Si la release no
existe, el workflow la crea con el nombre `Visor GRIB vX.Y.Z`.

## Verificación con wgrib2

1. Abrir el archivo: `python main.py FDP_MULTI.grib2`.
2. Elegir **Next (+1)** (segundo paso, por ejemplo +9 h) y el nivel **F100**.
   `FDP_MULTI.grib2` tiene exactamente los 14 niveles nominales de INDRA,
   así que el visor lo lee etiquetado por FL (modo INDRA): STATUS muestra
   `F100 = 69680 Pa ISA (nivel exacto, modo INDRA, etiqueta 700 hPa)` y el
   dato es el del mensaje de 700 mb sin interpolar. Con un GFS crudo (con
   1000 hPa, por ejemplo) F100 se interpola a 696,8 hPa entre 700 y 600 hPa,
   y el nivel exacto se elige al final de la lista «Otros FL».
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
