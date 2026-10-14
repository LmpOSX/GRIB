# -*- coding: utf-8 -*-
"""Descarga de GRIB2 del GFS desde NOMADS (NOAA) con el servicio "grib
filter", que permite pedir sólo las variables, los niveles y el recorte
geográfico necesarios. Módulo sin Qt: arma las URL y baja los archivos; el
diálogo lo usa desde un hilo.

Referencia: https://nomads.ncep.noaa.gov/  →  "GFS grib filter".
"""
import datetime as dt
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request

GRIB_MAGIC = b"GRIB"


def __getattr__(name):
    """DownloadError / DownloadCancelled viven en sources.base; se resuelven
    tarde para evitar la importación circular (sources.gfs importa este módulo)."""
    if name in ("DownloadError", "DownloadCancelled"):
        from .sources import base
        return getattr(base, name)
    raise AttributeError(name)

NOMADS_BASE = "https://nomads.ncep.noaa.gov/cgi-bin/"

# (clave, nombre, script del filtro, patrón del archivo,
#  script del producto "b" con los niveles intermedios, patrón de ese archivo)
# Los niveles intermedios (cada 25 hPa) están en el producto pgrb2b, que
# existe en las tres resoluciones, pero NOMADS sólo tiene grib filter para
# pgrb2b a 0,25°. A 0,50° el producto pgrb2full ya une pgrb2 + pgrb2b. A
# 1,00° habría que bajar pgrb2b.1p00 entero (~19 MB por paso, sin recorte).
RESOLUTIONS = [
    ("0p25", "0,25°", "filter_gfs_0p25.pl", "gfs.t{cyc:02d}z.pgrb2.0p25.f{fh:03d}",
     "filter_gfs_0p25b.pl", "gfs.t{cyc:02d}z.pgrb2b.0p25.f{fh:03d}"),
    ("0p50", "0,50°", "filter_gfs_0p50.pl", "gfs.t{cyc:02d}z.pgrb2full.0p50.f{fh:03d}",
     None, None),
    ("1p00", "1,00°", "filter_gfs_1p00.pl", "gfs.t{cyc:02d}z.pgrb2.1p00.f{fh:03d}",
     None, None),
]

# Variables ofrecidas: (clave NOMADS, nombre)
VARIABLES = [
    ("UGRD", "Viento U (UGRD)"),
    ("VGRD", "Viento V (VGRD)"),
    ("TMP", "Temperatura (TMP)"),
    ("HGT", "Altura geopotencial (HGT)"),
    ("RH", "Humedad relativa (RH)"),
]

# Niveles de presión (hPa) del producto pgrb2 del GFS
PRESSURE_LEVELS = [1000, 975, 950, 925, 900, 850, 800, 750, 700, 650, 600, 550, 500,
                   450, 400, 350, 300, 250, 200, 150, 100, 70, 50, 30, 20, 10]

# Niveles intermedios (cada 25 hPa) del producto pgrb2b (0,25°) / pgrb2full (0,50°)
EXTRA_LEVELS = [875, 825, 775, 725, 675, 625, 575, 525, 475, 425, 375, 325, 275,
                225, 175, 125]

ALL_LEVELS = sorted(PRESSURE_LEVELS + EXTRA_LEVELS, reverse=True)

# Niveles que usa el visor: los de pgrb2 y, si se piden intermedios, los que
# caen cerca de F320 / F360 / F410
VIEWER_LEVELS = [850, 700, 600, 500, 400, 350, 300, 250, 200, 150, 100]
VIEWER_EXTRA_LEVELS = [275, 225, 175]


def resolution_info(key):
    return next(r for r in RESOLUTIONS if r[0] == key)


def extra_levels_available(resolution):
    """True si la resolución ofrece los niveles intermedios cada 25 hPa."""
    return resolution in ("0p25", "0p50")


CYCLES = [0, 6, 12, 18]
MAX_HOUR = 384
AVAILABILITY_LAG_H = 4.5       # una corrida suele estar completa ~4–5 h después


class DownloadSpec:
    """Qué bajar: corrida, horas, variables, niveles, resolución, zona y destino."""

    def __init__(self, date, cycle, hours, variables, levels, resolution="0p25",
                 region=None, dest_dir=".", basename=None, merge=True):
        """levels puede incluir niveles intermedios (EXTRA_LEVELS); a 0,25° se
        piden al producto pgrb2b y se unen al mismo archivo."""
        self.date = date                      # datetime.date (UTC)
        self.cycle = int(cycle)               # 0, 6, 12, 18
        self.hours = sorted({int(h) for h in hours})
        self.variables = list(variables)      # claves NOMADS
        self.levels = sorted({int(lv) for lv in levels}, reverse=True)
        self.resolution = resolution
        self.region = region                  # (top, bottom, left, right) en grados o None (global)
        self.dest_dir = dest_dir
        self.basename = basename or self.default_basename()
        self.merge = bool(merge)

    @property
    def extra_levels(self):
        """Niveles pedidos que sólo existen en el producto de intermedios."""
        return [lv for lv in self.levels if lv in EXTRA_LEVELS]

    @property
    def main_levels(self):
        return [lv for lv in self.levels if lv in PRESSURE_LEVELS]

    def default_basename(self):
        return f"gfs_{self.date:%Y%m%d}_{self.cycle:02d}z_{self.resolution}"

    def validate(self):
        """Devuelve un mensaje de error o None si la especificación es válida."""
        if self.cycle not in CYCLES:
            return "El ciclo debe ser 00, 06, 12 o 18 UTC."
        if not self.hours:
            return "Elegí al menos una hora de pronóstico."
        if any(h < 0 or h > MAX_HOUR for h in self.hours):
            return f"Las horas de pronóstico van de 0 a {MAX_HOUR}."
        if not self.variables:
            return "Elegí al menos una variable."
        if not self.levels:
            return "Elegí al menos un nivel de presión."
        if self.resolution not in {r[0] for r in RESOLUTIONS}:
            return "Resolución desconocida."
        desconocidos = [lv for lv in self.levels if lv not in ALL_LEVELS]
        if desconocidos:
            return "Niveles que el GFS no ofrece: " + ", ".join(f"{lv}" for lv in desconocidos)
        if self.extra_levels and not extra_levels_available(self.resolution):
            return ("A 1,00° NOMADS no tiene grib filter para el producto pgrb2b, así "
                    "que los niveles intermedios (cada 25 hPa) no se pueden pedir "
                    "recortados; elegí 0,25° o 0,50° o quitalos.")
        if self.region is not None:
            top, bottom, left, right = self.region
            if not (-90 <= bottom < top <= 90):
                return "Latitud: el norte debe ser mayor que el sur (−90…90)."
            if not (-180 <= left <= 360 and -180 <= right <= 360) or left == right:
                return "Longitud: valores entre −180 y 180 (o 0 y 360), distintos entre sí."
        if not self.basename or any(c in self.basename for c in '/\\:*?"<>|'):
            return "Nombre de archivo inválido."
        return None

    def file_paths(self):
        """Rutas de salida: una por paso, o una sola si se unen."""
        if self.merge:
            return [os.path.join(self.dest_dir, self.basename + ".grib2")]
        return [os.path.join(self.dest_dir, f"{self.basename}_f{h:03d}.grib2") for h in self.hours]


