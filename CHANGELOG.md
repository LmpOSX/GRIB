# Cambios

## 0.5.1 — 2026-10-23

- El mapa y el hexadecimal, subsecciones del bloque del mapa, llevan el
  mismo recuadro redondeado que el encabezado de información.
- Panel hexadecimal: el volcado deja ver la ventana translúcida con la
  opacidad del tema (pintaba un fondo opaco); los colores de los niveles
  salen de la paleta del acento (tono a lo sumo ±45°, luminosidad en
  escalera) en vez de una rueda de tonos ajena; el separador con el mapa
  baja hasta dejar el hexadecimal chico (antes se frenaba casi enseguida
  por el alto mínimo).
- Al mostrar u ocultar el panel lateral y el hexadecimal en cualquier orden
  la ventana ya no se agranda sola (el mapa tiene un mínimo propio y el
  hexadecimal cede antes de forzar la ventana) y el mapa conserva la escala:
  al cambiar el tamaño del lienzo se ve más o menos región, pero el zoom no
  cambia. Antes cada cambio ampliaba la vista para llenar la proporción
  nueva y cada ida y vuelta alejaba un poco más.
- Panel hexadecimal: subsección del bloque del mapa, debajo del encabezado
  de información; con el panel lateral a la vista va debajo del mapa (un
  separador reparte el alto), sin el panel lateral a la derecha del mapa, con
  el ancho del árbol más el volcado y nunca más que el mapa. El árbol va a la
  izquierda y el volcado a la derecha en los dos casos.
- Panel hexadecimal: los valores de la sección 7 se listan por demanda,
  en filas de la grilla y celda por celda (`[j, i] lat lon`, tramo de bytes y
  valor decodificado; con empaquetado complejo, JPEG o PNG el valor sale de
  ecCodes y la celda abarca toda la sección). Un clic en el mapa, además de
  la ficha del punto, lleva el panel a la celda del archivo que muestra ese
  punto.
- El visor hexadecimal pasa a ser un panel fijo a la izquierda del mapa, del
  ancho del volcado, con el árbol arriba y el volcado abajo: botón `0x` de la
  barra de acciones o Vista ▸ Panel hexadecimal (⌘ ⇧ H), como el `▥` del
  panel lateral; el mapa cede ese ancho y la elección se recuerda. Carga el
  archivo sólo mientras está a la vista. Reemplaza al diálogo Ver hexadecimal….
- Visor hexadecimal: los colores son por nivel del árbol (mensaje, sección,
  campo, subcampo), con un cuadrito del color junto a cada nombre; al elegir
  un nodo se pinta toda su ruta, cada tramo con el color de su nivel y el
  elegido encima con el marco del acento. Los nodos con hijos llevan «+»,
  que pasa a «−» al abrirlos; abrir o cerrar no cambia lo pintado. Antes el
  nodo elegido se pintaba con el acento y cada hijo con un color propio.
- Visor hexadecimal: el resaltado coincidía mal con los bytes (empezaba en
  el segundo dígito, abarcaba los espacios que siguen al último byte y en el
  último byte de la fila pintaba parte del siguiente): las posiciones se
  calculaban con el ancho entero del carácter y el texto se dibuja con
  avances fraccionarios. Ahora cada byte se dibuja en su posición exacta.

## 0.5.0 — 2026-10-23

- Rectángulo del área de descarga y polígonos de FIR que llegan al polo
  (SAVF): el lado que baja al polo es un meridiano y ahora se densifica en
  latitud; en las proyecciones con meridianos curvos (estereográfica tangente
  a WA o del centro, Lambert) se dibujaba como una recta que no coincidía con
  el meridiano y dejaba datos fuera del marco.
- Bloque «Archivo a guardar» en Preferencias ▸ Guardar (valores por defecto,
  aplicados también al convertir al abrir), Obtener datos…, Generar GRIB… y el
  nuevo Archivo ▸ Guardar como… (⌘ ⇧ S), que recodifica entero el archivo
  abierto con otro nombre: viento U/V o dirección y velocidad (reemplaza al
  selector «Viento en el archivo»); decimales del viento y de la temperatura
  (0, 1 o 2, exactos: factor decimal con escala binaria 0 y los valores
  redondeados antes); etiqueta de capa de los archivos por Nivel (según el
  modo, nominal 850, ISA 843,1 o ISA entera 843, que el visor reconoce como
  ISA); empaquetado simple o un valor IEEE por celda; centro generador del
  origen o «sin centro» (65535). Todo queda en la procedencia (`guardado`,
  `por_nivel`).
