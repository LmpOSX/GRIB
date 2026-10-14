# -*- coding: utf-8 -*-
"""
Lectura de archivos GRIB2 (motor ecCodes o wgrib2, ver grib_engines),
inventario, cache de campos e interpolación vertical. Módulo sin interfaz gráfica: no importa Qt, Tk ni
matplotlib, así se puede testear y reutilizar por separado.

Contenido
---------
* Constantes de dominio: conversión m/s→kt, niveles de vuelo, escala fija de
  colores por velocidad (es del dominio ATC y no del tema de la interfaz).
* fl_to_hpa, speed_dir_from_uv, speed_color, fmt_dt.
* normalize_grid / orient_values: reordenamiento de la grilla (longitudes
  0–360 → −180..180, latitudes ascendentes).
* GribStep, GribReader (GribMessage y los motores viven en grib_engines).
"""

import datetime as dt
import math
import os

import numpy as np

from .grib_engines import (  # noqa: F401 - reexportados para quien importe de aquí
    ec, ECCODES_ERROR, ECCODES_HELP, WGRIB2_HELP, ENGINES, EngineUnavailable,
    GribMessage, make_backend, find_wgrib2, wgrib2_version, SURFACE_LEVEL,
)

# ---------------------------------------------------------------------------
# Constantes de dominio
# ---------------------------------------------------------------------------
MS_TO_KT = 1.943844          # m/s -> nudos
KELVIN = 273.15              # K -> °C

# Niveles de vuelo del panel de referencia
FLIGHT_LEVELS = [50, 100, 140, 180, 240, 270, 300, 320, 340, 360, 390, 410, 450, 530]

# Escala de colores fija de velocidad (kt)
SPEED_BINS = [0, 10, 20, 30, 40, 50]
SPEED_COLORS = ["#00e5ff", "#3b7bff", "#2ecc40", "#ffe600", "#ff8c00", "#ff2a2a"]
SPEED_LABELS = ["0–9 kt", "10–19 kt", "20–29 kt", "30–39 kt", "40–49 kt", "≥50 kt"]


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
# Reordenamiento de la grilla (funciones puras, testeables sin eccodes)
# ---------------------------------------------------------------------------
def normalize_grid(lat1d, lon1d):
    """Prepara el reordenamiento de una grilla regular lat/lon.

    lat1d, lon1d : arrays 1D con las latitudes y longitudes del archivo, en
                   el orden en que vienen (las longitudes pueden ser 0–360 y
                   las latitudes decrecientes, de norte a sur).

    Devuelve (lats, lons, lon_order, flip_lat):
      lats      latitudes ascendentes
      lons      longitudes normalizadas a −180..180 y ascendentes
      lon_order índices que reordenan las columnas originales
      flip_lat  True si hay que invertir las filas (latitudes decrecientes)
    """
    lat1d = np.asarray(lat1d, dtype=float)
    lon1d = np.asarray(lon1d, dtype=float)
    lon_norm = ((lon1d + 180.0) % 360.0) - 180.0
    lon_order = np.argsort(lon_norm, kind="stable")
    flip_lat = bool(len(lat1d) > 1 and lat1d[0] > lat1d[-1])
    lons = lon_norm[lon_order]
    lats = lat1d[::-1].copy() if flip_lat else lat1d.copy()
    return lats, lons, lon_order, flip_lat


def orient_values(values, nj, ni, flip_lat, lon_order):
    """Reorganiza el vector de valores de un mensaje (nj*ni) en un array
    (nj, ni) con latitudes y longitudes ascendentes, según lo calculado por
    normalize_grid."""
    arr = np.asarray(values, dtype=float).reshape(nj, ni)
    if flip_lat:
        arr = arr[::-1, :]
    arr = arr[:, lon_order]
    return np.ascontiguousarray(arr)


# ---------------------------------------------------------------------------
# Lectura de GRIB
# ---------------------------------------------------------------------------
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

    def __init__(self, path, engine="eccodes", wgrib2_path=""):
        """engine: 'eccodes' (biblioteca Python) o 'wgrib2' (programa externo,
        opcionalmente con su ruta). Lanza EngineUnavailable si no está."""
        self.backend = make_backend(engine, wgrib2_path)
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

    @property
    def engine(self):
        """Clave del motor en uso ('eccodes' o 'wgrib2')."""
        backend = getattr(self, "backend", None)
        return backend.key if backend is not None else "eccodes"

    # ------------------------------------------------------------------ scan
    def _scan(self):
        """Pide al motor los metadatos de todos los mensajes y arma el
        inventario, los pasos y el índice de campos útiles."""
        self.messages, grid = self.backend.scan(self.path)
        if not self.messages:
            raise ValueError("El archivo no contiene mensajes GRIB válidos.")
        if grid is None:
            raise ValueError("No se encontró una grilla regular (Ni/Nj) en el archivo; "
                             "sólo se soportan grillas lat/lon regulares.")
        self.lats, self.lons, self._lon_order, self._flip_lat = normalize_grid(
            grid.lat1d, grid.lon1d)
        self.grid = grid.as_dict()

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

        # Niveles de presión descendentes; la superficie (SURFACE_LEVEL) aparte
        self.levels = sorted((lv for lv in levels if lv != SURFACE_LEVEL), reverse=True)
        self.has_surface = SURFACE_LEVEL in levels
        # 'altura' si hay niveles de presión; 'superficie' si sólo hay viento 10 m / T 2 m
        self.kind = "altura" if self.levels else "superficie"
        self.variables = [v for v in ("u", "v", "t") if v in variables]
        if not self.index:
            raise ValueError(
                "El archivo no contiene campos U/V/T en niveles de presión "
                "(typeOfLevel isobaricInhPa) ni de superficie (10 m / 2 m) sobre la "
                "grilla principal.")

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
        """Lee los valores de un mensaje con el motor y los devuelve como
        array (nj, ni) orientado con latitudes y longitudes ascendentes."""
        values = self.backend.read(self.path, msg)
        return orient_values(values, self.grid["nj"], self.grid["ni"],
                             self._flip_lat, self._lon_order)

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
        """Niveles de presión (hPa, descendentes) disponibles para una variable
        y paso; la superficie no participa de la interpolación."""
        return sorted({lv for (s, v, lv) in self.index
                       if s == step_idx and v == var and lv != SURFACE_LEVEL}, reverse=True)

    def get_level_fields(self, step_idx, level_hpa):
        """u, v, t en un nivel exacto del archivo (sin interpolar)."""
        u = self.get_field(step_idx, "u", level_hpa)
        v = self.get_field(step_idx, "v", level_hpa)
        t = self.get_field(step_idx, "t", level_hpa)
        info = {"p": float(level_hpa), "mode": "nivel", "extrapolated": False,
                "nearest": float(level_hpa), "bracket": None}
        return u, v, t, info

    def get_surface_fields(self, step_idx):
        """Viento a 10 m y temperatura a 2 m (fuentes de superficie)."""
        u, v, t, info = self.get_level_fields(step_idx, SURFACE_LEVEL)
        info["mode"] = "superficie"
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
        backend = getattr(self, "backend", None)      # el lector sintético de tests no tiene
        if backend is not None:
            lines.append(f"Motor: {backend.label()}")
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
        lines.append("NIVELES (hPa): " + ", ".join(f"{lv:g}" for lv in self.levels)
                     + ("  + superficie (viento 10 m / T 2 m)"
                        if getattr(self, "has_surface", False) else ""))
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


