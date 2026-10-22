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
from . import fl_table as flt

# ---------------------------------------------------------------------------
# Constantes de dominio
# ---------------------------------------------------------------------------
MS_TO_KT = 1.943844          # m/s -> nudos
KELVIN = 273.15              # K -> °C

# Niveles de vuelo de la botonera: los 17 OACI del Anexo 3 (fl_table.OACI17)
FLIGHT_LEVELS = list(flt.OACI17)

# Escala de colores continua de velocidad (kt): el color de una velocidad
# es la interpolación lineal (RGB) entre los dos anclajes que la encierran;
# por encima del último anclaje queda el último color. La usan las barbas,
# flechas y curvas, el fondo de velocidad, la leyenda del mapa y el perfil
# de la ficha del clic (speed_color), así que todos pintan igual.
# Anclajes con sentido operativo: 0 calma, 30 moderado, 60 umbral de jet
# (OMM), 90 jet definido, 120 jet fuerte, 150 muy fuerte, 200+ extremo.
SPEED_STOPS = [0, 30, 60, 90, 120, 150, 200]
SPEED_COLORS = ["#27348f", "#33a1d6", "#43b04a", "#f2dc3b", "#f0831e", "#d2261f", "#6e0a2e"]
SPEED_TICKS = list(SPEED_STOPS)             # marcas de la leyenda (la última, «200+»)
_SPEED_RGB = np.array([[int(c[i:i + 2], 16) for i in (1, 3, 5)] for c in SPEED_COLORS], dtype=float)


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
    try:
        if float(fl).is_integer() and int(fl) in flt.FL_TABLE:
            return flt.isa_pa(int(fl)) / 100.0      # la tabla del servidor manda
    except (TypeError, ValueError):
        pass
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
    """Color (hex) de la escala continua para una velocidad en kt; gris sin dato."""
    if spd_kt is None or (isinstance(spd_kt, float) and math.isnan(spd_kt)):
        return "#888888"
    s = min(max(float(spd_kt), 0.0), float(SPEED_STOPS[-1]))
    rgb = (int(round(float(np.interp(s, SPEED_STOPS, _SPEED_RGB[:, k])))) for k in range(3))
    return "#%02x%02x%02x" % tuple(rgb)


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


class DerivedField:
    """U o V que no está en el archivo: se calcula del par WDIR/WIND del
    mismo plazo y nivel al leer (ver GribReader._read_values)."""

    def __init__(self, var, wdir_msg, ws_msg):
        self.var = var
        self.wdir = wdir_msg
        self.ws = ws_msg
        self.level_hpa = wdir_msg.level_hpa
        self.step_range = wdir_msg.step_range
        self.valid = wdir_msg.valid
        self.run = wdir_msg.run
        self.index = wdir_msg.index
        self.ni, self.nj = wdir_msg.ni, wdir_msg.nj


