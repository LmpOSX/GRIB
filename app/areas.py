# -*- coding: utf-8 -*-
"""Áreas de descarga definidas a partir de las FIR argentinas (sin Qt).

Una **área** es un recuadro lat/lon identificado por un código de hasta
cuatro letras (SAEF, SACF…), con nombre, límites norte/sur/oeste/este y una
casilla de habilitación. La tabla vive en la configuración (`areas`) y se
edita en Preferencias ▸ Áreas / FIR; las cinco FIR argentinas vienen
precargadas **a verificar contra el AIP Argentina ENR 2.1** (el visor no
inventa coordenadas: las carga el usuario).

Al descargar, el usuario elige el área a mano (modo *manual*) o marca una o
varias áreas (modo *por FIR*): la zona pedida es la **envolvente** de las
marcadas (la latitud más al norte, la más al sur, la longitud más al oeste
y la más al este) más un **margen** por fuera. El margen no se guarda sumado
en la tabla: se aplica sólo al momento de usar el área.

Convenciones: latitudes −90…90 (sur negativo), longitudes −180…180 (oeste
negativo). Un área puede llegar al polo (sur = −90) o cruzar el meridiano
de Greenwich (oeste negativo y este positivo): la zona resultante se pide
al servidor y se recorta localmente con longitudes negativas y positivas
en el mismo pedido (ver `regrid.crop_grib`).
"""
import csv
import io
import json
import math
import os
import re

CODE_RE = re.compile(r"^[A-Z0-9]{1,4}$")

# Las cinco FIR argentinas: valores iniciales **a verificar contra el AIP
# ENR 2.1** (los cargó el usuario; `verificar` = True hasta que los coteje).
DEFAULT_AREAS = [
    {"code": "SARR", "name": "Resistencia", "north": -22.25, "south": -30.70,
     "west": -62.67, "east": -53.67, "enabled": True, "verify": True},
    {"code": "SACF", "name": "Córdoba", "north": -21.72, "south": -34.03,
     "west": -69.65, "east": -60.20, "enabled": True, "verify": True},
    {"code": "SAMF", "name": "Mendoza", "north": -28.50, "south": -38.50,
     "west": -71.21, "east": -64.50, "enabled": True, "verify": True},
    {"code": "SAEF", "name": "Ezeiza", "north": -30.22, "south": -46.00,
     "west": -71.85, "east": -10.00, "enabled": True, "verify": True},
    {"code": "SAVF", "name": "Comodoro Rivadavia", "north": -39.28, "south": -90.00,
     "west": -73.57, "east": -10.00, "enabled": True, "verify": True},
]
ARGENTINA_CODES = [a["code"] for a in DEFAULT_AREAS]

VERIFY_NOTE = "a verificar contra AIP ENR 2.1"
MANUAL_TAG = "MANUAL"
DEFAULT_MARGIN_DEG = 1.0
# Grillas con nombre (ver `Grid`): un recuadro exacto más, si se quiere, la
# resolución; se usan tal cual, sin envolvente ni margen. De fábrica, la que
# lee el FDP de INDRA (Argentina): recorta 75°W–25°W, 55°S–20°S a 1° en una
# grilla fija de 51 × 36 puntos, así que la zona exacta da justo esa grilla.
# El perfil «FDP» la elige sola. La tabla vive en la configuración (`grids`)
# y se edita en Preferencias ▸ Áreas / FIR
FACTORY_GRIDS = [
    {"id": "fdp_arg", "name": "FDP Arg", "north": -20.0, "south": -55.0, "west": -75.0,
     "east": -25.0, "res": 1.0, "enabled": True,
     "note": "La grilla que lee el FDP de INDRA: 20°S–55°S, 75°W–25°W a 1°, 51 × 36 puntos"},
]
FDP_REGION = (-20.0, -55.0, -75.0, -25.0)     # la de FACTORY_GRIDS[0], para los tests
FDP_RES = 1.0
GRID_RES_CHOICES = [(None, "La de la fuente"), (0.25, "0,25°"), (0.5, "0,50°"), (1.0, "1,00°"),
                    (1.25, "1,25°")]
