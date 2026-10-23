# Plan de pruebas manual – Visor GRIB 0.5.2 (PyQt6)

Entorno: pyenv `Grib` (Python 3.14.3), macOS. Antes de empezar:

```bash
cd /ruta/al/proyecto
python -c "import PyQt6, eccodes, cartopy, matplotlib; print('ok')"
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -p "test_*.py"   # debe terminar en OK
```

Archivo de prueba: un GRIB2 de GFS con 3 pasos, u/v/t y niveles de presión
(por ejemplo `tests/data/FDP_MULTI.grib2`; al abrirlo el visor lo convierte a
WAFS, ver sección O). Marcar cada caso como OK / FALLA y anotar el
detalle.

## A. Arranque y ventana

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| A1 | Arranque vacío | `python main.py` | Ventana translúcida con desenfoque, menú Archivo / Vista / Ayuda, barra de acciones con `Abrir GRIB…` y `⚙`, bienvenida con título, botón y "No hay archivos recientes". |
| A2 | Nombre en la barra de menú | Mirar la barra de menú de macOS | Dice "Visor GRIB", no "Python". |
| A3 | Geometría persistida | Mover y redimensionar la ventana, cerrar con ⌘Q, volver a abrir | Se abre en la misma posición y tamaño. |
| A4 | Arranque con archivo | `python main.py FDP_MULTI.grib2` | Abre directamente el mapa con el primer paso y F300. |
| A5 | Errores a log | Provocar un error (p. ej. renombrar el archivo abierto y exportar CSV) | Aparece un diálogo de error, la app sigue viva y `errores.log` (junto a `config.json`) registra la traza. |

## B. Apertura de archivos

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| B1 | Abrir desde la bienvenida | Clic en `Abrir GRIB…`, elegir el archivo | Diálogo con filtro `*.grib2 *.grb2 *.grib *.grb`; al aceptar aparece el mapa, el panel y el inventario; título "archivo — Visor GRIB". |
| B2 | Abrir con ⌘O | Con un archivo abierto, ⌘O y elegir otro | Reemplaza el archivo; controles repoblados; STATUS actualizado. |
| B3 | Recientes en bienvenida | Cerrar archivo (⌘W) | Bienvenida con el archivo en "Archivos recientes"; clic lo vuelve a abrir. |
| B4 | Recientes en el menú | Archivo ▸ Recientes | Lista con el archivo; "Vaciar lista" la limpia. |
| B5 | Reciente faltante | Mover el archivo y abrirlo desde Recientes | Aviso "Archivo no encontrado" y se elimina de la lista. |
| B6 | Archivo inválido | Abrir un archivo que no es GRIB | Diálogo "Error al abrir el archivo"; la app sigue en el estado anterior. |
| B7 | Archivo sin U/V | Abrir un GRIB sólo con TMP | Aviso "Sin viento"; VARIABLE queda en Temperatura; el mapa muestra contornos. |
| B8 | Doble clic en el Finder (app empaquetada) | `scripts/build.sh`, instalar, doble clic en un `.grib2` | La app abre con ese archivo. |
| B9 | Viento como dirección y velocidad | Abrir un GRIB bajado con «Viento en el archivo: dirección y velocidad» (`…_dirvel.grib2`), con ecCodes y con wgrib2 | Abre igual que su gemelo en U/V: mismas barbas, STATUS y ficha del punto; el inventario dice `VARIABLES: UGRD (u), VGRD (v), TMP (t)` y `VIENTO: dirección y velocidad (WDIR/WIND); se combinan en U/V al leer`; FUENTE agrega `viento: dirección y velocidad (WDIR/WIND)`; `wgrib2 -s` lista `WDIR` y `WIND` en vez de `UGRD` y `VGRD`. |

## C. Inventario y STATUS

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| C1 | Inventario | Leer el panel INVENTARIO | Corrida, pasos con validez y ventana, variables, niveles, grilla (Ni/Nj, primer y último punto, incremento) y mensajes no usados. |
| C2 | STATUS | Con el primer paso y F300 | RUN, STEP `[0]`, `VALIDITY [hh:mm–hh:mm] UTC` y `LOCAL [...]` con la zona horaria del sistema, `LEVEL: F300 = 300.9 hPa (ISA)` e "interpolado en ln(p) entre …". |
| C3 | Hora local | Comparar LOCAL con UTC | Diferencia igual al huso del sistema (p. ej. −03). |

## D. TIME

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| D1 | Radios | Clic en `Next (+1)` y `Advanced (+2)` | El mapa se redibuja solo; STEP y VALIDITY cambian; al lado de cada radio se ve su hora de validez. |
| D2 | Menos de tres pasos | Abrir un archivo con 1 o 2 pasos | Los radios sin paso quedan deshabilitados con "--". |
| D3 | Más de tres pasos | Abrir un archivo con 4+ pasos | Aparece el combo "Todos los pasos"; elegir el 4.° destilda los radios y redibuja. |

## E. LEVEL

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| E1 | Botonera fija | Abrir cualquier archivo | Siempre los mismos 17 botones en cuatro columnas: F050 F080 F100 F140 / F180 F210 F240 F270 / F300 F320 F340 F360 / F390 F410 F450 F480 / F530 y, a su derecha en la misma fila, la lista «Otros FL» (tooltip «Otros FL del archivo: …»); con `tests/data/FDP_MULTI.grib2` (INDRA) F080, F210 y F480 quedan grises y la lista «Otros FL del archivo» dice «(ninguno: todos tienen botón)» inactiva; con un crudo cuyo nivel más alto sea 200 hPa, F450, F480 y F530 quedan grises (no se extrapola). |
| E2 | Botón FL | Clic en F100 | Botón resaltado; redibuja; el FL activo muestra `F100 · etiqueta 700 hPa · 696.8 hPa ISA` seguido de `(nivel exacto, modo …)` o `(interpolado en ln(p))`; STATUS lo repite. |
| E3 | Lista de otros FL | Abrir `tests/data/WAFS_like_test.grib2`; desplegar «Otros FL del archivo» | 32 entradas `FL060 · 812 hPa … FL520`; elegir FL060 deselecciona la botonera y muestra `F060 · etiqueta 800 hPa · 812.0 hPa ISA (nivel exacto, modo WAFS)`; hacer clic en F300 vuelve la lista a «(el FL del botón elegido)». |
| E4 | Nivel del archivo sin interpolar | Con un GFS crudo, al final de «Otros FL» elegir `700 hPa (nivel del archivo)` | Ningún FL queda marcado; STATUS «700 hPa (nivel del archivo, sin interpolar)»; el mapa muestra el nivel exacto. |
| E5 | Verificación wgrib2 | README, sección "Verificación con wgrib2" | Valores de u, v, T en 700 mb coinciden con la barra de estado / CSV. |
| E6 | Archivo INDRA | Abrir `tests/data/FDP_MULTI.grib2` | No se crea `_wafs.grib2`; inventario `FORMATO: etiquetado por FL, modo INDRA`; FUENTE `WAFS FL050–FL530 · modo INDRA`; STATUS `F300 = 30090 Pa ISA (nivel exacto, modo INDRA, etiqueta 300 hPa)`. |
| E7 | Muestra OACI del servidor | Abrir `tests/data/WAFS_oaci_test.grib2` (generada por `gfs_wafs/gfs_to_wafs.py --niveles oaci`) | No se convierte; los 17 botones activos y la lista inactiva; inventario `FORMATO: etiquetado por FL, modo OACI (etiqueta nominal en hPa): FL050–FL530, 17 niveles`; clic en F210 → `F210 · etiqueta 450 hPa · 446.5 hPa ISA (nivel exacto, modo OACI)`; `wgrib2 -s` coincide línea a línea con `tests/data/WAFS_oaci_test.grib2.idx`. |

