# Plan de pruebas manual – Visor GRIB 2.0.0 (PyQt6)

Entorno: pyenv `Grib` (Python 3.14.3), macOS. Antes de empezar:

```bash
cd /ruta/al/proyecto
python -c "import PyQt6, eccodes, cartopy, matplotlib; print('ok')"
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -p "test_*.py"   # debe terminar en OK
```

Archivo de prueba: un GRIB2 de GFS con 3 pasos, u/v/t y niveles de presión
(por ejemplo `FDP_MULTI.grib2`). Marcar cada caso como OK / FALLA y anotar el
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

## J. Ayuda

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| J1 | Atajos | Ayuda ▸ Atajos de teclado (⌘/) | Tabla con los atajos del README, con ⌘ en macOS. |
| J2 | Acerca de | Ayuda ▸ Acerca de Visor GRIB | Versión 2.0.0, Qt, Python, ecCodes, matplotlib y cartopy. |

## K. Empaquetado (opcional)

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| K1 | Build | `scripts/build.sh` | Genera `dist/Visor GRIB.app` y `dist/Visor_GRIB_2.0.0.dmg` con icono propio. |
| K2 | App empaquetada | Instalar y abrir | Arranca, abre un GRIB, dibuja con costas (ecCodes y cartopy incluidos) y guarda la configuración en `~/Library/Application Support/Visor GRIB/`. |