COORD_FORMATS = [("decimal", "Grados decimales con signo (−34.03)"),
                 ("gm", "Grados y minutos con hemisferio (34°01.8'S)")]

# Tamaño aproximado de un punto de grilla en un GRIB2 con empaquetado simple
# de 16 bits (lo que entregan NOMADS, ECMWF e ICON): 2 bytes por valor más
# ~200 bytes de cabecera por mensaje.
BYTES_PER_POINT = 2.0
BYTES_PER_MESSAGE = 200


# ── Coordenadas ──────────────────────────────────────────────────────────────

_DEC_RE = re.compile(r"^\s*(?P<sign>[-+])?\s*(?P<val>\d{1,3}(?:[.,]\d+)?)\s*°?\s*(?P<hem>[NSEWO])?\s*$",
                     re.IGNORECASE)
_DMS_RE = re.compile(
    r"^\s*(?P<hem1>[NSEWO])?\s*(?P<deg>\d{1,3})\s*[°º\s]\s*(?P<min>\d{1,2}(?:[.,]\d+)?)?\s*['′]?"
    r"\s*(?:(?P<sec>\d{1,2}(?:[.,]\d+)?)\s*(?:\"|″|'')?)?\s*(?P<hem2>[NSEWO])?\s*$", re.IGNORECASE)
_COMPACT_RE = re.compile(r"^\s*(?P<hem1>[NSEWO])?\s*(?P<digits>\d{4,7}(?:[.,]\d+)?)\s*(?P<hem2>[NSEWO])?\s*$",
                         re.IGNORECASE)


class CoordError(ValueError):
    pass


def _f(s):
    return float(str(s).replace(",", "."))


def _apply_hem(value, hem, kind):
    """Aplica el hemisferio (S y W/O negativos) y valida que corresponda a
    `kind` ('lat' | 'lon')."""
    hem = (hem or "").upper()
    if hem == "O":
        hem = "W"
    if hem:
        if kind == "lat" and hem not in "NS":
            raise CoordError(f"hemisferio {hem} no vale para una latitud")
        if kind == "lon" and hem not in "EW":
            raise CoordError(f"hemisferio {hem} no vale para una longitud")
        if hem in "SW":
            value = -abs(value)
        else:
            value = abs(value)
    return value


def parse_coord(text, kind):
    """Texto → grados decimales. Acepta grados decimales con signo
    (−34.03), grados-minutos(-segundos) con hemisferio (22°15'S, 34°01.8'S,
    062°40'15"W, 22 15 30 S) y el formato compacto del AIP (2215S, 06240W,
    221530S). `kind`: 'lat' o 'lon'. Lanza CoordError."""
    s = (text or "").strip().replace("′", "'").replace("″", '"')
    if not s:
        raise CoordError("coordenada vacía")
    lim = 90.0 if kind == "lat" else 180.0
    m = _COMPACT_RE.match(s)
    if m and (m.group("hem1") or m.group("hem2")) and "." not in m.group("digits") \
            and "," not in m.group("digits"):
        hem = (m.group("hem1") or m.group("hem2")).upper()
        if hem == "O":
            hem = "W"
        digits = m.group("digits")
        nd = 2 if hem in "NS" else 3
        if len(digits) < nd or len(digits[nd:]) not in (0, 2, 4):
            raise CoordError(f"coordenada compacta inválida: {s}")
        deg = float(digits[:nd])
        mn = float(digits[nd:nd + 2]) if len(digits) > nd else 0.0
        sec = float(digits[nd + 2:nd + 4]) if len(digits) > nd + 2 else 0.0
        if mn >= 60 or sec >= 60:
            raise CoordError(f"minutos o segundos fuera de rango: {s}")
        val = _apply_hem(deg + mn / 60.0 + sec / 3600.0, hem, kind)
    else:
        m = _DEC_RE.match(s)
        if m:
            val = _f(m.group("val"))
            if m.group("sign") == "-":
                val = -val
            if m.group("hem") and m.group("sign"):
                raise CoordError(f"no mezclar signo y hemisferio: {s}")
            val = _apply_hem(val, m.group("hem"), kind)
        else:
            m = _DMS_RE.match(s)
            if not m or not (m.group("hem1") or m.group("hem2")):
                raise CoordError(f"no se reconoce la coordenada: {s!r} (ej. -34.03, 34°01.8'S, 3401S)")
            deg = float(m.group("deg"))
            mn = _f(m.group("min")) if m.group("min") else 0.0
            sec = _f(m.group("sec")) if m.group("sec") else 0.0
            if mn >= 60 or sec >= 60:
                raise CoordError(f"minutos o segundos fuera de rango: {s}")
            val = _apply_hem(deg + mn / 60.0 + sec / 3600.0, m.group("hem1") or m.group("hem2"), kind)
    if abs(val) > lim + 1e-9:
        raise CoordError(f"{'latitud' if kind == 'lat' else 'longitud'} fuera de rango: {val:g}")
    return float(val)