## F. VARIABLE, VIENTO y MAPA

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| F1 | Viento | Radio Viento | Barbas en kt coloreadas por la escala continua (azul oscuro 0 → celeste 30 → verde 60 → amarillo 90 → naranja 120 → rojo 150 → granate 200 kt; dos barbas de velocidad parecida tienen color parecido), leyenda abajo a la izquierda: una franja vertical del gradiente (22 × 108 pt: unos 30 × 144 px a 96 dpi, el doble en retina) con el título «kt», marcas 0, 30, 60, 90, 120, 150, 200+ y margen dentro del recuadro (los números no pisan el borde, también en retina) (sin cuadritos por tramo), barbas invertidas en el hemisferio sur. |
| F2 | Temperatura | Radio Temperatura | Contornos cada 2 °C etiquetados; sin barbas ni leyenda. |
| F3 | Ambas | Radio Viento + Temp. | Barbas y contornos. |
| F4 | Extra Info | Marcar | `12 kt` junto a cada punto (y `−45 °C` con temperatura); los rótulos no se salen del mapa ni se pisan entre sí. |
| F4b | Rótulos configurables | Preferencias ▸ Mapa ▸ Rótulos: Tamaño 11, destildar «Mostrar unidades» ▸ Aplicar | Los números se ven más grandes y sin `kt`/`°C` (la temperatura queda `−45°`); persiste al reiniciar. |
| F5 | Grilla del archivo | Marcar `Grilla lat/lon del archivo` | Grilla fina punteada del dato (0,25°/0,50°/1°) además de la grilla de grados. |
| F5b | Grilla de grados | MAPA ▸ Grilla de grados ▸ 10° / 5° / 1° (o Vista ▸ Grilla de grados), en una pantalla Retina y con la fuente en 18 (⌘+ cinco veces), también en Lambert | 10°: líneas principales continuas, bien contrastadas, rotuladas en los bordes cada 10°. 5°: se suman secundarias a rayas cada 5° y los rótulos pasan a cada 5°. 1°: principales continuas cada 5° (10 y 5 iguales) y secundarias punteadas cada 1°, con rótulos cada 5° (nunca cada grado). Los rótulos de la izquierda se leen enteros («30°S», no «0°S») y entre el rótulo y el borde del mapa queda sólo un aire de pocos píxeles, también en Lambert y al cambiar la fuente; con Capas ▸ Grilla de grados apagada el mapa se pega al borde izquierdo e inferior. Persiste y el menú lo refleja. |
| F5c | Margen de inscripciones | Cualquier proyección, con y sin zoom | Las etiquetas de grados a la izquierda y abajo se ven enteras; nada las tapa. |
| F6 | Fondo de velocidad | Marcar | Relleno semitransparente con la misma escala continua, sombreado sin bandas ni costuras entre celdas; también en estereográfica. |
| F7 | Densidad | Poner 2 y 3 | Barbas cada 2 / 3 puntos; redibuja al cambiar. |
| F7b | Zoom out con barbas | Alejar con la rueda hasta ver todo el continente | Las barbas se achican y afinan antes de ralearse; con curvas, las líneas y sus flechas se afinan. |
| F11 | Flechas | VIENTO ▸ Estilo ▸ Flechas (vectores) (o Vista ▸ Viento) | Flechas (asta de ~4 px con punta triangular, no cuñas gordas) de largo fijo que apuntan hacia donde sopla el viento, color de la escala continua, sin flecha en calma; se rotan en estereográfica; al alejar primero se acortan y afinan (hasta la mitad) y recién después se ralean; al acercar recuperan el tamaño; Densidad las ralea más; Extra Info sigue rotulando. |
| F12 | Curvas | VIENTO ▸ Estilo ▸ Curvas (líneas de corriente) | Líneas de corriente continuas con varias flechas de sentido por línea, coloreadas por velocidad; al pasar a Barbas o Flechas y volver no queda ninguna flecha suelta; en estereográfica siguen la proyección; Densidad 4 muestra menos líneas; al hacer zoom se recalculan sobre la vista; el PNG las incluye. |
| F13 | Estilo persistente | Elegir Curvas, reiniciar; Preferencias ▸ Mapa ▸ Viento = Barbas ▸ Aplicar | Arranca en Curvas; Preferencias cambia el panel, el menú Vista y el mapa. |
| F8 | Actualizar | Clic en `Actualizar` (barra de acciones) | Redibuja sin cambiar nada (también F5 y Vista ▸ Actualizar). |
| F9 | Ocultar / Mostrar capa | `Capas` ▸ destildar «GRIB (viento / temperatura)» (o ⌘D) | Sólo mapa base, "Capa de datos deshabilitada" en el mapa y en STATUS; Vista ▸ "Capa de datos desactivada"; ⌘D alterna y el menú Capas lo refleja. |
| F10 | Menú Capas | `Capas` ▸ apagar y prender una por una: Marco del GRIB, Fondo de velocidad, Extra Info, Costas y fronteras, Grilla de grados, Grilla del archivo, Límites de FIR, Working Areas | Cada capa desaparece y vuelve sin afectar a las demás; las casillas del panel (Fondo, Extra Info, + la del archivo, FIR, WA) y Vista ▸ FIR se actualizan; sin costas ni grilla de grados queda el fondo liso con el viento; persiste tras reiniciar (`map_coast`, `map_graticule`). |
| F14 | Menú Vista sincronizado | Vista ▸ Extra Info; luego destildar Extra Info en el panel; Vista ▸ Proyección ▸ Mercator | La casilla del panel sigue al menú y viceversa; el combo Proyección del panel pasa a Mercator y el mapa cambia. |
| F16 | Panel sin scroll | Ventana por defecto (1600×1000) y también con ⌘+ hasta fuente 18 | El panel no tiene barra de scroll propia; sólo el INVENTARIO (alto restante) se desplaza por dentro, vertical y horizontal; LEVEL tiene 17 botones (F050…F530, con F210) en cuatro columnas, F530 solo en la quinta fila con la lista «Otros FL» al lado; ningún texto largo de la lista ensancha el panel. |
| F19 | Barra de acciones | Mirar la barra | Botones del mismo alto en tres grupos (datos / mapa / salida) separados con aire, sin líneas; «Fuente» y su selector forman un solo control con borde. |
| F20 | STATUS fijo | ⌘+ varias veces | La franja STATUS y la barra inferior conservan su tamaño de letra; el panel y los menús sí crecen. |
| F21 | Márgenes del mapa | Abrir un archivo; Guardar PNG | En pantalla el mapa llega casi al borde de su tarjeta (sin título ni franjas vacías arriba, a la izquierda ni abajo); el PNG exportado sí lleva el título arriba. |
| F17 | Ocultar panel | Clic en `▥` (barra de acciones) o ⌘⇧P | El panel desaparece y el mapa ocupa todo el ancho; el botón y Vista ▸ Panel lateral quedan destildados; al reiniciar sigue oculto; volver a clic lo muestra. |
| F18 | Contraste | Mirar botones, combos, campos y tarjetas del panel | Tienen borde visible sobre el fondo; las líneas entre grupos se distinguen del fondo de la ventana. |
| F15 | Panel sin recortes | Preferencias ▸ Apariencia ▸ tamaño de fuente 18; abrir un archivo ECMWF (nombre largo) | Ningún botón, combo ni campo queda fuera del panel; los combos recortan el texto largo con «…» y el desplegable lo muestra entero; STATUS va en la franja sobre el mapa. |