- Vista ▸ Ver hexadecimal… (⌘ ⇧ H): el archivo abierto como un `hexdump -C`
  con su estructura en árbol (mensaje → sección → campo → subcampo) y el valor
  decodificado de cada campo. Cada mensaje lleva un tinte alternado; el nodo
  elegido se pinta con el acento y sus hijos con colores propios, así al
  entrar en el árbol se ven las secciones del mensaje, los campos de la
  sección y los bytes del campo. Clic en un byte abre el árbol hasta el campo
  que lo contiene; «Ir al byte», línea de detalle con la ruta, los bytes y la
  interpretación, y «Copiar bytes». Análisis propio, sin ecCodes, de las
  plantillas del GFS, el WAFS y el visor.

## 0.4.2 — 2026-10-22

- Crudo o por Nivel al abrir: el `.json` de procedencia decide. Un archivo
  bajado de un modelo sin convertir (GFS, ICON, ECMWF, SMN…) se toma como
  capas crudas y se interpola aunque sus capas coincidan con las etiquetas
  nominales de INDRA/OACI (antes, con las 14 capas de INDRA, se mostraba como
  «nivel exacto» sin interpolar); si la conversión al abrir está activada, se
  convierte. Lo convertido, generado o exportado por el visor cuenta como por
  Nivel aunque tenga pocos FL. Sin `.json` se deduce como siempre y el
  inventario lo aclara («deducido de las capas»). Exportar a WAFS también
  convierte (en vez de sólo reetiquetar) un crudo con procedencia, y anota en
  el `.json` de salida que está por Nivel.
- Exportar a WAFS con «variables básicas» conserva el viento en dirección y
  velocidad (WDIR/WIND); antes lo descartaba y quedaba sólo la temperatura.
- Generar GRIB: centro 65535 («Missing value» de la tabla C-11) en vez de 255
  («no usar»), y tabla maestra 25 en vez de la 4 de la plantilla de ecCodes.
- Generar GRIB: los campos (constantes) se graban con factor decimal 0; con 2,
  wgrib2 avisaba «simple encode/decode may differ from WMO standard» en cada
  mensaje. El valor decodificado es el mismo.

## 0.4.1 — 2026-10-21

- Generar GRIB: botón en la barra (junto a «Obtener datos…») y en la pantalla
  de inicio (junto a «Abrir GRIB…»); «Viento en el archivo» pasa al recuadro
  de niveles, a la derecha de los botones de modo (la tabla se carga siempre
  en velocidad y dirección; el archivo se graba según esa opción). En la tabla
  siempre hay una fila elegida: al entrar, la última; Agregar inserta FL + 10
  encima de la elegida (con su viento y la T ISA; si el FL ya existe lo marca
  «repetido») y mantiene la elección; Quitar saca la elegida y pasa a la de
  abajo, o a la nueva última; sin filas, Agregar pone FL050. Edición a la
  vista: clic, Tab o flechas abren la celda en edición con el editor tapando
  la celda, centrado y con el valor preseleccionado (una tecla lo reemplaza,
  las flechas sueltan la selección), la celda actual lleva un marco de acento,
  Enter aplica, Esc sale sin cambiar, Tab recorre celdas y filas salteando
  Presión. El editor es un campo normal: opaco y ocupando la celda entera (el
  valor de la celda no se dibuja debajo), alineado a la derecha con lugar a la
  izquierda, cursor a la derecha del valor preseleccionado; ← suelta la
  selección para insertar y Backspace / Supr borran de a un carácter. Plazos
  desde / hasta / cada en vez de uno solo (el mismo perfil en cada plazo; el
  nombre lleva `f006-f024`). Esc en edición sólo sale de la edición y deja la
  fila elegida; con el foco en la tabla no cierra el diálogo. Al entrar y tras
  Agregar, Quitar o un botón de modo la fila queda elegida sin edición.

## 0.4.0 — 2026-10-21

