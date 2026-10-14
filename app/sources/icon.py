# -*- coding: utf-8 -*-
"""Fuente DWD ICON global (~13 km): datos abiertos en GRIB2 por nivel de
presión sobre la grilla icosaédrica R03B07 (2 949 120 celdas). Se regrilla
localmente a lat/lon 0,25° con los pesos que publica DWD para cdo
(ICON_GLOBAL2WORLD_025_EASY: vecino más cercano, un enlace por punto
destino), sin necesidad de cdo: se aplica el índice con numpy.

Archivos: https://opendata.dwd.de/weather/nwp/icon/grib/HH/<var>/
  icon_global_icosahedral_pressure-level_YYYYMMDDHH_FFF_LLL_VAR.grib2.bz2
(uno por variable, nivel y plazo; ~3,7 MB cada uno). DWD conserva sólo la
última corrida de cada ciclo. Corridas 00/12 hasta +180 h, 06/18 hasta
+120 h; horarios hasta +78 y cada 3 h después.
"""
import bz2
import io
import os
import tarfile

import numpy as np

from ..grib_engines import ec
from ..regrid import crop_grib
from .base import Source, Param, Request, DownloadError, classify_exception
from .cache import default_cache_dir

DWD_BASE = "https://opendata.dwd.de/weather/nwp/icon/grib"
WEIGHTS_URL = "https://opendata.dwd.de/weather/lib/cdo/ICON_GLOBAL2WORLD_025_EASY.tar.bz2"
WEIGHTS_NAME = "weights_icogl2world_025.nc"

ICON_LEVELS = [1000, 950, 925, 900, 850, 800, 700, 600, 500, 400, 300, 250, 200, 150, 100, 70, 50, 30]
# (clave del visor, texto, nombre en la URL de DWD)
ICON_VARIABLES = [
    ("U", "Viento U (U)", "u"),
    ("V", "Viento V (V)", "v"),
    ("T", "Temperatura (T)", "t"),
    ("FI", "Geopotencial (FI)", "fi"),
    ("RELHUM", "Humedad relativa (RELHUM)", "relhum"),
]


def weights_path():
    return os.path.join(default_cache_dir(), "..", "icon", WEIGHTS_NAME)


class IconWeights:
    """Índice vecino-más-cercano icosaédrica → lat/lon 0,25° (721×1440)."""

    _cache = None

    @classmethod
    def load(cls, path=None):
        if cls._cache is not None:
            return cls._cache
        path = path or weights_path()
        if not os.path.isfile(path):
            raise DownloadError("Faltan los pesos de regrillado de ICON (se bajan con «Probar "
                                "conexión» o en la primera descarga).")
        try:
            import netCDF4
        except Exception as exc:
            raise DownloadError("El regrillado de ICON requiere netCDF4 (pip install netCDF4).") from exc
        ds = netCDF4.Dataset(path)
        try:
            dims = [int(x) for x in ds.variables["dst_grid_dims"][:]]
            src = np.asarray(ds.variables["src_address"][:], dtype=np.int64) - 1
            dst = np.asarray(ds.variables["dst_address"][:], dtype=np.int64) - 1
            lat = np.degrees(np.asarray(ds.variables["dst_grid_center_lat"][:]))
            lon = np.degrees(np.asarray(ds.variables["dst_grid_center_lon"][:]))
        finally:
            ds.close()
        ni, nj = dims[0], dims[1]
        index = np.full(ni * nj, -1, dtype=np.int64)
        index[dst] = src
        lat1d = lat.reshape(nj, ni)[:, 0]
        lon1d = lon.reshape(nj, ni)[0, :]
        cls._cache = {"ni": ni, "nj": nj, "index": index, "lat1d": lat1d, "lon1d": lon1d}
        return cls._cache

    @staticmethod
    def extract(tar_bytes, path=None):
        """Saca el .nc del tar.bz2 de DWD y lo guarda en la caché."""
        path = path or weights_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:bz2") as tar:
            for m in tar.getmembers():
                if m.name.endswith(WEIGHTS_NAME):
                    with tar.extractfile(m) as src, open(path + ".parte", "wb") as dst:
                        dst.write(src.read())
                    os.replace(path + ".parte", path)
                    return path
        raise DownloadError("El paquete de pesos de DWD no contiene " + WEIGHTS_NAME)