def format_coord(value, kind, fmt="decimal"):
    """Grados decimales → texto en el formato elegido ('decimal' o 'gm')."""
    value = float(value)
    if fmt != "gm":
        return f"{value:.2f}".replace("-0.00", "0.00")
    if kind == "lat":
        hem = "S" if value < 0 else "N"
        nd = 2
    else:
        hem = "W" if value < 0 else "E"
        nd = 3
    a = abs(value)
    deg = int(math.floor(a + 1e-9))
    mn = (a - deg) * 60.0
    if mn >= 59.95:
        deg, mn = deg + 1, 0.0
    return f"{deg:0{nd}d}°{mn:04.1f}'{hem}"


def short_coord(value, kind):
    """`20°S`, `75°W`, `34.5°S`: para resúmenes cortos."""
    value = float(value)
    hem = ("S" if value < 0 else "N") if kind == "lat" else ("W" if value < 0 else "E")
    a = abs(value)
    return f"{a:g}°{hem}"


# ── Áreas ────────────────────────────────────────────────────────────────────

class Area:
    """Un recuadro con código. Los límites se guardan tal cual los cargó el
    usuario (sin margen)."""

    FIELDS = ("code", "name", "north", "south", "west", "east", "enabled", "verify")

    def __init__(self, code, name="", north=0.0, south=0.0, west=0.0, east=0.0,
                 enabled=True, verify=False):
        self.code = str(code or "").strip().upper()
        self.name = str(name or "").strip()
        self.north, self.south = float(north), float(south)
        self.west, self.east = float(west), float(east)
        self.enabled = bool(enabled)
        self.verify = bool(verify)

    @classmethod
    def from_dict(cls, d):
        d = dict(d or {})
        return cls(d.get("code", ""), d.get("name", ""), d.get("north", 0.0), d.get("south", 0.0),
                   d.get("west", 0.0), d.get("east", 0.0), d.get("enabled", True),
                   d.get("verify", False))

    def to_dict(self):
        return {"code": self.code, "name": self.name, "north": self.north, "south": self.south,
                "west": self.west, "east": self.east, "enabled": self.enabled, "verify": self.verify}

    @property
    def region(self):
        """(top, bottom, left, right): la convención de DownloadJob.region."""
        return (self.north, self.south, self.west, self.east)

    @property
    def label(self):
        return f"{self.code} {self.name}".strip()

    def copy(self):
        return Area.from_dict(self.to_dict())

    def __repr__(self):
        return f"Area({self.code}, N{self.north:g} S{self.south:g} W{self.west:g} E{self.east:g})"


