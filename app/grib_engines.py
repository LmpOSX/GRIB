# -*- coding: utf-8 -*-
"""Motores de lectura de GRIB2: la biblioteca ecCodes (Python) o el programa
externo wgrib2 de NOAA. Ambos entregan lo mismo al lector:

* ``scan(path)`` → lista de ``GribMessage`` con los metadatos de cada mensaje
  y, para la grilla principal, un ``GridInfo`` con las latitudes y longitudes
  1D **en el orden del archivo**;
* ``read(path, msg)`` → vector 1D de valores en el orden del archivo
  (``nan`` donde falta dato).

El reordenamiento de la grilla (latitudes ascendentes, longitudes −180…180)
lo hace el lector con ``normalize_grid`` / ``orient_values``, así que los dos
motores se comportan igual aguas abajo. Módulo sin Qt.
"""
import datetime as dt
import os
import re
import shutil
import subprocess
import tempfile

import numpy as np

# ---------------------------------------------------------------------------
# Dependencia opcional: ecCodes
# ---------------------------------------------------------------------------
try:
    import eccodes as ec
    ECCODES_ERROR = None
except Exception as _exc:  # pragma: no cover - depende del entorno
    ec = None
    ECCODES_ERROR = str(_exc)

ECCODES_HELP = (
    "No se pudo importar el módulo 'eccodes'.\n\n"
    "Instalación recomendada:\n"
    "  pip install eccodes          (incluye la biblioteca en ruedas recientes)\n"
    "Si pip no alcanza:\n"
    "  conda install -c conda-forge eccodes python-eccodes\n"
    "  o en macOS: brew install eccodes && pip install eccodes\n"
    "  o en Debian/Ubuntu: sudo apt install libeccodes0 && pip install eccodes\n"
)

WGRIB2_HELP = (
    "No se encontró el programa 'wgrib2'.\n\n"
    "Indicá su ruta en Preferencias ▸ Motor, o instalalo y dejalo en el PATH:\n"
    "  macOS: compilarlo desde https://ftp.cpc.ncep.noaa.gov/wd51we/wgrib2/\n"
    "         (o 'conda install -c conda-forge wgrib2')\n"
    "  Debian/Ubuntu: sudo apt install wgrib2\n"
)

# (clave, nombre para mostrar)
ENGINES = [
    ("eccodes", "ecCodes (biblioteca Python)"),
    ("wgrib2", "wgrib2 (programa externo de NOAA)"),
]

# Valor que wgrib2 escribe donde el GRIB no tiene dato
WGRIB2_UNDEFINED = 9.999e20

# Nombre y unidades de las variables que conoce el visor (wgrib2 no las da)
_VAR_INFO = {
    "UGRD": ("u", "U component of wind", "m s**-1"),
    "VGRD": ("v", "V component of wind", "m s**-1"),
    "TMP": ("t", "Temperature", "K"),
    # Viento como dirección (de dónde sopla, grados verdaderos) y velocidad:
    # el lector los combina en U/V al leer (ver GribReader)
    "WDIR": ("wdir", "Wind direction", "Degree true"),
    "WIND": ("ws", "Wind speed", "m s**-1"),
}


# Clave de "nivel" de los campos de superficie (viento a 10 m, T a 2 m) en el
# índice del lector: se guardan como un nivel más, con este valor.
SURFACE_LEVEL = 0.0
SURFACE_MAX_M = 50.0          # alturas sobre el suelo hasta acá cuentan como superficie


def isa_pressure_from_m(h_m):
    """Presión ISA (hPa) de una altura geométrica sobre el nivel del mar."""
    h_ft = float(h_m) / 0.3048
    h_trop = 36089.0
    if h_ft <= h_trop:
        return 1013.25 * (1.0 - 6.8756e-6 * h_ft) ** 5.2559
    p_trop = 1013.25 * (1.0 - 6.8756e-6 * h_trop) ** 5.2559
    import math
    return p_trop * math.exp(-(h_ft - h_trop) / 20805.8)


def level_to_hpa(type_of_level, level):
    """Nivel del mensaje → hPa para el índice del lector: isobáricos tal
    cual; alturas sobre el nivel del mar (productos WAFS por FL) con la ISA;
    alturas sobre el suelo bajas (10 m, 2 m) como SURFACE_LEVEL; otros None."""
    if level is None:
        return None
    if type_of_level == "isobaricInhPa":
        return float(level)
    if type_of_level == "isobaricInPa":
        return float(level) / 100.0
    if type_of_level == "heightAboveSea":
        return round(isa_pressure_from_m(level), 2)
    if type_of_level == "heightAboveGround" and float(level) <= SURFACE_MAX_M:
        return SURFACE_LEVEL
    return None