## G. Mapa, zoom y recuadro

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| G1 | Zoom con rueda | Girar la rueda sobre el mapa | Acerca / aleja alrededor del cursor un 20 % por muesca; en el trackpad un gesto corto acerca poco y uno largo no pasa de una muesca por evento (ya no se va de golpe). |
| G21 | Rueda fina | Girar la rueda con ⌘ (o Shift) apretado | Acerca / aleja un 4 % por muesca (20 % ÷ 5), alrededor del cursor. |
| G22 | Arrastre fino | Arrastrar el mapa con ⌘ (o Shift) apretado desde el inicio del arrastre | El mapa se mueve la quinta parte del recorrido del mouse; soltar la tecla a mitad del arrastre no cambia el modo hasta el próximo arrastre. |
| G23 | Botones ± | Botones `+` y `−` de la barra, Vista ▸ Acercar / Alejar (fino), ⌘⌥= / ⌘⌥− | Paso fino (4 %) alrededor del centro de la vista; con Alt + clic, paso normal (20 %); sin archivo abierto no hacen nada. |
| G24 | Preferencias de zoom | Preferencias ▸ Mapa ▸ Rueda 10 %, Modo fino ÷ 10 ▸ Aplicar | La rueda pasa a 10 % y el modo fino a 1 %; el arrastre fino se mueve un décimo; queda en `config.json` (`map_zoom_step`, `map_fine_divisor`). |
| G2 | Pan por arrastre | Arrastrar el mapa con el botón izquierdo | Cursor de mano abierta sobre el mapa, cerrada al arrastrar; el mapa sigue al mouse. |
| G19 | El mapa llena el área | Abrir un archivo, redimensionar la ventana, aplicar un recuadro | No quedan franjas vacías a los costados ni arriba/abajo: la vista se amplía para ocupar todo el canvas y el dominio sigue completo. |
| G3 | Inicio | Tras zoom, clic en `Inicio` | Vuelve a la vista inicial. |
| G4 | Recuadro | Escribir lat/lon mín/máx y Enter (o "Aplicar recuadro") | La vista se ajusta; con valores inválidos aparece un aviso. |
| G5 | Recuadro sincronizado | Hacer zoom con el mouse | Los campos lat/lon reflejan la vista actual. |
| G6 | Todo el dominio | Botón o ⌘⇧0 | Vuelve a la grilla completa. |
| G7 | Cambio de nivel con zoom | Hacer zoom y cambiar de FL, paso, variable, Extra Info, grilla o densidad | La vista se mantiene en todos los casos. |
| G15 | Rueda del mouse | Girar la rueda sobre el mapa | Acerca/aleja alrededor del cursor; `Inicio` vuelve a la vista completa. |
| G20 | Velocidad al cambiar de capa | Archivo GFS 0,25° de una zona grande; cambiar de FL con barbas, con Extra Info, con curvas y en estereográfica | Cada cambio se dibuja en menos de medio segundo en todos los casos; con Extra Info los rótulos aparecen junto con las barbas (son una sola colección). |
| G16 | Fluidez del pan | Densidad 1 + Extra Info + grilla, arrastrar el mapa | El mapa sigue al mouse sin trabarse; los rótulos y las etiquetas de la grilla desaparecen durante el arrastre y vuelven al soltar (≈0,2 s). |
| G17 | Raleo automático | Vista completa con densidad 1 | Barbas y rótulos raleados pero legibles; al acercar aparecen todos los puntos; el cambio no "salta" entre vistas. |
| G18 | Fluidez en proyecciones | Repetir G16 en estereográfica | Mismo comportamiento. |
| G8 | Hover | Mover el mouse sobre el mapa | La barra inferior muestra lat/lon, punto de grilla, viento kt / dirección y T °C; fuera de la grilla sólo lat/lon. |
| G25 | Ficha del punto | Abrir `tests/data/WAFS_oaci_test.grib2`; clic (sin arrastrar) cerca de 31°25'S 64°11'W | Junto al mouse, sobre el mapa, la ficha con el tema: PUNTO con una fila Geodésico `3125S06411W`, Hora UTC `2610140000` (validez del paso Current; se pueden tipear los 10 dígitos) y FL 300 (el del panel); origen de celda `3200S06500W (-32.00, -65.00)` (esquina SO de la celda de 1°, convención del FDP) y el paso; debajo el perfil vertical de la celda: 17 filas de F530 a F050 con la etiqueta, la barra pintada con el color de la escala continua de velocidad (el mismo de la barba de ese punto en el mapa; largo según los kt, llena a 200), la barba sobre una brújula (norte arriba; barbas hacia el sur, hemisferio sur) y `NN kt  DDD°  -NN.N °C`; la fila F300 resaltada con el acento y en negrita, y debajo «F300 = 300.9 hPa ISA · nivel exacto del archivo». No hay sección ARCHIVO ni otra ventana de consulta: el clic derecho no hace nada. |
| G26 | Cualquier FL y hora, ahí mismo | En la ficha escribir FL 310 y hora `2610140930`; después `2610142000` | Los campos se editan en la ficha (toman el foco con un clic; ese clic no cierra la ficha, no mueve el mapa ni abre otra; un clic en una parte de la ficha que no es campo no hace nada). Con 310: una fila `F310` resaltada entre F320 y F300 con el valor intermedio, y debajo «F310 = 287.4 hPa ISA · interpolado en ln(p) entre 300 hPa (F300, 300.9 hPa ISA) y 275 hPa (F320, 274.5 hPa ISA) (peso 0.50)»; la hora 09:30 elige `paso [2] +12 h  06:00 14/10 UTC  (fuera de las ventanas: el más cercano)` y 20:00 también el más cercano; una hora mal escrita (`261014`) dice «hora inválida» y vacía las filas. FL 20 → fila `F020` resaltada abajo de todo con el valor de F050 y «fuera del rango…capa más cercana (850 hPa (F050…))»; FL 600 → fila `F600` arriba de todo con el valor de F530. |
| G27 | Copiar | `Copiar` y pegar en un editor | El texto pegado empieza con `Geodésico (grados y minutos): 3125S06411W`, `Hora de sobrevuelo (YYMMDDHHMM): …`, `Nivel de sobrevuelo (banda, sin F): 310`, `Step: [n] +h h  validez …  (ventana …)`, `Origen de celda: …` las tres capas con `Viento (kt / grados)` y `Temperatura (°C)` y al final `Perfil de la celda (de arriba hacia abajo):` con una línea por nivel. Con norte magnético (WA con tangencia y variación) el viento agrega `(DDD°M)`. |
| G28 | Cierre, otro clic y ⌘ I | Escape; clic en otro lugar del mapa; clic afuera de la ficha; escribir `0500S03600W` en Geodésico; Archivo ▸ Cerrar archivo; Vista ▸ Consultar punto… (⌘ I) | Escape cierra la ficha. Un clic en otro lugar la abre ahí con el paso y el FL del panel. Con la ficha abierta, un clic afuera (mapa o panel) sólo la cierra: no abre otra ni mueve el mapa; el clic siguiente sí la abre. El punto escrito a mano se consulta al completar los 11 caracteres. Al cerrar el archivo la ficha desaparece; ⌘ I la muestra en el centro del mapa con «Sin archivo abierto»; abrir otro archivo y ⌘ I la rellena en el último punto. |
| G29 | Ficha con FIR | Con la capa FIR activa, clic (sin arrastrar) dentro de Córdoba; con un GFS crudo en modo presión, otro clic | La ficha agrega la sección FIR (`FIR Córdoba (SACF): N -21.72° …`, cobertura, fuente) y la primera línea va a la barra de estado; sin FIR debajo no hay sección FIR. Con el GFS crudo en modo presión (p. ej. 300 hPa) la ficha es la misma consulta: FL 300 (el FL de ese nivel), filas `NNN hPa` por cada nivel del archivo (41 o más: filas finas, números cada tantas filas y siempre el del FL pedido, la columna de colores entera) y `F300` intercalada. Con un archivo de superficie, PUNTO muestra el nodo más cercano con viento y T, sin campos ni `Copiar`. |
| G30 | Ficha tras un punto sin datos | Con un WAFS de 56 FL y la ventana no muy alta: clic fuera de la grilla del archivo (ficha «origen de celda: fuera de la grilla», sin perfil), clic en el mapa para cerrarla, y clic en un punto con datos | La ficha del punto con datos queda igual que la de un primer clic: el perfil con las 56 filas comprimidas y la ficha entera dentro del mapa, sin filas estiradas ni cortadas abajo. |
| G9 | Sin cartopy | Desinstalar cartopy temporalmente (`pip uninstall cartopy`) | El mapa se dibuja sin costas con el aviso; Acerca de lo indica. Reinstalar después. |
| G11 | Proyección estereográfica | CONFIG ▸ Proyección ▸ "Estereográfica conforme (centro del dominio)" | El mapa se redibuja con meridianos convergentes, barbas rotadas, etiquetas de lat/lon en los bordes; el hover sigue mostrando lat/lon correctos; zoom, pan, Inicio y recuadro funcionan. |
| G12 | Resto de proyecciones | Elegir polar sur, polar norte, Mercator y Lambert | Todas dibujan sin error; Lambert con un dominio ecuatorial también. |
| G13 | Proyección persistida | Elegir estereográfica, cerrar y reabrir la app | Arranca con la proyección elegida. |
| G14 | Grilla visible | Marcar `Grilla lat/lon del archivo` con opacidad alta y baja | Meridianos/paralelos cada 10° en línea continua y la grilla del archivo punteada, ambas visibles sobre el fondo. |
| G10 | Sin red la primera vez | Borrar `~/.local/share/cartopy` y abrir sin conexión | Aviso "No se pudieron cargar las costas"; el mapa igual se dibuja. |