class Grid:
    """Grilla con nombre: recuadro exacto (norte, sur, oeste, este) más la
    resolución (grados; None = la que tenga la fuente). `id` es estable (no
    se edita; los de fábrica conservan el suyo), `name` es lo que se
    muestra; `builtin` marca los de fábrica, que se ocultan en vez de
    borrarse (`enabled`)."""
    FIELDS = ("id", "name", "north", "south", "west", "east", "res", "note", "builtin", "enabled")

    def __init__(self, id, name="", north=0.0, south=0.0, west=0.0, east=0.0, res=None,
                 note="", builtin=False, enabled=True):
        self.id = str(id or "").strip()
        self.name = str(name or "").strip()
        self.north, self.south = float(north), float(south)
        self.west, self.east = float(west), float(east)
        self.res = None if res in (None, "", 0) else float(res)
        self.note = str(note or "").strip()
        self.builtin = bool(builtin)
        self.enabled = bool(enabled)

    @classmethod
    def from_dict(cls, d):
        d = dict(d or {})
        return cls(d.get("id", ""), d.get("name", ""), d.get("north", 0.0), d.get("south", 0.0),
                   d.get("west", 0.0), d.get("east", 0.0), d.get("res"), d.get("note", ""),
                   d.get("builtin", False), d.get("enabled", True))

    def to_dict(self):
        return {k: getattr(self, k) for k in self.FIELDS}

    @property
    def region(self):
        return (self.north, self.south, self.west, self.east)

    @property
    def tag(self):
        """Etiqueta para el nombre del archivo: el nombre sin espacios ni
        signos, en mayúsculas (`FDPARG`), o el id."""
        t = re.sub(r"[^A-Za-z0-9]+", "", self.name).upper()[:12]
        return t or re.sub(r"[^A-Za-z0-9]+", "", self.id).upper()[:12] or "GRILLA"

    def size(self, res=None):
        """(columnas, filas) a la resolución propia (o a `res`), o None."""
        r = self.res if res is None else res
        if not r:
            return None
        s = region_size(self.region, r)
        return (s["nlon"], s["nlat"])

    def summary(self, res=None):
        """`20°S–55°S · 75°W–25°W · 1° → 51 × 36 puntos`."""
        txt = (f"{short_coord(self.north, 'lat')}–{short_coord(self.south, 'lat')} · "
               f"{short_coord(self.west, 'lon')}–{short_coord(self.east, 'lon')}")
        r = self.res if res is None else res
        if r:
            n = self.size(r)
            txt += f" · {r:g}° → {n[0]} × {n[1]} puntos"
        return txt

    def same_values(self, other):
        return all(getattr(self, k) == getattr(other, k)
                   for k in ("name", "north", "south", "west", "east", "res", "note"))

    def copy(self):
        return Grid.from_dict(self.to_dict())

    def __repr__(self):
        return f"Grid({self.id}, {self.name!r}, N{self.north:g} S{self.south:g} W{self.west:g} E{self.east:g}, {self.res})"


def validate_grid(grid):
    """Mensaje de error (claro, para mostrar) o None."""
    name = grid.name or grid.id or "(sin nombre)"
    if not grid.name:
        return "Una grilla no tiene nombre."
    for v, what in ((grid.north, "norte"), (grid.south, "sur")):
        if not -90.0 <= v <= 90.0:
            return f"{name}: latitud {what} fuera de −90…90."
    for v, what in ((grid.west, "oeste"), (grid.east, "este")):
        if not -180.0 <= v <= 180.0:
            return f"{name}: longitud {what} fuera de −180…180."
    if not grid.north > grid.south:
        return f"{name}: la latitud norte debe ser mayor que la sur."
    if not grid.west < grid.east:
        return f"{name}: la longitud oeste debe ser menor que la este."
    if grid.res is not None and not 0.0 < grid.res <= 10.0:
        return f"{name}: resolución fuera de rango (0…10°)."
    return None


def validate_grids(grids):
    errors, seen = [], set()
    for g in grids:
        err = validate_grid(g)
        if err:
            errors.append(err)
        key = g.name.strip().lower()
        if key and key in seen:
            errors.append(f"Nombre de grilla repetido: {g.name}.")
        seen.add(key)
    return errors


def factory_grids():
    return [Grid.from_dict(dict(d, builtin=True)) for d in FACTORY_GRIDS]


def factory_grid(gid):
    for d in FACTORY_GRIDS:
        if d["id"] == gid:
            return Grid.from_dict(dict(d, builtin=True))
    return None


