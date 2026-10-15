# -*- coding: utf-8 -*-
"""Límites de las Regiones de Información de Vuelo (FIR) para la capa del
mapa. Módulo sin Qt: carga polígonos desde GeoJSON (también KML y Shapefile),
los filtra por código OACI, calcula extremos, punto interior para la
etiqueta, pertenencia de un punto y cobertura de la grilla meteorológica.

Fuentes (ver docs/FUENTES_FIR.md):

* AIP Argentina, ENR 2.1 (EANA / ANAC): oficial. Los límites vienen como
  listas de vértices en texto; `fir_aip` los convierte a GeoJSON.
* VATSpy Data Project (`Boundaries.geojson`, CC BY-SA 4.0): fuente abierta
  de respaldo, derivada de las AIP, NO oficial. Una copia filtrada viene
  con el visor (`resources/fir/fir_vatspy.geojson`) y «Descargar límites
  de FIR» la renueva en la carpeta de datos del usuario.
* openAIP (API con clave, CC BY-NC 4.0): tercera fuente opcional
  (`sources/openaip_fir.py`).

Prioridad al cargar: el archivo propio del usuario reemplaza, para los
códigos que contenga, a las demás fuentes; después la fuente preferida
(VATSpy u openAIP) y por último la copia incluida con el visor.
"""
import datetime as dt
import json
import os
import re
import sys
import zipfile

import numpy as np

from .config import APP_NAME

# ── Códigos de interés ───────────────────────────────────────────────────────
ARGENTINA_FIRS = [
    ("SARR", "Resistencia"),
    ("SACF", "Córdoba"),
    ("SAMF", "Mendoza"),
    ("SAEF", "Ezeiza"),
    ("SAVF", "Comodoro Rivadavia"),
]
NEIGHBOR_FIRS = [
    ("SUEO", "Montevideo"),
    ("SGFA", "Asunción"),
    ("SLLF", "La Paz"),
    ("SCEZ", "Santiago"),
    ("SCCZ", "Punta Arenas"),
    ("SBCW", "Curitiba"),
    ("SBBS", "Brasilia"),
    ("SBAO", "Atlántico"),
    ("FAJO", "Johannesburgo Oceánico"),
]
FIR_NAMES = dict(ARGENTINA_FIRS + NEIGHBOR_FIRS)
ARGENTINA_CODES = [c for c, _ in ARGENTINA_FIRS]
NEIGHBOR_CODES = [c for c, _ in NEIGHBOR_FIRS]
ALL_CODES = ARGENTINA_CODES + NEIGHBOR_CODES

VATSPY_URL = ("https://raw.githubusercontent.com/vatsimnetwork/vatspy-data-project/"
              "master/Boundaries.geojson")
VATSPY_PROJECT_URL = "https://github.com/vatsimnetwork/vatspy-data-project"
VATSPY_LICENSE = "CC BY-SA 4.0"
VATSPY_NOTICE = ("Límites del VATSpy Data Project (derivados de las AIP, NO oficiales). "
                 "Para uso operativo verificarlos contra el AIP Argentina ENR 2.1.")

# Densificación de los lados antes de proyectar (grados): un lado largo que
# en lat/lon es recto se curva en las proyecciones conformes
DENSIFY_DEG = 0.5

# Carpeta de datos del usuario (se puede redefinir en los tests)
BUNDLED_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "resources", "fir", "fir_vatspy.geojson")


def _default_data_dir():
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    elif sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, APP_NAME, "fir")


DATA_DIR = _default_data_dir()
VATSPY_FILE = "fir_vatspy.geojson"
OPENAIP_FILE = "fir_openaip.geojson"
USER_FILE = "fir_usuario.geojson"


def data_dir():
    return DATA_DIR


def data_file(name):
    return os.path.join(DATA_DIR, name)


# ── Geometría ────────────────────────────────────────────────────────────────
def points_in_ring(ring, lons, lats):
    """Pertenencia (trazado de rayo hacia +x) de los puntos (lons, lats) al
    anillo (N, 2) lon/lat, vectorizada con numpy."""
    ring = np.asarray(ring, dtype=float)
    lons = np.atleast_1d(np.asarray(lons, dtype=float))
    lats = np.atleast_1d(np.asarray(lats, dtype=float))
    if len(ring) < 3:
        return np.zeros(lons.shape, dtype=bool)
    x, y = ring[:, 0], ring[:, 1]
    x2, y2 = np.roll(x, -1), np.roll(y, -1)
    px = lons[:, None]
    py = lats[:, None]
    cross = (y[None, :] > py) != (y2[None, :] > py)
    with np.errstate(all="ignore"):
        xint = x[None, :] + (py - y[None, :]) * (x2 - x)[None, :] / (y2 - y)[None, :]
    hits = cross & (px < xint)
    return (np.count_nonzero(hits, axis=1) % 2) == 1


