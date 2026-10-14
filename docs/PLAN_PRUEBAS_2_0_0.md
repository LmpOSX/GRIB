# Plan de pruebas manual – Visor GRIB 2.0.0 (PyQt6)

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
| E1 | Botón FL | Clic en F100 | Botón resaltado con el color de acento; redibuja; STATUS `F100 = 696.8 hPa` interpolado 700/600 (o 700/500 según niveles). |
| E2 | Extrapolación | Clic en F530 con nivel mínimo 100 hPa → interpola. Con un archivo cuyo nivel más alto sea 200 hPa | STATUS "extrapolado / nivel más cercano: 200 hPa" y el título del mapa lo indica. |
| E3 | Nivel de presión directo | Combo "Nivel de presión" ▸ 700 hPa | Ningún FL queda marcado; STATUS "700 hPa (nivel del archivo)"; el mapa muestra el nivel exacto. |
| E4 | Volver a FL | Clic en un FL con el combo en un nivel | El combo vuelve a "(interpolar por FL)". |
| E5 | Verificación wgrib2 | README, sección "Verificación con wgrib2" | Valores de u, v, T en 700 mb coinciden con la barra de estado / CSV. |

## F. VARIABLE y CONFIG

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| F1 | Viento | Radio Viento | Barbas en kt coloreadas por la escala fija, leyenda abajo a la izquierda, barbas invertidas en el hemisferio sur. |
| F2 | Temperatura | Radio Temperatura | Contornos cada 2 °C etiquetados; sin barbas ni leyenda. |
| F3 | Ambas | Radio Viento + Temp. | Barbas y contornos. |
| F4 | Extra Info | Marcar | Velocidad en kt junto a cada barba (y °C con temperatura); los rótulos no se salen del mapa. |
| F5 | Grilla | Marcar | Grilla fina de 1° (o la del archivo) además de meridianos/paralelos cada 10°. |
| F6 | Fondo de velocidad | Marcar | Contornos rellenos con la misma escala, semitransparentes. |
| F7 | Densidad | Poner 2 y 3 | Barbas cada 2 / 3 puntos; redibuja al cambiar. |
| F8 | Update | Clic | Redibuja sin cambiar nada (también F5). |
| F9 | Disable / Enable | Clic en Disable | Sólo mapa base, "Capa de datos deshabilitada" en el mapa y en STATUS; el botón pasa a Enable y Vista ▸ "Capa de datos desactivada"; ⌘D alterna. |