class EngineUnavailable(RuntimeError):
    """El motor pedido no está disponible en este equipo."""


class GribMessage:
    """Metadatos mínimos de un mensaje GRIB (sin los valores)."""

    __slots__ = ("index", "record", "offset", "var", "short_name", "name", "units",
                 "type_of_level", "level", "level_hpa", "step_range",
                 "end_step", "data_date", "data_time", "run", "valid",
                 "ni", "nj", "grid_type")

    def __init__(self):
        for name in self.__slots__:
            setattr(self, name, None)


class GridInfo:
    """Grilla regular lat/lon tal como viene en el archivo."""

    __slots__ = ("grid_type", "ni", "nj", "lat1d", "lon1d", "lat_first", "lon_first",
                 "i_negative", "alt_rows",
                 "lat_last", "lon_last", "di", "dj", "j_positive")

    def __init__(self, **kw):
        for name in self.__slots__:
            setattr(self, name, kw.get(name))

    def as_dict(self):
        return {k: getattr(self, k) for k in self.__slots__ if k not in ("lat1d", "lon1d")}


def parse_datetime(date_int, time_int):
    """dataDate (YYYYMMDD) + dataTime (HHMM) -> datetime UTC."""
    try:
        date_int = int(date_int)
        time_int = int(time_int)
        return dt.datetime(date_int // 10000, (date_int // 100) % 100,
                           date_int % 100, time_int // 100, time_int % 100,
                           tzinfo=dt.timezone.utc)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# ecCodes