def icosahedral_to_latlon(data, weights):
    """GRIB2 icosaédrico (uno o más mensajes) → GRIB2 regular_ll 0,25° global."""
    if ec is None:
        raise RuntimeError("regrillar requiere eccodes")
    ni, nj, index = weights["ni"], weights["nj"], weights["index"]
    lat1d, lon1d = weights["lat1d"], weights["lon1d"]
    out = bytearray()
    pos = 0
    while pos < len(data):
        gid = ec.codes_new_from_message(data[pos:])
        if gid is None:
            break
        try:
            total = ec.codes_get_message_size(gid)
            vals = np.asarray(ec.codes_get_double_array(gid, "values"), dtype=float)
            if vals.size != int(np.max(index)) + 1 and vals.size < int(np.max(index)) + 1:
                raise DownloadError(f"El campo ICON tiene {vals.size} celdas y los pesos esperan "
                                    f"{int(np.max(index)) + 1}: grilla distinta.")
            if ec.codes_get(gid, "bitmapPresent"):
                vals = np.where(vals == ec.codes_get(gid, "missingValue"), np.nan, vals)
            grid = vals[index].reshape(nj, ni)
            new = ec.codes_grib_new_from_samples("regular_ll_pl_grib2")
            try:
                for key in ("discipline", "parameterCategory", "parameterNumber", "dataDate",
                            "dataTime", "typeOfLevel", "level", "centre"):
                    try:
                        ec.codes_set(new, key, ec.codes_get(gid, key))
                    except Exception:
                        pass
                # El plazo, en horas (DWD lo codifica en minutos)
                try:
                    ec.codes_set(new, "stepUnits", "h")
                    ec.codes_set(new, "forecastTime", int(round(float(ec.codes_get(gid, "endStep")))))
                except Exception:
                    pass
                ec.codes_set(new, "Ni", ni)
                ec.codes_set(new, "Nj", nj)
                ec.codes_set(new, "latitudeOfFirstGridPointInDegrees", float(lat1d[0]))
                ec.codes_set(new, "latitudeOfLastGridPointInDegrees", float(lat1d[-1]))
                ec.codes_set(new, "longitudeOfFirstGridPointInDegrees", float(lon1d[0]))
                ec.codes_set(new, "longitudeOfLastGridPointInDegrees", float(lon1d[-1]))
                ec.codes_set(new, "iDirectionIncrementInDegrees", float(abs(lon1d[1] - lon1d[0])))
                ec.codes_set(new, "jDirectionIncrementInDegrees", float(abs(lat1d[1] - lat1d[0])))
                ec.codes_set(new, "jScansPositively", 1 if lat1d[1] > lat1d[0] else 0)
                if np.isnan(grid).any():
                    ec.codes_set(new, "missingValue", 9999.0)
                    ec.codes_set(new, "bitmapPresent", 1)
                    grid = np.where(np.isnan(grid), 9999.0, grid)
                ec.codes_set_values(new, grid.ravel())
                out += ec.codes_get_message(new)
            finally:
                ec.codes_release(new)
        finally:
            pos += total
            ec.codes_release(gid)
    return bytes(out)