- Viento como dirección y velocidad (WDIR/WIND) además de U/V: el diálogo de
  descarga tiene «Viento en el archivo» (componentes U y V, o dirección y
  velocidad); con la segunda, al terminar cada par U/V se reemplaza por WDIR
  (grados verdaderos, de dónde sopla) y WIND (m/s), el nombre lleva `_dirvel` y
  la procedencia `viento: dirspeed`. El visor lee los dos formatos: de un
  WDIR/WIND deriva U/V al leer (motor ecCodes y wgrib2), la conversión a WAFS
  interpola en U/V y devuelve el formato del origen, y el validador acepta
  WDIR/WIND avisando que el WAFS operativo lleva U/V.
- Archivo ▸ «Generar GRIB…» (⌘G): fabrica un GRIB2 a mano con un perfil
  uniforme por FL. Corrida y plazo; área manual o por FIR con margen;
  resolución 0,25 / 0,50 / 1,00°; botones INDRA (14), OACI (17), OACI (56) y
  WAFS (56) que llenan la tabla de niveles y fijan el etiquetado; tabla con
  temperatura (arranca en la ISA), velocidad en kt y dirección por FL, con
  Temperatura ISA, Copiar hacia abajo, Agregar y Quitar FL; viento como U/V o
  dirección y velocidad; escribe el `.grib2` con `.idx` y `.json` de
  procedencia (`fuente: generado`) y lo abre en el visor.

## 0.3.8 — 2026-10-20

- Ficha del punto: después de tocar un punto sin datos (fuera de la grilla),
  la ficha del siguiente punto con datos salía con el perfil estirado y se
  pasaba del mapa; el alto disponible se calculaba con el tamaño cacheado de
  la ficha anterior, sin perfil. Ahora se refrescan los layouts antes de
  medir y la ficha queda igual que la de un primer clic.

## 0.3.7 — 2026-10-20

- Mapa: los rótulos de latitud de la izquierda se cortaban en pantallas Retina
  («0°S» en vez de «30°S»). El margen de las inscripciones, a la izquierda y
  abajo, ya no es una constante: tras cada dibujado se mide lo que ocupan los
  rótulos que cartopy puso en cada borde, con la fuente y el dpi reales, y se
  deja eso más un aire mínimo, así no se corta ni desperdicia mapa (sin la
  grilla de grados el margen desaparece; en Lambert no se reserva lugar para
  meridianos que no caen a la izquierda). Con la grilla
  de 5° los rótulos van cada 5° (antes sólo cada 10°); con 1° siguen cada 5°,
  nunca cada grado.
- GFS: la última corrida se calcula con 3,5 h de demora en vez de 4,5 (NOMADS
  publica los primeros plazos a esa hora): a las 15:33Z el diálogo ofrece la
  12Z, no la 06Z. Un plazo largo pedido demasiado temprano sigue avisando
  «todavía no publicado» y sugiere la corrida anterior.
- Build de macOS: el instalador ya no deja registradas en Launch Services las
  copias de `dist/` ni del DMG temporal, que el Finder listaba en «Abrir con»
  como versiones distintas de la app; el README pide expulsar el DMG tras
  instalar por el mismo motivo.

## 0.3.6 — 2026-10-20

- Preferencias ▸ Descarga: «Directorio de trabajo por defecto» (vacío =
  Documentos), con botón para elegirlo y aviso si la carpeta no existe. Es la
  carpeta inicial de «Obtener datos…» y de las exportaciones al arrancar. El
  directorio de trabajo ya no se guarda entre sesiones: al abrir un archivo
  (también desde el Finder, el gestor de archivos o la línea de comandos)
  pasa a ser la carpeta de ese archivo, y cambiar el por defecto sin archivo
  abierto rige de inmediato.

## 0.3.5 — 2026-10-20