## P. Límites de FIR

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| P1 | Activar la capa | Abrir un GFS de Sudamérica; marcar `FIR Argentina` en MAPA (o ⌘⇧F, o Vista ▸ FIR) | Contornos lavanda de SARR, SACF, SAMF, SAEF y SAVF con etiqueta nombre + código dentro de cada polígono; casilla, menú y `config.json` (`fir_enabled`) sincronizados; el viento se sigue viendo por encima. |
| P2 | Vecinas | Marcar `+ vecinas` | Montevideo, Asunción, La Paz, Santiago, Punta Arenas, Curitiba, Brasilia, Atlántico y Johannesburgo Oceánico en gris a rayas, etiquetas más chicas; `+ vecinas` se deshabilita si se apaga `FIR Argentina`. |
| P3 | Polo y sector oceánico | Con la capa activa, elegir cada proyección (Lat/Lon, estereográfica, polar sur, polar norte, Mercator, Lambert) y alejar la vista | SAVF llega a 90° S y SAEF/SAVF a 10° W sin trazos cruzados ni líneas disparadas; en Mercator el borde polar simplemente se corta; el contorno se recorta a la vista. |
| P4 | Fluidez | Capa activa + vecinas + Extra Info; arrastrar y hacer zoom; cambiar de FL | Igual de fluido que sin la capa (G16/G20); la capa no se reconstruye al cambiar de nivel (sólo al cambiar proyección, selección o estilo). |
| P5 | Hover | Mover el mouse dentro de Ezeiza y luego sobre el límite Ezeiza/Comodoro | Barra de estado: `… \| FIR Ezeiza (SAEF)`; sobre el contorno agrega `\| límite SAEF · SAVF`. |
| P6 | Clic | Clic (sin arrastrar) dentro de Córdoba | Barra de estado y tooltip: `FIR Córdoba (SACF): N −21.72° S −34.03° E −60.20° O −69.65° · la grilla cubre la FIR completa · …`; arrastrar no dispara el tooltip. |
| P7 | Diálogo Regiones | `FIR…` ▸ Regiones: destildar SAVF, color rojo, relleno 25 %, etiqueta 12 ▸ Aplicar | Comodoro desaparece; las demás en rojo con relleno; etiquetas más grandes; `Estilo por defecto` vuelve al lavanda. Persisten tras reiniciar. |
| P8 | Extremos y cobertura | `FIR…` ▸ Extremos (o Vista ▸ FIR ▸ Extremos y cobertura…) | Tabla con N/S/E/O, vértices, fuente y cobertura: con un GFS 4N–64S / 90W–22W las argentinas continentales dan `completa`, SAEF/SAVF `parcial`, FAJO `ninguna`; sin archivo abierto, "—". |
| P9 | Descargar VATSpy | `FIR…` ▸ Datos ▸ `Descargar límites de FIR (VATSpy)` | Progreso en MB, `Cancelar descarga` corta; al terminar "VATSpy: 14 FIR guardadas en fir_vatspy.geojson"; el rótulo pasa de "copia incluida" a "Descargado: 14 FIR, fecha"; el aviso de no oficial está a la vista. Sin red: error claro. |
| P10 | openAIP | Preferencias ▸ Fuentes ▸ openAIP ▸ `Configurar…` ▸ Token = clave ▸ Guardar ▸ `Probar conexión`; luego `FIR…` ▸ Datos ▸ `Descargar de openAIP` | `Conexión OK: openAIP responde: N FIR/UIR del país AR` (o "no tiene FIR del país AR"); la clave se ve enmascarada y no está en `config.json`; `Borrar` la quita. Con clave, la descarga guarda `fir_openaip.geojson` y la fuente preferida pasa a openAIP. **No verificado por falta de clave.** |
| P11 | Convertir AIP | `FIR…` ▸ Datos ▸ `Convertir texto del AIP…`, pegar los vértices de ENR 2.1 de SAVF (con "a lo largo del límite internacional…"), Convertir | Informe con la cantidad de vértices y los tramos pendientes; `Guardar GeoJSON…` escribe el archivo y, con la casilla marcada, lo deja como archivo propio: SAVF pasa a "AIP … (oficial)" en Regiones y Extremos; las demás siguen de VATSpy. |
| P12 | Archivo propio KML/SHP | `Cargar archivo propio…` con un KML o un .shp con el código en el nombre o en un campo `ICAO` | Se lee, se copia a la carpeta de datos y reemplaza esas FIR; `Quitar` vuelve a las fuentes descargadas. Un archivo sin códigos reconocibles da un aviso. |
| P13 | PNG | Exportar PNG con la capa activa | El PNG incluye los límites y etiquetas. |
| P14 | FIR de a una | Capa apagada; Vista ▸ FIR ▸ FIR a mostrar ▸ tildar `SAEF Ezeiza` | Se enciende la capa y se ve sólo Ezeiza (casilla `FIR Argentina` tildada); tildar `SACF` la suma; tildar `SUEO` enciende `+ vecinas` y la suma; destildar `SAEF` la quita; `Ninguna` deja el mapa sin FIR; `Todas` muestra las 14 y `Sólo Argentina` las 5. La lista de `FIR…` ▸ Regiones refleja lo mismo. |
| P15 | Cargar una WA | `FIR…` ▸ Working Area ▸ `Agregar WA`; código SAEF, tangencia 34°48'S 058°30'W, vértice SO 42°S 066°W, 700 × 700 NM; `Radio conforme WGS84 en la tangencia` ▸ Aplicar | El radio pasa a ≈ 6370.6 km; abajo aparece «Esquinas: SAEF: 700 × 700 NM, SO −42.0000° −66.0000°, NE …»; con ancho 0 o radio fuera de 6000–6500 Aplicar avisa y no cierra; tras aplicar, `config.json` tiene `working_areas` con la fila. |
| P16 | Mostrar la WA | Con SAEF mostrada, marcar `WA` en MAPA (o Vista ▸ FIR ▸ Working Area de las FIR mostradas) | Cuadrado amarillo a rayas y puntos con rótulo `WA SAEF` en el vértice SO, además del contorno lavanda; el viento sigue por encima. Destildar SAEF en «FIR a mostrar» quita también su WA; destildar `WA` quita todas. En estereográfica los lados se ven rectos; en Lat/Lon, apenas curvos. |
| P17 | WA deshabilitada y varias | Agregar WA de SACF; destildar `Activa` en la de SAEF; mostrar ambas FIR con `WA` marcada | Sólo se dibuja la WA de SACF; `Borrar` quita la fila elegida; el estilo (color, grosor, etiqueta) se aplica a todas las WA. |
| P18 | Variación magnética | En la WA de SAEF escribir `10W` en `Var. mag.` (también probar `6°55'E`, `-10`, `abc`) | Queda `-10.0` (con convención este positivo); `6°55'E` → `+6.9`; `abc` da aviso y bloquea Aplicar; en el mapa el cuadrado de SAEF aparece girado: su lado «norte» apunta 10° a la izquierda del norte verdadero. Con Preferencias ▸ Mapa ▸ convención oeste positivo, la celda muestra `+10.0` y `7` se entiende como 7° W. |
| P19 | Tangencia | Marcar `Tangencia` en SAEF, luego en SACF | Al marcar SACF se desmarca SAEF sola. Con SAEF marcada aparecen habilitadas «Estereográfica conforme (tangente a WA SAEF)» y «Lambert conforme (tangente a WA SAEF)» en el combo, en Vista ▸ Proyección y en Preferencias; al elegir la estereográfica tangente la barra de estado describe punto, radio y «norte magnético arriba (variación 10.0°W)», el cuadrado de SAEF se ve derecho con lados rectos, costas y FIR giradas 10°, y el cursor muestra `… / 304.8° (314.8°M)`. «Estereográfica conforme (centro del dominio)» sigue sin girar. Desmarcar la tangencia grisa las dos variantes y, si estaba en uso una, el mapa pasa solo a la del centro del dominio (aviso en la barra de estado). Destildar `WA` en el panel o `Activa` en la hoja sólo esconde el cuadrado. |
| P20 | Tangencia sin WA válida | Marcar `Tangencia` en una fila con ancho 0 | Aplicar la rechaza; si se fuerza en `config.json`, el mapa usa el centro del dominio y la barra de estado no menciona tangencia. |
| P21 | Lambert tangente | Con la tangencia en SAEF, elegir *Lambert conforme (tangente a WA SAEF)* | La barra de estado dice «Lambert conforme centrada en la WA SAEF … norte verdadero arriba», el mapa no gira (el cuadrado de SAEF se ve girado por su variación), el cursor no muestra °M; *Lambert conforme (centro del dominio)* sigue igual que antes. Mercator y las polares no cambian. |

## Q. Áreas de descarga por FIR

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| Q1 | Tabla precargada | `⚙` ▸ Áreas / FIR | Cinco filas SARR/SACF/SAMF/SAEF/SAVF con los valores iniciales, *Habilitada* y *A verificar* tildadas (tooltip "a verificar contra AIP ENR 2.1"); margen 1,00°; formato decimal. |
| Q1b | Botón Límites de FIR | `⚙` ▸ Áreas / FIR ▸ «Límites de FIR y Working Areas…» | Se abre la ventana «Límites de FIR» (Regiones, Extremos, Datos, Working Area) sobre Preferencias; al aplicarla, el mapa se actualiza igual que desde Vista ▸ FIR, y Preferencias sigue abierta. |
| Q2 | Editar coordenadas | Escribir `22°15'S` en Lat norte de SARR; luego `xx`; luego `-10` en Lat sur | Se muestra `-22.25`; `xx` vuelve al valor anterior con aviso "Coordenada inválida"; con sur > norte aparece el aviso "la latitud norte … debe ser mayor que la sur" y `Aplicar` no cierra (vuelve a la pestaña). |
| Q3 | Formato grados-minutos | Formato = "Grados y minutos con hemisferio" | Toda la tabla pasa a `22°15.0'S`, `062°40.2'W`; el diálogo de descarga muestra los campos en ese formato. |
| Q4 | Agregar / borrar | `Agregar área`, código `sueo`, nombre Montevideo, límites; `Borrar` | El código queda `SUEO`; aparece como casilla en el diálogo de descarga; al borrar desaparece. `Las cinco FIR por defecto` restaura las cinco y conserva las demás. |
| Q5 | Exportar / importar | `Exportar tabla…` (JSON y CSV), modificar una fila, `Importar tabla…` | Los archivos se escriben; al importar vuelve la tabla exportada (y el margen del JSON); un CSV con norte < sur se rechaza con el detalle. |
| Q6 | Modo por FIR | `Obtener datos…`, bloque Área, `Por FIR`; marcar sólo SAEF; luego SAEF + SACF | Campos bloqueados: SAEF sola → N −29.22 S −47.00 W −72.85 E −9.00 (caja + 1°); SAEF + SACF → N −20.72 S −47.00 W −72.85 E −9.00. Debajo: Δlat/Δlon, puntos a la resolución elegida y MB estimados; `Todas` / `Ninguna` funcionan; con ninguna marcada `Descargar` avisa. |
| Q7 | Pasar a manual | Con SAEF + SACF marcadas, `Manual` | Los cuatro campos se copian y se habilitan; se pueden retocar (también en grados-minutos); `Todo el globo` y `Dominio del archivo abierto` aparecen sólo en manual. |
| Q8 | Memoria | Cerrar el diálogo sin bajar y reabrir | Mismo modo, mismas casillas, misma zona manual y margen. |
| Q9 | Descarga por FIR (red) | GFS 0,25°, `Por FIR` SAEF + SACF, un plazo, `Descargar` | URL de NOMADS con `toplat=-20.5 bottomlat=-47 leftlon=-73 rightlon=-9` (redondeo hacia afuera a 0,25°); archivo `gfs_…_0p25_SACF+SAEF_wafs.grib2`; `.json` con bloque `area` (`etiqueta`, `codigos`, `margen_deg`, `zona_pedida`, `zona_servidor`, `zona_obtenida`, `cubre: true`); STATUS `… · área SACF+SAEF`. |
| Q10 | Polo y Greenwich (red) | Marcar SAVF (llega a −90); luego manual N 11 S −11 W −21 E 16 con ECMWF | El pedido lleva `bottomlat=-90`; el archivo llega al polo y se dibuja en estereográfica sur. Con ECMWF (grilla 0…360) el recorte local devuelve lon −21…16 contiguas; el mapa no muestra costura en Greenwich. |
| Q11 | Grilla más chica que lo pedido | Fuente genérica con un GRIB regional más chico que el área | Aviso "La grilla obtenida es más chica que la zona pedida … lados que faltan"; STATUS `área … (incompleta)`; `.json` con `cubre: false`. |
| Q12 | Rectángulos en el mapa | `Mostrar el área en el mapa` (o Vista ▸ FIR ▸ Rectángulos del área de descarga) con la capa FIR activa | Rectángulo naranja de la envolvente (con margen) y a rayas el de cada FIR marcada con su código, sobre los contornos de FIR; en manual sólo la envolvente; se ve en las seis proyecciones; el PNG lo incluye. |
| Q13 | Extremos de la capa FIR | Seleccionar la fila SAEF ▸ `Extremos de la capa FIR` | Toma N/S/W/E del polígono de la capa (VATSpy) y deja *A verificar* tildada. |
| Q14 | El marco sigue al archivo | Con «Rectángulos del área de descarga» activos: bajar con SAEF+SACF, luego abrir un archivo local sin procedencia, luego otro bajado con SAVF, luego cerrar | Tras la descarga, envolvente + rectángulos SAEF y SACF; al abrir el archivo local sólo el recuadro de su grilla (los rectángulos anteriores desaparecen); con el de SAVF, su envolvente y su rectángulo; al cerrar vuelve la última selección del bloque Área. |

