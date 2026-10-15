# -*- coding: utf-8 -*-
"""Fuente NOAA WAFS 0,25° (WAFC Washington) vía WIFS.

El producto OACI de viento y temperatura en altura a 0,25° ya no se publica
en NOMADS (ni en la carpeta del GFS ni en un paquete `wafs`): hoy se obtiene
del WAFS Internet File Service de la FAA, que exige una clave de API
(encabezado X-API-Key) y una cuenta aprobada por la autoridad meteorológica
del Estado y la FAA. La API publica los campos por **nivel de vuelo** (FL050
a FL600 cada 1000 ft para viento, temperatura y altura geopotencial),
agrupados en archivos de tres plazos (por ejemplo F06–F08).

Referencia: https://aviationweather.gov/wifs/users_guide/  (colección
kwbc_wafs_windtempgeo_0p25; ítems YUVDYG006_008FLALL, YTDYG…, YHDYG…).

No verificado contra el servidor: no se cuenta con una clave de WIFS. Los
nombres de ítem, el agrupamiento de plazos y la forma de la respuesta siguen
la guía; «Probar conexión» muestra el error exacto si algo no coincide.
"""
import json

from ..grib_reader import fl_to_hpa
from ..regrid import crop_grib, filter_grib
from .base import Source, Param, Request, DownloadError

WIFS_API = "https://aviationweather.gov/wifs/api/collections"
COLLECTION = "kwbc_wafs_windtempgeo_0p25"

# Niveles de vuelo publicados: FL050…FL600 cada 1000 ft → presión ISA
WAFS_FLIGHT_LEVELS = list(range(50, 601, 10))
WAFS_LEVELS = [round(fl_to_hpa(fl), 1) for fl in WAFS_FLIGHT_LEVELS]

# (clave, texto, T2 del ítem)
WAFS_VARIABLES = [
    ("UV", "Viento U y V (YUVD)", "UV"),
    ("T", "Temperatura (YTD)", "T"),
    ("H", "Altura geopotencial (YHD)", "H"),
]
# Variables del visor (shortName de ecCodes) por clave pedida
_KEEP_VARS = {"UV": ("u", "v"), "T": ("t",), "H": ("gh", "z")}


def bundle_for(step):
    """(inicio, fin) del archivo de tres plazos que contiene `step` según la
    guía: horario F06–F24, cada 3 h F27–F48, cada 6 h F54–F120."""
    if 6 <= step <= 26:
        start = 6 + 3 * ((step - 6) // 3)
        return start, start + 2
    if 27 <= step <= 53:
        start = 27 + 9 * ((step - 27) // 9)
        return start, start + 6
    if 54 <= step <= 120:
        start = 54 + 18 * ((step - 54) // 18)
        return start, start + 12
    raise ValueError(step)


class WAFSSource(Source):
    key = "wafs"
    name = "NOAA WAFS 0,25° (WIFS)"
    model = "WAFC Washington, viento/temperatura OACI por FL (WIFS, FAA)"
    kind = "altura"
    flight_levels = True
    needs_credentials = True
    auth_kinds = ["token"]
    doc_url = "https://aviationweather.gov/wifs/users_guide/"
    description = ("Producto oficial OACI de viento y temperatura en altura: FL050–FL600 cada "
                   "1000 ft (el nivel del archivo coincide con el FL del visor, sin interpolar). "
                   "Requiere clave de API de WIFS (Token). Sólo está disponible la última corrida; "
                   "campos globales recortados localmente.")
    enabled_default = False
    params = [
        Param("centro", "Centro WAFC", "choice", "kwbc",
              choices=[("kwbc", "Washington (kwbc)"), ("egrr", "Londres (egrr)")]),
    ]
    variables = [(k, n) for k, n, _ in WAFS_VARIABLES]
    default_variables = ["UV", "T"]
    levels = WAFS_LEVELS
    viewer_levels = [round(fl_to_hpa(fl), 1) for fl in
                     (50, 100, 140, 180, 240, 270, 300, 320, 340, 360, 390, 410, 450, 530)]
    cycles = [0, 6, 12, 18]
    availability_lag_h = 5.0
    region_filter = "local"
    grid_resolution_deg = 0.25

    def steps(self, params=None, cycle=None):
        return list(range(6, 25)) + list(range(27, 49, 3)) + list(range(54, 121, 6))

    def default_basename(self, job):
        return f"wafs_{job.run_date:%Y%m%d}_{job.cycle:02d}z_0p25"

    def _headers(self):
        token = (self.credentials() or {}).get("token")
        if not token:
            raise DownloadError("WIFS requiere una clave de API: cargala como Token en la "
                                "configuración de la fuente.", "credenciales")
        return {"X-API-Key": token, "Accept": "application/x-grib2, application/json"}

    def build_requests(self, job, step):
        p = self.merged_params(job.params)
        start, end = bundle_for(step)
        collection = COLLECTION.replace("kwbc", p["centro"])
        reqs = []
        for key, _name, t2 in WAFS_VARIABLES:
            if key in job.variables:
                item = f"Y{t2}DYG{start:03d}_{end:03d}FLALL"
                reqs.append(Request(f"{WIFS_API}/{collection}/items/{item}", tag=f"{key} F{start:03d}–F{end:03d}",
                                    headers=self._headers()))
        return reqs

    def fetch_request(self, req, fetch_fn, chunk_cb=None, cancel=None, retry_wait=1.5,
                      max_bytes=None, status_cb=None):
        data = super().fetch_request(req, fetch_fn, chunk_cb, cancel, retry_wait, max_bytes)
        # Si la API devuelve el ítem como JSON (OGC API Features), se sigue el
        # enlace al GRIB2.
        if data[:1] == b"{":
            try:
                doc = json.loads(data.decode("utf-8", "replace"))
            except Exception:
                return data
            href = None
            for link in doc.get("links", []) + list((doc.get("assets") or {}).values()):
                h = link.get("href", "")
                if link.get("rel") in ("data", "enclosure", "download") or "grib" in (link.get("type") or "") \
                        or h.lower().endswith(".grib2"):
                    href = h
                    break
            if not href:
                raise DownloadError("WIFS devolvió un ítem sin enlace al GRIB2:\n" + data[:300].decode("utf-8", "replace"))
            req2 = Request(href, req.tag, req.headers, req.expect)
            return super().fetch_request(req2, fetch_fn, chunk_cb, cancel, retry_wait, max_bytes)
        return data

    def postprocess_step(self, data, job, step=None):
        """Los archivos traen todos los FL y tres plazos: se filtran los
        niveles pedidos y se recorta la zona."""
        keep = []
        for key in job.variables:
            keep += _KEEP_VARS.get(key, ())
        data = filter_grib(data, keep_levels_hpa=job.levels or None, keep_vars=keep or None, tol=1.5)
        if job.region is not None:
            data = crop_grib(data, job.region)
        return data, {"resolucion_final": "0p25", "niveles": "por FL (OACI)"}