def grids_from_config(cfg):
    """Tabla de grillas de la configuración: vacía o ausente = las de
    fábrica. Se sanea (ids repetidos, sin id) y se agregan al final las de
    fábrica que falten (una versión nueva trae más) sin revivir las que el
    usuario ocultó."""
    raw = cfg.get("grids") if isinstance(cfg, dict) else None
    if not raw:
        return factory_grids()
    out, seen = [], set()
    for d in raw:
        try:
            g = Grid.from_dict(d)
        except (TypeError, ValueError):
            continue
        if not g.id or g.id in seen:
            continue
        if factory_grid(g.id) is not None:
            g.builtin = True
        seen.add(g.id)
        out.append(g)
    for f in factory_grids():
        if f.id not in seen:
            out.append(f)
    return out


def grids_to_config(grids):
    return [g.to_dict() for g in grids]


def find_grid(grids, gid, enabled_only=False):
    for g in grids:
        if g.id == gid and (g.enabled or not enabled_only):
            return g
    return None


def grid_is_modified(grid):
    f = factory_grid(grid.id) if grid.builtin else None
    return f is not None and not grid.same_values(f)


def new_grid_id():
    import uuid
    return "u_" + uuid.uuid4().hex[:8]


def validate_area(area):
    """Mensaje de error (claro, para mostrar) o None."""
    if not CODE_RE.match(area.code or ""):
        return f"Código inválido {area.code!r}: hasta 4 letras o dígitos (p. ej. SAEF)."
    for v, what in ((area.north, "norte"), (area.south, "sur")):
        if not -90.0 <= v <= 90.0:
            return f"{area.code}: latitud {what} fuera de −90…90."
    for v, what in ((area.west, "oeste"), (area.east, "este")):
        if not -180.0 <= v <= 180.0:
            return f"{area.code}: longitud {what} fuera de −180…180."
    if not area.north > area.south:
        return (f"{area.code}: la latitud norte ({format_coord(area.north, 'lat')}) debe ser mayor "
                f"que la sur ({format_coord(area.south, 'lat')}).")
    if not area.west < area.east:
        return (f"{area.code}: la longitud oeste ({format_coord(area.west, 'lon')}) debe ser menor "
                f"que la este ({format_coord(area.east, 'lon')}).")
    return None


def validate_areas(areas):
    """Lista de mensajes de error (vacía si todo está bien); también detecta
    códigos repetidos."""
    errors = []
    seen = set()
    for a in areas:
        err = validate_area(a)
        if err:
            errors.append(err)
        if a.code in seen:
            errors.append(f"Código repetido: {a.code}.")
        seen.add(a.code)
    return errors


def default_areas():
    return [Area.from_dict(d) for d in DEFAULT_AREAS]


def areas_from_config(cfg):
    """Tabla de áreas de la configuración (o las cinco por defecto)."""
    raw = cfg.get("areas") if isinstance(cfg, dict) else None
    if not raw:
        return default_areas()
    out = []
    for d in raw:
        try:
            a = Area.from_dict(d)
        except (TypeError, ValueError):
            continue
        if a.code:
            out.append(a)
    return out or default_areas()


def areas_to_config(areas):
    return [a.to_dict() for a in areas]


def find_area(areas, code):
    code = (code or "").strip().upper()
    for a in areas:
        if a.code == code:
            return a
    return None


# ── Envolvente, margen y redondeo ────────────────────────────────────────────

def clamp_region(region):
    top, bottom, left, right = region
    return (min(90.0, top), max(-90.0, bottom), max(-180.0, left), min(180.0, right))


def envelope(areas, margin=0.0):
    """Zona (top, bottom, left, right) que envuelve a todas las áreas dadas
    más `margin` grados por fuera de cada límite (recortado a ±90 / ±180).
    None si no hay áreas."""
    areas = list(areas)
    if not areas:
        return None
    top = max(a.north for a in areas)
    bottom = min(a.south for a in areas)
    left = min(a.west for a in areas)
    right = max(a.east for a in areas)
    m = float(margin or 0.0)
    return clamp_region((top + m, bottom - m, left - m, right + m))