- Diálogo de descarga: debajo de la grilla de niveles hay cuatro botones
  excluyentes, INDRA (14), OACI (17), OACI (56) y WAFS (56), que tildan los
  niveles que ese modo necesita y fijan el modo de conversión de esta
  descarga (arranca con el de Preferencias ▸ WAFS). INDRA y OACI sin
  «Convertir a WAFS» bajan los nominales del Anexo 3 tal cual, sin
  interpolar; con la casilla, o siempre en OACI56 y WAFS (56 FL que ningún
  modelo tiene: la casilla queda tildada y bloqueada), se baja el rango
  completo de la fuente (GFS: 850–70 cada 25 hPa) para interpolar cada FL
  entre dos capas cercanas, y los intermedios del GFS se encienden solos.
  Lo tildado a mano se suma; «Todos» y «Ninguno» salen del modo. Si se
  desmarca «Incluir niveles intermedios» los intermedios se destildan y
  deshabilitan, y al marcarla otra vez se vuelven a tildar los del modo. Una línea
  debajo dice qué se baja y qué sale, con los FL que quedan sin nivel. La
  casilla «Convertir a WAFS» y «Preferencias WAFS…» pasan del bloque
  Destino al de niveles. Desaparece «Los del visor».
- El diálogo de descarga agrupa sus campos en cuatro recuadros con título:
  Corrida y plazos; Variables y niveles (variables, grilla de niveles,
  botones de modo, «Incluir niveles intermedios», «Convertir a WAFS» y la
  línea descriptiva); Grilla y resolución (área y después las opciones de
  la fuente: resolución, regrillado, suavizado); Descarga y archivo. Los
  parámetros de cada fuente declaran a qué grupo van. Para que entre sin
  scroll en una pantalla de notebook: la descripción de la fuente va en el
  renglón del título; corrida, plazos y la cantidad de plazos (sin la
  lista) en un solo renglón; «Variables», «Niveles» y «Área» como rótulos a la izquierda de
  sus casillas; «Unir» y «Abrir» juntos; y abajo quedan sólo los botones (la
  barra de progreso y el estado aparecen al descargar). El área va en dos
  renglones, «Manual» con los cuatro campos y «Por FIR» con las casillas
  (código; nombre en el tooltip), Todas / Ninguna y el margen, y el modo
  que no está elegido queda grisado en vez de ocultarse; debajo,
  «Configurar áreas…», «Todo el globo», «Dominio del archivo abierto» y el
  tamaño. Las opciones de la fuente van en dos columnas (resolución y
  suavizado en un renglón, «bajar siempre 0,25°» debajo) con «Mostrar el
  área en el mapa» a la derecha.
- Lo deshabilitado se nota: texto bien atenuado y borde punteado en
  casillas, radios, botones, combos, campos numéricos y de texto, en toda
  la aplicación (antes el tema casi no los distinguía).
- El progreso de la descarga va en un diálogo modal centrado sobre el de
  descarga, con el mensaje del plazo, la barra y «Cancelar»; no se quita con
  Escape ni con el botón de la ventana y se cierra solo al terminar. El
  diálogo de descarga ya no cambia de tamaño al descargar.
- Al cambiar de fuente en el diálogo de descarga, el diálogo toma el alto
  de su contenido nuevo (crece al pasar de SMN al GFS y se achica al revés).
  Antes usaba `adjustSize()`, que Qt limita a dos tercios de la pantalla, y
  al volver a una fuente con más opciones las grillas quedaban aplastadas.

## 0.3.4 — 2026-10-19

- La ficha del clic muestra el perfil vertical de la celda en lugar de la
  tabla de tres capas y de la sección ARCHIVO: una fila por nivel del
  archivo, con la etiqueta, una barra con el color de la escala de
  velocidad del mapa (largo según los kt), la barba sobre una brújula con
  el norte arriba y los números (kt, ° y °M, °C); el FL pedido se intercala
  interpolado y resaltado. Con muchos niveles las filas se achican para
  entrar en el mapa. La consulta funciona también en modo presión (arranca
  con el FL del nivel elegido) y `Copiar` agrega el perfil entero.
- Escala de colores del viento continua: el color se interpola entre los
  anclajes con sentido operativo (0 azul oscuro, 30 celeste, 60 verde
  —umbral de jet—, 90 amarillo, 120 naranja, 150 rojo, 200+ granate) en
  vez de saltar cada 10 kt, en barbas, flechas, curvas, fondo de velocidad
  y el perfil de la ficha. La leyenda del mapa pasa a ser una franja
  vertical con el gradiente y marcas en los anclajes, sin cuadros por tramo.
- Las flechas (vectores) pasan a ser un asta de cuatro píxeles con punta
  triangular, en vez de las cuñas gordas que tapaban la dirección.

## 0.3.3 — 2026-10-16

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