# ---------------------------------------------------------------------------
class EccodesBackend:
    key = "eccodes"

    def __init__(self):
        if ec is None:
            raise EngineUnavailable(ECCODES_HELP)

    def label(self):
        try:
            return f"ecCodes {ec.codes_get_api_version()}"
        except Exception:
            return "ecCodes"

    @staticmethod
    def _get(gid, key, default=None, kind=None):
        """Lee una clave de ecCodes devolviendo default si no existe."""
        try:
            if kind == "long":
                return ec.codes_get_long(gid, key)
            if kind == "double":
                return ec.codes_get_double(gid, key)
            if kind == "str":
                return ec.codes_get_string(gid, key)
            return ec.codes_get(gid, key)
        except Exception:
            return default

    @classmethod
    def _classify(cls, gid):
        """Devuelve 'u', 'v', 't' o None según el parámetro del mensaje.
        Usa shortName y, como respaldo, discipline/category/number GRIB2."""
        short = cls._get(gid, "shortName", "", "str")
        if short in ("u", "v", "t", "wdir", "ws"):
            return short
        upper = short.upper()
        if upper in ("UGRD", "U"):
            return "u"
        if upper in ("VGRD", "V"):
            return "v"
        if upper in ("TMP", "T"):
            return "t"
        if upper == "WDIR":
            return "wdir"
        if upper in ("WIND", "WSPD"):
            return "ws"
        disc = cls._get(gid, "discipline", -1, "long")
        cat = cls._get(gid, "parameterCategory", -1, "long")
        num = cls._get(gid, "parameterNumber", -1, "long")
        if (disc, cat, num) == (0, 2, 2):
            return "u"
        if (disc, cat, num) == (0, 2, 3):
            return "v"
        if (disc, cat, num) == (0, 0, 0):
            return "t"
        if (disc, cat, num) == (0, 2, 0):
            return "wdir"
        if (disc, cat, num) == (0, 2, 1):
            return "ws"
        return None

    def scan(self, path):
        messages = []
        grid = None
        with open(path, "rb") as fh:
            while True:
                gid = ec.codes_grib_new_from_file(fh)
                if gid is None:
                    break
                try:
                    msg = GribMessage()
                    msg.index = len(messages) + 1
                    msg.record = str(msg.index)
                    msg.offset = self._get(gid, "offset", None, "long")
                    msg.short_name = self._get(gid, "shortName", "?", "str")
                    msg.name = self._get(gid, "name", "?", "str")
                    msg.units = self._get(gid, "units", "", "str")
                    msg.type_of_level = self._get(gid, "typeOfLevel", "?", "str")
                    msg.level = self._get(gid, "level", None, "double")
                    if msg.type_of_level in ("isobaricInhPa", "isobaricInPa"):
                        # 'level' trunca a entero (843 para 84310 Pa): los niveles
                        # WAFS (presión ISA de cada FL) necesitan el valor exacto
                        scaled = self._get(gid, "scaledValueOfFirstFixedSurface", None, "long")
                        factor = self._get(gid, "scaleFactorOfFirstFixedSurface", None, "long")
                        if scaled is not None and factor is not None:
                            pa = float(scaled) * 10.0 ** (-int(factor))
                            msg.level = pa / 100.0 if msg.type_of_level == "isobaricInhPa" else pa
                    msg.step_range = str(self._get(gid, "stepRange", "0", "str"))
                    msg.end_step = self._get(gid, "endStep", None, "long")
                    msg.data_date = self._get(gid, "dataDate", None, "long")
                    msg.data_time = self._get(gid, "dataTime", None, "long")
                    msg.run = parse_datetime(msg.data_date, msg.data_time)
                    msg.valid = parse_datetime(
                        self._get(gid, "validityDate", None, "long"),
                        self._get(gid, "validityTime", None, "long"))
                    msg.ni = self._get(gid, "Ni", None, "long")
                    msg.nj = self._get(gid, "Nj", None, "long")
                    msg.grid_type = self._get(gid, "gridType", "?", "str")
                    msg.var = self._classify(gid)
                    msg.level_hpa = level_to_hpa(msg.type_of_level, msg.level)
                    if grid is None and msg.ni and msg.nj:
                        grid = self._read_grid(gid, msg)
                    messages.append(msg)
                finally:
                    ec.codes_release(gid)
        return messages, grid

    def _read_grid(self, gid, msg):
        ni, nj = int(msg.ni), int(msg.nj)
        lats = np.asarray(ec.codes_get_double_array(gid, "latitudes")).reshape(nj, ni)
        lons = np.asarray(ec.codes_get_double_array(gid, "longitudes")).reshape(nj, ni)
        return GridInfo(
            grid_type=msg.grid_type, ni=ni, nj=nj,
            lat1d=lats[:, 0].copy(), lon1d=lons[0, :].copy(),
            lat_first=self._get(gid, "latitudeOfFirstGridPointInDegrees", float(lats[0, 0]), "double"),
            lon_first=self._get(gid, "longitudeOfFirstGridPointInDegrees", float(lons[0, 0]), "double"),
            lat_last=self._get(gid, "latitudeOfLastGridPointInDegrees", float(lats[-1, -1]), "double"),
            lon_last=self._get(gid, "longitudeOfLastGridPointInDegrees", float(lons[-1, -1]), "double"),
            di=self._get(gid, "iDirectionIncrementInDegrees", None, "double"),
            dj=self._get(gid, "jDirectionIncrementInDegrees", None, "double"),
            j_positive=self._get(gid, "jScansPositively", None, "long"),
            i_negative=self._get(gid, "iScansNegatively", 0, "long"),
            alt_rows=bool(self._get(gid, "alternativeRowScanning", 0, "long")),
        )

    def read(self, path, msg):
        with open(path, "rb") as fh:
            fh.seek(int(msg.offset))
            gid = ec.codes_grib_new_from_file(fh)
            if gid is None:
                raise IOError(f"No se pudo releer el mensaje {msg.index}")
            try:
                values = np.asarray(ec.codes_get_double_array(gid, "values"), dtype=float)
                if self._get(gid, "bitmapPresent", 0, "long"):
                    missing = self._get(gid, "missingValue", 9999.0, "double")
                    values = np.where(values == missing, np.nan, values)
            finally:
                ec.codes_release(gid)
        return values