def latest_cycle(now=None):
    """Última corrida que debería estar disponible (fecha, ciclo) según la
    hora UTC actual y la demora típica de publicación."""
    now = now or dt.datetime.now(dt.timezone.utc)
    ref = now - dt.timedelta(hours=AVAILABILITY_LAG_H)
    cyc = (ref.hour // 6) * 6
    return ref.date(), cyc


def _filter_url(spec, script, pattern, fh, levels):
    params = [
        ("dir", f"/gfs.{spec.date:%Y%m%d}/{spec.cycle:02d}/atmos"),
        ("file", pattern.format(cyc=spec.cycle, fh=fh)),
    ]
    for var in spec.variables:
        params.append((f"var_{var}", "on"))
    for lv in levels:
        params.append((f"lev_{lv}_mb", "on"))
    if spec.region is not None:
        top, bottom, left, right = spec.region
        params += [("subregion", ""), ("toplat", f"{top:g}"), ("leftlon", f"{left:g}"),
                   ("rightlon", f"{right:g}"), ("bottomlat", f"{bottom:g}")]
    return NOMADS_BASE + script + "?" + urllib.parse.urlencode(params)


def build_urls(spec, fh):
    """URLs del grib filter para una hora de pronóstico: una por producto
    (pgrb2 y, si hay niveles intermedios a 0,25°, pgrb2b). Cada una viene
    como (url, etiqueta)."""
    _key, _name, script, pattern, script_b, pattern_b = resolution_info(spec.resolution)
    extra = spec.extra_levels
    if script_b is None or not extra:
        # Un solo producto (a 0,50° pgrb2full ya incluye los intermedios)
        levels = spec.levels if script_b is None else spec.main_levels
        return [(_filter_url(spec, script, pattern, fh, levels), "")]
    urls = []
    if spec.main_levels:
        urls.append((_filter_url(spec, script, pattern, fh, spec.main_levels), ""))
    urls.append((_filter_url(spec, script_b, pattern_b, fh, extra), "niveles intermedios"))
    return urls


def build_url(spec, fh):
    """URL del producto principal (compatibilidad)."""
    return build_urls(spec, fh)[0][0]


def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def fetch(url, timeout=120, chunk_cb=None, cancel=None, headers=None, max_bytes=None):
    """Baja una URL y devuelve los bytes. chunk_cb(recibidos, total_o_None)
    informa el progreso; cancel() → True aborta con DownloadCancelled;
    max_bytes corta la lectura (para probar conexión sin bajar todo)."""
    hdrs = {"User-Agent": "VisorGRIB/2.0"}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
        total = resp.headers.get("Content-Length")
        total = int(total) if total and total.isdigit() else None
        chunks = []
        got = 0
        while True:
            if cancel is not None and cancel():
                raise DownloadCancelled()
            block = resp.read(256 * 1024)
            if not block:
                break
            chunks.append(block)
            got += len(block)
            if chunk_cb is not None:
                chunk_cb(got, total)
            if max_bytes is not None and got >= max_bytes:
                break
    return b"".join(chunks)


def download(spec, progress_cb=None, cancel=None, fetch_fn=fetch):
    """Compatibilidad: baja una DownloadSpec con la fuente GFS del esquema de
    fuentes (caché desactivada, sin reintentos con espera). fetch_fn puede
    tener la firma vieja fetch_fn(url, chunk_cb=None, cancel=None)."""
    from .sources.gfs import GFSSource
    from .sources.base import DownloadJob

    def _fetch(url, headers=None, chunk_cb=None, cancel=None, **kw):
        return fetch_fn(url, chunk_cb=chunk_cb, cancel=cancel)
    extra = any(lv in EXTRA_LEVELS for lv in spec.levels)
    job = DownloadJob(spec.date, spec.cycle, spec.hours, spec.variables, spec.levels,
                      spec.region, spec.dest_dir, spec.basename, spec.merge,
                      params={"resolucion": spec.resolution, "niveles_intermedios": extra})
    return GFSSource().download(job, progress_cb=progress_cb, cancel=cancel, fetch_fn=_fetch,
                                retry_wait=0, write_provenance=False)
