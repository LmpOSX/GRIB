# -*- coding: utf-8 -*-
"""Fuente ECMWF Open Data: pronóstico IFS 0,25° (CC BY 4.0) con la librería
oficial `ecmwf-opendata`. Los campos son globales: el recorte por zona se
hace localmente después de bajar.

Corridas 00/12 (stream oper): plazos cada 3 h hasta +144 y cada 6 h hasta
+240. Corridas 06/18 (stream scda): cada 3 h hasta +90. La librería elige el
stream según la hora de la corrida.
"""
import os
import tempfile

from ..regrid import crop_grib
from .base import Source, Param, Request, TestResult, DownloadError, classify_exception

ECMWF_LEVELS = [1000, 925, 850, 700, 600, 500, 400, 300, 250, 200, 150, 100, 50]
ECMWF_VARIABLES = [
    ("u", "Viento U (u)"),
    ("v", "Viento V (v)"),
    ("t", "Temperatura (t)"),
    ("gh", "Altura geopotencial (gh)"),
    ("r", "Humedad relativa (r)"),
]


def _client(source):
    try:
        from ecmwf.opendata import Client
    except Exception as exc:
        raise DownloadError("Falta la librería ecmwf-opendata (pip install ecmwf-opendata).") from exc
    return Client(source=source, model="ifs", resol="0p25")


class ECMWFSource(Source):
    key = "ecmwf"
    name = "ECMWF Open Data"
    model = "IFS 0,25° (ECMWF, CC BY 4.0)"
    kind = "altura"
    flight_levels = False
    doc_url = "https://www.ecmwf.int/en/forecasts/datasets/open-data"
    description = ("Modelo global del ECMWF, 4 corridas diarias (00/12 hasta +240 h, 06/18 hasta "
                   "+90 h), cada 3 h. Campos globales: la zona se recorta localmente. Descarga con "
                   "la librería oficial ecmwf-opendata.")
    params = [
        Param("servidor", "Servidor", "choice", "aws",
              choices=[("aws", "Espejo AWS (recomendado)"), ("azure", "Espejo Azure"),
                       ("ecmwf", "data.ecmwf.int (limita las peticiones)")]),
    ]
    variables = ECMWF_VARIABLES
    default_variables = ["u", "v", "t"]
    levels = ECMWF_LEVELS
    viewer_levels = [850, 700, 600, 500, 400, 300, 250, 200, 150, 100]
    cycles = [0, 6, 12, 18]
    availability_lag_h = 8.0
    region_filter = "local"

    def steps(self, params=None, cycle=None):
        if cycle in (6, 18):
            return list(range(0, 91, 3))
        return list(range(0, 145, 3)) + list(range(150, 241, 6))

    def default_basename(self, job):
        return f"ecmwf_{job.run_date:%Y%m%d}_{job.cycle:02d}z_0p25"

    def build_requests(self, job, step):
        p = self.merged_params(job.params)
        q = (f"ecmwf-opendata://{p['servidor']}/{job.run_date:%Y%m%d}/{job.cycle:02d}/{step}"
             f"?param={','.join(job.variables)}&levelist={','.join(str(lv) for lv in job.levels)}")
        return [Request(q, expect="grib")]

    def _request_dict(self, job, step):
        return dict(type="fc", stream=None, date=job.run_date.strftime("%Y%m%d"),
                    time=job.cycle, step=step, param=list(job.variables),
                    levelist=list(job.levels), levtype="pl")

    def fetch_request(self, req, fetch_fn, chunk_cb=None, cancel=None, retry_wait=1.5,
                      max_bytes=None):
        """Descarga con la librería a un archivo temporal y devuelve los bytes."""
        from urllib.parse import urlparse, parse_qs
        u = urlparse(req.url)
        q = parse_qs(u.query)
        _, date, cyc, step = u.path.split("/")
        client = _client(u.netloc)
        fd, tmp = tempfile.mkstemp(prefix="ecmwf_", suffix=".grib2")
        os.close(fd)
        try:
            kw = dict(type="fc", date=date, time=int(cyc), step=int(step),
                      param=q["param"][0].split(","),
                      levelist=[int(x) for x in q["levelist"][0].split(",")], levtype="pl",
                      target=tmp)
            if max_bytes is not None:
                kw["param"] = kw["param"][:1]
                kw["levelist"] = kw["levelist"][:1]
            try:
                client.retrieve(**kw)
            except Exception as exc:
                status, msg = classify_exception(exc)
                text = str(exc)
                if "No index" in text or "404" in text or "not found" in text.lower():
                    status = "no_publicado"
                raise DownloadError(f"ECMWF Open Data: {text[:200]}", status) from exc
            with open(tmp, "rb") as fh:
                data = fh.read(max_bytes) if max_bytes is not None else fh.read()
            if chunk_cb:
                chunk_cb(len(data), len(data))
            return data
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

    def postprocess_step(self, data, job, step=None):
        if job.region is not None:
            data = crop_grib(data, job.region)
        return data, {"resolucion_final": "0p25", "recorte": "local" if job.region else "global"}

    def test_connection(self, params=None, credentials=None, fetch_fn=None):
        p = self.merged_params(params)
        try:
            client = _client(p["servidor"])
            latest = client.latest(type="fc", step=6, param="t", levtype="pl", levelist=500)
            return TestResult("ok", f"{self.name}: última corrida publicada {latest:%Y-%m-%d %H}Z "
                                    f"(servidor {p['servidor']})")
        except DownloadError as exc:
            return TestResult(exc.status, str(exc))
        except Exception as exc:
            status, msg = classify_exception(exc)
            return TestResult(status, msg)