def round_outward(region, res_deg):
    """Lleva cada límite al múltiplo de `res_deg` que lo contiene (nunca
    achica la zona). Con res None o 0 devuelve la zona tal cual."""
    if region is None or not res_deg:
        return region
    r = float(res_deg)
    top, bottom, left, right = region
    eps = 1e-9

    def up(v):
        return math.ceil(v / r - eps) * r

    def down(v):
        return math.floor(v / r + eps) * r
    out = (up(top), down(bottom), down(left), up(right))
    return clamp_region(tuple(round(v, 6) for v in out))


def region_size(region, res_deg=None):
    """Tamaño de la zona: dict con dlat, dlon (grados), y, si se conoce la
    resolución, nlat, nlon y puntos (una zona de 360° de longitud cuenta el
    meridiano de corte una sola vez, como la grilla que entrega el servidor)."""
    top, bottom, left, right = region
    dlat, dlon = float(top - bottom), float(right - left)
    out = {"dlat": dlat, "dlon": dlon, "nlat": None, "nlon": None, "puntos": None}
    if res_deg:
        r = float(res_deg)
        nlat = int(round(dlat / r)) + 1
        nlon = int(round(dlon / r)) + 1
        if dlon >= 360.0 - 1e-6:
            # La vuelta completa no repite el meridiano de corte (180°E y
            # 180°W son el mismo): 288 columnas a 1,25°, 360 a 1°
            nlon = int(round(360.0 / r))
        out.update({"nlat": nlat, "nlon": nlon, "puntos": nlat * nlon})
    return out


def estimate_bytes(points, n_messages):
    """Tamaño aproximado del GRIB2 (empaquetado simple 16 bits)."""
    if points is None:
        return None
    return int(n_messages * (points * BYTES_PER_POINT + BYTES_PER_MESSAGE))


def format_bytes(n):
    if n is None:
        return "?"
    if n < 1e6:
        return f"{n / 1e3:.0f} kB"
    if n < 1e9:
        return f"{n / 1e6:.1f} MB"
    return f"{n / 1e9:.2f} GB"


def describe_size(region, res_deg=None, n_messages=1):
    """Texto para el diálogo: grados, puntos y tamaño estimado."""
    s = region_size(region, res_deg)
    txt = f"Δlat {s['dlat']:.2f}° × Δlon {s['dlon']:.2f}°"
    if s["puntos"] is not None:
        txt += (f"  ·  {s['nlat']} × {s['nlon']} = {s['puntos']:,} puntos a {res_deg:g}°"
                .replace(",", "."))
        txt += f"  ·  ≈ {format_bytes(estimate_bytes(s['puntos'], max(1, n_messages)))}"
        if n_messages > 1:
            txt += f" ({n_messages} campos)"
    else:
        txt += "  ·  resolución de la fuente desconocida"
    return txt


def crosses_greenwich(region):
    return region is not None and region[2] < 0.0 < region[3]


def reaches_pole(region):
    return region is not None and (region[1] <= -90.0 + 1e-9 or region[0] >= 90.0 - 1e-9)


# ── Etiqueta y procedencia ───────────────────────────────────────────────────

def area_tag(codes=None, mode="fir"):
    """'SAEF+SACF' (en el orden de la tabla), la etiqueta de la grilla con
    nombre ('FDPARG') o 'MANUAL'."""
    if mode == "grid" and codes:
        return str(codes[0])
    if mode != "fir" or not codes:
        return MANUAL_TAG
    return "+".join(c for c in codes)


def area_info(mode, codes, margin, region, region_requested=None):
    """Bloque `area` de la procedencia de una descarga."""
    tag = area_tag(codes, mode)
    return {"modo": mode, "codigos": list(codes or []) if mode in ("fir", "grid") else [], "etiqueta": tag,
            "margen_deg": float(margin or 0.0) if mode == "fir" else 0.0,
            "zona_pedida": list(region) if region is not None else None,
            "zona_servidor": list(region_requested) if region_requested is not None else None}


# ── Cobertura de la grilla obtenida ──────────────────────────────────────────