## H. Exportar

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| H1 | PNG | `Guardar PNG` o ⌘E | Diálogo con nombre `archivo_pasoN_F300.png` en la última carpeta usada; el PNG reproduce la vista actual (zoom incluido). |
| H2 | CSV | ⌘⇧E | `archivo_pasoN_F300.csv` con cabeceras de comentario y columnas lat, lon, u_ms, v_ms, velocidad_kt, direccion_deg, t_c; una fila por punto de grilla. |
| H3 | CSV con nivel directo | Combo 700 hPa, exportar | Nombre `…_700hPa.csv` y "modo, nivel exacto" en la cabecera. |
| H4 | Sin archivo | Bienvenida, ⌘E | Las acciones de exportar están deshabilitadas. |
| H5 | Exportar a WAFS, un archivo por plazo | Con un archivo abierto, Archivo ▸ Exportar a WAFS… (⌘⇧W), Todos, Exportar | Un `gfs.tHHz.wafs_RES.fFFF.grib2` por plazo en la carpeta elegida, cada uno con su `.idx`; el mensaje final dice «Verificación OK», mensajes = variables × 49 niveles, sin avisos del validador. |
| H6 | Exportar selección y recorte | Sólo +6 h, rango FL300–FL340, Recortar a la zona, un único archivo | Un solo archivo con 3 variables × 5 niveles; `wgrib2 -s` muestra sólo `30090…25000 Pa`; la grilla es el recuadro pedido. |
| H7 | Exportar regrillando | Regrillar a 0,25° bilineal | Archivo `…wafs_0p25…` con incremento 0,25°; verificación OK (los puntos originales se conservan). |
| H8 | Exportar desde superficie | Abrir un archivo del SMN, ⌘⇧W | Aviso «El WAFS es un producto de altura…», no se exporta. |

## O. Formato WAFS

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| O1 | Descarga convertida | Obtener datos… con el GFS, botón `OACI (17)` y casilla «Convertir a WAFS» marcada (arranca como «Convertir a WAFS por defecto» de Preferencias ▸ WAFS; el botón, con el modo de Preferencias) | El archivo termina en `_wafs.grib2`; `wgrib2 -s` lista los 17 niveles nominales `850 mb, 750 mb, 700 mb, 600 mb, 500 mb, 450 mb, … 100 mb` por variable y plazo; el `.json` tiene `wafs.convertido: true`, `modo: OACI`, `fl_rango FL050–FL600` y 32 `niveles_origen_hpa`. Con el botón OACI (56), 56 niveles `850 mb, 800 mb, …, 60 mb`; con WAFS, `843.1 mb, 812 mb, …`; con INDRA, 14. El modo del `.json` es el del botón aunque Preferencias diga otro. |
| O1b | Descarga sin convertir | Obtener datos… con el GFS, botón `OACI (17)`, «Convertir a WAFS» desmarcada y «Abrir en el visor al terminar» marcada, con «Convertir también los archivos locales al abrirlos» activa en Preferencias | El archivo no lleva `_wafs`; `wgrib2 -s` lista los 17 nominales de NOAA tal cual (850, 750, …, 125, 100 mb), sin interpolar; se abre tal cual en modo presión (botonera con hPa, sin `_wafs.grib2` nuevo al lado). Al reabrirlo con Archivo ▸ Abrir sí se convierte (rige la preferencia). Con la fuente SMN WRF o WAFS la casilla queda inactiva. Al reabrir el diálogo, la casilla vuelve al valor de Preferencias. |
| O1c | Botón Preferencias WAFS | En el diálogo de descarga tocar «Preferencias WAFS…», desmarcar «Convertir a WAFS por defecto», elegir modo INDRA y Aplicar | Se abre «Preferencias · WAFS» encima del diálogo, con sólo la pestaña WAFS accesible (las otras seis grisadas); al volver, la casilla «Convertir a WAFS» del diálogo queda desmarcada, el botón INDRA queda elegido con sus 14 niveles y el nombre propuesto pierde `_wafs`. Cancelar no cambia nada. |
| O2 | Visor con WAFS | Abrir el archivo de O1 (y el de OACI56) | STATUS: `FUENTE … / WAFS FL050–FL530 · modo OACI (convertido)`; `LEVEL: F300 = 30090 Pa ISA (nivel exacto, modo OACI, etiqueta 300 hPa)`; los 17 botones activos y la lista inactiva; el inventario dice `FORMATO: etiquetado por FL, modo OACI`. Con el de OACI56 la lista «Otros FL del archivo» trae `FL060 · 800 hPa (812 ISA) …`. Cambiar de FL redibuja sin «interpolado entre». |
| O3 | Archivo local crudo convertido | Abrir un GFS con 1000 hPa en niveles de presión | Barra de estado «Convertido a WAFS: …_wafs.grib2»; junto al original aparecen `<nombre>_wafs.grib2`, `.json` e `.idx`; el visor muestra el convertido. Con «Convertir también los archivos locales» desmarcado, se abre el original e interpola. |
| O4 | Rango ampliado | Bajar ECMWF o ICON con niveles 1000 y 50 hPa, convertir | El rango llega a FL050–FL600 (con «ampliar» marcado; la tabla empieza en F050); sin marcarlo, FL050–FL530. |
| O5 | Extrapolar | Bajar sólo 700–300 hPa con «extrapolar» marcado | Hay 49 niveles; el `.json` lista `extrapolados`; sin marcar, sólo FL100–FL300 y `fl_omitidos`. |
| O6 | Ya etiquetado | Abrir `tests/data/WAFS_like_test.grib2`, `tests/data/FDP_MULTI.grib2` y `tests/data/WAFS_oaci_test.grib2` | No se crea ningún `_wafs.grib2`; se abren tal cual con FUENTE «archivo local» y `WAFS FL050–FL530 · modo WAFS` / `· modo INDRA` / `· modo OACI`. |
| O7 | Línea de comandos | `python -m app.wafs_format tests/data/FDP_MULTI.grib2 /tmp/w.grib2 --forzar --modo WAFS` y `--validar` | «441 mensajes escritos …; FL050–FL530», `/tmp/w.grib2.idx` creado; `wgrib2 -s` igual que `tests/data/WAFS_like_test.grib2` salvo F290 (`314.9 mb` contra `314.8 mb`); sin `--forzar` dice «ya está etiquetado por FL (modo INDRA)»; `--validar` responde OK. |
| O8 | Validador avisa | `python -m app.wafs_format --validar` con un GRIB que tenga 1000 hPa | Aviso «nivel 100000 Pa no es la presión ISA ni la etiqueta nominal de un FL» y no bloquea. |
| O9 | Modos al exportar | Archivo ▸ Exportar a WAFS… ▸ modo INDRA, OACI, OACI56 y WAFS, «Ver tabla» en cada uno | El selector arranca en el modo de Preferencias (OACI); «Ver tabla» muestra 14 / 17 / 56 / 56 filas con FL, ISA_Pa, etiqueta (`850 hPa` o `84310 Pa`), la columna Regla (`nominal OACI`, `múltiplo de 25`, `múltiplo de 5`) y los tildes OACI17 / INDRA14; cada exportación se reabre con el mismo FL activo, el modo detectado y el mismo dato (STATUS igual salvo la etiqueta); exportar un WAFS de 56 en modo OACI deja sólo los 17. |
| O10 | Modo por defecto | Preferencias ▸ WAFS ▸ modo WAFS ▸ Aplicar; abrir un GFS crudo | El convertido lleva presiones ISA (`843.1 mb`); `config.json` tiene `wafs_mode: WAFS`. |

