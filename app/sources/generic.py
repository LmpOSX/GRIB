# -*- coding: utf-8 -*-
"""Fuente genérica con URL configurable: servidores institucionales o
restringidos (espejo SADIS/WIFS, FTP del SMN, servidor interno) que publican
GRIB2 o NetCDF con nombres predecibles por fecha, ciclo y plazo.

La plantilla de URL admite los marcadores {YYYY} {MM} {DD} {HH} {FFF} {FF}
{YYYYMMDD} {YYYYMMDDHH} y también formato Python: {date:%Y%m%d} {cycle:02d}
{step:03d}. Esquemas: http, https, ftp, sftp. Autenticación: ninguna,
usuario/clave (HTTP básica, FTP, SFTP) o token (HTTP Bearer). Las
credenciales se guardan en el llavero del sistema.
"""
from ..regrid import crop_grib
from .base import Source, Param, Request, DownloadError, DownloadCancelled, TestResult, \
    classify_exception, check_content
from .transport import fetch_any


def parse_int_list(text, default):
    """'0,6,12' o '6-48/3' → lista de enteros."""
    text = (text or "").strip()
    if not text:
        return list(default)
    out = []
    for part in text.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            rng, _, st = part.partition("/")
            a, b = rng.split("-")
            out += list(range(int(a), int(b) + 1, int(st or 1)))
        else:
            out.append(int(part))
    return sorted(set(out))


def expand_template(template, run_date, cycle, step):
    t = (template or "")
    rep = {"{YYYY}": f"{run_date:%Y}", "{MM}": f"{run_date:%m}", "{DD}": f"{run_date:%d}",
           "{HH}": f"{cycle:02d}", "{FFF}": f"{step:03d}", "{FF}": f"{step:02d}",
           "{YYYYMMDD}": f"{run_date:%Y%m%d}", "{YYYYMMDDHH}": f"{run_date:%Y%m%d}{cycle:02d}"}
    for k, v in rep.items():
        t = t.replace(k, v)
    try:
        t = t.format(date=run_date, cycle=cycle, step=step)
    except (KeyError, ValueError, IndexError):
        pass
    return t


class GenericSource(Source):
    key = "generica"
    name = "Fuente genérica (URL configurable)"
    model = "Servidor propio: GRIB2 o NetCDF por fecha, ciclo y plazo"
    kind = "altura"
    flight_levels = False
    needs_credentials = True
    auth_kinds = ["ninguna", "usuario", "token"]
    enabled_default = False
    description = ("Definí la plantilla de URL con {YYYY} {MM} {DD} {HH} {FFF}, los ciclos y los "
                   "plazos. Se baja el archivo completo; si es GRIB2 en grilla lat/lon se recorta "
                   "a la zona localmente. NetCDF sólo se valida y guarda (el visor abre GRIB2).")
    params = [
        Param("plantilla", "Plantilla de URL", "text",
              "https://servidor/ruta/{YYYYMMDD}/{HH}/modelo_{YYYYMMDDHH}_f{FFF}.grib2",
              help="http(s)://, ftp:// o sftp://; marcadores {YYYY} {MM} {DD} {HH} {FFF} {FF} "
                   "{YYYYMMDD} {YYYYMMDDHH} o {date:%Y%m%d} {cycle:02d} {step:03d}"),
        Param("ciclos", "Ciclos (UTC)", "text", "0,6,12,18"),
        Param("plazos", "Plazos (h)", "text", "0-120/3", help="Lista '6,9,12' o rango '0-120/3'"),
        Param("formato", "Formato del archivo", "choice", "grib",
              choices=[("grib", "GRIB2"), ("netcdf", "NetCDF")]),
        Param("demora_h", "Demora de publicación (h)", "float", 4.0, lo=0, hi=48,
              help="Para proponer la última corrida disponible"),
        Param("recortar", "Recortar GRIB2 a la zona localmente", "bool", True),
    ]
    variables = []
    levels = []
    cycles = [0, 6, 12, 18]
    region_filter = "local"

    # Los ciclos y plazos salen de los parámetros
    def _cycles(self, params):
        return parse_int_list(self.merged_params(params).get("ciclos"), [0, 6, 12, 18])

    def steps(self, params=None, cycle=None):
        return parse_int_list(self.merged_params(params).get("plazos"), range(0, 121, 3))

    def latest_run(self, now=None, params=None):
        import datetime as dt
        p = self.merged_params(params)
        self.cycles = self._cycles(p)
        self.availability_lag_h = float(p.get("demora_h", 4.0))
        return super().latest_run(now)

    @property
    def file_ext(self):
        return ".nc" if getattr(self, "_fmt", "grib") == "netcdf" else ".grib2"

    def validate(self, job):
        p = self.merged_params(job.params)
        self.cycles = self._cycles(p)
        self._fmt = p["formato"]
        if "://" not in (p.get("plantilla") or ""):
            return "La plantilla de URL debe empezar con http://, https://, ftp:// o sftp://."
        return super().validate(job)

    def default_basename(self, job):
        return f"generica_{job.run_date:%Y%m%d}_{job.cycle:02d}z"

    def build_requests(self, job, step):
        p = self.merged_params(job.params)
        self._fmt = p["formato"]
        url = expand_template(p["plantilla"], job.run_date, job.cycle, step)
        return [Request(url, expect="netcdf" if p["formato"] == "netcdf" else "grib")]

    def fetch_request(self, req, fetch_fn, chunk_cb=None, cancel=None, retry_wait=1.5,
                      max_bytes=None):
        creds = self.credentials() or {}
        auth = creds.get("auth") or getattr(self, "_auth", None) or "ninguna"
        import time
        last = None
        for i in range(3):
            if cancel is not None and cancel():
                raise DownloadCancelled()
            try:
                return fetch_any(req.url, auth=auth, creds=creds, chunk_cb=chunk_cb, cancel=cancel,
                                 max_bytes=max_bytes, http_fetch=fetch_fn)
            except DownloadCancelled:
                raise
            except Exception as exc:
                status, _msg = classify_exception(exc)
                last = exc
                if status in ("no_publicado", "credenciales") or max_bytes is not None:
                    raise
                if i < 2 and retry_wait:
                    time.sleep(retry_wait * (2 ** i))
        raise last

    def postprocess_step(self, data, job, step=None):
        p = self.merged_params(job.params)
        if p["formato"] == "grib" and p["recortar"] and job.region is not None:
            try:
                data = crop_grib(data, job.region)
            except ValueError as exc:
                raise DownloadError(f"{self.name}: {exc}") from exc
        return data, {"formato": p["formato"]}

    def test_connection(self, params=None, credentials=None, fetch_fn=None):
        p = self.merged_params(params)
        self._creds = credentials or None
        self._auth = (credentials or {}).get("auth") or p.get("auth") or "ninguna"
        from .base import DownloadJob
        try:
            day, cyc = self.latest_run(params=p)
            steps = self.steps(p, cyc)
            job = DownloadJob(day, cyc, [steps[0]], [], [], None, params=p)
            err = self.validate(job)
            if err:
                return TestResult("error", err)
            req = self.build_requests(job, steps[0])[0]
            data = self.fetch_request(req, fetch_fn, max_bytes=4096)
            check_content(data, req.expect, "la prueba")
            return TestResult("ok", f"{req.url}: responde con {p['formato'].upper()}")
        except DownloadError as exc:
            return TestResult(exc.status, str(exc).splitlines()[0])
        except Exception as exc:
            status, msg = classify_exception(exc)
            return TestResult(status, msg)
