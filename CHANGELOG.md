# Cambios

## Sin publicar

- Botón «Preferencias WAFS…» al lado de la casilla «Convertir a WAFS» del
  diálogo de descarga: abre Preferencias limitadas a la pestaña WAFS (las
  demás bloqueadas), encima del diálogo, y al aplicar la casilla toma el
  nuevo valor por defecto.
- Botón «Límites de FIR y Working Areas…» en Preferencias ▸ Áreas / FIR
  que abre la ventana «Límites de FIR» (la de Vista ▸ FIR).
- ⌘+ volvía a hacer zoom en el mapa en vez de agrandar la fuente: el zoom
  fino de Vista ▸ Acercar / Alejar (fino) tenía ⌘⇧+ y ⌘⇧−, y como «+» es
  Shift+= chocaba con ⌘+ (Qt lo tomaba por ambiguo). El zoom fino pasa a
  ⌘⌥= / ⌘⌥− (Ctrl Alt en Windows y Linux); ⌘+ / ⌘− / ⌘0 son sólo para el
  tamaño de fuente de toda la ventana.
- La franja STATUS y la barra de estado inferior siguen el tamaño de
  fuente de la aplicación (antes tenían un tamaño fijo).
- Una sola consulta de punto: la ficha del clic (sin arrastrar) sobre el
  mapa, con el tema en vez del tooltip amarillo: PUNTO (la consulta
  editable ahí mismo: geodésico, hora UTC, FL y las tres capas alineadas
  en letra monoespaciada), ARCHIVO (lo de STATUS) y FIR (extremos y
  cobertura), con «Copiar». Mientras está abierta el mapa no reconoce el
  botón izquierdo: un clic sobre la ficha edita el campo (o no hace nada),
  y Escape o un clic afuera la cierran sin abrir otra. Desaparece la ventana «Consulta de punto» del clic derecho; Vista
  ▸ Consultar punto… (⌘ I) abre la ficha en el último punto o en el
  centro de la vista.

## 0.3.2 — 2026-10-16

- Consulta de punto con el clic derecho sobre el mapa (también Vista ▸
  Consultar punto…, ⌘ I): ventana al estilo del FDP con el punto en grados
  y minutos (`3125S06411W`), la hora de sobrevuelo `YYMMDDHHMM` (elige el
  paso cuya ventana de validez la contiene) y cualquier nivel de
  sobrevuelo; muestra viento y temperatura de la capa inferior, la
  superior y el valor en el FL (nivel exacto, interpolado en ln(p) o, fuera
  del rango, el de la capa más cercana), con el origen de la celda usada
  (esquina suroeste, la convención del FDP) y un botón para copiar el
  informe.
- La interpolación a un FL que no es nivel del archivo usa la presión real
  de cada capa: en archivos etiquetados por FL, la ISA del FL en lugar de
  la etiqueta nominal (300.9 hPa en vez de 300 para F300).
- Botonera de niveles en cuatro columnas (cuatro filas de cuatro y F530);
  la lista «Otros FL» ocupa el hueco al lado de F530.
- La casilla «Convertir a WAFS» está en el diálogo de descarga (bloque
  Destino); la opción de Preferencias ▸ WAFS pasa a llamarse «Convertir a
  WAFS por defecto» y sólo fija cómo arranca esa casilla. Sin marcar, el
  GFS queda en niveles de presión y sin sufijo `_wafs`, y «Abrir en el
  visor al terminar» lo abre tal cual, sin la conversión de archivos
  locales de Preferencias.

## 0.3.1 — 2026-10-16

- Niveles alineados con el generador WAFS del servidor (`gfs_wafs`): el modo
  OACI pasa a 17 FL (se suma F210 = 450 hPa, Anexo 3 Ap. 2 1.2.2) y es el
  modo por defecto para convertir y exportar; INDRA sigue siendo OACI sin
  F080, F210 y F480. Un archivo con los 17 niveles nominales se lee como
  OACI (antes caía en OACI56).
- Botonera de 17 botones en tres filas de seis; la lista «Otros FL» queda
  inactiva cuando todos los FL del archivo tienen botón (INDRA u OACI).
- «Ver tabla» muestra de dónde sale cada etiqueta nominal (OACI, múltiplo
  de 25 o de 5) y las columnas OACI17 / INDRA14.
- Referencia y pruebas: `docs/referencia/gfs_to_wafs.py` (el generador del
  servidor, cuya tabla se compara con la del visor) y
  `tests/data/WAFS_oaci_test.grib2` (muestra OACI con su `.idx`, que el
  visor reproduce byte a byte).
- Instaladores: se discontinúa el DMG de macOS Intel. El de Apple Silicon se
  construye en forma local (`scripts/build.sh`) y se sube a la release; el
  workflow genera los de Linux y Windows (macOS sólo a pedido).

## 0.3.0 — 2026-10-16