## I. Tema y preferencias

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| I1 | Color de acento | `⚙` ▸ preset Verde ▸ Aplicar | Toda la interfaz y el fondo del mapa cambian; se conserva al reiniciar. |
| I2 | Vista previa y cancelar | `⚙` ▸ elegir color ▸ Cancelar | Vuelve al color anterior. |
| I3 | Transparencia | Mover el deslizador con un archivo abierto | Toda la ventana cambia de opacidad en vivo, incluido el panel derecho (controles e inventario): con el valor mínimo se ve el escritorio desenfocado detrás; sólo el mapa queda opaco. |
| I4 | Zoom de fuente | ⌘+ / ⌘− / ⌘0 con un archivo abierto, varias veces seguidas en los dos sentidos | El texto de la interfaz crece / achica / vuelve a 13 (entre 9 y 22), incluidas la franja STATUS y la barra de estado inferior, y también el título, las etiquetas, la leyenda y los rótulos del mapa; el panel lateral se ensancha y no se corta; la vista del mapa no cambia de zoom; después de llegar al mínimo, ⌘+ vuelve a agrandar; persiste al reiniciar. |
| I7 | Mapa translúcido | Bajar la transparencia con un archivo abierto | El fondo del mapa deja ver el escritorio desenfocado; las barbas y costas siguen nítidas; el PNG exportado sale con fondo opaco. |
| I5 | Escala de barbas | Cambiar el acento | Los colores de las barbas (azul oscuro…granate) y de los contornos de temperatura no cambian; el recuadro y el texto de la leyenda sí toman el tema. |
| I8 | Casillas y radios | Marcar Extra Info y cambiar de variable | El indicador se pinta con el acento y además muestra el tilde (casillas) o el punto (radios). |
| I9 | Pantalla completa (macOS) | Clic en el botón verde, o Vista ▸ Pantalla completa (⌃⌘F) | La ventana entra en el Space de pantalla completa nativo ocupando toda la pantalla; mientras dura es opaca con el fondo del tema (sin negro detrás); al salir (⌃⌘F, Esc en la barra de menú o el botón verde) vuelve translúcida con desenfoque; Vista ▸ Pantalla completa queda tildada mientras está activa. |
| I10 | Pantalla completa (Windows / Linux) | F11 | Ocupa toda la pantalla y vuelve con F11; la ventana sigue opaca. |
| I6 | Diálogos glass | Abrir Preferencias, Atajos y Acerca de | Fondo translúcido con desenfoque, barra de título nativa, contenido sin aplastar; Esc / Cerrar los cierran. |
| I10 | Pestañas | `⚙` | Seis pestañas: Apariencia, Mapa, Fuentes, Descarga, WAFS, Motor; se ven con el tema (pestaña activa resaltada con el acento). |
| I11 | Mapa | Pestaña Mapa ▸ proyección Mercator, Grilla marcada, densidad 2 ▸ Aplicar, con archivo abierto | El mapa pasa a Mercator con grilla y barbas cada 2 puntos; el panel CONFIG refleja los valores; se conservan al reiniciar. |
| I12 | CONFIG persiste | Marcar Extra Info en el panel, cerrar y reabrir la app | Extra Info arranca marcado; Preferencias ▸ Mapa lo muestra marcado. |
| I13 | Descarga | Pestaña Descarga ▸ 0,50°, intermedios, horas 0–24 cada 6 ▸ Aplicar ▸ `Descargar GFS…` | El diálogo abre con esos valores. |
| I16 | Directorio de trabajo por defecto | Pestaña Descarga ▸ «Directorio de trabajo por defecto» `Elegir…` una carpeta A ▸ Aplicar, sin archivo abierto ▸ `Obtener datos…` y Archivo ▸ Abrir; luego abrir un GRIB de otra carpeta B (desde el Finder o Archivo ▸ Abrir) ▸ `Obtener datos…` y Exportar PNG; cerrar y reabrir la app ▸ `Obtener datos…` | Con el campo vacío la ayuda dice que se usa Documentos; con una carpeta inexistente avisa «no existe». Tras aplicar, la carpeta del diálogo de descarga y el diálogo Abrir arrancan en A. Tras abrir el archivo de B, descarga y exportación proponen B. Al reabrir la app vuelve a A (el directorio de trabajo no se recuerda entre sesiones); si la app se abre con doble clic en un archivo de B, arranca en B. |
| I14 | Motor wgrib2 ausente | Pestaña Motor ▸ wgrib2 con ruta vacía y sin wgrib2 en el PATH ▸ `Probar` ▸ Aplicar ▸ abrir un GRIB | `Probar` dice "no encontrado"; al abrir avisa "wgrib2 no disponible" y abre con ecCodes (inventario: `Motor: ecCodes`). |
| I15 | Motor wgrib2 | Con un wgrib2 compilado: `Buscar…` ▸ `Probar` ▸ Aplicar con un archivo abierto | `Probar` muestra la versión; el archivo se reabre y el inventario dice `Motor: wgrib2 v3…`; barbas, STATUS y CSV idénticos a los de ecCodes. |

## J. Ayuda

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| J1 | Atajos | Ayuda ▸ Atajos de teclado (⌘/) | Tabla con los atajos del README, con ⌘ en macOS. |
| J2 | Acerca de | Ayuda ▸ Acerca de Visor GRIB | Versión 0.3.0, Qt, Python, ecCodes, matplotlib y cartopy. |

## L. Obtener datos: fuente NOAA GFS (requiere conexión)

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| L1 | Abrir el diálogo | Selector `Fuente` = NOAA GFS, `Obtener datos…` o ⌘⇧D | Diálogo glass con la fuente arriba y cuatro recuadros con título: «Corrida y plazos» (corrida, Última, plazos y «3 plazo(s)» en un renglón), «Variables y niveles de presión (hPa)» (rótulos «Variables» y «Niveles» a la izquierda de sus casillas, botones de modo, «Incluir niveles intermedios», «Convertir a WAFS» y la línea descriptiva), «Grilla y resolución» («Área»: renglón Manual con Lat N / Lat S / Lon W / Lon E, renglón Por FIR con las casillas SARR…SAVF, Todas / Ninguna y Margen, el modo no elegido grisado; debajo «Configurar áreas…», «Todo el globo», «Dominio del archivo abierto» y el tamaño; después «Opciones de la fuente» en dos columnas con «Mostrar el área en el mapa» a la derecha) y «Descarga y archivo» (carpeta, nombre, unir y abrir en un renglón). Con ECMWF, en «Grilla y resolución» aparecen servidor, reintentos y espera. La descripción de la fuente va en el renglón del título y «3 plazo(s)» en el de los plazos; abajo sólo Cerrar y Descargar, y la barra de progreso con el estado aparece al descargar. |
| L2 | Descarga básica | Valores por defecto (UGRD/VGRD/TMP, botón OACI con «Convertir a WAFS»: 32 niveles 850–70 con intermedios, 0,25°, zona 4N–64S / 90W–22W, +6…+12 cada 3) y `Descargar` | Aparece un diálogo modal «Descargando…» centrado con el plazo en curso y la barra; el de descarga queda grisado atrás sin cambiar de tamaño; al terminar se cierra y se abre en el visor con 3 pasos; STATUS muestra `FUENTE: NOAA GFS`, modelo, corrida y plazo; junto al archivo queda `.grib2.json`. |
| L3 | Dominio del archivo | Con un archivo abierto, `Dominio del archivo abierto` | Los cuatro campos toman el recuadro del archivo. |
| L4 | Todo el globo | Marcar `Todo el globo` con 1,00° | Los campos de zona se deshabilitan; el archivo bajado cubre 180W–180E. |
| L5 | Archivos separados | Desmarcar "Unir los plazos" | Un archivo por plazo `nombre_f006.grib2`, etc.; se abre el primero; cada uno con su `.json`. |
| L6 | Corrida no publicada | Elegir la corrida más nueva del combo si hace menos de 1 h | Mensaje claro con HTTP 404 y la sugerencia de probar la corrida anterior; sin archivo a medias. |
| L7 | Cancelar | `Cancelar` en el diálogo de progreso durante la descarga; antes probar Escape y el botón de cerrar de esa ventana | Escape no lo quita y no tiene botón de cerrar; con `Cancelar` dice «Cancelando…», se detiene, no queda archivo parcial, el de progreso se cierra y el de descarga sigue abierto con «Descarga cancelada». |
| L8 | Validaciones | Sin variables, sin niveles, lat norte < sur, plazos 121–125 cada 1 | Aviso antes de empezar (los plazos no ofrecidos se marcan debajo de los campos). |
| L9 | Reemplazo | Bajar dos veces con el mismo nombre | Pregunta si reemplazar. |
| L10 | Niveles intermedios | 0,25°, desmarcar `Incluir niveles intermedios`, tocar `OACI (17)`; después desmarcarla y volver a marcarla a mano | La casilla se enciende sola, las 875…125 se habilitan y quedan tildadas 850–70 (32); al desmarcarla a mano los intermedios se destildan y deshabilitan, y al marcarla otra vez se vuelven a tildar los que el modo necesita; el progreso muestra "· niveles intermedios"; F320 interpola entre 275 y 250 (STATUS). Con «Convertir a WAFS» desmarcada quedan sólo los 17 nominales (850, 750, 700, 600, 500, 450, …, 125, 100). |
| L11 | Intermedios a 1,00° | Resolución 1,00° y tocar `OACI (17)` | Las casillas intermedias se apagan, quedan 17 niveles y la línea dice «faltan 15 de los 32»; `Descargar` no avisa; marcando "Bajar siempre 0,25°" y tocando otra vez el botón vuelven los 32. |
| L16 | Botones de modo | Tocar INDRA (14), OACI (17), OACI (56) y WAFS (56) con y sin «Convertir a WAFS» | INDRA/OACI sin convertir: 14/17 nominales y la línea «sin convertir … sin interpolar»; con convertir: 850–70 (32) y «para interpolar 14/17 FL»; OACI (56) y WAFS (56) tildan y bloquean la casilla (el texto no cambia: «FL cada 1000 ft, interpolado a presiones reales»; el tooltip explica), 32 niveles, «56 FL» y, en WAFS, «etiqueta = ISA en Pa». Tildar 1000 a mano lo suma sin salir del modo; destildar 750 en OACI sin convertir avisa «sin nivel para FL080». `Todos` / `Ninguno` apagan los botones y liberan la casilla. Con ECMWF en OACI sin convertir quedan 10 niveles y la línea lista FL080, FL210, FL270, FL320, FL360, FL410 y FL480 sin nivel. |
| L12 | Caché | Repetir la descarga L2 (mismo nombre, reemplazar) | El progreso dice "en caché" y termina en segundos sin red; Preferencias ▸ Descarga muestra archivos y MB; `Vaciar caché` los borra. |
| L13 | Bajar 0,25° y regrillar | Resolución 1,00° + "Bajar siempre 0,25°" | El nombre lleva `_desde_0p25`; STATUS: `1,00° desde 0,25° (ninguno)`; grilla 1° idéntica al producto real de 1,00°. |
| L14 | Suavizado | Resolución 1,00° + suavizado `Promedio de área` | Nombre `_desde_0p25_suav`; STATUS `(promedio)`; las barbas en bordes del chorro difieren del producto real. |
| L15 | Sin red | Desconectar la red y descargar | Tras tres intentos, mensaje "no se pudo conectar"; nada a medias. |