## G. Mapa, zoom y recuadro

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| G1 | Zoom con rueda | Girar la rueda sobre el mapa | Acerca / aleja alrededor del cursor, sin botones ni modos. |
| G2 | Pan por arrastre | Arrastrar el mapa con el botón izquierdo | Cursor de mano abierta sobre el mapa, cerrada al arrastrar; el mapa sigue al mouse. |
| G19 | El mapa llena el área | Abrir un archivo, redimensionar la ventana, aplicar un recuadro | No quedan franjas vacías a los costados ni arriba/abajo: la vista se amplía para ocupar todo el canvas y el dominio sigue completo. |
| G3 | Inicio | Tras zoom, clic en `Inicio` | Vuelve a la vista inicial. |
| G4 | Recuadro | Escribir lat/lon mín/máx y Enter (o "Aplicar recuadro") | La vista se ajusta; con valores inválidos aparece un aviso. |
| G5 | Recuadro sincronizado | Hacer zoom con el mouse | Los campos lat/lon reflejan la vista actual. |
| G6 | Todo el dominio | Botón o ⌘⇧0 | Vuelve a la grilla completa. |
| G7 | Cambio de nivel con zoom | Hacer zoom y cambiar de FL, paso, variable, Extra Info, grilla o densidad | La vista se mantiene en todos los casos. |
| G15 | Rueda del mouse | Girar la rueda sobre el mapa | Acerca/aleja alrededor del cursor; `Inicio` vuelve a la vista completa. |
| G16 | Fluidez del pan | Densidad 1 + Extra Info + grilla, arrastrar el mapa | El mapa sigue al mouse sin trabarse; los rótulos y las etiquetas de la grilla desaparecen durante el arrastre y vuelven al soltar (≈0,2 s). |
| G17 | Raleo automático | Vista completa con densidad 1 | Barbas y rótulos raleados pero legibles; al acercar aparecen todos los puntos; el cambio no "salta" entre vistas. |
| G18 | Fluidez en proyecciones | Repetir G16 en estereográfica | Mismo comportamiento. |
| G8 | Hover | Mover el mouse sobre el mapa | La barra inferior muestra lat/lon, punto de grilla, viento kt / dirección y T °C; fuera de la grilla sólo lat/lon. |
| G9 | Sin cartopy | Desinstalar cartopy temporalmente (`pip uninstall cartopy`) | El mapa se dibuja sin costas con el aviso; Acerca de lo indica. Reinstalar después. |
| G11 | Proyección estereográfica | CONFIG ▸ Proyección ▸ "Estereográfica conforme (centro del dominio)" | El mapa se redibuja con meridianos convergentes, barbas rotadas, etiquetas de lat/lon en los bordes; el hover sigue mostrando lat/lon correctos; zoom, pan, Inicio y recuadro funcionan. |
| G12 | Resto de proyecciones | Elegir polar sur, polar norte, Mercator y Lambert | Todas dibujan sin error; Lambert con un dominio ecuatorial también. |
| G13 | Proyección persistida | Elegir estereográfica, cerrar y reabrir la app | Arranca con la proyección elegida. |
| G14 | Grilla visible | Marcar `Grilla lat/lon del archivo` con opacidad alta y baja | Meridianos/paralelos cada 10° en línea continua y la grilla del archivo punteada, ambas visibles sobre el fondo. |
| G10 | Sin red la primera vez | Borrar `~/.local/share/cartopy` y abrir sin conexión | Aviso "No se pudieron cargar las costas"; el mapa igual se dibuja. |

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
| O1 | Descarga convertida | Obtener datos… con el GFS (Preferencias ▸ WAFS con «Convertir al descargar» marcado) | El archivo termina en `_wafs.grib2`; `wgrib2 -s` lista niveles `843.1 mb, 812 mb, … 100.4 mb` (49 por variable y plazo); el `.json` tiene `wafs.convertido: true` y `fl_rango FL050–FL530`. |
| O2 | Visor con WAFS | Abrir el archivo de O1 | STATUS: `FUENTE … / WAFS FL050–FL530 (convertido)`; `LEVEL: F300 = 30090 Pa (WAFS, nivel exacto)`; el combo «Nivel de presión» lista `FL050 · 843.1 hPa …`; el inventario dice `FORMATO: WAFS`. Cambiar de FL redibuja sin «interpolado entre». |
| O3 | Archivo local convertido | Abrir un GFS en niveles de presión (por ejemplo `tests/data/FDP_MULTI.grib2` copiado a otra carpeta) | Barra de estado «Convertido a WAFS: …_wafs.grib2»; junto al original aparecen `<nombre>_wafs.grib2`, `.json` e `.idx`; el visor muestra el convertido. Con «Convertir también los archivos locales» desmarcado, se abre el original e interpola como antes. |
| O4 | Rango ampliado | Bajar ECMWF o ICON con niveles 1000 y 50 hPa, convertir | El rango llega a FL010–FL600 (con «ampliar» marcado); sin marcarlo, FL050–FL530. |
| O5 | Extrapolar | Bajar sólo 700–300 hPa con «extrapolar» marcado | Hay 49 niveles; el `.json` lista `extrapolados`; sin marcar, sólo FL100–FL300 y `fl_omitidos`. |
| O6 | Ya en WAFS | Abrir `tests/data/WAFS_like_test.grib2` | No se crea ningún `_wafs.grib2`; se abre tal cual con FUENTE «archivo local» y `WAFS FL050–FL530`. |
| O7 | Línea de comandos | `python -m app.wafs_format tests/data/FDP_MULTI.grib2 /tmp/w.grib2` y `--validar` | «441 mensajes escritos …; FL050–FL530», `/tmp/w.grib2.idx` creado, `cmp /tmp/w.grib2 tests/data/WAFS_like_test.grib2` sin diferencias; `--validar` responde OK. |
| O8 | Validador avisa | `python -m app.wafs_format --validar tests/data/FDP_MULTI.grib2` | Avisos «nivel 10000 Pa no es la presión ISA de un FL…» y no bloquea. |