class GribReader:
    """Lee un archivo GRIB2 con ecCodes, construye el inventario y entrega
    campos (u, v, t) en niveles de presión, con cache en memoria e
    interpolación vertical lineal en ln(p)."""

    VAR_NAMES = {"u": "UGRD (u)", "v": "VGRD (v)", "t": "TMP (t)",
                 "wdir": "WDIR (dirección)", "ws": "WIND (velocidad)"}

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
            usable = (m.var in ("u", "v", "t", "wdir", "ws") and m.level_hpa is not None
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
        # Viento como dirección y velocidad (WDIR/WIND): donde no hay U/V se
        # derivan de ese par al leer, así todo lo demás trabaja con U/V
        self.wind_format = "uv"
        derived = 0
        for (s, var, lv) in list(self.index):
            if var != "wdir" or (s, "ws", lv) not in self.index:
                continue
            if (s, "u", lv) in self.index or (s, "v", lv) in self.index:
                continue
            pair = (self.index[(s, "wdir", lv)], self.index[(s, "ws", lv)])
            self.index[(s, "u", lv)] = DerivedField("u", *pair)
            self.index[(s, "v", lv)] = DerivedField("v", *pair)
            variables.update(("u", "v"))
            derived += 1
        if derived:
            self.wind_format = "dirspeed" if not ({"u", "v"} & {m.var for m in self.messages}) else "mixto"

        # Niveles de presión descendentes; la superficie (SURFACE_LEVEL) aparte
        self.levels = sorted((lv for lv in levels if lv != SURFACE_LEVEL), reverse=True)
        self.has_surface = SURFACE_LEVEL in levels
        # 'altura' si hay niveles de presión; 'superficie' si sólo hay viento 10 m / T 2 m
        self.kind = "altura" if self.levels else "superficie"
        # Niveles etiquetados por FL (tabla fl_table): primero por la columna
        # ISA (modo WAFS), después por la nominal ×100 (INDRA / OACI / OACI56).
        # Si un modo explica todos los niveles (y, en los nominales, están al
        # menos los 14 de INDRA) el archivo es «por FL»: cada FL cae en un
        # nivel exacto, sin interpolar. Si no, es crudo y se interpola.
        self._classify_fl_levels()
        self.variables = [v for v in ("u", "v", "t") if v in variables]
        if not any(k[1] in ("u", "v", "t") for k in self.index):
            raise ValueError(
                "El archivo no contiene campos U/V/T en niveles de presión "
                "(typeOfLevel isobaricInhPa) ni de superficie (10 m / 2 m) sobre la "
                "grilla principal.")

    def _classify_fl_levels(self):
        """Clasifica `self.levels` con la tabla de FL (ver fl_table.classify)
        y deja fl_mode, fl_labeled, fl_column, fl_levels ({FL: hPa}) y
        unrecognized_levels. También lo usa el lector sintético de los tests."""
        det = flt.classify([lv * 100.0 for lv in self.levels])
        said = flt.labeled_by_provenance(self._read_provenance())
        self.fl_mode = det["mode"]
        if said is None:
            self.fl_labeled = bool(det["labeled"])
            self.fl_decided_by = "deducción" if self.levels else None
        else:
            # La procedencia manda: por Nivel si los niveles se explican con
            # un modo (aunque sean pocos FL), crudo aunque coincidan con
            # etiquetas nominales
            self.fl_labeled = bool(said and det["mode"] and not det["unrecognized"])
            self.fl_decided_by = "procedencia"
        self.fl_column = det["column"]
        self.unrecognized_levels = [pa / 100.0 for pa in det["unrecognized"]]
        self.fl_levels = {}
        if self.fl_labeled:
            for lv in self.levels:
                fl = det["fls"].get(int(round(lv * 100.0)))
                if fl is not None and fl not in self.fl_levels:
                    self.fl_levels[fl] = lv
        self.is_wafs = self.fl_labeled

    def _read_provenance(self):
        """`archivo.json` de procedencia junto al archivo, o None."""
        path = getattr(self, "path", None)
        if not path or not os.path.isfile(path + ".json"):
            return None
        try:
            import json
            with open(path + ".json", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return None

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
        array (nj, ni) orientado con latitudes y longitudes ascendentes.
        Un DerivedField (U o V a partir de WDIR/WIND) se calcula de sus dos
        mensajes."""
        if isinstance(msg, DerivedField):
            from .wind_format import dirspeed_to_uv
            direc = self._read_values(msg.wdir)
            spd = self._read_values(msg.ws)
            u, v = dirspeed_to_uv(direc, spd)
            return u if msg.var == "u" else v
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

    def level_label(self, level_hpa):
        """Texto de un nivel para el panel: 'FL300 · 300 hPa (300.9 ISA)' en
        archivos etiquetados por FL, '300 hPa' en los demás."""
        for fl, lv in getattr(self, "fl_levels", {}).items():
            if lv == level_hpa:
                return self.fl_text(fl)
        return f"{level_hpa:g} hPa"

    def fl_text(self, fl):
        """'FL050 · 850 hPa (843.1 ISA)': etiqueta y presión exacta del FL."""
        fl = int(fl)
        isa = flt.isa_pa(fl) / 100.0 if fl in flt.FL_TABLE else fl_to_hpa(fl)
        lv = getattr(self, "fl_levels", {}).get(fl)
        if lv is not None and getattr(self, "fl_column", None) == "nominal":
            return f"FL{fl:03d} · {lv:g} hPa ({isa:g} ISA)"
        return f"FL{fl:03d} · {isa:g} hPa"

    def available_fls(self):
        """FL que el archivo puede mostrar: los etiquetados si es por FL; si
        es crudo, los de la tabla cuya presión ISA cae dentro de los niveles
        del archivo (no se extrapola)."""
        if getattr(self, "fl_labeled", False):
            return sorted(self.fl_levels)
        if not self.levels:
            return []
        p_max, p_min = max(self.levels), min(self.levels)
        return [fl for fl in flt.FLS if p_min <= flt.isa_pa(fl) / 100.0 <= p_max]

    def fields_for_fl(self, step_idx, fl):
        """u, v, t para un nivel de vuelo: en un archivo etiquetado por FL el
        nivel exacto del FL (modo 'wafs'); si no, interpolación en ln(p) a la
        presión ISA exacta de la tabla."""
        lv = getattr(self, "fl_levels", {}).get(int(fl))
        if lv is not None and any((step_idx, var, lv) in self.index for var in ("u", "v", "t")):
            u, v, t, info = self.get_level_fields(step_idx, lv)
            info["mode"] = "wafs"
            info["fl"] = int(fl)
            info["p"] = flt.isa_pa(int(fl)) / 100.0 if int(fl) in flt.FL_TABLE else lv
            info["label_hpa"] = float(lv)
            return u, v, t, info
        return self.interp_to_pressure(step_idx, fl_to_hpa(fl))

    def true_pressure(self, level_hpa):
        """Presión real del dato de un nivel del archivo (hPa). En un archivo
        etiquetado por FL el dato está en la ISA exacta del FL (la etiqueta
        es nominal: 300 hPa para F300, cuyo dato está en 300.9); en un
        archivo crudo la etiqueta es la presión."""
        fl = self.fl_of_level(level_hpa)
        if fl is not None and fl in flt.FL_TABLE:
            return flt.isa_pa(fl) / 100.0
        return float(level_hpa)

    def fl_of_level(self, level_hpa):
        """FL etiquetado en ese nivel del archivo, o None (archivo crudo)."""
        for fl, lv in getattr(self, "fl_levels", {}).items():
            if lv == level_hpa:
                return int(fl)
        return None

    def profile(self, step_idx, var):
        """[(presión real, etiqueta)] de los niveles de la variable en el
        paso, de abajo hacia arriba (presión descendente)."""
        return sorted(((self.true_pressure(lv), float(lv)) for lv in self.levels_for(step_idx, var)),
                      reverse=True)

    def interp_to_pressure(self, step_idx, p_target):
        """Interpola u, v, t linealmente en ln(p) al nivel p_target (hPa),
        usando la presión real de cada nivel (ISA del FL si el archivo está
        etiquetado por FL). Si p_target cae fuera del rango de niveles
        disponibles se usa el nivel más cercano y se marca 'extrapolated'."""
        info = {"p": float(p_target), "mode": "interp", "extrapolated": False,
                "nearest": None, "bracket": None}
        out = {}
        lnp = math.log(p_target)
        for var in ("u", "v", "t"):
            prof = self.profile(step_idx, var)
            if not prof:
                out[var] = None
                continue
            (p_max, l_max), (p_min, l_min) = prof[0], prof[-1]
            if p_target >= p_max:
                out[var] = self.get_field(step_idx, var, l_max)
                info["extrapolated"] = True
                info["nearest"] = p_max if info["nearest"] is None else info["nearest"]
            elif p_target <= p_min:
                out[var] = self.get_field(step_idx, var, l_min)
                info["extrapolated"] = True
                info["nearest"] = p_min if info["nearest"] is None else info["nearest"]
            else:
                # Buscar niveles consecutivos p1 > p_target > p2
                p1 = p2 = l1 = l2 = None
                for (a, la), (b, lb) in zip(prof[:-1], prof[1:]):
                    if a >= p_target >= b:
                        p1, p2, l1, l2 = a, b, la, lb
                        break
                f1 = self.get_field(step_idx, var, l1)
                f2 = self.get_field(step_idx, var, l2)
                w = (lnp - math.log(p1)) / (math.log(p2) - math.log(p1))
                out[var] = (1.0 - w) * f1 + w * f2
                if info["bracket"] is None:
                    info["bracket"] = (p1, p2)
                    info["bracket_labels"] = (l1, l2)
                    info["nearest"] = p1 if abs(lnp - math.log(p1)) <= abs(lnp - math.log(p2)) else p2
        return out["u"], out["v"], out["t"], info

    # ------------------------------------------------------ consulta puntual
    def step_for_time(self, when):
        """(índice de paso, True si `when` cae dentro de su ventana de
        validez). Fuera de todas las ventanas se toma el paso de validez
        más cercana. (None, False) si no hay pasos o `when` es None."""
        if when is None or not self.steps:
            return None, False
        if when.tzinfo is None:
            when = when.replace(tzinfo=dt.timezone.utc)
        for i, s in enumerate(self.steps):
            if (s.window_start is not None and s.window_end is not None
                    and s.window_start <= when < s.window_end):
                return i, True
        best, best_d = None, None
        for i, s in enumerate(self.steps):
            if s.valid is None:
                continue
            d = abs((s.valid - when).total_seconds())
            if best_d is None or d < best_d:
                best, best_d = i, d
        return best, False

    def grid_index(self, lat, lon, cell="nearest"):
        """(j, i) del punto de grilla que representa a (lat, lon): el más
        cercano ('nearest') o el origen de la celda que lo contiene
        ('origin', esquina suroeste, como el FDP). None si queda fuera."""
        lats, lons = self.lats, self.lons
        if lats is None or lons is None or len(lats) == 0 or len(lons) == 0:
            return None
        dlat = float(abs(lats[1] - lats[0])) if len(lats) > 1 else 1.0
        dlon = float(abs(lons[1] - lons[0])) if len(lons) > 1 else 1.0
        if cell == "origin":
            if lat < lats[0] - 1e-9 or lon < lons[0] - 1e-9:
                return None
            j = int(np.searchsorted(lats, lat + 1e-9, side="right") - 1)
            i = int(np.searchsorted(lons, lon + 1e-9, side="right") - 1)
            if lat > lats[-1] + dlat or lon > lons[-1] + dlon:
                return None
            return max(0, min(j, len(lats) - 1)), max(0, min(i, len(lons) - 1))
        j = int(np.argmin(np.abs(lats - lat)))
        i = int(np.argmin(np.abs(lons - lon)))
        if abs(lats[j] - lat) > dlat / 2.0 + 1e-9 or abs(lons[i] - lon) > dlon / 2.0 + 1e-9:
            return None
        return j, i

    def _layer_at(self, step_idx, p_true, label, j, i):
        """Valores de un nivel del archivo en el punto (j, i)."""
        d = {"p": float(p_true), "label": float(label), "fl": self.fl_of_level(label),
             "u": None, "v": None, "t": None, "spd": None, "dir": None}
        for var in ("u", "v", "t"):
            f = self.get_field(step_idx, var, label)
            if f is not None:
                val = float(f[j, i])
                d[var] = val if np.isfinite(val) else None
        if d["u"] is not None and d["v"] is not None:
            spd, direc = speed_dir_from_uv(d["u"], d["v"])
            d["spd"], d["dir"] = float(spd), float(direc)
        return d

    def point_query(self, step_idx, fl, lat, lon, cell="nearest"):
        """Viento y temperatura en un punto para un FL cualquiera: la capa
        del archivo de abajo ('lower'), la de arriba ('upper') y el valor en
        el FL ('value'), interpolado en ln(p) entre ambas con la presión real
        de cada capa. Si el FL coincide con una capa ('exact') el valor es
        el de esa capa; fuera del rango ('extrapolated') es el de la capa
        más cercana y la otra queda en None. None si el punto está fuera
        de la grilla."""
        idx = self.grid_index(lat, lon, cell)
        if idx is None:
            return None
        j, i = idx
        p_t = fl_to_hpa(fl)
        res = {"fl": int(fl), "p": float(p_t), "j": j, "i": i,
               "lat": float(self.lats[j]), "lon": float(self.lons[i]),
               "lower": None, "upper": None, "value": None,
               "mode": "interp", "extrapolated": False, "w": None}
        present = [v for v in ("u", "v", "t") if self.levels_for(step_idx, v)]
        if not present:
            return res
        # Niveles con todas las variables presentes (si no, los de la primera)
        common = None
        for var in present:
            lv = set(self.levels_for(step_idx, var))
            common = lv if common is None else (common & lv)
        if not common:
            common = set(self.levels_for(step_idx, present[0]))
        prof = sorted(((self.true_pressure(lv), lv) for lv in common), reverse=True)
        exact = [(p, lv) for p, lv in prof if abs(p - p_t) < 0.05]
        if exact:
            p, lv = exact[0]
            k = prof.index((p, lv))
            res["mode"] = "exact"
            res["value"] = self._layer_at(step_idx, p, lv, j, i)
            # prof va de más presión a menos: la capa de abajo es la anterior
            if k > 0:
                res["lower"] = self._layer_at(step_idx, *prof[k - 1], j, i)
            if k + 1 < len(prof):
                res["upper"] = self._layer_at(step_idx, *prof[k + 1], j, i)
            return res
        if p_t > prof[0][0]:
            res["mode"], res["extrapolated"] = "nearest", True
            res["upper"] = self._layer_at(step_idx, *prof[0], j, i)
            res["value"] = dict(res["upper"], p=float(p_t), label=None, fl=int(fl))
            return res
        if p_t < prof[-1][0]:
            res["mode"], res["extrapolated"] = "nearest", True
            res["lower"] = self._layer_at(step_idx, *prof[-1], j, i)
            res["value"] = dict(res["lower"], p=float(p_t), label=None, fl=int(fl))
            return res
        for (a, la), (b, lb) in zip(prof[:-1], prof[1:]):
            if a > p_t > b:
                lower = self._layer_at(step_idx, a, la, j, i)
                upper = self._layer_at(step_idx, b, lb, j, i)
                w = (math.log(p_t) - math.log(a)) / (math.log(b) - math.log(a))
                val = {"p": float(p_t), "label": None, "fl": int(fl),
                       "u": None, "v": None, "t": None, "spd": None, "dir": None}
                for var in ("u", "v", "t"):
                    if lower[var] is not None and upper[var] is not None:
                        val[var] = (1.0 - w) * lower[var] + w * upper[var]
                if val["u"] is not None and val["v"] is not None:
                    spd, direc = speed_dir_from_uv(val["u"], val["v"])
                    val["spd"], val["dir"] = float(spd), float(direc)
                res.update({"lower": lower, "upper": upper, "value": val, "w": float(w)})
                break
        return res

    def column_query(self, step_idx, lat, lon, cell="nearest"):
        """Perfil vertical del punto: todos los niveles del archivo en la
        celda (de más presión a menos, es decir de abajo hacia arriba), cada
        uno como en point_query ('p' real, 'label', 'fl', 'spd', 'dir', 't').
        None si el punto está fuera de la grilla; [] sin niveles."""
        idx = self.grid_index(lat, lon, cell)
        if idx is None:
            return None
        j, i = idx
        present = [v for v in ("u", "v", "t") if self.levels_for(step_idx, v)]
        if not present:
            return []
        common = None
        for var in present:
            lv = set(self.levels_for(step_idx, var))
            common = lv if common is None else (common & lv)
        if not common:
            common = set(self.levels_for(step_idx, present[0]))
        prof = sorted(((self.true_pressure(lv), lv) for lv in common), reverse=True)
        return [self._layer_at(step_idx, p, lv, j, i) for p, lv in prof]

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
        wf = getattr(self, "wind_format", "uv")
        if wf == "dirspeed":
            lines.append("VIENTO: dirección y velocidad (WDIR/WIND); se combinan en U/V al leer")
        elif wf == "mixto":
            lines.append("VIENTO: U/V en algunos niveles y WDIR/WIND en otros (se combinan en U/V)")
        lines.append("NIVELES (hPa): " + ", ".join(f"{lv:g}" for lv in self.levels)
                     + ("  + superficie (viento 10 m / T 2 m)"
                        if getattr(self, "has_surface", False) else ""))
        if getattr(self, "fl_labeled", False):
            fls = sorted(self.fl_levels)
            col = ("presión ISA en Pa" if getattr(self, "fl_column", "") == "isa"
                   else "etiqueta nominal en hPa")
            lines.append(f"FORMATO: etiquetado por FL, modo {self.fl_mode} ({col}): "
                         f"FL{fls[0]:03d}–FL{fls[-1]:03d}, {len(fls)} niveles; el dato está en la "
                         f"presión ISA exacta de cada FL"
                         + ("" if getattr(self, "fl_decided_by", None) != "deducción" else
                            " (deducido de las capas: no hay .json de procedencia)"))
        elif self.levels:
            mode = getattr(self, "fl_mode", None)
            txt = "FORMATO: niveles de presión crudos (los FL se interpolan en ln(p) a la ISA exacta)"
            if mode and getattr(self, "fl_decided_by", None) == "procedencia":
                txt += f"; según la procedencia son capas del modelo, aunque coinciden con etiquetas {mode}"
            elif mode:
                txt += f"; los niveles coinciden con etiquetas {mode} pero faltan FL de INDRA"
            if getattr(self, "unrecognized_levels", None):
                txt += ("; no reconocidos como FL: "
                        + ", ".join(f"{lv:g} hPa" for lv in self.unrecognized_levels))
            lines.append(txt)
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


