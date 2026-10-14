#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
grib_viewer.py
==============

Visor de escritorio para archivos GRIB2 de viento y temperatura generados a
partir de GFS (o cualquier modelo con campos U/V/T en niveles de presión).

Características principales
---------------------------
* Lectura de GRIB2 con los bindings Python de ecCodes, iterando mensaje por
  mensaje (robusto frente a archivos con distintos typeOfLevel o pasos).
* Inventario del archivo: corrida, pasos, horas de validez, variables, niveles
  y grilla, mostrado en un panel de texto.
* Interfaz tkinter con mapa matplotlib embebido (cartopy si está disponible).
* Selección de paso (Current / Next / Advanced o combo con todos los pasos).
* Selección de nivel de vuelo (FL) con conversión ISA a presión e
  interpolación lineal en ln(p), o selección directa de un nivel de presión.
* Barbas de viento en nudos coloreadas por velocidad, contornos de
  temperatura, fondo de velocidad, grilla, "Extra Info" (valores al lado de
  cada barba), zoom/pan, exportación a PNG y CSV.

Uso
---
    python grib_viewer.py [archivo.grib2]

Clases
------
* GribReader : lectura, inventario, cache de campos e interpolación vertical.
* WindPlot   : dibujo del mapa (matplotlib + cartopy opcional).
* App        : interfaz gráfica (tkinter).
"""

import csv
import datetime as dt
import math
import os
import sys
import traceback

import numpy as np

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.ticker as mticker  # noqa: E402
from matplotlib.backends.backend_tkagg import (  # noqa: E402
    FigureCanvasTkAgg, NavigationToolbar2Tk)
from matplotlib.colors import BoundaryNorm, ListedColormap  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

# ---------------------------------------------------------------------------
# Dependencias opcionales
# ---------------------------------------------------------------------------
try:
    import eccodes as ec
    ECCODES_ERROR = None
except Exception as _exc:  # pragma: no cover - depende del entorno
    ec = None
    ECCODES_ERROR = str(_exc)

# Certificados SSL: cartopy descarga las costas de Natural Earth la primera
# vez que se usan; algunos Python (p. ej. instaladores de python.org en macOS)
# no encuentran los certificados del sistema. Si 'certifi' está instalado se
# usa su paquete de certificados.
if "SSL_CERT_FILE" not in os.environ:
    try:
        import certifi
        os.environ["SSL_CERT_FILE"] = certifi.where()
    except Exception:
        pass

try:
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    HAVE_CARTOPY = True
except Exception:  # pragma: no cover - depende del entorno
    ccrs = None
    cfeature = None
    HAVE_CARTOPY = False

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
MS_TO_KT = 1.943844          # m/s -> nudos
KELVIN = 273.15              # K -> °C

# Niveles de vuelo del panel de referencia
FLIGHT_LEVELS = [50, 100, 140, 180, 240, 270, 300, 320, 340, 360, 390, 410, 450, 530]

# Escala de colores fija de velocidad (kt)
SPEED_BINS = [0, 10, 20, 30, 40, 50]
SPEED_COLORS = ["#00e5ff", "#3b7bff", "#2ecc40", "#ffe600", "#ff8c00", "#ff2a2a"]
SPEED_LABELS = ["0–9 kt", "10–19 kt", "20–29 kt", "30–39 kt", "40–49 kt", "≥50 kt"]
SPEED_CMAP = ListedColormap(SPEED_COLORS)
SPEED_NORM = BoundaryNorm(SPEED_BINS + [10000], ncolors=len(SPEED_COLORS))

# Colores de la interfaz (estilo pantalla ATC)
UI_BG = "#1b1b1b"
UI_BG2 = "#2a2a2a"
UI_FG = "#e8e8e8"
UI_ACCENT = "#2d7dd2"
UI_TITLE = "#9ecbff"
MAP_BG = "#000000"
MAP_AX_BG = "#060606"

ECCODES_HELP = (
    "No se pudo importar el módulo 'eccodes'.\n\n"
    "Instalación recomendada:\n"
    "  pip install eccodes          (incluye la biblioteca en ruedas recientes)\n"
    "Si pip no alcanza:\n"
    "  conda install -c conda-forge eccodes python-eccodes\n"
    "  o en macOS: brew install eccodes && pip install eccodes\n"
    "  o en Debian/Ubuntu: sudo apt install libeccodes0 && pip install eccodes\n"
)


# ---------------------------------------------------------------------------
# Utilidades físicas
# ---------------------------------------------------------------------------
def fl_to_hpa(fl):
    """Convierte un nivel de vuelo (centenas de pies) a presión en hPa con la
    atmósfera estándar ISA.

    Tropósfera (h <= 36089 ft): p = 1013.25 * (1 - 6.8756e-6 * h)^5.2559
    Estratosfera baja (isotérmica, 216.65 K): decaimiento exponencial con una
    altura de escala R*T/g = 20805.8 ft.
    """
    h_ft = float(fl) * 100.0
    h_trop = 36089.0
    if h_ft <= h_trop:
        return 1013.25 * (1.0 - 6.8756e-6 * h_ft) ** 5.2559
    p_trop = 1013.25 * (1.0 - 6.8756e-6 * h_trop) ** 5.2559   # ≈ 226.32 hPa
    return p_trop * math.exp(-(h_ft - h_trop) / 20805.8)


def speed_dir_from_uv(u, v):
    """Velocidad (kt) y dirección meteorológica (grados, de dónde viene) a
    partir de componentes U y V en m/s. Acepta escalares o arrays numpy."""
    spd_kt = np.hypot(u, v) * MS_TO_KT
    direc = (270.0 - np.degrees(np.arctan2(v, u))) % 360.0
    return spd_kt, direc


def speed_color(spd_kt):
    """Color de la escala fija para una velocidad en kt."""
    if spd_kt is None or (isinstance(spd_kt, float) and math.isnan(spd_kt)):
        return "#888888"
    idx = int(np.searchsorted(SPEED_BINS, spd_kt, side="right")) - 1
    idx = max(0, min(idx, len(SPEED_COLORS) - 1))
    return SPEED_COLORS[idx]


def fmt_dt(d, with_date=True):
    """Formatea un datetime como 'HH:MM dd/mm' o 'HH:MM'."""
    if d is None:
        return "--:--"
    return d.strftime("%H:%M %d/%m") if with_date else d.strftime("%H:%M")


# ---------------------------------------------------------------------------
# Lectura de GRIB
# ---------------------------------------------------------------------------
class GribMessage:
    """Metadatos mínimos de un mensaje GRIB (sin los valores)."""

    __slots__ = ("index", "offset", "var", "short_name", "name", "units",
                 "type_of_level", "level", "level_hpa", "step_range",
                 "end_step", "data_date", "data_time", "run", "valid",
                 "ni", "nj", "grid_type")

    def __init__(self):
        for name in self.__slots__:
            setattr(self, name, None)


class GribStep:
    """Un paso de pronóstico: rango de paso, hora de validez y ventana."""

    def __init__(self, step_range, run, valid):
        self.step_range = step_range      # texto, ej. "6" o "6-9"
        self.run = run                    # datetime UTC de la corrida
        self.valid = valid                # datetime UTC de validez
        self.window_start = valid         # inicio de ventana de validez
        self.window_end = valid           # fin de ventana (se completa luego)

    @property
    def hours(self):
        """Horas de pronóstico (fin del rango)."""
        if self.run is None or self.valid is None:
            return None
        return (self.valid - self.run).total_seconds() / 3600.0

    def label(self):
        h = self.hours
        hs = f"+{h:g}h" if h is not None else self.step_range
        return f"{hs}  {fmt_dt(self.valid)} UTC"


class GribReader:
    """Lee un archivo GRIB2 con ecCodes, construye el inventario y entrega
    campos (u, v, t) en niveles de presión, con cache en memoria e
    interpolación vertical lineal en ln(p)."""

    VAR_NAMES = {"u": "UGRD (u)", "v": "VGRD (v)", "t": "TMP (t)"}

    def __init__(self, path):
        if ec is None:
            raise RuntimeError(ECCODES_HELP)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"No existe el archivo: {path}")
        self.path = path
        self.messages = []          # lista de GribMessage
        self.steps = []             # lista de GribStep ordenada por validez
        self.levels = []            # niveles de presión (hPa) descendentes
        self.variables = []         # variables presentes de interés (u, v, t)
        self.other_messages = []    # mensajes no usados (otros niveles/vars)
        self.index = {}             # (step_idx, var, level_hpa) -> GribMessage
        self.cache = {}             # (step_idx, var, level_hpa) -> ndarray
        self.lats = None            # latitudes 1D ascendentes
        self.lons = None            # longitudes 1D ascendentes (-180..180)
        self.grid = {}              # información de la grilla original
        self.warnings = []
        self._lon_order = None
        self._flip_lat = False
        self._scan()

    # ------------------------------------------------------------------ util
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
        if short in ("u", "v", "t"):
            return short
        upper = short.upper()
        if upper in ("UGRD", "U"):
            return "u"
        if upper in ("VGRD", "V"):
            return "v"
        if upper in ("TMP", "T"):
            return "t"
        disc = cls._get(gid, "discipline", -1, "long")
        cat = cls._get(gid, "parameterCategory", -1, "long")
        num = cls._get(gid, "parameterNumber", -1, "long")
        if (disc, cat, num) == (0, 2, 2):
            return "u"
        if (disc, cat, num) == (0, 2, 3):
            return "v"
        if (disc, cat, num) == (0, 0, 0):
            return "t"
        return None

    @staticmethod
    def _parse_datetime(date_int, time_int):
        """dataDate (YYYYMMDD) + dataTime (HHMM) -> datetime UTC."""
        try:
            date_int = int(date_int)
            time_int = int(time_int)
            return dt.datetime(date_int // 10000, (date_int // 100) % 100,
                               date_int % 100, time_int // 100, time_int % 100,
                               tzinfo=dt.timezone.utc)
        except Exception:
            return None

    # ------------------------------------------------------------------ scan
    def _scan(self):
        """Recorre todos los mensajes del archivo y arma el inventario."""
        n_total = 0
        with open(self.path, "rb") as fh:
            while True:
                gid = ec.codes_grib_new_from_file(fh)
                if gid is None:
                    break
                try:
                    n_total += 1
                    msg = GribMessage()
                    msg.index = n_total
                    msg.offset = self._get(gid, "offset", None, "long")
                    msg.short_name = self._get(gid, "shortName", "?", "str")
                    msg.name = self._get(gid, "name", "?", "str")
                    msg.units = self._get(gid, "units", "", "str")
                    msg.type_of_level = self._get(gid, "typeOfLevel", "?", "str")
                    msg.level = self._get(gid, "level", None, "double")
                    msg.step_range = str(self._get(gid, "stepRange", "0", "str"))
                    msg.end_step = self._get(gid, "endStep", None, "long")
                    msg.data_date = self._get(gid, "dataDate", None, "long")
                    msg.data_time = self._get(gid, "dataTime", None, "long")
                    msg.run = self._parse_datetime(msg.data_date, msg.data_time)
                    msg.valid = self._parse_datetime(
                        self._get(gid, "validityDate", None, "long"),
                        self._get(gid, "validityTime", None, "long"))
                    msg.ni = self._get(gid, "Ni", None, "long")
                    msg.nj = self._get(gid, "Nj", None, "long")
                    msg.grid_type = self._get(gid, "gridType", "?", "str")
                    msg.var = self._classify(gid)

                    # Nivel en hPa (isobaricInhPa o isobaricInPa)
                    if msg.type_of_level == "isobaricInhPa" and msg.level is not None:
                        msg.level_hpa = float(msg.level)
                    elif msg.type_of_level == "isobaricInPa" and msg.level is not None:
                        msg.level_hpa = float(msg.level) / 100.0
                    else:
                        msg.level_hpa = None

                    # La grilla se toma del primer mensaje con grilla regular
                    if not self.grid and msg.ni and msg.nj:
                        self._read_grid(gid, msg)

                    self.messages.append(msg)
                finally:
                    ec.codes_release(gid)

        if n_total == 0:
            raise ValueError("El archivo no contiene mensajes GRIB válidos.")
        if not self.grid:
            raise ValueError("No se encontró una grilla regular (Ni/Nj) en el archivo; "
                             "sólo se soportan grillas lat/lon regulares.")

        # Pasos: ordenados por hora de validez (y por stepRange como respaldo)
        step_keys = {}
        for m in self.messages:
            key = (m.valid, m.step_range)
            if key not in step_keys:
                step_keys[key] = GribStep(m.step_range, m.run, m.valid)
        ordered = sorted(step_keys.values(),
                         key=lambda s: (s.valid or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
                                        s.step_range))
        self.steps = ordered
        self._compute_windows()
        step_index = {(s.valid, s.step_range): i for i, s in enumerate(self.steps)}

        # Índice de campos útiles: variable u/v/t en nivel de presión y
        # grilla compatible con la primera
        levels = set()
        variables = set()
        for m in self.messages:
            usable = (m.var in ("u", "v", "t") and m.level_hpa is not None
                      and m.ni == self.grid["ni"] and m.nj == self.grid["nj"])
            if not usable:
                self.other_messages.append(m)
                continue
            key = (step_index[(m.valid, m.step_range)], m.var, m.level_hpa)
            if key in self.index:
                self.warnings.append(
                    f"Mensaje {m.index} duplicado ({m.var} {m.level_hpa:g} hPa, "
                    f"paso {m.step_range}); se usa el primero.")
                continue
            self.index[key] = m
            levels.add(m.level_hpa)
            variables.add(m.var)

        self.levels = sorted(levels, reverse=True)
        self.variables = [v for v in ("u", "v", "t") if v in variables]
        if not self.index:
            raise ValueError(
                "El archivo no contiene campos U/V/T en niveles de presión "
                "(typeOfLevel isobaricInhPa) sobre la grilla principal.")

    def _read_grid(self, gid, msg):
        """Lee la descripción de la grilla y prepara el reordenamiento
        (latitudes ascendentes, longitudes -180..180 ascendentes)."""
        ni, nj = int(msg.ni), int(msg.nj)
        lats = np.asarray(ec.codes_get_double_array(gid, "latitudes")).reshape(nj, ni)
        lons = np.asarray(ec.codes_get_double_array(gid, "longitudes")).reshape(nj, ni)
        lat1d = lats[:, 0].copy()
        lon1d = lons[0, :].copy()
        lon_norm = ((lon1d + 180.0) % 360.0) - 180.0
        order = np.argsort(lon_norm, kind="stable")
        self._lon_order = order
        self._flip_lat = bool(lat1d[0] > lat1d[-1])
        self.lons = lon_norm[order]
        self.lats = lat1d[::-1].copy() if self._flip_lat else lat1d
        self.grid = {
            "grid_type": msg.grid_type,
            "ni": ni,
            "nj": nj,
            "lat_first": self._get(gid, "latitudeOfFirstGridPointInDegrees", float(lats[0, 0]), "double"),
            "lon_first": self._get(gid, "longitudeOfFirstGridPointInDegrees", float(lons[0, 0]), "double"),
            "lat_last": self._get(gid, "latitudeOfLastGridPointInDegrees", float(lats[-1, -1]), "double"),
            "lon_last": self._get(gid, "longitudeOfLastGridPointInDegrees", float(lons[-1, -1]), "double"),
            "di": self._get(gid, "iDirectionIncrementInDegrees", None, "double"),
            "dj": self._get(gid, "jDirectionIncrementInDegrees", None, "double"),
            "j_positive": self._get(gid, "jScansPositively", None, "long"),
        }

    def _compute_windows(self):
        """Calcula la ventana de validez de cada paso. Si el stepRange es un
        rango 'a-b' se usa directamente; si no, va desde la validez del paso
        hasta la validez del siguiente (o el intervalo típico entre pasos)."""
        n = len(self.steps)
        for i, s in enumerate(self.steps):
            start, end = s.valid, None
            if s.run is not None and "-" in s.step_range:
                try:
                    a, b = s.step_range.split("-")
                    start = s.run + dt.timedelta(hours=float(a))
                    end = s.run + dt.timedelta(hours=float(b))
                except ValueError:
                    end = None
            if end is None and s.valid is not None:
                if i + 1 < n and self.steps[i + 1].valid is not None:
                    end = self.steps[i + 1].valid
                elif i > 0 and self.steps[i - 1].valid is not None:
                    end = s.valid + (s.valid - self.steps[i - 1].valid)
                else:
                    end = s.valid + dt.timedelta(hours=3)
            s.window_start, s.window_end = start, end

    # ------------------------------------------------------------- lectura
    def _read_values(self, msg):
        """Lee los valores de un mensaje (por offset) y los devuelve como
        array (nj, ni) orientado con latitudes y longitudes ascendentes."""
        with open(self.path, "rb") as fh:
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
        arr = values.reshape(self.grid["nj"], self.grid["ni"])
        if self._flip_lat:
            arr = arr[::-1, :]
        arr = arr[:, self._lon_order]
        return np.ascontiguousarray(arr)

    def get_field(self, step_idx, var, level_hpa):
        """Campo 2D (nj, ni) de la variable en el nivel y paso dados, o None
        si no existe. Los campos leídos quedan en cache."""
        key = (step_idx, var, float(level_hpa))
        if key in self.cache:
            return self.cache[key]
        msg = self.index.get(key)
        if msg is None:
            return None
        arr = self._read_values(msg)
        self.cache[key] = arr
        return arr

    def levels_for(self, step_idx, var):
        """Niveles (hPa, descendentes) disponibles para una variable y paso."""
        return sorted({lv for (s, v, lv) in self.index if s == step_idx and v == var},
                      reverse=True)

    def get_level_fields(self, step_idx, level_hpa):
        """u, v, t en un nivel exacto del archivo (sin interpolar)."""
        u = self.get_field(step_idx, "u", level_hpa)
        v = self.get_field(step_idx, "v", level_hpa)
        t = self.get_field(step_idx, "t", level_hpa)
        info = {"p": float(level_hpa), "mode": "nivel", "extrapolated": False,
                "nearest": float(level_hpa), "bracket": None}
        return u, v, t, info

    def interp_to_pressure(self, step_idx, p_target):
        """Interpola u, v, t linealmente en ln(p) al nivel p_target (hPa).
        Si p_target cae fuera del rango de niveles disponibles se usa el
        nivel más cercano y se marca 'extrapolated'."""
        info = {"p": float(p_target), "mode": "interp", "extrapolated": False,
                "nearest": None, "bracket": None}
        out = {}
        lnp = math.log(p_target)
        for var in ("u", "v", "t"):
            lv = self.levels_for(step_idx, var)
            if not lv:
                out[var] = None
                continue
            p_max, p_min = lv[0], lv[-1]
            if p_target >= p_max:
                out[var] = self.get_field(step_idx, var, p_max)
                info["extrapolated"] = True
                info["nearest"] = p_max if info["nearest"] is None else info["nearest"]
            elif p_target <= p_min:
                out[var] = self.get_field(step_idx, var, p_min)
                info["extrapolated"] = True
                info["nearest"] = p_min if info["nearest"] is None else info["nearest"]
            else:
                # Buscar niveles consecutivos p1 > p_target > p2
                p1, p2 = None, None
                for a, b in zip(lv[:-1], lv[1:]):
                    if a >= p_target >= b:
                        p1, p2 = a, b
                        break
                f1 = self.get_field(step_idx, var, p1)
                f2 = self.get_field(step_idx, var, p2)
                w = (lnp - math.log(p1)) / (math.log(p2) - math.log(p1))
                out[var] = (1.0 - w) * f1 + w * f2
                if info["bracket"] is None:
                    info["bracket"] = (p1, p2)
                    info["nearest"] = p1 if abs(lnp - math.log(p1)) <= abs(lnp - math.log(p2)) else p2
        return out["u"], out["v"], out["t"], info

    # ---------------------------------------------------------- inventario
    def run_time(self):
        """datetime UTC de la corrida (del primer paso disponible)."""
        for s in self.steps:
            if s.run is not None:
                return s.run
        return None

    def inventory_text(self):
        """Inventario legible del archivo."""
        g = self.grid
        lines = []
        lines.append(f"Archivo: {os.path.basename(self.path)}")
        lines.append(f"Mensajes: {len(self.messages)}  (útiles: {len(self.index)})")
        run = self.run_time()
        lines.append(f"Corrida: {fmt_dt(run)} UTC" if run else "Corrida: desconocida")
        lines.append("")
        lines.append("PASOS:")
        for i, s in enumerate(self.steps):
            lines.append(f"  [{i}] stepRange={s.step_range:<6} validez {fmt_dt(s.valid)} UTC  "
                         f"ventana [{fmt_dt(s.window_start, False)}–{fmt_dt(s.window_end, False)}]")
        lines.append("")
        lines.append("VARIABLES: " + ", ".join(self.VAR_NAMES[v] for v in self.variables))
        lines.append("NIVELES (hPa): " + ", ".join(f"{lv:g}" for lv in self.levels))
        lines.append("")
        lines.append("GRILLA:")
        lines.append(f"  tipo: {g.get('grid_type')}   Ni={g.get('ni')}  Nj={g.get('nj')}")
        lines.append(f"  primer punto: lat {g.get('lat_first'):.3f}, lon {g.get('lon_first'):.3f}")
        lines.append(f"  último punto: lat {g.get('lat_last'):.3f}, lon {g.get('lon_last'):.3f}")
        di = g.get("di")
        dj = g.get("dj")
        lines.append(f"  incremento: di={di if di is not None else '?'}  dj={dj if dj is not None else '?'}"
                     f"   jScansPositively={g.get('j_positive')}")
        lines.append(f"  (normalizada) lon {self.lons[0]:.2f}..{self.lons[-1]:.2f}, "
                     f"lat {self.lats[0]:.2f}..{self.lats[-1]:.2f}")
        # Detalle de disponibilidad por paso
        lines.append("")
        lines.append("DISPONIBILIDAD POR PASO (variable: nº de niveles):")
        for i, s in enumerate(self.steps):
            parts = []
            for v in self.variables:
                parts.append(f"{v}:{len(self.levels_for(i, v))}")
            lines.append(f"  [{i}] {s.step_range:<6} " + "  ".join(parts))
        if self.other_messages:
            lines.append("")
            lines.append(f"OTROS MENSAJES NO USADOS ({len(self.other_messages)}):")
            shown = {}
            for m in self.other_messages:
                k = (m.short_name, m.type_of_level)
                shown[k] = shown.get(k, 0) + 1
            for (sn, tol), n in sorted(shown.items()):
                lines.append(f"  {sn} @ {tol}: {n} mensaje(s)")
        if self.warnings:
            lines.append("")
            lines.append("AVISOS:")
            lines.extend("  " + w for w in self.warnings)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Dibujo del mapa
# ---------------------------------------------------------------------------
class WindPlot:
    """Encapsula la figura matplotlib (con cartopy si está disponible) y
    dibuja barbas, contornos, leyenda y grilla sobre un fondo oscuro."""

    def __init__(self, master):
        self.fig = Figure(figsize=(9, 7), dpi=100, facecolor=MAP_BG)
        self.canvas = FigureCanvasTkAgg(self.fig, master=master)
        self.use_cartopy = HAVE_CARTOPY
        self.proj = ccrs.PlateCarree() if self.use_cartopy else None
        self.ax = None
        self.has_data = False
        self._features = None           # (costas, fronteras) ya cargadas
        self._features_error = None     # texto del error si no se pudieron cargar
        self._make_axes()
        self._style_axes()
        self.draw_empty()

    # ----------------------------------------------------------- helpers
    def _make_axes(self):
        self.fig.clear()
        if self.use_cartopy:
            self.ax = self.fig.add_subplot(1, 1, 1, projection=self.proj)
        else:
            self.ax = self.fig.add_subplot(1, 1, 1)
        self.fig.subplots_adjust(left=0.06, right=0.99, top=0.95, bottom=0.07)

    def _style_axes(self):
        ax = self.ax
        ax.set_facecolor(MAP_AX_BG)
        for sp in ax.spines.values():
            sp.set_edgecolor("#666666")
        ax.tick_params(colors="#dddddd", labelsize=8)
        ax.xaxis.label.set_color("#dddddd")
        ax.yaxis.label.set_color("#dddddd")

    def _tr(self):
        """kwargs de transformación para cartopy (vacío sin cartopy)."""
        return {"transform": self.proj} if self.use_cartopy else {}

    def get_extent(self):
        """Extensión actual [lonmin, lonmax, latmin, latmax]."""
        try:
            if self.use_cartopy:
                return list(self.ax.get_extent(crs=self.proj))
            x0, x1 = self.ax.get_xlim()
            y0, y1 = self.ax.get_ylim()
            return [x0, x1, y0, y1]
        except Exception:
            return None

    def set_extent(self, extent):
        """Fija la extensión [lonmin, lonmax, latmin, latmax]."""
        lon0, lon1, lat0, lat1 = extent
        if lon1 <= lon0 or lat1 <= lat0:
            return
        if self.use_cartopy:
            self.ax.set_extent([lon0, lon1, lat0, lat1], crs=self.proj)
        else:
            self.ax.set_xlim(lon0, lon1)
            self.ax.set_ylim(lat0, lat1)
        self.canvas.draw_idle()

    def draw_empty(self, message="Abra un archivo GRIB2 para comenzar"):
        self.ax.clear()
        self._style_axes()
        self.has_data = False
        self._base_map()
        self.ax.text(0.5, 0.5, message, transform=self.ax.transAxes, ha="center",
                     va="center", color="#aaaaaa", fontsize=12)
        if self.use_cartopy:
            self.ax.set_global()
        self.canvas.draw_idle()

    def _load_features(self):
        """Carga (y descarga si hace falta) las costas y fronteras de Natural
        Earth a 50 m. Se fuerza la lectura de las geometrías aquí para que un
        fallo de descarga (sin red, SSL) se capture y no rompa el dibujo."""
        if self._features is not None or self._features_error is not None:
            return
        try:
            coast = cfeature.NaturalEarthFeature("physical", "coastline", "50m",
                                                 edgecolor="#c8c8c8", facecolor="none")
            borders = cfeature.NaturalEarthFeature("cultural", "admin_0_boundary_lines_land",
                                                   "50m", edgecolor="#8c8c8c",
                                                   facecolor="none")
            # Fuerza la descarga/lectura de los shapefiles ahora
            list(coast.geometries())
            list(borders.geometries())
            self._features = (coast, borders)
        except Exception as exc:
            self._features_error = f"{type(exc).__name__}: {exc}"

    def _base_map(self):
        """Costas y fronteras (cartopy) o aviso si no está disponible."""
        if self.use_cartopy:
            self._load_features()
            if self._features is not None:
                coast, borders = self._features
                self.ax.add_feature(coast, linewidth=0.8, zorder=3)
                self.ax.add_feature(borders, linewidth=0.6, linestyle="-", zorder=3)
            else:
                self.ax.text(0.99, 0.99,
                             "No se pudieron cargar las costas de Natural Earth "
                             f"(¿sin conexión?): {self._features_error}",
                             transform=self.ax.transAxes, color="#ff9966", fontsize=7,
                             ha="right", va="top", zorder=10, wrap=True)
        else:
            self.ax.set_aspect("equal", adjustable="box")
            self.ax.text(0.99, 0.99, "cartopy no instalado: mapa sin costas ni fronteras",
                         transform=self.ax.transAxes, color="#ff9966", fontsize=7,
                         ha="right", va="top", zorder=10)

    def _gridlines(self, lons, lats, fine):
        """Meridianos/paralelos cada 10° con etiquetas y, opcionalmente, la
        grilla fina del archivo."""
        dlon = float(abs(lons[1] - lons[0])) if len(lons) > 1 else 1.0
        dlat = float(abs(lats[1] - lats[0])) if len(lats) > 1 else 1.0
        if self.use_cartopy:
            gl = self.ax.gridlines(crs=self.proj, draw_labels=True,
                                   xlocs=mticker.MultipleLocator(10),
                                   ylocs=mticker.MultipleLocator(10),
                                   color="#5a5a5a", linewidth=0.6, linestyle="--", zorder=2)
            gl.top_labels = False
            gl.right_labels = False
            gl.xlabel_style = {"color": "#dddddd", "size": 8}
            gl.ylabel_style = {"color": "#dddddd", "size": 8}
            if fine:
                self.ax.gridlines(crs=self.proj, draw_labels=False,
                                  xlocs=mticker.MultipleLocator(dlon),
                                  ylocs=mticker.MultipleLocator(dlat),
                                  color="#333333", linewidth=0.4, zorder=1)
        else:
            self.ax.xaxis.set_major_locator(mticker.MultipleLocator(10))
            self.ax.yaxis.set_major_locator(mticker.MultipleLocator(10))
            self.ax.xaxis.set_minor_locator(mticker.MultipleLocator(dlon))
            self.ax.yaxis.set_minor_locator(mticker.MultipleLocator(dlat))
            self.ax.grid(True, which="major", color="#5a5a5a", linewidth=0.6, linestyle="--")
            if fine:
                self.ax.grid(True, which="minor", color="#333333", linewidth=0.4)
            self.ax.set_xlabel("Longitud")
            self.ax.set_ylabel("Latitud")

    def _legend(self):
        handles = [Line2D([0], [0], color=c, lw=3) for c in SPEED_COLORS]
        leg = self.ax.legend(handles, SPEED_LABELS, loc="lower left", fontsize=7,
                             title="Viento (kt)", title_fontsize=8, facecolor="#111111",
                             edgecolor="#777777", labelcolor="#eeeeee", framealpha=0.85)
        leg.get_title().set_color("#eeeeee")
        leg.set_zorder(20)

    # -------------------------------------------------------------- draw
    def draw(self, lats, lons, u, v, t, opts):
        """Dibuja el mapa.

        lats, lons : arrays 1D ascendentes.
        u, v       : componentes en m/s (arrays 2D o None).
        t          : temperatura en K (array 2D o None).
        opts       : dict con claves
            mode        'viento' | 'temperatura' | 'ambos'
            show_wind   bool  (False = capa de viento deshabilitada)
            extra_info  bool  (velocidad/temperatura al lado de cada barba)
            grid        bool  (grilla fina del archivo)
            fill        bool  (fondo de velocidad en contornos rellenos)
            stride      int   (submuestreo de barbas)
            extent      [lonmin, lonmax, latmin, latmax] o None
            title       str
        """
        ax = self.ax
        ax.clear()
        self._style_axes()
        self._base_map()
        tr = self._tr()

        X, Y = np.meshgrid(lons, lats)
        stride = max(1, int(opts.get("stride", 1)))
        sl = (slice(None, None, stride), slice(None, None, stride))
        mode = opts.get("mode", "viento")
        show_wind = opts.get("show_wind", True)
        wind_ok = (u is not None and v is not None)
        temp_ok = t is not None
        draw_wind = show_wind and wind_ok and mode in ("viento", "ambos")
        draw_temp = show_wind and temp_ok and mode in ("temperatura", "ambos")
        extra = opts.get("extra_info", False)

        spd = direc = None
        if wind_ok:
            uk = np.ma.masked_invalid(u * MS_TO_KT)
            vk = np.ma.masked_invalid(v * MS_TO_KT)
            spd, direc = speed_dir_from_uv(u, v)
            spd = np.ma.masked_invalid(spd)

        # Fondo de velocidad
        if draw_wind and opts.get("fill", False):
            top = max(float(np.nanmax(spd)) + 1.0, SPEED_BINS[-1] + 10.0)
            ax.contourf(X, Y, spd, levels=SPEED_BINS + [top], colors=SPEED_COLORS,
                        alpha=0.30, zorder=1, **tr)

        # Contornos de temperatura cada 2 °C
        if draw_temp:
            tc = np.ma.masked_invalid(t - KELVIN)
            if tc.count() > 0:
                tmin = math.floor(float(tc.min()) / 2.0) * 2.0
                tmax = math.ceil(float(tc.max()) / 2.0) * 2.0
                levels = np.arange(tmin, tmax + 0.1, 2.0)
                if len(levels) >= 2:
                    cs = ax.contour(X, Y, tc, levels=levels, colors="#ff5cf0",
                                    linewidths=0.7, linestyles="solid", zorder=4, **tr)
                    try:
                        ax.clabel(cs, fmt="%d", fontsize=7, colors="#ffb3f7", inline=True)
                    except Exception:
                        pass

        # Barbas de viento coloreadas por velocidad
        if draw_wind:
            ax.barbs(X[sl], Y[sl], uk[sl], vk[sl], spd[sl], cmap=SPEED_CMAP, norm=SPEED_NORM,
                     length=5.5, linewidth=0.7, pivot="middle", flip_barb=(Y[sl] < 0),
                     zorder=5, clip_on=True, **tr)

        # Extra Info: valores numéricos al lado de cada barba
        if extra and show_wind and (draw_wind or draw_temp):
            dlon = float(abs(lons[1] - lons[0])) if len(lons) > 1 else 1.0
            dlat = float(abs(lats[1] - lats[0])) if len(lats) > 1 else 1.0
            xs, ys = X[sl], Y[sl]
            spd_s = spd[sl] if (draw_wind and spd is not None) else None
            t_s = (t[sl] - KELVIN) if draw_temp else None
            nj, ni = xs.shape
            for j in range(nj):
                for i in range(ni):
                    parts = []
                    col = "#dddddd"
                    if spd_s is not None and not np.ma.is_masked(spd_s[j, i]):
                        s_val = float(spd_s[j, i])
                        parts.append(f"{s_val:.0f}")
                        col = speed_color(s_val)
                    if t_s is not None and not np.isnan(t_s[j, i]):
                        parts.append(f"{t_s[j, i]:.0f}°")
                    if parts:
                        txt = ax.text(xs[j, i] + 0.12 * dlon * stride,
                                      ys[j, i] + 0.12 * dlat * stride,
                                      " ".join(parts), fontsize=6, color=col, ha="left",
                                      va="bottom", zorder=6, **tr)
                        # Recorta el texto al área del mapa (no se dibuja fuera).
                        # Con cartopy sólo funciona el recorte por bbox.
                        txt.set_clip_box(ax.bbox)
                        txt.set_clip_on(True)

        # Grilla, leyenda, título
        self._gridlines(lons, lats, opts.get("grid", False))
        if draw_wind:
            self._legend()
        ax.set_title(opts.get("title", ""), color="#e8e8e8", fontsize=10, loc="left")
        if not show_wind:
            ax.text(0.99, 0.01, "Capa de datos deshabilitada", transform=ax.transAxes,
                    ha="right", va="bottom", color="#ff9966", fontsize=8, zorder=10)

        # Extensión
        extent = opts.get("extent")
        if extent is None:
            extent = [float(lons.min()), float(lons.max()), float(lats.min()), float(lats.max())]
        self.set_extent(extent)
        self.has_data = True
        self.canvas.draw_idle()

    def save_png(self, path, dpi=150):
        self.fig.savefig(path, dpi=dpi, facecolor=self.fig.get_facecolor())


# ---------------------------------------------------------------------------
# Interfaz gráfica
# ---------------------------------------------------------------------------
class App(tk.Tk):
    """Ventana principal: mapa a la izquierda y panel de controles a la
    derecha, imitando el panel de un sistema ATC."""

    TIME_LABELS = ["Current (+0)", "Next (+1)", "Advanced (+2)"]
    P_COMBO_NONE = "(interpolar por FL)"

    def __init__(self, path=None):
        super().__init__()
        self.title("Visor GRIB2 – Viento y Temperatura (GFS)")
        self.geometry("1380x860")
        self.minsize(1000, 650)
        self.configure(bg=UI_BG)

        self.reader = None
        self.step_idx = 0
        self.level_mode = "fl"          # 'fl' o 'p'
        self.sel_fl = 300
        self.sel_p = None
        self.wind_enabled = True
        self.current = None             # dict con campos actuales para hover/CSV
        self._updating_ui = False       # evita redibujos recursivos
        self._fl_buttons = {}

        self._setup_style()
        self._build_ui()
        self._bind_events()

        if path:
            self.after(150, lambda: self.open_file(path))

    # ------------------------------------------------------------- estilo
    def _setup_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=UI_BG, foreground=UI_FG, fieldbackground=UI_BG2,
                        bordercolor="#444444", lightcolor=UI_BG, darkcolor=UI_BG)
        style.configure("TFrame", background=UI_BG)
        style.configure("TLabel", background=UI_BG, foreground=UI_FG)
        style.configure("Title.TLabel", background=UI_BG, foreground=UI_TITLE,
                        font=("TkDefaultFont", 10, "bold"))
        style.configure("Status.TLabel", background="#101010", foreground="#9ff09f",
                        font=("TkFixedFont", 10))
        style.configure("TLabelframe", background=UI_BG, foreground=UI_FG, bordercolor="#555555")
        style.configure("TLabelframe.Label", background=UI_BG, foreground=UI_TITLE,
                        font=("TkDefaultFont", 10, "bold"))
        style.configure("TButton", background="#3a3a3a", foreground=UI_FG, padding=3)
        style.map("TButton", background=[("active", "#4a4a4a"), ("pressed", "#555555")])
        style.configure("FL.TButton", background="#3a3a3a", foreground=UI_FG, padding=2,
                        width=6)
        style.configure("Sel.FL.TButton", background=UI_ACCENT, foreground="#ffffff", padding=2,
                        width=6)
        style.map("Sel.FL.TButton", background=[("active", UI_ACCENT)])
        style.configure("TCheckbutton", background=UI_BG, foreground=UI_FG)
        style.map("TCheckbutton", background=[("active", UI_BG)])
        style.configure("TRadiobutton", background=UI_BG, foreground=UI_FG)
        style.map("TRadiobutton", background=[("active", UI_BG)])
        style.configure("TEntry", fieldbackground=UI_BG2, foreground=UI_FG, insertcolor=UI_FG)
        style.configure("TCombobox", fieldbackground=UI_BG2, foreground=UI_FG,
                        background="#3a3a3a", arrowcolor=UI_FG)
        style.map("TCombobox", fieldbackground=[("readonly", UI_BG2)],
                  foreground=[("readonly", UI_FG)])
        style.configure("TSpinbox", fieldbackground=UI_BG2, foreground=UI_FG,
                        background="#3a3a3a", arrowcolor=UI_FG)
        self.option_add("*TCombobox*Listbox.background", UI_BG2)
        self.option_add("*TCombobox*Listbox.foreground", UI_FG)

    # ------------------------------------------------------------ widgets
    def _build_ui(self):
        # Contenedor principal: mapa (izquierda) + panel (derecha)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self)
        left.grid(row=0, column=0, sticky="nsew")
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        self.plot = WindPlot(left)
        self.plot.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        tb_frame = ttk.Frame(left)
        tb_frame.grid(row=1, column=0, sticky="ew")
        self.toolbar = NavigationToolbar2Tk(self.plot.canvas, tb_frame, pack_toolbar=False)
        self.toolbar.config(background=UI_BG)
        self.toolbar.pack(side=tk.LEFT, fill=tk.X)
        self.toolbar.update()

        # Panel derecho con scroll (por si la pantalla es baja)
        right_outer = ttk.Frame(self, width=360)
        right_outer.grid(row=0, column=1, sticky="ns")
        right_outer.rowconfigure(0, weight=1)
        self._panel_canvas = tk.Canvas(right_outer, bg=UI_BG, highlightthickness=0, width=350)
        vsb = ttk.Scrollbar(right_outer, orient="vertical", command=self._panel_canvas.yview)
        self._panel_canvas.configure(yscrollcommand=vsb.set)
        self._panel_canvas.grid(row=0, column=0, sticky="ns")
        vsb.grid(row=0, column=1, sticky="ns")
        panel = ttk.Frame(self._panel_canvas)
        self._panel_window = self._panel_canvas.create_window((0, 0), window=panel, anchor="nw")
        panel.bind("<Configure>", lambda e: self._panel_canvas.configure(
            scrollregion=self._panel_canvas.bbox("all")))
        self._panel_canvas.bind("<Configure>", lambda e: self._panel_canvas.itemconfigure(
            self._panel_window, width=e.width))

        row = 0
        # --- Abrir archivo
        fr = ttk.Frame(panel)
        fr.grid(row=row, column=0, sticky="ew", padx=6, pady=(8, 4))
        row += 1
        ttk.Button(fr, text="Abrir GRIB...", command=self.open_dialog).pack(side=tk.LEFT)
        self.lbl_file = ttk.Label(fr, text="(sin archivo)", foreground="#bbbbbb")
        self.lbl_file.pack(side=tk.LEFT, padx=8)

        # --- STATUS
        st = ttk.LabelFrame(panel, text="STATUS")
        st.grid(row=row, column=0, sticky="ew", padx=6, pady=4)
        row += 1
        self.lbl_run = ttk.Label(st, text="RUN: --", style="Status.TLabel")
        self.lbl_step = ttk.Label(st, text="STEP: --", style="Status.TLabel")
        self.lbl_valid_utc = ttk.Label(st, text="VALIDITY [--:-- – --:--] UTC", style="Status.TLabel")
        self.lbl_valid_loc = ttk.Label(st, text="LOCAL    [--:-- – --:--]", style="Status.TLabel")
        self.lbl_level = ttk.Label(st, text="LEVEL: --", style="Status.TLabel", wraplength=320,
                                   justify=tk.LEFT)
        for w in (self.lbl_run, self.lbl_step, self.lbl_valid_utc, self.lbl_valid_loc, self.lbl_level):
            w.pack(fill=tk.X, padx=4, pady=1)

        # --- TIME
        tf = ttk.LabelFrame(panel, text="TIME")
        tf.grid(row=row, column=0, sticky="ew", padx=6, pady=4)
        row += 1
        self.var_time = tk.IntVar(value=0)
        self.rb_time = []
        self.lbl_time = []
        for i, txt in enumerate(self.TIME_LABELS):
            rb = ttk.Radiobutton(tf, text=txt, value=i, variable=self.var_time,
                                 command=self._on_time_radio)
            rb.grid(row=i, column=0, sticky="w", padx=4, pady=1)
            lb = ttk.Label(tf, text="--", foreground="#9ff09f")
            lb.grid(row=i, column=1, sticky="w", padx=6)
            self.rb_time.append(rb)
            self.lbl_time.append(lb)
        self.fr_steps = ttk.Frame(tf)
        ttk.Label(self.fr_steps, text="Todos los pasos:").pack(side=tk.LEFT, padx=4)
        self.cb_steps = ttk.Combobox(self.fr_steps, state="readonly", width=26)
        self.cb_steps.pack(side=tk.LEFT)
        self.cb_steps.bind("<<ComboboxSelected>>", self._on_step_combo)
        self.fr_steps.grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 2))
        self.fr_steps.grid_remove()

        # --- LEVEL
        lf = ttk.LabelFrame(panel, text="LEVEL")
        lf.grid(row=row, column=0, sticky="ew", padx=6, pady=4)
        row += 1
        grid_fr = ttk.Frame(lf)
        grid_fr.pack(fill=tk.X, padx=2, pady=2)
        for k, fl in enumerate(FLIGHT_LEVELS):
            b = ttk.Button(grid_fr, text=f"F{fl:03d}", style="FL.TButton",
                           command=lambda f=fl: self.select_fl(f))
            b.grid(row=k // 4, column=k % 4, padx=2, pady=2, sticky="ew")
            self._fl_buttons[fl] = b
        for c in range(4):
            grid_fr.columnconfigure(c, weight=1)
        pf = ttk.Frame(lf)
        pf.pack(fill=tk.X, padx=4, pady=(4, 4))
        ttk.Label(pf, text="Nivel de presión:").pack(side=tk.LEFT)
        self.cb_press = ttk.Combobox(pf, state="readonly", width=18,
                                     values=[self.P_COMBO_NONE])
        self.cb_press.current(0)
        self.cb_press.pack(side=tk.LEFT, padx=6)
        self.cb_press.bind("<<ComboboxSelected>>", self._on_press_combo)
        self.lbl_fl_p = ttk.Label(lf, text="", foreground="#bbbbbb")
        self.lbl_fl_p.pack(anchor="w", padx=6, pady=(0, 4))

        # --- Variable
        vf = ttk.LabelFrame(panel, text="VARIABLE")
        vf.grid(row=row, column=0, sticky="ew", padx=6, pady=4)
        row += 1
        self.var_mode = tk.StringVar(value="viento")
        for txt, val in (("Viento", "viento"), ("Temperatura", "temperatura"),
                         ("Viento + Temperatura", "ambos")):
            ttk.Radiobutton(vf, text=txt, value=val, variable=self.var_mode,
                            command=self.redraw).pack(side=tk.LEFT, padx=4, pady=2)

        # --- CONFIG
        cf = ttk.LabelFrame(panel, text="CONFIG")
        cf.grid(row=row, column=0, sticky="ew", padx=6, pady=4)
        row += 1
        self.var_extra = tk.BooleanVar(value=False)
        self.var_grid = tk.BooleanVar(value=False)
        self.var_fill = tk.BooleanVar(value=False)
        ttk.Checkbutton(cf, text="Extra Info (kt / °C junto a cada barba)",
                        variable=self.var_extra, command=self.redraw).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=4)
        ttk.Checkbutton(cf, text="Grilla lat/lon del archivo", variable=self.var_grid,
                        command=self.redraw).grid(row=1, column=0, columnspan=3, sticky="w", padx=4)
        ttk.Checkbutton(cf, text="Fondo de velocidad (contornos rellenos)",
                        variable=self.var_fill, command=self.redraw).grid(
            row=2, column=0, columnspan=3, sticky="w", padx=4)
        ttk.Label(cf, text="Densidad: cada N puntos").grid(row=3, column=0, sticky="w", padx=4, pady=3)
        self.var_stride = tk.IntVar(value=1)
        self.sp_stride = ttk.Spinbox(cf, from_=1, to=10, width=4, textvariable=self.var_stride,
                                     command=self.redraw, wrap=False)
        self.sp_stride.grid(row=3, column=1, sticky="w", padx=4)
        self.sp_stride.bind("<Return>", lambda e: self.redraw())
        bf = ttk.Frame(cf)
        bf.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(4, 4))
        ttk.Button(bf, text="Update", command=self.redraw).pack(side=tk.LEFT, padx=4)
        self.btn_disable = ttk.Button(bf, text="Disable", command=self.toggle_wind)
        self.btn_disable.pack(side=tk.LEFT, padx=4)

        # --- Recuadro (extensión)
        ef = ttk.LabelFrame(panel, text="RECUADRO (lat/lon)")
        ef.grid(row=row, column=0, sticky="ew", padx=6, pady=4)
        row += 1
        self.ent_latmin = self._labeled_entry(ef, "lat min", 0, 0)
        self.ent_latmax = self._labeled_entry(ef, "lat max", 0, 2)
        self.ent_lonmin = self._labeled_entry(ef, "lon min", 1, 0)
        self.ent_lonmax = self._labeled_entry(ef, "lon max", 1, 2)
        bf2 = ttk.Frame(ef)
        bf2.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(4, 4))
        ttk.Button(bf2, text="Aplicar recuadro", command=self.apply_extent).pack(side=tk.LEFT, padx=4)
        ttk.Button(bf2, text="Todo el dominio", command=self.full_extent).pack(side=tk.LEFT, padx=4)

        # --- Exportar
        xf = ttk.Frame(panel)
        xf.grid(row=row, column=0, sticky="ew", padx=6, pady=4)
        row += 1
        ttk.Button(xf, text="Exportar PNG", command=self.export_png).pack(side=tk.LEFT, padx=4)
        ttk.Button(xf, text="Exportar CSV", command=self.export_csv).pack(side=tk.LEFT, padx=4)

        # --- Inventario
        inv = ttk.LabelFrame(panel, text="INVENTARIO")
        inv.grid(row=row, column=0, sticky="nsew", padx=6, pady=4)
        row += 1
        self.txt_inv = ScrolledText(inv, height=14, width=44, bg="#101010", fg="#dddddd",
                                    insertbackground=UI_FG, font=("TkFixedFont", 9),
                                    wrap=tk.NONE, relief=tk.FLAT)
        self.txt_inv.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        self._set_inventory("Sin archivo abierto.\n\n" +
                            ("" if ec is not None else ECCODES_HELP) +
                            ("" if HAVE_CARTOPY else "\ncartopy no instalado: el mapa se dibuja sin costas.\n"))
        panel.columnconfigure(0, weight=1)

        # --- Barra de estado inferior
        self.lbl_status = ttk.Label(self, text="Listo.", style="Status.TLabel", anchor="w")
        self.lbl_status.grid(row=1, column=0, columnspan=2, sticky="ew")

        self._refresh_fl_buttons()
        self._update_level_label()

    def _labeled_entry(self, parent, text, r, c):
        ttk.Label(parent, text=text).grid(row=r, column=c, sticky="e", padx=(6, 2), pady=2)
        e = ttk.Entry(parent, width=9)
        e.grid(row=r, column=c + 1, sticky="w", padx=(0, 6), pady=2)
        e.bind("<Return>", lambda ev: self.apply_extent())
        return e

    def _bind_events(self):
        self.plot.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.plot.canvas.mpl_connect("draw_event", self._on_draw)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        try:
            self.quit()
        finally:
            self.destroy()

    # ------------------------------------------------------------ archivo
    def open_dialog(self):
        path = filedialog.askopenfilename(
            title="Abrir archivo GRIB2",
            filetypes=[("GRIB", "*.grib2 *.grb2 *.grib *.grb"), ("Todos", "*.*")])
        if path:
            self.open_file(path)

    def open_file(self, path):
        if ec is None:
            messagebox.showerror("eccodes no disponible", ECCODES_HELP)
            return
        self.set_status(f"Leyendo {os.path.basename(path)} ...")
        self.update_idletasks()
        try:
            reader = GribReader(path)
        except Exception as exc:
            traceback.print_exc()
            messagebox.showerror("Error al abrir el archivo",
                                 f"No se pudo leer el archivo:\n{path}\n\n{exc}")
            self.set_status("Error al abrir el archivo.")
            return

        if "u" not in reader.variables or "v" not in reader.variables:
            if "t" in reader.variables:
                messagebox.showwarning(
                    "Sin viento",
                    "El archivo no contiene componentes U/V del viento en niveles de "
                    "presión. Sólo se podrá mostrar temperatura.")
                self.var_mode.set("temperatura")
            else:
                messagebox.showerror(
                    "Sin datos de viento",
                    "El archivo no contiene componentes U/V (UGRD/VGRD) ni temperatura "
                    "en niveles de presión.")
                self.set_status("Archivo sin U/V.")
                return

        self.reader = reader
        self.step_idx = 0
        self.current = None
        self.lbl_file.config(text=os.path.basename(path))
        self._set_inventory(reader.inventory_text())
        self._populate_controls()
        self.redraw(keep_extent=False)
        self.set_status(f"Archivo cargado: {path}")

    def _set_inventory(self, text):
        self.txt_inv.config(state=tk.NORMAL)
        self.txt_inv.delete("1.0", tk.END)
        self.txt_inv.insert(tk.END, text)
        self.txt_inv.config(state=tk.DISABLED)

    def _populate_controls(self):
        """Llena los controles de paso y nivel según el inventario."""
        r = self.reader
        self._updating_ui = True
        try:
            # Pasos
            n = len(r.steps)
            for i in range(3):
                if i < n:
                    self.rb_time[i].state(["!disabled"])
                    self.lbl_time[i].config(text=r.steps[i].label())
                else:
                    self.rb_time[i].state(["disabled"])
                    self.lbl_time[i].config(text="--")
            self.var_time.set(0)
            self.cb_steps.config(values=[f"[{i}] {s.label()}" for i, s in enumerate(r.steps)])
            if n > 0:
                self.cb_steps.current(0)
            if n > 3:
                self.fr_steps.grid()
            else:
                self.fr_steps.grid_remove()
            # Niveles de presión
            vals = [self.P_COMBO_NONE] + [f"{lv:g} hPa" for lv in r.levels]
            self.cb_press.config(values=vals)
            self.cb_press.current(0)
            self.level_mode = "fl"
            self.sel_p = None
            # Recuadro
            self._fill_extent_entries([r.lons.min(), r.lons.max(), r.lats.min(), r.lats.max()])
        finally:
            self._updating_ui = False
        self._refresh_fl_buttons()

    # ---------------------------------------------------------- callbacks
    def _on_time_radio(self):
        if self._updating_ui:
            return
        self.step_idx = int(self.var_time.get())
        if self.reader and self.reader.steps:
            self.cb_steps.current(min(self.step_idx, len(self.reader.steps) - 1))
        self.redraw()

    def _on_step_combo(self, _event=None):
        if self._updating_ui:
            return
        idx = self.cb_steps.current()
        if idx < 0:
            return
        self.step_idx = idx
        if idx < 3:
            self.var_time.set(idx)
        else:
            self.var_time.set(-1)
        self.redraw()

    def select_fl(self, fl):
        self.sel_fl = fl
        self.level_mode = "fl"
        self.sel_p = None
        self._updating_ui = True
        try:
            self.cb_press.current(0)
        finally:
            self._updating_ui = False
        self._refresh_fl_buttons()
        self._update_level_label()
        self.redraw()

    def _on_press_combo(self, _event=None):
        if self._updating_ui:
            return
        idx = self.cb_press.current()
        if idx <= 0 or self.reader is None:
            self.level_mode = "fl"
            self.sel_p = None
        else:
            self.level_mode = "p"
            self.sel_p = self.reader.levels[idx - 1]
        self._refresh_fl_buttons()
        self._update_level_label()
        self.redraw()

    def _refresh_fl_buttons(self):
        for fl, b in self._fl_buttons.items():
            sel = (self.level_mode == "fl" and fl == self.sel_fl)
            b.configure(style="Sel.FL.TButton" if sel else "FL.TButton")

    def _update_level_label(self):
        if self.level_mode == "fl":
            self.lbl_fl_p.config(text=f"F{self.sel_fl:03d} ≈ {fl_to_hpa(self.sel_fl):.1f} hPa (ISA)")
        else:
            self.lbl_fl_p.config(text=f"Nivel del archivo: {self.sel_p:g} hPa (sin interpolar)")

    def toggle_wind(self):
        self.wind_enabled = not self.wind_enabled
        self.btn_disable.config(text="Disable" if self.wind_enabled else "Enable")
        self.redraw()

    def apply_extent(self):
        try:
            lat0 = float(self.ent_latmin.get())
            lat1 = float(self.ent_latmax.get())
            lon0 = float(self.ent_lonmin.get())
            lon1 = float(self.ent_lonmax.get())
        except ValueError:
            messagebox.showwarning("Recuadro", "Ingrese valores numéricos en lat/lon min/max.")
            return
        if lat1 <= lat0 or lon1 <= lon0:
            messagebox.showwarning("Recuadro", "Los máximos deben ser mayores que los mínimos.")
            return
        if self.plot.has_data:
            self.plot.set_extent([lon0, lon1, lat0, lat1])

    def full_extent(self):
        if self.reader is None:
            return
        r = self.reader
        self.plot.set_extent([float(r.lons.min()), float(r.lons.max()),
                              float(r.lats.min()), float(r.lats.max())])
        self.toolbar.update()

    def _fill_extent_entries(self, extent):
        lon0, lon1, lat0, lat1 = extent
        for ent, val in ((self.ent_latmin, lat0), (self.ent_latmax, lat1),
                         (self.ent_lonmin, lon0), (self.ent_lonmax, lon1)):
            ent.delete(0, tk.END)
            ent.insert(0, f"{val:.2f}")

    def _on_draw(self, _event):
        """Tras cada dibujo (zoom/pan incluidos) refleja la extensión en los
        campos del recuadro."""
        if self.plot.has_data:
            ext = self.plot.get_extent()
            if ext:
                self._fill_extent_entries(ext)

    def _on_motion(self, event):
        """Muestra lat/lon y valores bajo el cursor en la barra de estado."""
        if event.inaxes is not self.plot.ax or event.xdata is None or event.ydata is None:
            return
        lon, lat = float(event.xdata), float(event.ydata)
        txt = f"Lat {lat:7.2f}   Lon {lon:8.2f}"
        cur = self.current
        if cur is not None and self.reader is not None:
            lons, lats = self.reader.lons, self.reader.lats
            i = int(np.argmin(np.abs(lons - lon)))
            j = int(np.argmin(np.abs(lats - lat)))
            dlon = float(abs(lons[1] - lons[0])) if len(lons) > 1 else 1.0
            dlat = float(abs(lats[1] - lats[0])) if len(lats) > 1 else 1.0
            if abs(lons[i] - lon) <= dlon and abs(lats[j] - lat) <= dlat:
                txt += f"   | punto ({lats[j]:.2f}, {lons[i]:.2f})"
                if cur["spd"] is not None:
                    s = cur["spd"][j, i]
                    d = cur["dir"][j, i]
                    if not np.isnan(s):
                        txt += f"   | Viento {s:5.1f} kt / {d:5.1f}°"
                    else:
                        txt += "   | Viento: sin dato"
                if cur["t"] is not None:
                    tv = cur["t"][j, i]
                    if not np.isnan(tv):
                        txt += f"   | T {tv - KELVIN:6.1f} °C"
        self.set_status(txt)

    def set_status(self, text):
        self.lbl_status.config(text=text)

    # ------------------------------------------------------------- dibujo
    def redraw(self, keep_extent=True):
        """Recalcula los campos del paso/nivel seleccionados y redibuja."""
        if self._updating_ui:
            return
        if self.reader is None:
            self.plot.draw_empty()
            return
        r = self.reader
        if not r.steps:
            return
        self.step_idx = max(0, min(self.step_idx, len(r.steps) - 1))
        step = r.steps[self.step_idx]

        try:
            if self.level_mode == "p" and self.sel_p is not None:
                u, v, t, info = r.get_level_fields(self.step_idx, self.sel_p)
            else:
                u, v, t, info = r.interp_to_pressure(self.step_idx, fl_to_hpa(self.sel_fl))
        except Exception as exc:
            traceback.print_exc()
            messagebox.showerror("Error de lectura", f"No se pudieron leer los campos:\n{exc}")
            return

        spd = direc = None
        if u is not None and v is not None:
            spd, direc = speed_dir_from_uv(u, v)
        self.current = {"u": u, "v": v, "t": t, "spd": spd, "dir": direc, "info": info,
                        "step": step}

        # Textos de STATUS
        self._update_status_panel(step, info, u, v, t)

        # Título del mapa
        run = r.run_time()
        if self.level_mode == "p":
            lvl_txt = f"{info['p']:g} hPa"
        else:
            lvl_txt = f"F{self.sel_fl:03d} ({info['p']:.0f} hPa)"
            if info["extrapolated"]:
                lvl_txt += f" → nivel más cercano {info['nearest']:g} hPa"
            elif info["bracket"]:
                lvl_txt += f" interp. {info['bracket'][0]:g}/{info['bracket'][1]:g} hPa"
        mode_txt = {"viento": "Viento", "temperatura": "Temperatura",
                    "ambos": "Viento + Temperatura"}[self.var_mode.get()]
        title = (f"Corrida {fmt_dt(run)}Z  {step.label()}  |  {lvl_txt}  |  {mode_txt}")

        try:
            stride = int(self.var_stride.get())
        except (tk.TclError, ValueError):
            stride = 1
        extent = self.plot.get_extent() if (keep_extent and self.plot.has_data) else None
        opts = {
            "mode": self.var_mode.get(),
            "show_wind": self.wind_enabled,
            "extra_info": self.var_extra.get(),
            "grid": self.var_grid.get(),
            "fill": self.var_fill.get(),
            "stride": stride,
            "extent": extent,
            "title": title,
        }
        try:
            self.plot.draw(r.lats, r.lons, u, v, t, opts)
        except Exception as exc:
            traceback.print_exc()
            messagebox.showerror("Error al dibujar", f"No se pudo dibujar el mapa:\n{exc}")
            return
        if extent is None:
            self.toolbar.update()

    def _update_status_panel(self, step, info, u, v, t):
        run = self.reader.run_time()
        self.lbl_run.config(text=f"RUN:   {fmt_dt(run)} UTC" if run else "RUN: --")
        h = step.hours
        hs = f"+{h:g} h" if h is not None else step.step_range
        self.lbl_step.config(text=f"STEP:  [{self.step_idx}] {hs}  (stepRange {step.step_range})")
        ws, we = step.window_start, step.window_end
        self.lbl_valid_utc.config(
            text=f"VALIDITY [{fmt_dt(ws, False)}–{fmt_dt(we, False)}] UTC  {ws.strftime('%d/%m/%Y') if ws else ''}")
        if ws is not None and we is not None:
            ls = ws.astimezone()
            le = we.astimezone()
            tzname = ls.tzname() or "local"
            self.lbl_valid_loc.config(
                text=f"LOCAL    [{fmt_dt(ls, False)}–{fmt_dt(le, False)}] {tzname}  {ls.strftime('%d/%m/%Y')}")
        else:
            self.lbl_valid_loc.config(text="LOCAL    [--:-- – --:--]")

        if self.level_mode == "p":
            lvl = f"LEVEL: {info['p']:g} hPa (nivel del archivo)"
        else:
            lvl = f"LEVEL: F{self.sel_fl:03d} = {info['p']:.1f} hPa (ISA)"
            if info["extrapolated"]:
                lvl += f"\n  extrapolado / nivel más cercano: {info['nearest']:g} hPa"
            elif info["bracket"]:
                lvl += f"\n  interpolado en ln(p) entre {info['bracket'][0]:g} y {info['bracket'][1]:g} hPa"
        missing = [n for n, f in (("U", u), ("V", v), ("T", t)) if f is None]
        if missing:
            lvl += f"\n  sin datos de: {', '.join(missing)}"
        if not self.wind_enabled:
            lvl += "\n  capa de datos DESHABILITADA"
        self.lbl_level.config(text=lvl)

    # ---------------------------------------------------------- exportar
    def export_png(self):
        if not self.plot.has_data:
            messagebox.showinfo("Exportar PNG", "No hay mapa para exportar.")
            return
        path = filedialog.asksaveasfilename(
            title="Guardar PNG", defaultextension=".png",
            initialfile=self._default_name("png"),
            filetypes=[("PNG", "*.png")])
        if not path:
            return
        try:
            self.plot.save_png(path)
            self.set_status(f"PNG guardado: {path}")
        except Exception as exc:
            messagebox.showerror("Exportar PNG", f"No se pudo guardar:\n{exc}")

    def export_csv(self):
        if self.current is None or self.reader is None:
            messagebox.showinfo("Exportar CSV", "No hay datos cargados.")
            return
        path = filedialog.asksaveasfilename(
            title="Guardar CSV", defaultextension=".csv",
            initialfile=self._default_name("csv"),
            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        cur = self.current
        lats, lons = self.reader.lats, self.reader.lons

        def cell(arr, j, i):
            if arr is None:
                return ""
            val = arr[j, i]
            return "" if np.isnan(val) else f"{val:.3f}"

        try:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["# archivo", os.path.basename(self.reader.path)])
                w.writerow(["# paso", cur["step"].step_range, "validez_utc",
                            cur["step"].valid.isoformat() if cur["step"].valid else ""])
                w.writerow(["# nivel_hPa", f"{cur['info']['p']:.2f}",
                            "modo", "FL interpolado" if self.level_mode == "fl" else "nivel exacto"])
                w.writerow(["lat", "lon", "u_ms", "v_ms", "velocidad_kt", "direccion_deg", "t_c"])
                tc = (cur["t"] - KELVIN) if cur["t"] is not None else None
                for j in range(len(lats)):
                    for i in range(len(lons)):
                        w.writerow([f"{lats[j]:.3f}", f"{lons[i]:.3f}",
                                    cell(cur["u"], j, i), cell(cur["v"], j, i),
                                    cell(cur["spd"], j, i), cell(cur["dir"], j, i),
                                    cell(tc, j, i)])
            self.set_status(f"CSV guardado: {path}")
        except Exception as exc:
            messagebox.showerror("Exportar CSV", f"No se pudo guardar:\n{exc}")

    def _default_name(self, ext):
        base = os.path.splitext(os.path.basename(self.reader.path))[0] if self.reader else "grib"
        lvl = f"F{self.sel_fl:03d}" if self.level_mode == "fl" else f"{self.sel_p:g}hPa"
        return f"{base}_paso{self.step_idx}_{lvl}.{ext}"


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------
def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    path = argv[0] if argv else None
    app = App(path)
    app.mainloop()


if __name__ == "__main__":
    main()