## I. Tema y preferencias

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| I1 | Color de acento | `⚙` ▸ preset Verde ▸ Aplicar | Toda la interfaz y el fondo del mapa cambian; se conserva al reiniciar. |
| I2 | Vista previa y cancelar | `⚙` ▸ elegir color ▸ Cancelar | Vuelve al color anterior. |
| I3 | Transparencia | Mover el deslizador con un archivo abierto | Toda la ventana cambia de opacidad en vivo, incluido el panel derecho (controles e inventario): con el valor mínimo se ve el escritorio desenfocado detrás; sólo el mapa queda opaco. |
| I4 | Zoom de fuente | ⌘+ / ⌘− / ⌘0 con un archivo abierto | El texto de la interfaz crece / achica / vuelve a 13 y también el título, las etiquetas, la leyenda y los rótulos del mapa; el panel lateral se ensancha y no se corta; persiste al reiniciar. |
| I7 | Mapa translúcido | Bajar la transparencia con un archivo abierto | El fondo del mapa deja ver el escritorio desenfocado; las barbas y costas siguen nítidas; el PNG exportado sale con fondo opaco. |
| I5 | Escala de barbas | Cambiar el acento | Los colores de las barbas (cian…rojo) y de los contornos de temperatura no cambian. |
| I8 | Casillas y radios | Marcar Extra Info y cambiar de variable | El indicador se pinta con el acento y además muestra el tilde (casillas) o el punto (radios). |
| I9 | Botón verde (macOS) | Clic en el botón verde de la ventana | La ventana se maximiza sobre el escritorio (no entra al Space de pantalla completa) y conserva el desenfoque y la transparencia. |
| I6 | Diálogos glass | Abrir Preferencias, Atajos y Acerca de | Fondo translúcido con desenfoque, barra de título nativa, contenido sin aplastar; Esc / Cerrar los cierran. |
| I10 | Pestañas | `⚙` | Seis pestañas: Apariencia, Mapa, Fuentes, Descarga, WAFS, Motor; se ven con el tema (pestaña activa resaltada con el acento). |
| I11 | Mapa | Pestaña Mapa ▸ proyección Mercator, Grilla marcada, densidad 2 ▸ Aplicar, con archivo abierto | El mapa pasa a Mercator con grilla y barbas cada 2 puntos; el panel CONFIG refleja los valores; se conservan al reiniciar. |
| I12 | CONFIG persiste | Marcar Extra Info en el panel, cerrar y reabrir la app | Extra Info arranca marcado; Preferencias ▸ Mapa lo muestra marcado. |
| I13 | Descarga | Pestaña Descarga ▸ 0,50°, intermedios, horas 0–24 cada 6 ▸ Aplicar ▸ `Descargar GFS…` | El diálogo abre con esos valores. |
| I14 | Motor wgrib2 ausente | Pestaña Motor ▸ wgrib2 con ruta vacía y sin wgrib2 en el PATH ▸ `Probar` ▸ Aplicar ▸ abrir un GRIB | `Probar` dice "no encontrado"; al abrir avisa "wgrib2 no disponible" y abre con ecCodes (inventario: `Motor: ecCodes`). |
| I15 | Motor wgrib2 | Con un wgrib2 compilado: `Buscar…` ▸ `Probar` ▸ Aplicar con un archivo abierto | `Probar` muestra la versión; el archivo se reabre y el inventario dice `Motor: wgrib2 v3…`; barbas, STATUS y CSV idénticos a los de ecCodes. |

## J. Ayuda

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| J1 | Atajos | Ayuda ▸ Atajos de teclado (⌘/) | Tabla con los atajos del README, con ⌘ en macOS. |
| J2 | Acerca de | Ayuda ▸ Acerca de Visor GRIB | Versión 2.0.0, Qt, Python, ecCodes, matplotlib y cartopy. |

