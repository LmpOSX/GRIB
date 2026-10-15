# Fuentes de los límites de FIR y sus licencias

La capa de FIR del visor dibuja polígonos que vienen de archivos externos.
El programa **no trae coordenadas inventadas**: cada contorno proviene de
una de estas fuentes, y el visor muestra en cada FIR de dónde salió
(`FIR…` ▸ Extremos, columna *Fuente*).

## 1. AIP Argentina, ENR 2.1 — fuente oficial

* Publicación: AIP Argentina, parte ENR, sección 2.1 «FIR, UIR, TMA»,
  del Servicio de Información Aeronáutica (AIS) de EANA S.E. / ANAC
  (<https://ais.anac.gob.ar/>; descargas de la AIP y enmiendas AIRAC).
* Formato: los límites laterales figuran como listas de vértices en texto
  (por ejemplo `3917S06307W`) con tramos descriptos con palabras
  («siguiendo el límite internacional», «por la costa»).
* Conversión: `app/fir_aip.py` (interfaz `FIR…` ▸ Datos ▸ *Convertir texto
  del AIP…* o `python -m app.fir_aip`). Los tramos descriptos con palabras
  quedan marcados en la propiedad `tramos_pendientes` del GeoJSON y hay
  que completarlos a mano (o con otra fuente). El GeoJSON generado lleva
  `oficial: true` y `verificado: false`: es responsabilidad del usuario
  cotejarlo con la enmienda vigente.
* Licencia / uso: documento oficial del Estado argentino; los datos de la
  AIP se usan para la navegación aérea bajo las condiciones del AIS. El
  visor no redistribuye ningún extracto del AIP.

## 2. VATSpy Data Project — fuente abierta de respaldo (NO oficial)

* Proyecto: <https://github.com/vatsimnetwork/vatspy-data-project>, archivo
  `Boundaries.geojson` (rama `master`). Contiene los polígonos de las FIR
  del mundo para el cliente VAT-Spy de la red VATSIM; cada feature lleva
  el código OACI en la propiedad `id`, `oceanic` (0/1), `label_lon` /
  `label_lat` (punto de etiqueta), `region` y `division`.
* Licencia: **Creative Commons Attribution-ShareAlike 4.0 International
  (CC BY-SA 4.0)** (archivo LICENSE del repositorio). Atribución: «VATSpy
  Data Project, VATSIM». El archivo filtrado que se redistribuye con el
  visor (`resources/fir/fir_vatspy.geojson`) conserva esa licencia; el
  código del visor no es obra derivada del dataset.
* Carácter: límites **derivados de las AIP por voluntarios, pensados para
  simulación de vuelo**. No son una publicación aeronáutica. Para uso
  operativo deben verificarse contra el AIP (fuente 1). El visor lo avisa
  en el diálogo y en «Acerca de».
* Uso en el visor: una copia filtrada a las 14 FIR de interés viene con el
  programa (fecha en el miembro `_visor.descargado` del archivo);
  `Descargar límites de FIR (VATSpy)` baja el archivo completo (~2 MB), lo
  filtra y lo guarda en la carpeta de datos del usuario, que tiene
  prioridad sobre la copia incluida. Los sectores oceánicos que vienen
  como feature aparte (p. ej. Montevideo) se unen con la FIR continental.

## 3. openAIP — tercera fuente opcional (NO oficial, con clave)

* Sitio: <https://www.openaip.net>; API Core:
  <https://api.core.openaip.net/api> (documentación interactiva en
  <https://docs.openaip.net/>, especificación OpenAPI en
  `/api/system/specs/v1/schema.json`).
* Endpoint usado: `GET /airspaces?country=AR&type=10[&type=11]&page=N&limit=100`.
  Tipos de espacio aéreo según la especificación: `10` = Flight
  Information Region (FIR), `11` = Upper FIR (UIR). La respuesta es
  `{items: [{name, geometry (GeoJSON), …}], totalCount, totalPages}`.
* Autenticación: clave de API gratuita, creada en el perfil de usuario de
  openaip.net, enviada en el encabezado `x-openaip-api-key`. En el visor se
  guarda como «token» de la fuente `openaip_fir` en el llavero del sistema
  (`keyring`), nunca en `config.json` ni en logs, y se borra desde el
  mismo diálogo (Preferencias ▸ Fuentes ▸ openAIP ▸ Borrar).
* Licencia: **CC BY-NC 4.0** (Creative Commons Attribution-NonCommercial
  4.0), según el pie del sitio: uso no comercial con atribución a openAIP.
* Cobertura: no se pudo verificar sin clave si openAIP publica las FIR
  argentinas. `Probar conexión` informa cuántas FIR/UIR devuelve la API
  para el país; si devuelve 0 el visor lo dice y se sigue con VATSpy o el
  AIP. Como los ítems no traen el indicador OACI, las FIR se reconocen por
  nombre (Resistencia, Córdoba, Mendoza, Ezeiza, Comodoro Rivadavia…); las
  que no se reconocen se informan al terminar la descarga.

## 4. Archivo propio del usuario

`FIR…` ▸ Datos ▸ *Cargar archivo propio…* acepta GeoJSON (Feature,
FeatureCollection, Polygon/MultiPolygon), KML/KMZ (un Placemark por FIR,
con `outerBoundaryIs` e `innerBoundaryIs`) y Shapefile (`.shp` + `.dbf`,
leído con pyshp). El código OACI se toma de una propiedad `id`, `icao`,
`code`, `codigo`, `identifier` o `fir`, o de cuatro letras mayúsculas en
el nombre. El archivo se copia a la carpeta de datos y reemplaza, para las
FIR que contiene, a las fuentes descargadas y a la copia incluida.

## Carpeta de datos

* macOS: `~/Library/Application Support/Visor GRIB/fir/`
* Windows: `%APPDATA%\Visor GRIB\fir\`
* Linux: `$XDG_DATA_HOME/Visor GRIB/fir/` (o `~/.local/share/Visor GRIB/fir/`)

Archivos: `fir_vatspy.geojson` (descarga filtrada), `fir_openaip.geojson`,
`fir_usuario.geojson` / `.kml` / `.kmz` (copia del archivo propio). Todos
llevan en el miembro `_visor` la fuente, la licencia, la fecha y el aviso
de no oficial cuando corresponde.

## Otras fuentes consideradas

* Natural Earth no publica FIR.
* Los datasets de FIR de proveedores de cartas (Jeppesen, Navigraph, NASR
  de la FAA para EE. UU.) son propietarios o no cubren Argentina; no se
  usan.