# ---------------------------------------------------------------------------
# wgrib2
# ---------------------------------------------------------------------------
_RE_NXNY = re.compile(r"\((\d+) x (\d+)\)")
_RE_RUN = re.compile(r":D=(\d{14})|:d=(\d{10})")
_RE_VALID = re.compile(r":(?:VT|vt)=(\d{10,14})")
_RE_MB = re.compile(r"^(\d+(?:\.\d+)?) mb$")
_RE_AGL = re.compile(r"^(\d+(?:\.\d+)?) m above ground$")
_RE_MSL = re.compile(r"^(\d+(?:\.\d+)?) m above mean sea level$")
_RE_FTIME = re.compile(r"^(\d+)(?:-(\d+))? (hour|day|min)")
# «input WE:NS»; con filas intercaladas wgrib2 informa «input EW|WE:NS»
_RE_GRID_LL = re.compile(r"lat-lon grid:\((\d+) x (\d+)\).*?input (WE|EW)(\|(?:WE|EW))?:(NS|SN)", re.S)
_RE_GRID_LAT = re.compile(r"lat (-?\d+(?:\.\d+)?) to (-?\d+(?:\.\d+)?) by (-?\d+(?:\.\d+)?)")
_RE_GRID_LON = re.compile(r"lon (-?\d+(?:\.\d+)?) to (-?\d+(?:\.\d+)?) by (-?\d+(?:\.\d+)?)")


def find_wgrib2(hint=""):
    """Ruta ejecutable de wgrib2: la indicada (si sirve), la variable de
    entorno WGRIB2 o el PATH. Devuelve None si no hay."""
    candidates = [hint, os.environ.get("WGRIB2", "")]
    for c in candidates:
        c = os.path.expanduser((c or "").strip())
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return shutil.which("wgrib2")


def wgrib2_version(exe):
    """Primera línea de `wgrib2 -version`, o None si no corre."""
    try:
        out = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    text = (out.stdout or out.stderr or "").strip().splitlines()
    return text[0].strip() if text else None


def _ts(text):
    """YYYYMMDDHH[MMSS] -> datetime UTC."""
    text = text.ljust(14, "0")
    try:
        return dt.datetime.strptime(text, "%Y%m%d%H%M%S").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def parse_inventory_line(line):
    """Línea de `wgrib2 -s -T -VT -nxny` -> GribMessage (sin grilla), o None."""
    fields = line.strip().split(":")
    if len(fields) < 6:
        return None
    msg = GribMessage()
    msg.record = fields[0]
    try:
        msg.index = int(float(fields[0]))
        msg.offset = int(fields[1])
    except ValueError:
        return None
    msg.short_name = fields[3]
    lev = fields[4]
    ftime = fields[5]
    info = _VAR_INFO.get(msg.short_name.upper())
    if info:
        msg.var, msg.name, msg.units = info
    else:
        msg.name, msg.units = msg.short_name, ""
    m = _RE_MB.match(lev)
    if m:
        msg.type_of_level = "isobaricInhPa"
        msg.level = float(m.group(1))
        msg.level_hpa = float(m.group(1))
    else:
        msg.type_of_level = lev
        m = _RE_AGL.match(lev)
        if m:
            msg.type_of_level = "heightAboveGround"
            msg.level = float(m.group(1))
            msg.level_hpa = level_to_hpa("heightAboveGround", msg.level)
        m = _RE_MSL.match(lev)
        if m:
            msg.type_of_level = "heightAboveSea"
            msg.level = float(m.group(1))
            msg.level_hpa = level_to_hpa("heightAboveSea", msg.level)
    # Paso: "anl", "6 hour fcst", "6-9 hour ave fcst", "1 day fcst"
    if ftime.startswith("anl"):
        msg.step_range, msg.end_step = "0", 0
    else:
        m = _RE_FTIME.match(ftime)
        if m:
            a, b, unit = m.groups()
            mult = {"hour": 1.0, "day": 24.0, "min": 1.0 / 60.0}[unit]
            a_h = float(a) * mult
            b_h = float(b) * mult if b else None
            fmt = lambda x: f"{x:g}"  # noqa: E731
            msg.step_range = f"{fmt(a_h)}-{fmt(b_h)}" if b_h is not None else fmt(a_h)
            msg.end_step = b_h if b_h is not None else a_h
        else:
            msg.step_range = ftime
    m = _RE_RUN.search(line)
    if m:
        txt = m.group(1) or m.group(2)
        msg.run = _ts(txt)
        msg.data_date = int(txt[:8])
        msg.data_time = int(txt[8:12]) if len(txt) >= 12 else int(txt[8:10]) * 100
    m = _RE_VALID.search(line)
    if m:
        msg.valid = _ts(m.group(1))
    elif msg.run is not None and msg.end_step is not None:
        msg.valid = msg.run + dt.timedelta(hours=float(msg.end_step))
    m = _RE_NXNY.search(line)
    if m:
        msg.ni, msg.nj = int(m.group(1)), int(m.group(2))
    return msg