def check_coverage(region, grid_bbox, tol=1e-6):
    """Comprueba que la grilla obtenida (lonmin, lonmax, latmin, latmax, en
    −180…180) contenga la zona pedida (top, bottom, left, right). Devuelve
    una lista de faltantes en texto (vacía si cubre todo)."""
    if region is None or grid_bbox is None:
        return []
    top, bottom, left, right = region
    lonmin, lonmax, latmin, latmax = grid_bbox
    out = []
    if latmax < top - tol:
        out.append(f"norte: pedido {top:.2f}°, obtenido {latmax:.2f}°")
    if latmin > bottom + tol:
        out.append(f"sur: pedido {bottom:.2f}°, obtenido {latmin:.2f}°")
    if lonmin > left + tol:
        out.append(f"oeste: pedido {left:.2f}°, obtenido {lonmin:.2f}°")
    if lonmax < right - tol:
        out.append(f"este: pedido {right:.2f}°, obtenido {lonmax:.2f}°")
    return out


# ── Exportar / importar la tabla ─────────────────────────────────────────────

CSV_HEADER = ["codigo", "nombre", "lat_norte", "lat_sur", "lon_oeste", "lon_este", "habilitada",
              "a_verificar"]


def export_areas(path, areas, margin=None, fmt=None):
    """Escribe la tabla como JSON o CSV (según la extensión o `fmt`)."""
    fmt = fmt or ("csv" if str(path).lower().endswith(".csv") else "json")
    if fmt == "csv":
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(CSV_HEADER)
            for a in areas:
                w.writerow([a.code, a.name, f"{a.north:.4f}", f"{a.south:.4f}", f"{a.west:.4f}",
                            f"{a.east:.4f}", "1" if a.enabled else "0", "1" if a.verify else "0"])
    else:
        doc = {"formato": "visor-grib-areas", "version": 1, "areas": areas_to_config(areas)}
        if margin is not None:
            doc["margen_deg"] = float(margin)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2)
    return path


def _truthy(s):
    return str(s).strip().lower() in ("1", "true", "si", "sí", "x", "yes")


def parse_areas_text(text, fmt):
    """Contenido de un archivo (texto) → (áreas, margen o None)."""
    if fmt == "json":
        doc = json.loads(text)
        items = doc.get("areas", doc) if isinstance(doc, dict) else doc
        if not isinstance(items, list):
            raise ValueError("El JSON no contiene una lista de áreas.")
        areas = [Area.from_dict(d) for d in items]
        margin = doc.get("margen_deg") if isinstance(doc, dict) else None
        return areas, (float(margin) if margin is not None else None)
    rows = list(csv.reader(io.StringIO(text)))
    rows = [r for r in rows if r and any(c.strip() for c in r)]
    if not rows:
        raise ValueError("El CSV está vacío.")
    head = [c.strip().lower() for c in rows[0]]
    if head[:2] == CSV_HEADER[:2] or "codigo" in head:
        rows = rows[1:]
    areas = []
    for r in rows:
        if len(r) < 6:
            raise ValueError(f"Fila incompleta en el CSV: {r}")
        areas.append(Area(r[0], r[1], parse_coord(r[2], "lat"), parse_coord(r[3], "lat"),
                          parse_coord(r[4], "lon"), parse_coord(r[5], "lon"),
                          _truthy(r[6]) if len(r) > 6 and r[6].strip() else True,
                          _truthy(r[7]) if len(r) > 7 and r[7].strip() else False))
    return areas, None


def import_areas(path):
    """Lee la tabla desde JSON o CSV. Devuelve (áreas, margen o None).
    Lanza ValueError si el contenido no sirve (con los errores de validación)."""
    fmt = "csv" if str(path).lower().endswith(".csv") else "json"
    with open(path, encoding="utf-8-sig") as fh:
        text = fh.read()
    try:
        areas, margin = parse_areas_text(text, fmt)
    except (json.JSONDecodeError, CoordError, KeyError, TypeError) as exc:
        raise ValueError(f"No se pudo leer {os.path.basename(path)}: {exc}") from exc
    errors = validate_areas(areas)
    if errors:
        raise ValueError("El archivo tiene áreas inválidas:\n" + "\n".join(errors))
    if not areas:
        raise ValueError("El archivo no contiene áreas.")
    return areas, margin