## L. Obtener datos: fuente NOAA GFS (requiere conexión)

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| L1 | Abrir el diálogo | Selector `Fuente` = NOAA GFS, `Obtener datos…` o ⌘⇧D | Diálogo glass con fuente, corrida (combo con las últimas 12), plazos, variables, opciones de la fuente, niveles, zona y destino. |
| L2 | Descarga básica | Valores por defecto (UGRD/VGRD/TMP, niveles del visor, 0,25°, zona 4N–64S / 90W–22W, +6…+12 cada 3) y `Descargar` | Progreso por plazo; al terminar se abre en el visor con 3 pasos; STATUS muestra `FUENTE: NOAA GFS`, modelo, corrida y plazo; junto al archivo queda `.grib2.json`. |
| L3 | Dominio del archivo | Con un archivo abierto, `Dominio del archivo abierto` | Los cuatro campos toman el recuadro del archivo. |
| L4 | Todo el globo | Marcar `Todo el globo` con 1,00° | Los campos de zona se deshabilitan; el archivo bajado cubre 180W–180E. |
| L5 | Archivos separados | Desmarcar "Unir los plazos" | Un archivo por plazo `nombre_f006.grib2`, etc.; se abre el primero; cada uno con su `.json`. |
| L6 | Corrida no publicada | Elegir la corrida más nueva del combo si hace menos de 1 h | Mensaje claro con HTTP 404 y la sugerencia de probar la corrida anterior; sin archivo a medias. |
| L7 | Cancelar | `Cancelar` durante la descarga | Se detiene, no queda archivo parcial, el diálogo sigue abierto. |
| L8 | Validaciones | Sin variables, sin niveles, lat norte < sur, plazos 121–125 cada 1 | Aviso antes de empezar (los plazos no ofrecidos se marcan debajo de los campos). |
| L9 | Reemplazo | Bajar dos veces con el mismo nombre | Pregunta si reemplazar. |
| L10 | Niveles intermedios | 0,25°, marcar `Incluir niveles intermedios`, `Los del visor`, descargar | Las casillas 875…125 se habilitan y "Los del visor" suma 275/225/175; el progreso muestra "· niveles intermedios"; F320 interpola entre 300 y 275 (STATUS). |
| L11 | Intermedios a 1,00° | Resolución 1,00° con la casilla marcada | Las casillas intermedias se apagan y `Descargar` avisa; marcando "Bajar siempre 0,25°" vuelven a habilitarse. |
| L12 | Caché | Repetir la descarga L2 (mismo nombre, reemplazar) | El progreso dice "en caché" y termina en segundos sin red; Preferencias ▸ Descarga muestra archivos y MB; `Vaciar caché` los borra. |
| L13 | Bajar 0,25° y regrillar | Resolución 1,00° + "Bajar siempre 0,25°" | El nombre lleva `_desde_0p25`; STATUS: `1,00° desde 0,25° (ninguno)`; grilla 1° idéntica al producto real de 1,00°. |
| L14 | Suavizado | Resolución 1,00° + suavizado `Promedio de área` | Nombre `_desde_0p25_suav`; STATUS `(promedio)`; las barbas en bordes del chorro difieren del producto real. |
| L15 | Sin red | Desconectar la red y descargar | Tras tres intentos, mensaje "no se pudo conectar"; nada a medias. |

## M. Fuentes (Preferencias)

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| M1 | Lista | `⚙` ▸ Fuentes | NOAA GFS con casilla marcada, modelo y tipo "altura"; sin `✓ FL` (lo tendrán WAFS y las que publiquen niveles OACI). |
| M2 | Deshabilitar | Destildar NOAA GFS ▸ Aplicar | Desaparece del selector de la ventana; si no queda ninguna habilitada, el selector muestra todas. |
| M3 | Configurar | `Configurar…` (o doble clic) | Diálogo glass con descripción, enlace a la documentación, casilla de habilitación, parámetros por defecto y `Probar conexión`. |
| M4 | Probar conexión | `Probar conexión` con red | `✔ Conexión OK: NOAA GFS: corrida … disponible`; sin red: `✖ Sin red`. |
| M5 | Parámetros por defecto | Resolución 0,50° + intermedios ▸ Aplicar dos veces ▸ `Obtener datos…` | El diálogo de descarga abre con 0,50° e intermedios marcados. |
| M6 | Selector persistente | Cambiar la fuente en el selector y reiniciar | Se conserva la elegida. |

## N. Otras fuentes (requiere conexión)

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| N1 | ECMWF | Fuente = ECMWF Open Data, `Obtener datos…`, 1 plazo, 2 niveles, zona de prueba | Baja por la librería (espejo AWS), recorta localmente, abre con FUENTE `ECMWF Open Data (IFS …)`; grilla 0,25° de la zona. |
| N2 | ECMWF 06/18 | Corrida 06Z, plazo +96 | Aviso "no ofrece" (06/18 llegan a +90). |
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
| K1 | Build | `scripts/build.sh` | Genera `dist/Visor GRIB.app` y `dist/Visor_GRIB_2.0.0.dmg` con icono propio. |
| K2 | App empaquetada | Instalar y abrir | Arranca, abre un GRIB, dibuja con costas (ecCodes y cartopy incluidos) y guarda la configuración en `~/Library/Application Support/Visor GRIB/`. |