def parse_grid(text):
    """Salida de `wgrib2 -d N -grid` -> GridInfo (sólo grillas lat/lon regulares)."""
    m = _RE_GRID_LL.search(text)
    if not m:
        first = text.strip().splitlines()
        kind = first[1].strip() if len(first) > 1 else text.strip()
        raise ValueError("Sólo se soportan grillas lat/lon regulares; wgrib2 informa: " + kind)
    ni, nj = int(m.group(1)), int(m.group(2))
    mlat = _RE_GRID_LAT.search(text)
    mlon = _RE_GRID_LON.search(text)
    if not mlat or not mlon:
        raise ValueError("No se pudo interpretar la grilla que informa wgrib2:\n" + text)
    lat_a, lat_b, dj = (float(x) for x in mlat.groups())
    lon_a, lon_b, di = (float(x) for x in mlon.groups())
    # Las longitudes pueden cruzar 0/360; con barrido E→O («input EW») van en
    # bajada, así que el cruce es hacia el otro lado
    if m.group(3) == "EW":
        lon_b_eff = lon_b if lon_b <= lon_a else lon_b - 360.0
    else:
        lon_b_eff = lon_b if lon_b >= lon_a else lon_b + 360.0
    lat1d = np.linspace(lat_a, lat_b, nj) if nj > 1 else np.array([lat_a])
    lon1d = np.linspace(lon_a, lon_b_eff, ni) if ni > 1 else np.array([lon_a])
    return GridInfo(
        grid_type="regular_ll", ni=ni, nj=nj, lat1d=lat1d, lon1d=lon1d,
        lat_first=lat_a, lon_first=lon_a, lat_last=lat_b, lon_last=lon_b,
        di=di, dj=dj, j_positive=1 if m.group(5) == "SN" else 0,
        i_negative=1 if m.group(3) == "EW" else 0, alt_rows=bool(m.group(4)),
    )


class Wgrib2Backend:
    key = "wgrib2"

    def __init__(self, exe=None):
        self.exe = find_wgrib2(exe or "")
        if not self.exe:
            raise EngineUnavailable(WGRIB2_HELP)
        self.version = wgrib2_version(self.exe)

    def label(self):
        ver = (self.version or "").split(" ")[0]
        return f"wgrib2 {ver} ({self.exe})".replace("  ", " ")

    def _run(self, args, timeout=120):
        try:
            out = subprocess.run([self.exe] + args, capture_output=True, text=True,
                                 timeout=timeout)
        except OSError as exc:
            raise IOError(f"No se pudo ejecutar wgrib2 ({self.exe}): {exc}") from exc
        if out.returncode != 0:
            err = (out.stderr or out.stdout or "").strip().splitlines()
            raise IOError("wgrib2 falló: " + (err[-1] if err else f"código {out.returncode}"))
        return out.stdout

    def scan(self, path):
        text = self._run([path, "-s", "-T", "-VT", "-nxny"])
        messages = []
        for line in text.splitlines():
            msg = parse_inventory_line(line)
            if msg is not None:
                messages.append(msg)
        grid = None
        for msg in messages:
            if msg.ni and msg.nj:
                grid = parse_grid(self._run([path, "-d", msg.record, "-grid"]))
                msg.grid_type = grid.grid_type
                break
        for msg in messages:
            if msg.grid_type is None:
                msg.grid_type = "?"
        return messages, grid

    def read(self, path, msg):
        fd, tmp = tempfile.mkstemp(prefix="wgrib2_", suffix=".bin")
        os.close(fd)
        try:
            # -order raw: mismo orden que en el archivo (como ecCodes); sin
            # cabeceras Fortran; float32 nativo.
            self._run([path, "-d", msg.record, "-order", "raw", "-no_header", "-bin", tmp])
            values = np.fromfile(tmp, dtype=np.float32).astype(float)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
        n = int(msg.ni or 0) * int(msg.nj or 0)
        if n and values.size != n:
            raise IOError(f"wgrib2 devolvió {values.size} valores y la grilla tiene {n}")
        values[values >= WGRIB2_UNDEFINED * 0.999] = np.nan
        return values


def make_backend(engine="eccodes", wgrib2_path=""):
    """Instancia el motor pedido o lanza EngineUnavailable con la ayuda."""
    if engine == "wgrib2":
        return Wgrib2Backend(wgrib2_path)
    if engine in (None, "", "eccodes"):
        return EccodesBackend()
    raise EngineUnavailable(f"Motor desconocido: {engine}")