def _ring_area(ring):
    """Área (fórmula del zapato, en grados²) con el coseno de la latitud
    media como peso, sólo para comparar anillos entre sí."""
    r = np.asarray(ring, dtype=float)
    if len(r) < 3:
        return 0.0
    x, y = r[:, 0], r[:, 1]
    a = 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))
    return a * max(0.05, np.cos(np.deg2rad(float(np.mean(y)))))


def interior_point(ring, holes=()):
    """Punto interior del polígono para la etiqueta: se barre el anillo con
    paralelos a varias latitudes y se toma el punto medio de la cuerda
    interior más larga (medida en grados de longitud × cos lat). A
    diferencia del centroide, en polígonos cóncavos siempre cae adentro."""
    r = np.asarray(ring, dtype=float)
    if len(r) < 3:
        return None
    x, y = r[:, 0], r[:, 1]
    x2, y2 = np.roll(x, -1), np.roll(y, -1)
    lat0, lat1 = float(y.min()), float(y.max())
    best = None
    for f in np.linspace(0.08, 0.92, 29):
        lat = lat0 + (lat1 - lat0) * f
        cross = (y > lat) != (y2 > lat)
        if not cross.any():
            continue
        with np.errstate(all="ignore"):
            xs = x[cross] + (lat - y[cross]) * (x2[cross] - x[cross]) / (y2[cross] - y[cross])
        xs = np.sort(xs[np.isfinite(xs)])
        for k in range(0, len(xs) - 1, 2):
            a, b = xs[k], xs[k + 1]
            mid = 0.5 * (a + b)
            if any(points_in_ring(h, [mid], [lat])[0] for h in holes):
                continue
            w = (b - a) * max(0.05, np.cos(np.deg2rad(lat)))
            if best is None or w > best[0]:
                best = (w, mid, lat)
    if best is None:
        return None
    return float(best[1]), float(best[2])