## R. Generar GRIB

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| R1 | Abrir el diálogo | Archivo ▸ Generar GRIB… (⌘G), el botón `Generar GRIB…` de la barra (junto a `Obtener datos…`) y el de la pantalla de inicio (junto a `Abrir GRIB…`) | Los tres abren el mismo diálogo glass con cuatro recuadros: «Corrida y plazo» (fecha de hoy, ciclo actual, plazos desde 6 hasta 12 cada 3 h y «3 plazo(s) · validez … – … UTC»), «Área y grilla» (Manual / Por FIR como en la descarga, resolución con «Margen por FIR» al lado, y la grilla resultante, p. ej. `grilla 264 × 279 puntos · zona 20.5S–90S, 74.75W–9W (redondeada hacia afuera a 0.25°) · margen 1° incluido`), «Niveles y valores» (botones INDRA (14) / OACI (17) / OACI (56) / WAFS (56) con el de Preferencias ▸ WAFS tildado y, a su derecha, «Viento en el archivo»; la tabla FL / Presión / T / Viento / Dir con scroll, y los botones Temperatura ISA, Copiar hacia abajo, Agregar FL, Quitar FL) y «Archivo» (carpeta, nombre, Abrir al terminar). La tabla arranca con los FL del modo, T en la ISA de cada FL, viento 0 y la última fila (abajo) elegida, sin edición. |
| R2 | Modos | Tocar cada botón de modo | 14 / 17 / 56 / 56 filas; la columna Presión dice `300 hPa (nominal)` en INDRA/OACI/OACI56 y `300.9 hPa` en WAFS; lo escrito en un FL se conserva al cambiar de modo si el FL sigue. |
| R3 | Tabla | Elegir la fila FL410, escribir T −40, viento 60, dir 250, `Copiar hacia abajo`; `Temperatura ISA`; `Agregar FL` dos veces; `Quitar FL`; elegir la última fila y `Quitar FL`; quitar todas; `Agregar FL` | Las filas de abajo copian los tres valores; ISA vuelve a poner la T de cada FL; Agregar inserta encima de FL410 una fila FL420 con T ISA y 60 kt / 250°, FL410 sigue elegida y los botones de modo se destildan (el rótulo sigue diciendo `modo OACI`); el segundo Agregar inserta otra FL420 y las dos dicen `repetido` en Presión; Quitar saca la elegida y pasa a la de abajo; al quitar la última de abajo queda elegida la nueva última; sin filas no hay nada elegido y Agregar pone FL050 elegida. Cuando la tabla vuelve a coincidir con el modo, el botón se tilda. |
| R3b | Edición de celdas | Clic en la celda T de una fila; escribir −41.5 y Enter; Tab; escribir 99 y Esc; Tab varias veces; en una celda con `-56.5`: ←, escribir `1`, Backspace dos veces, Supr | El clic elige la fila y abre la celda en edición como un campo normal: ocupa la celda entera, opaco (no se ve el valor anterior debajo), borde de acento, valor alineado a la derecha con lugar libre a la izquierda, preseleccionado y con el cursor a su derecha; −41.5 reemplaza y Enter lo aplica; Tab pasa a Viento ya en edición; 99 + Esc deja el valor anterior, sin edición, con la fila todavía elegida y la celda actual con marco, y el diálogo sigue abierto (otro Esc con el foco en la tabla tampoco lo cierra; Cerrar sí); Tab recorre Viento, Dir y sigue en el FL de la fila siguiente salteando Presión; ← suelta la selección y deja el cursor antes del último carácter, `1` se inserta (`-56.15`), Backspace borra hacia la izquierda y Supr hacia la derecha, como en cualquier campo. |
| R4 | Generar y abrir | OACI (17), viento 30 kt / 270° en todas, Por FIR SAEF, 1,00°, plazos 6–12 cada 3, `Generar` | Se escribe `generado_<fecha>_<HH>z_f006-f012_1p00_SAEF_OACI.grib2` con `.idx` y `.json` (`fuente: generado`, `plazos_h: [6, 9, 12]`, `area.codigos: ["SAEF"]`, `tabla` con 17 filas) y se abre en el visor: 3 pasos en TIME, 17 FL con botón, barbas uniformes de 30 kt del oeste iguales en cada paso, FUENTE `Generado a mano (perfil uniforme)`, `corrida … +6 h · 1,00° · área SAEF`, `WAFS FL050–FL530 · modo OACI`; `wgrib2 -s` lista 153 mensajes (TMP, UGRD, VGRD × 17 × 3) con `300 mb` etc. |
| R5 | Dirección y velocidad | Igual que R4 con Viento = «Dirección y velocidad» | El nombre termina en `_OACI_dirvel.grib2`; `wgrib2 -s` lista `WDIR` y `WIND`; en el visor se ve igual que R4 y FUENTE agrega `viento: dirección y velocidad (WDIR/WIND)`. |
| R6 | Validación | FL 305 en una celda, o dir 400, o una celda vacía, o Por FIR sin casillas, o zona manual invertida; `Generar` | Aviso claro con la fila y el motivo; no se escribe nada. Si el archivo ya existe pregunta si reemplazar. |
| R7 | Centro y tablas | Generar un archivo y mirar `wgrib2 -center archivo` (o `grib_ls -p centre,tablesVersion`) | `center=65535` y tablas 25. |
| R8 | Crudo con procedencia | Bajar GFS con las capas de INDRA **sin** convertir a WAFS y abrirlo (con la conversión al abrir apagada) | Inventario: «niveles de presión crudos… según la procedencia son capas del modelo»; FL050 se interpola. Borrando el `.json` y reabriendo: por Nivel, «deducido de las capas». |
| R9 | Exportar viento dir/vel | Abrir un archivo con WDIR/WIND; Exportar a WAFS con «Sólo viento… y TMP» | La salida conserva WDIR y WIND además de TMP. |

## M. Fuentes (Preferencias)

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| M1 | Lista | `⚙` ▸ Fuentes | NOAA GFS con casilla marcada, modelo y tipo "altura"; sin `✓ FL` (lo tendrán WAFS y las que publiquen niveles OACI). |
| M2 | Deshabilitar | Destildar NOAA GFS ▸ Aplicar | Desaparece del selector de la ventana; si no queda ninguna habilitada, el selector muestra todas. |
| M3 | Configurar | `Configurar…` (o doble clic) | Diálogo glass con descripción, enlace a la documentación, casilla de habilitación, parámetros por defecto y `Probar conexión`. |
| M4 | Probar conexión | `Probar conexión` con red | `✔ Conexión OK: NOAA GFS: corrida … disponible`; sin red: `✖ Sin red`. |
| M5 | Parámetros por defecto | Resolución 0,50° + intermedios ▸ Aplicar dos veces ▸ `Obtener datos…` | El diálogo de descarga abre con 0,50° e intermedios marcados. |
| M6 | Selector persistente | Cambiar la fuente en el selector y reiniciar | Se conserva la elegida. |
| M7 | openAIP en Fuentes | `⚙` ▸ Fuentes, sección «Límites de FIR (capa del mapa)» ▸ `Configurar…` | Diálogo de la fuente con tipo "límites de FIR (capa del mapa)", país AR, casilla UIR, token en el llavero y `Probar conexión` (ver P10). |

## N. Otras fuentes (requiere conexión)

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| N1 | ECMWF | Fuente = ECMWF Open Data, `Obtener datos…`, 1 plazo, 2 niveles, zona de prueba | Baja por la librería (espejo AWS), recorta localmente, abre con FUENTE `ECMWF Open Data (IFS …)`; grilla 0,25° de la zona. |
| N2 | ECMWF 06/18 | Corrida 06Z, plazo +96 | Aviso "no ofrece" (06/18 llegan a +90). |
| N2b | ECMWF saturado | Preferencias ▸ Fuentes ▸ ECMWF: Reintentos = 2, Espera = 10 s; bajar justo después de una publicación (o con el espejo `data.ecmwf.int`) | La ventana de avance muestra `servidor saturado (503 Slow Down), reintento 1 de 2` y la cuenta regresiva `reintento en N s`; `Cancelar` corta la espera al instante; si se agotan, error "el servidor está saturado … tras 2 reintentos". En consola la librería sigue imprimiendo su barra y el aviso CC BY 4.0 (informativo). |
| N3 | ICON | Fuente = DWD ICON global, 1 plazo, 2 niveles, U/V/T | Primera vez baja los pesos (44 MB) y luego un archivo por campo; abre con grilla 0,25° recortada; FUENTE `regrillado: vecino más cercano`. |
| N4 | ICON corrida vieja | Elegir la 3.ª corrida del combo | 404 explicado (DWD sólo conserva la última por ciclo). |
| N5 | SMN | Fuente = SMN Argentina WRF 4 km, 1 plazo, zona dentro del dominio | Baja ~38 MB, convierte a GRIB2 0,04°; el panel no muestra LEVEL; STATUS `LEVEL: superficie`; FUENTE `SMN …`; barbas de viento a 10 m y T a 2 m. |
| N6 | SMN fuera del dominio | Zona 10N–0 / 0–10E | Error claro: la zona no se cruza con el dominio. |
| N7 | WAFS sin clave | Habilitar la fuente, `Obtener datos…` | Mensaje "WIFS requiere una clave de API". |
| N8 | WAFS con clave | Preferencias ▸ Fuentes ▸ WAFS ▸ Token = clave de WIFS ▸ Guardar ▸ Probar conexión | `Conexión OK` (o el error exacto de la API); descarga F06–F08 y el visor muestra `✓FL` en FUENTE y "nivel exacto" en los FL. **No verificado por falta de clave.** |
| N9 | Genérica HTTP | Plantilla a un servidor propio, ciclos y plazos, `Probar conexión` | Resultado ok / sin red / credenciales / no publicado según el servidor; descarga y recorte. |
| N10 | Genérica FTP/SFTP | Plantilla `ftp://` o `sftp://` con usuario/clave guardados | Igual que N9. **No verificado contra un servidor real.** |
| N11 | Credenciales | Guardar y borrar credenciales en el diálogo de la fuente | Se ven enmascaradas; no aparecen en `config.json`; tras borrar, "(sin definir)". |