- Tabla de niveles de vuelo única (`app/fl_table.py`), copiada literal del
  generador WAFS del servidor: presión ISA exacta y etiqueta nominal OACI56
  por FL. Cuatro modos de etiquetado (INDRA, OACI, OACI56 por defecto, WAFS)
  para convertir y exportar, con selector y «Ver tabla» en Exportar a WAFS y
  en Preferencias ▸ WAFS; al leer, cada nivel se mapea a FL por la columna
  ISA o por la nominal y el inventario dice qué modo explica el archivo.
- Selección de nivel: botonera fija de 16 botones (OACI16) con los FL que el
  archivo no tiene en gris, y lista con los demás FL del archivo; el FL
  activo muestra etiqueta y presión exacta.

## 0.2.2 — 2026-10-15

- Pantalla completa nativa en macOS (botón verde o ⌃⌘F; F11 en Windows y
  Linux): la ventana ocupa toda la pantalla y pasa a opaca mientras dura,
  porque en ese Space no hay escritorio detrás del desenfoque; vuelve
  translúcida al salir. Vista ▸ Pantalla completa.

## 0.2.1 — 2026-10-15

- Menú `Capas` en la barra de acciones (reemplaza a `Ocultar capa`): GRIB,
  Marco del GRIB, Fondo de velocidad, Extra Info, Costas y fronteras, Grilla
  de grados, Grilla del archivo, FIR y Working Areas, cada una
  independiente; costas y grilla de grados son nuevas capas apagables.
- La tangencia de la WA va en variantes propias del selector de proyección,
  «Estereográfica conforme (tangente a WA XXXX)» y «Lambert conforme
  (tangente a WA XXXX)», grisadas si ninguna WA tiene Tangencia; las de
  «centro del dominio» no cambian. La Lambert tangente usa el punto y el
  radio de la WA, sin giro magnético.

## 0.2.0 — 2026-10-15

- Working Area por FIR: cuadrado en millas náuticas sobre un plano
  estereográfico tangente (punto de tangencia, vértice SO, ancho, alto y
  radio de la esfera conforme), cargado a mano en `FIR…` ▸ Working Area y
  dibujado junto con cada FIR mostrada (casilla `WA`, Vista ▸ FIR).
- Las FIR se muestran de a una o sumadas desde Vista ▸ FIR ▸ FIR a mostrar
  (una entrada por FIR, Todas, Sólo Argentina, Ninguna).
- Variación magnética por Working Area (`10W`, `6°55'E` o número según la
  convención de signo elegida en Preferencias ▸ Mapa) que gira su plano, y
  columna `Tangencia` (una sola): la estereográfica conforme pasa a ser
  tangente a esa WA, con su radio y girada para dejar el norte magnético
  arriba; el cursor agrega la dirección magnética del viento. Sin tangencia,
  centro del dominio como antes.
- Zoom y desplazamiento finos: con ⌘/Ctrl o Shift apretados la rueda y el
  arrastre se dividen por 5; botones `+` y `−` en la barra (Vista ▸ Acercar
  / Alejar (fino), ⌘⇧+ / ⌘⇧−); la rueda del trackpad ya no acerca de golpe;
  % por paso y divisor fino en Preferencias ▸ Mapa.
- El marco del área de descarga acompaña al archivo abierto (zona pedida de
  su procedencia o recuadro de su grilla); al abrir otro archivo se
  reemplaza en vez de quedar el anterior.

## 0.1.0 — 2026-10-15

Primera versión publicada del visor en PyQt6. Instaladores para macOS (Apple
Silicon e Intel), Linux (.deb, AppImage, tar.gz) y Windows (Setup.exe, zip),
generados por GitHub Actions a partir de la etiqueta `v0.1.0`.

- Visor de viento y temperatura por nivel de vuelo (FL) con mapa matplotlib y
  cartopy, seis proyecciones, barbas, flechas o líneas de corriente, rótulos,
  grilla de grados y fondo de temperatura.
- Formato WAFS como formato interno único: conversión automática al abrir o
  descargar, exportación a WAFS y validador.
- Fuentes de datos: NOAA GFS, NOAA WAFS (WIFS), ECMWF Open Data, DWD ICON, SMN
  Argentina WRF y fuente genérica por URL con credenciales en el llavero del
  sistema.
- Capa de límites de FIR (Argentina y vecinas) desde GeoJSON, KML o Shapefile,
  conversor AIP ENR 2.1 → GeoJSON y datos VATSpy incluidos.
- Descarga por área geográfica definida a partir de las FIR argentinas, con
  margen de seguridad, redondeo hacia afuera a la grilla del modelo,
  validación de cobertura y rectángulos en el mapa.
- Preferencias por pestañas, tema con desenfoque nativo en macOS y Windows,
  zoom de fuente, atajos y configuración persistente por usuario.

Las coordenadas precargadas de las cinco FIR argentinas y los contornos de
VATSpy no son oficiales: verificarlos contra el AIP Argentina ENR 2.1 antes de
cualquier uso operativo.