def densify(ring, step=DENSIFY_DEG):
    """Inserta vértices cada `step` grados a lo largo de cada lado (lineal
    en lon/lat, como dibujan los clientes de VATSpy). Los lados que tocan
    el polo no se densifican (allí la longitud es indefinida)."""
    r = np.asarray(ring, dtype=float)
    if len(r) < 2 or step <= 0:
        return r
    out = []
    n = len(r)
    for i in range(n):
        a = r[i]
        b = r[(i + 1) % n]
        out.append(a)
        if abs(a[1]) >= 89.99 or abs(b[1]) >= 89.99:
            continue
        span = max(abs(b[0] - a[0]), abs(b[1] - a[1]))
        k = int(span // step)
        if k >= 1:
            t = np.linspace(0.0, 1.0, k + 2)[1:-1]
            out.extend(a + (b - a) * t[:, None])
    return np.asarray(out, dtype=float)


class FirRegion:
    """Una FIR: código OACI, nombre y uno o más polígonos (exterior y
    agujeros) en lon/lat. `label` es el punto de etiqueta del dataset si
    lo trae; si no, se calcula uno interior."""

    def __init__(self, code, name=None, polygons=(), label=None, source="", official=False,
                 props=None):
        self.code = code
        self.name = name or FIR_NAMES.get(code, code)
        self.polygons = []
        for ext, holes in polygons:
            ext = _clean_ring(ext)
            if ext is None:
                continue
            hs = [h for h in (_clean_ring(h) for h in holes) if h is not None]
            self.polygons.append((ext, hs))
        self.label = tuple(float(v) for v in label) if label else None
        self.source = source
        self.official = bool(official)
        self.props = dict(props or {})
        self._bbox = None
        self._interior = None

    # ── Propiedades ──
    @property
    def rings(self):
        return [ext for ext, _h in self.polygons]

    @property
    def n_vertices(self):
        return int(sum(len(ext) + sum(len(h) for h in holes) for ext, holes in self.polygons))

    @property
    def argentina(self):
        return self.code in ARGENTINA_CODES

    @property
    def bbox(self):
        """(lonmin, lonmax, latmin, latmax) de todos los polígonos."""
        if self._bbox is None and self.polygons:
            pts = np.concatenate(self.rings)
            self._bbox = (float(pts[:, 0].min()), float(pts[:, 0].max()),
                          float(pts[:, 1].min()), float(pts[:, 1].max()))
        return self._bbox

    def extremes(self):
        """Extremos geográficos: {'norte', 'sur', 'este', 'oeste'} en grados."""
        b = self.bbox
        if b is None:
            return None
        return {"norte": b[3], "sur": b[2], "este": b[1], "oeste": b[0]}

    def contains(self, lon, lat):
        for ext, holes in self.polygons:
            if points_in_ring(ext, [lon], [lat])[0]:
                if any(points_in_ring(h, [lon], [lat])[0] for h in holes):
                    continue
                return True
        return False

    def label_point(self):
        """Punto de etiqueta: el del dataset si cae adentro; si no, uno
        interior calculado sobre el polígono más grande."""
        if self.label and self.contains(*self.label):
            return self.label
        if self._interior is None and self.polygons:
            ext, holes = max(self.polygons, key=lambda p: _ring_area(p[0]))
            self._interior = interior_point(ext, holes)
        return self._interior

    def merge(self, other):
        """Suma los polígonos de otra feature con el mismo código (p. ej.
        el sector oceánico de Montevideo viene como feature aparte)."""
        self.polygons.extend(other.polygons)
        if not self.label and other.label:
            self.label = other.label
        self._bbox = None
        self._interior = None

    def to_feature(self):
        coords = []
        for ext, holes in self.polygons:
            rings = [ext] + list(holes)
            coords.append([[[float(x), float(y)] for x, y in np.vstack([r, r[:1]])] for r in rings])
        props = {"id": self.code, "name": self.name, "fuente": self.source,
                 "oficial": self.official}
        if self.label:
            props["label_lon"] = self.label[0]
            props["label_lat"] = self.label[1]
        for k, v in self.props.items():
            props.setdefault(k, v)
        return {"type": "Feature", "properties": props,
                "geometry": {"type": "MultiPolygon", "coordinates": coords}}

    def __repr__(self):
        return f"FirRegion({self.code} {self.name!r}, {len(self.polygons)} polígono(s), {self.n_vertices} vértices)"


def _clean_ring(ring):
    r = np.asarray(ring, dtype=float)
    if r.ndim != 2 or r.shape[1] < 2:
        return None
    r = r[:, :2]
    r = r[np.isfinite(r).all(axis=1)]
    if len(r) >= 2 and np.allclose(r[0], r[-1]):
        r = r[:-1]
    return r if len(r) >= 3 else None


# ── Cobertura de la grilla ───────────────────────────────────────────────────
def normalize_grid_bbox(lonmin, lonmax, latmin, latmax):
    """Pasa una grilla en 0–360 a −180…180. Si cruza el antimeridiano se
    toma toda la vuelta en longitud."""
    if lonmax > 180.0:
        lonmin -= 360.0
        lonmax -= 360.0
        if lonmin < -180.0:
            return -180.0, 180.0, latmin, latmax
    return float(lonmin), float(lonmax), float(latmin), float(latmax)


def coverage(region, grid_bbox):
    """'completa' si el recuadro de la grilla contiene el de la FIR,
    'parcial' si se solapan, 'ninguna' si no se tocan. `grid_bbox` =
    (lonmin, lonmax, latmin, latmax); None → 'sin grilla'."""
    if grid_bbox is None:
        return "sin grilla"
    b = region.bbox
    if b is None:
        return "sin datos"
    g0, g1, g2, g3 = normalize_grid_bbox(*grid_bbox)
    if g0 <= b[0] and b[1] <= g1 and g2 <= b[2] and b[3] <= g3:
        return "completa"
    if b[1] < g0 or b[0] > g1 or b[3] < g2 or b[2] > g3:
        return "ninguna"
    return "parcial"


# ── Carga ────────────────────────────────────────────────────────────────────
_CODE_KEYS = ("id", "icao", "ICAO", "code", "codigo", "código", "identifier", "fir")
_NAME_KEYS = ("name", "nombre", "NAME", "Nombre")


def _code_from_props(props, fallback_name=""):
    for k in _CODE_KEYS:
        v = props.get(k)
        if isinstance(v, str) and re.fullmatch(r"[A-Za-z]{4}", v.strip()):
            return v.strip().upper()
    m = re.search(r"\b([A-Z]{4})\b", fallback_name or "")
    return m.group(1) if m else None


def _geometry_polygons(geom):
    """[(exterior, [agujeros])] de una geometría GeoJSON."""
    if not geom:
        return []
    t = geom.get("type")
    if t == "Polygon":
        rings = geom.get("coordinates") or []
        return [(rings[0], rings[1:])] if rings else []
    if t == "MultiPolygon":
        return [(poly[0], poly[1:]) for poly in (geom.get("coordinates") or []) if poly]
    if t == "GeometryCollection":
        out = []
        for g in geom.get("geometries") or []:
            out.extend(_geometry_polygons(g))
        return out
    return []


def _feature_to_region(feature, source, official):
    props = feature.get("properties") or {}
    name = next((props[k] for k in _NAME_KEYS if isinstance(props.get(k), str)), "")
    code = _code_from_props(props, name)
    if not code:
        return None
    polys = _geometry_polygons(feature.get("geometry"))
    if not polys:
        return None
    label = None
    if props.get("label_lon") not in (None, "") and props.get("label_lat") not in (None, ""):
        try:
            label = (float(props["label_lon"]), float(props["label_lat"]))
        except (TypeError, ValueError):
            label = None
    if str(props.get("oceanic", "0")) == "1":
        label = None        # el sector oceánico no debe mover la etiqueta
    # Para las FIR conocidas se usa el nombre canónico (las etiquetas quedan
    # iguales venga de donde venga); para el resto, el del archivo
    name = FIR_NAMES.get(code) or (name if name and not re.fullmatch(r"[A-Z]{4}", name) else code)
    extra = {k: v for k, v in props.items() if k in ("tramos_pendientes", "verificado", "fuente_detalle")}
    return FirRegion(code, name, polys, label=label,
                     source=props.get("fuente") or source,
                     official=bool(props.get("oficial", official)), props=extra)


def _merge_regions(regions):
    by_code = {}
    for r in regions:
        if r is None:
            continue
        if r.code in by_code:
            by_code[r.code].merge(r)
        else:
            by_code[r.code] = r
    return list(by_code.values())


def load_geojson(src, source="archivo", official=False, codes=None, source_override=None):
    """Lista de FirRegion de un GeoJSON (ruta o dict). Las features con el
    mismo código se unen. `codes` filtra por código OACI. `source` es el
    valor por defecto cuando ni el archivo (`_visor.fuente`) ni la feature
    (`fuente`) lo traen; `source_override` lo impone a todas (etiqueta de
    la capa: «VATSpy (copia incluida)»)."""
    if isinstance(src, (str, os.PathLike)):
        with open(src, "r", encoding="utf-8") as fh:
            obj = json.load(fh)
    else:
        obj = src
    t = obj.get("type")
    if t == "FeatureCollection":
        feats = obj.get("features") or []
    elif t == "Feature":
        feats = [obj]
    else:
        feats = [{"type": "Feature", "properties": {}, "geometry": obj}]
    meta = obj.get("_visor") or {}
    source = meta.get("fuente") or source
    regions = [_feature_to_region(f, source, official) for f in feats]
    regions = _merge_regions(regions)
    if source_override:
        for r in regions:
            r.source = source_override
    if codes is not None:
        regions = [r for r in regions if r.code in codes]
    return regions


def _kml_iter(el, local):
    """Descendientes con ese nombre local (Element.iter no admite el comodín
    de espacio de nombres {*}; find/findall sí)."""
    return [e for e in el.iter() if isinstance(e.tag, str) and e.tag.rsplit("}", 1)[-1] == local]


def _kml_coords(text):
    pts = []
    for tok in (text or "").split():
        parts = tok.split(",")
        if len(parts) >= 2:
            try:
                pts.append((float(parts[0]), float(parts[1])))
            except ValueError:
                continue
    return pts


def load_kml(src, source="archivo", official=False, codes=None):
    """FirRegion de un KML/KMZ: un Placemark por FIR, con el código OACI en
    el nombre o en ExtendedData (id / icao / code)."""
    import xml.etree.ElementTree as ET
    if isinstance(src, (str, os.PathLike)) and str(src).lower().endswith(".kmz"):
        with zipfile.ZipFile(src) as z:
            name = next((n for n in z.namelist() if n.lower().endswith(".kml")), None)
            if name is None:
                raise ValueError("El KMZ no contiene ningún .kml")
            root = ET.fromstring(z.read(name))
    elif isinstance(src, (str, os.PathLike)):
        root = ET.parse(src).getroot()
    else:
        root = ET.fromstring(src)
    regions = []
    for pm in _kml_iter(root, "Placemark"):
        name_el = pm.find("{*}name")
        name = (name_el.text or "").strip() if name_el is not None else ""
        props = {"name": name}
        for data in _kml_iter(pm, "Data"):
            val = data.find("{*}value")
            if data.get("name") and val is not None:
                props[data.get("name")] = (val.text or "").strip()
        for sd in _kml_iter(pm, "SimpleData"):
            if sd.get("name"):
                props[sd.get("name")] = (sd.text or "").strip()
        polys = []
        for poly in _kml_iter(pm, "Polygon"):
            outer = poly.find("{*}outerBoundaryIs/{*}LinearRing/{*}coordinates")
            if outer is None:
                continue
            ext = _kml_coords(outer.text)
            holes = [_kml_coords(c.text) for c in
                     poly.findall("{*}innerBoundaryIs/{*}LinearRing/{*}coordinates")]
            if len(ext) >= 3:
                polys.append([ext] + [h for h in holes if len(h) >= 3])
        if not polys:
            continue
        geom = {"type": "MultiPolygon", "coordinates": polys}
        regions.append(_feature_to_region({"properties": props, "geometry": geom}, source, official))
    regions = _merge_regions(regions)
    if codes is not None:
        regions = [r for r in regions if r.code in codes]
    return regions


def load_shapefile(path, source="archivo", official=False, codes=None):
    """FirRegion de un Shapefile (.shp con .dbf al lado) vía pyshp, que
    viene con cartopy. El código OACI se toma de un campo id / ICAO / code
    o del nombre."""
    try:
        import shapefile
    except Exception as exc:
        raise RuntimeError("Leer Shapefile requiere pyshp (lo instala cartopy)") from exc
    regions = []
    with shapefile.Reader(str(path)) as rd:
        for sr in rd.iterShapeRecords():
            geom = sr.shape.__geo_interface__
            props = dict(sr.record.as_dict())
            regions.append(_feature_to_region({"properties": props, "geometry": geom},
                                              source, official))
    regions = _merge_regions(regions)
    if codes is not None:
        regions = [r for r in regions if r.code in codes]
    return regions


def load_any(path, source="archivo", official=False, codes=None):
    ext = os.path.splitext(str(path))[1].lower()
    if ext in (".kml", ".kmz"):
        return load_kml(path, source, official, codes)
    if ext == ".shp":
        return load_shapefile(path, source, official, codes)
    return load_geojson(path, source, official, codes)


def save_geojson(regions, path, meta=None):
    obj = {"type": "FeatureCollection", "features": [r.to_feature() for r in regions]}
    if meta:
        obj["_visor"] = dict(meta)
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = path + ".parte"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return path


# ── VATSpy ───────────────────────────────────────────────────────────────────
def parse_json_bytes(data, what="el servidor"):
    """JSON de la respuesta o DownloadError si es HTML u otra cosa (página
    de error, límite de descargas…)."""
    from .sources.base import DownloadError
    head = data.lstrip()[:1]
    if head not in (b"{", b"["):
        texto = data[:300].decode("utf-8", "replace").strip()
        raise DownloadError(f"La respuesta de {what} no es JSON (¿página de error HTML?).\n{texto}",
                            status="contenido")
    try:
        return json.loads(data.decode("utf-8"))
    except Exception as exc:
        raise DownloadError(f"La respuesta de {what} no es un JSON válido: {exc}", status="contenido")


def filter_vatspy(obj, codes=ALL_CODES, when=None):
    """FeatureCollection sólo con las features cuyo `id` está en `codes`
    (se conservan tal cual, incluidos los sectores oceánicos) más la
    procedencia en el miembro `_visor`."""
    codes = set(codes)
    feats = [f for f in (obj.get("features") or [])
             if str((f.get("properties") or {}).get("id", "")).upper() in codes]
    when = when or dt.datetime.now(dt.timezone.utc)
    return {"type": "FeatureCollection", "features": feats,
            "_visor": {"fuente": "VATSpy", "oficial": False, "licencia": VATSPY_LICENSE,
                       "url": VATSPY_URL, "proyecto": VATSPY_PROJECT_URL,
                       "descargado": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
                       "aviso": VATSPY_NOTICE}}


def download_vatspy(fetch_fn=None, progress_cb=None, cancel=None, codes=ALL_CODES, dest=None):
    """Baja Boundaries.geojson, lo filtra y lo guarda en la carpeta de datos.
    Devuelve (ruta, códigos encontrados, códigos faltantes)."""
    from .sources.base import fetch_with_retries
    if fetch_fn is None:
        from .gfs_download import fetch as fetch_fn

    def chunk(got, total):
        if progress_cb is None:
            return
        if total:
            progress_cb(f"Descargando Boundaries.geojson… {got / 1e6:.1f} de {total / 1e6:.1f} MB",
                        min(0.95, got / total))
        else:
            progress_cb(f"Descargando Boundaries.geojson… {got / 1e6:.1f} MB", 0.0)

    if progress_cb:
        progress_cb("Conectando con GitHub (VATSpy Data Project)…", 0.0)
    data = fetch_with_retries(fetch_fn, VATSPY_URL, chunk_cb=chunk, cancel=cancel)
    obj = parse_json_bytes(data, "VATSpy")
    sub = filter_vatspy(obj, codes)
    dest = dest or data_file(VATSPY_FILE)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".parte"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(sub, fh, ensure_ascii=False)
    os.replace(tmp, dest)
    found = sorted({str(f["properties"]["id"]).upper() for f in sub["features"]})
    missing = [c for c in codes if c not in found]
    if progress_cb:
        progress_cb(f"Guardado: {len(found)} FIR en {dest}", 1.0)
    return dest, found, missing


# ── Capa completa según configuración ────────────────────────────────────────
def file_info(path):
    """Resumen de un archivo de límites para la interfaz: fuente, fecha,
    cantidad de FIR. None si no existe."""
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            obj = json.load(fh)
        meta = obj.get("_visor") or {}
        n = len({str((f.get("properties") or {}).get("id", "")).upper()
                 for f in obj.get("features") or []})
        return {"ruta": path, "fuente": meta.get("fuente", "archivo"),
                "descargado": meta.get("descargado", ""), "n": n,
                "oficial": bool(meta.get("oficial", False)),
                "modificado": dt.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")}
    except Exception:
        return {"ruta": path, "fuente": "archivo", "descargado": "", "n": 0, "oficial": False,
                "modificado": ""}


def load_layer(cfg=None, codes=ALL_CODES):
    """Regiones para la capa: la copia incluida, tapada por la fuente
    preferida descargada (VATSpy u openAIP) y, por encima de todo, el
    archivo propio del usuario. Devuelve (dict código → FirRegion, lista
    de avisos)."""
    cfg = cfg or {}
    out = {}
    notes = []

    def take(regions, label):
        n = 0
        for r in regions:
            if r.code in codes:
                out[r.code] = r
                n += 1
        if n:
            notes.append(f"{label}: {n} FIR")

    if os.path.isfile(BUNDLED_FILE):
        try:
            take(load_geojson(BUNDLED_FILE, source_override="VATSpy (copia incluida)"), "copia incluida")
        except Exception as exc:
            notes.append(f"copia incluida ilegible: {exc}")
    preferred = cfg.get("fir_preferred", "vatspy")
    order = [("vatspy", VATSPY_FILE, "VATSpy (descargado)"), ("openaip", OPENAIP_FILE, "openAIP")]
    if preferred == "openaip":
        order.reverse()
    for key, fname, label in order:
        p = data_file(fname)
        if os.path.isfile(p):
            try:
                take(load_geojson(p, source_override=label), label)
            except Exception as exc:
                notes.append(f"{label} ilegible: {exc}")
    user = cfg.get("fir_user_file") or ""
    if user and os.path.isfile(user):
        try:
            take(load_any(user, source="archivo propio"), "archivo propio")
        except Exception as exc:
            notes.append(f"archivo propio ilegible: {exc}")
    elif user:
        notes.append(f"archivo propio no encontrado: {user}")
    return out, notes
