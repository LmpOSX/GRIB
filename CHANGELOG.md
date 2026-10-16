# Cambios

## Sin publicar

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