## K. Empaquetado (opcional)

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| K1 | Build | `scripts/build.sh` | Genera `dist/Visor GRIB.app` y `dist/Visor_GRIB_0.3.0_macOS_arm64.dmg` con icono propio. |
| K2 | App empaquetada | Instalar y abrir | Arranca, abre un GRIB, dibuja con costas (ecCodes y cartopy incluidos) y guarda la configuración en `~/Library/Application Support/Visor GRIB/`. |
| K3 | Linux | `scripts/build_linux.sh` en Ubuntu 22.04 o posterior | Genera `.tar.gz`, `.deb` y `.AppImage`; `sudo apt install ./…deb` deja el comando `visor-grib` y la entrada del menú; la prueba de humo del script termina en `smoke: ok`. |
| K4 | Windows | `pwsh scripts\build_windows.ps1` con Inno Setup 6 | Genera `…_Setup.exe` y `.zip`; el instalador asocia `.grib2` si se marca la tarea; la app arranca y abre un GRIB. |
| K5 | GitHub Actions | `git tag vX.Y.Z && git push origin vX.Y.Z` | El workflow «Instaladores» termina en verde en los cuatro sistemas y la release de la etiqueta tiene los siete archivos. |

## S. Visor hexadecimal

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| S1 | Abrir | Con un archivo abierto y el panel lateral a la vista, clic en `0x` (barra de acciones) o Vista ▸ Panel hexadecimal (⌘ ⇧ H) | Dentro del bloque del mapa, debajo del encabezado de información y del mapa, aparece la subsección «HEXADECIMAL» con «N bytes · M mensajes», a todo el ancho del mapa y con un separador para repartir el alto (el mapa más alto); el árbol a la izquierda, un renglón por mensaje con su posición, el primero elegido; el volcado a la derecha (posición, 16 bytes en hex, ASCII) sin cortar la columna ASCII. El botón y Vista ▸ Panel hexadecimal quedan tildados; al reiniciar sigue abierto. Sin archivo, el botón y la opción están deshabilitados. |
| S1b | Según el panel lateral | Con el hexadecimal abierto, ocultar el panel lateral (`▥` o ⌘ ⇧ P); volver a mostrarlo | Sin panel lateral el hexadecimal pasa a la derecha del mapa, los dos bajo el encabezado de información, con el ancho del árbol más el volcado y nunca más ancho que el mapa (el separador deja cambiarlo); al volver el panel lateral, el hexadecimal vuelve debajo del mapa. |
| S1c | Ocultar y cambiar de archivo | Con el panel abierto, cerrar el archivo (⌘ W), abrir otro, y luego clic en `0x` | Al cerrar el archivo el panel dice «Sin archivo.»; al abrir otro lo muestra; al ocultarlo con `0x` el mapa recupera el lugar y el botón queda destildado. |
| S1d | Celdas de la sección 7 | Abrir un mensaje, Sección 7, «Datos empaquetados», una fila, una celda | «Datos empaquetados» se abre en filas `Fila j=… · lat …` (una por fila de la grilla); cada fila en celdas `[j, i] lat lon` con su valor decodificado (igual al que muestra Consultar punto en esa celda) y, con empaquetado simple o IEEE, sus bytes propios pintados en el volcado; con un GFS de NOMADS (empaquetado complejo) la celda abarca toda la sección y el valor igual se muestra. |
| S1f | Alternar paneles | Hacer zoom en el mapa; mostrar y ocultar `0x` y `▥` en distinto orden varias veces | La ventana no cambia de tamaño; el mapa conserva la escala (se ve más o menos región, pero el zoom no cambia) y al volver a la disposición inicial el encuadre es el mismo. En una ventana angosta el hexadecimal cede ancho (el volcado muestra barra horizontal) antes que agrandar la ventana. |
| S1e | Clic en el mapa | Con el panel abierto, clic sobre un punto del mapa | Además de la ficha del punto, el árbol se abre hasta la celda del mensaje que muestra el mapa (U en modo viento, T en temperatura; la capa que se ve o, en un FL interpolado, la más cercana) y el volcado la pinta; la celda dice la lat/lon del punto de grilla más cercano y su valor coincide con el de la ficha. |
| S2 | Entrar en el árbol | Abrir un mensaje con su «+», luego Sección 4, luego elegir «Primera superficie» y después su «Valor» | Los nodos con hijos tienen «+», que pasa a «−» al abrirlos; abrir con el «+» no cambia lo pintado ni el nodo elegido. Cada renglón lleva un cuadrito con el color de su nivel (todos los mensajes uno, todas las secciones otro, los campos otro, los subcampos otro). Al elegir «Primera superficie» el volcado muestra el mensaje con el color de nivel 0, encima la sección 4 con el de nivel 1 y encima el campo con el de nivel 2 y marco del acento; la línea de detalle muestra `64 00 00 01 4c 08 → capa 85000 Pa = 850 hPa` (o la capa que sea). Al elegir «Valor» se agregan sus 4 bytes con el color de nivel 3 y el marco pasa a ellos, sin perder los colores del mensaje, la sección y el campo. |
| S3 | Clic en un byte | Clic sobre un byte del volcado dentro de otro mensaje | El árbol se abre hasta el campo que lo contiene y queda elegido; el volcado se desplaza para mostrarlo. |
| S4 | Ir al byte | Escribir `0x15` (o `21`) y Enter | Queda elegido «Centro generador» del primer mensaje, con su nombre de la tabla C-11 (7 = NCEP; 65535 = faltante en un generado). |
| S5 | Copiar | Elegir un campo y «Copiar bytes» | El portapapeles tiene los bytes en hexadecimal (`64 00 00 01 4c 08`). |
| S6 | Archivo grande | Abrir un GFS con miles de mensajes | Abre al instante; desplazar el volcado con la rueda es fluido; desplegar un mensaje es inmediato. |

## T. Archivo a guardar

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| T1 | Preferencias | Preferencias ▸ Guardar: viento «Dirección y velocidad», temperatura 0 decimales; Aplicar. Abrir Obtener datos… y Generar GRIB… | Los dos arrancan con esas opciones en su bloque «Archivo a guardar». |
| T2 | Descarga | GFS, convertir a WAFS, bloque: viento dir/vel, viento 1 decimal, centro «sin centro»; bajar y abrir | El inventario dice `VIENTO: dirección y velocidad`; en el panel hexadecimal el centro es `65535 = faltante` y en la sección 5 de un WDIR, D = 1 y E = 0; el `.json` tiene `guardado` con la descripción. |
| T3 | Etiqueta de capa | Descargar con modo INDRA y etiqueta «ISA entera»; abrir | Capas 84300, 69700… (`wgrib2 -s` muestra `843 mb`); el inventario dice modo WAFS (presión ISA en Pa) y los FL se muestran sin interpolar. Con «Convertir a WAFS» apagado en un GFS la etiqueta queda deshabilitada. |
| T4 | Generar | Generar GRIB con empaquetado «un valor por celda (IEEE)» y etiqueta ISA con un decimal, modo OACI | Panel hexadecimal: plantilla 5.4 = IEEE y la sección 7 tiene un float por punto, todos iguales; capa 84310 Pa aunque el modo sea OACI. Sin decimales ni centro en el bloque de Generar. |
| T5 | Guardar como | Abrir un archivo convertido; Archivo ▸ Guardar como… (⌘ ⇧ S): viento dir/vel, temperatura 0 decimales; Guardar con «Abrir el archivo guardado» | Se escribe `nombre_rec_dirvel.grib2` con `.json` (`por_nivel: true`, `guardado`) e `.idx`, se abre, el inventario dice por Nivel y las temperaturas en la ficha del punto son enteras en K (decimales en °C vienen de los −273,15). |
| T7 | Orden de las celdas | Guardar como con «Orden de las celdas: S→N, E→O» y «filas intercaladas»; abrir el guardado | El inventario del guardado dice `ORDEN DE LAS CELDAS: S→N, E→O, filas intercaladas`; el mapa y la ficha del punto muestran exactamente lo mismo que el original; en el panel hexadecimal, Sección 3 ▸ Modo de barrido tiene bits 1, 2 y 4 en 1, La1 es la latitud sur y Lo1 la longitud este, y la fila j=1 de «Datos empaquetados» lista las celdas de oeste a este (la impar corre al revés). Con motor wgrib2 el archivo también se abre. |
| T6 | Guardar como de un crudo | Abrir un GFS sin convertir (conversión al abrir apagada); Guardar como | La etiqueta de capa está deshabilitada; el guardado sigue crudo (`por_nivel: false`) y al abrirse se interpola. No deja sobreescribir el archivo abierto. |