class IconSource(Source):
    key = "icon"
    name = "DWD ICON global"
    model = "ICON global ~13 km (DWD), regrillado local a 0,25°"
    kind = "altura"
    flight_levels = False
    doc_url = "https://www.dwd.de/EN/ourservices/opendata/opendata.html"
    description = ("Datos abiertos de DWD en grilla icosaédrica; cada campo (variable × nivel × "
                   "plazo) es un archivo de ~3,7 MB que se regrilla a 0,25° con los pesos de DWD "
                   "(44 MB, se bajan una vez). Sólo la última corrida de cada ciclo. Elegí pocos "
                   "niveles y plazos para no bajar cientos de MB.")
    enabled_default = True
    params = [
        Param("recortar", "Recortar a la zona (local)", "bool", True),
    ]
    variables = [(k, n) for k, n, _ in ICON_VARIABLES]
    default_variables = ["U", "V", "T"]
    levels = ICON_LEVELS
    viewer_levels = [850, 700, 600, 500, 400, 300, 250, 200, 150, 100]
    cycles = [0, 6, 12, 18]
    availability_lag_h = 5.0
    region_filter = "local"

    def steps(self, params=None, cycle=None):
        last = 120 if cycle in (6, 18) else 180
        return list(range(0, 79)) + list(range(81, last + 1, 3))

    def available_runs(self, now=None, count=8):
        # DWD sólo conserva la última corrida de cada ciclo
        return super().available_runs(now, count=4)

    def default_basename(self, job):
        return f"icon_{job.run_date:%Y%m%d}_{job.cycle:02d}z_0p25"

    def build_requests(self, job, step):
        reqs = []
        for key, _name, folder in ICON_VARIABLES:
            if key not in job.variables:
                continue
            for lv in job.levels:
                fn = (f"icon_global_icosahedral_pressure-level_{job.run_date:%Y%m%d}{job.cycle:02d}"
                      f"_{step:03d}_{lv}_{key}.grib2.bz2")
                reqs.append(Request(f"{DWD_BASE}/{job.cycle:02d}/{folder}/{fn}",
                                    tag=f"{key} {lv} hPa", expect="grib"))
        return reqs

    def ensure_weights(self, fetch_fn=None, progress_cb=None, cancel=None, retry_wait=1.5):
        """Baja y extrae los pesos de DWD una sola vez (quedan en la caché)."""
        if os.path.isfile(weights_path()):
            return weights_path()
        from .. import gfs_download
        fetch_fn = fetch_fn or gfs_download.fetch

        def chunk_cb(got, total):
            if progress_cb:
                progress_cb(0, 1, f"Pesos de regrillado de DWD (una vez): {got / 1e6:.0f} MB", 0.0)
        data = Source.fetch_request(self, Request(WEIGHTS_URL, expect="any"), fetch_fn,
                                    chunk_cb=chunk_cb, cancel=cancel, retry_wait=retry_wait)
        return IconWeights.extract(data)

    def download(self, job, progress_cb=None, cancel=None, fetch_fn=None, cache=None,
                 retry_wait=1.5, write_provenance=True, credentials=None):
        self.ensure_weights(fetch_fn, progress_cb, cancel, retry_wait)
        return super().download(job, progress_cb, cancel, fetch_fn, cache, retry_wait,
                                write_provenance, credentials)

    def fetch_request(self, req, fetch_fn, chunk_cb=None, cancel=None, retry_wait=1.5,
                      max_bytes=None, status_cb=None):
        data = super().fetch_request(req, fetch_fn, chunk_cb, cancel, retry_wait, max_bytes)
        if max_bytes is not None:
            # Prueba de conexión: alcanza con que sea un bz2
            return b"GRIB" if data[:3] == b"BZh" else data
        try:
            return bz2.decompress(data)
        except OSError as exc:
            raise DownloadError(f"DWD: el archivo {os.path.basename(req.url)} no es un bz2 válido "
                                f"(¿plazo no publicado?).") from exc

    def postprocess_step(self, data, job, step=None):
        p = self.merged_params(job.params)
        out = icosahedral_to_latlon(data, IconWeights.load())
        if p["recortar"] and job.region is not None:
            out = crop_grib(out, job.region)
        return out, {"resolucion_final": "0p25", "regrillado": "vecino más cercano (pesos DWD)"}

    def test_connection(self, params=None, credentials=None, fetch_fn=None):
        res = super().test_connection(params, credentials, fetch_fn)
        if res.ok and not os.path.isfile(weights_path()):
            res.message += ". Los pesos de regrillado (44 MB) se bajarán en la primera descarga."
        return res
