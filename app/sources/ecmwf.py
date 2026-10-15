# -*- coding: utf-8 -*-
"""Fuente ECMWF Open Data: pronóstico IFS 0,25° (CC BY 4.0) con la librería
oficial `ecmwf-opendata`. Los campos son globales: el recorte por zona se
hace localmente después de bajar.

Corridas 00/12 (stream oper): plazos cada 3 h hasta +144 y cada 6 h hasta
+240. Corridas 06/18 (stream scda): cada 3 h hasta +90. La librería elige el
stream según la hora de la corrida.
"""
import logging
import os
import re
import tempfile
import threading
import time

from ..regrid import crop_grib
from .base import (Source, Param, Request, TestResult, DownloadError, DownloadCancelled,
                   classify_exception)

DEFAULT_RETRIES = 10      # la librería trae 500 reintentos cada 120 s: demasiado para una UI
DEFAULT_WAIT_S = 30

ECMWF_LEVELS = [1000, 925, 850, 700, 600, 500, 400, 300, 250, 200, 150, 100, 50]
ECMWF_VARIABLES = [
    ("u", "Viento U (u)"),
    ("v", "Viento V (v)"),
    ("t", "Temperatura (t)"),
    ("gh", "Altura geopotencial (gh)"),
    ("r", "Humedad relativa (r)"),
]


def _client(source, reintentos=DEFAULT_RETRIES, espera_s=DEFAULT_WAIT_S):
    """Cliente oficial con la política de reintentos del usuario. La librería
    respeta el `Retry-After` del servidor cuando lo manda."""
    try:
        from ecmwf.opendata import Client
    except Exception as exc:
        raise DownloadError("Falta la librería ecmwf-opendata (pip install ecmwf-opendata).") from exc
    _install_hooks()
    return Client(source=source, model="ifs", resol="0p25",
                  maximum_retries=max(1, int(reintentos)), retry_after=max(1, int(espera_s)),
                  use_server_retry_after=True)


# ── Puente entre la librería y la ventana de avance ──────────────────────────
# `ecmwf-opendata` delega los reintentos en `multiurl.retry.robust`, que ante
# un 503 «Slow Down» (u otro 5xx/429) avisa por `logging` y duerme con
# `time.sleep`. Acá se capturan esos avisos para mostrarlos en la ventana de
# avance y se reemplaza la siesta por una espera cancelable. Lo que sigue
# imprimiendo la librería por consola (barra tqdm, aviso de licencia CC BY
# 4.0 al terminar) es informativo y no requiere respuesta.

_ctx = threading.local()      # status_cb / cancel del hilo que está descargando
_RE_RECOVER = re.compile(r"Recovering from (HTTP|connection) error \[(.*?)\], attempt (\d+) of (\d+)")
_RE_RETRY = re.compile(r"Retrying in (\S+) seconds")


def _status(text):
    cb = getattr(_ctx, "status_cb", None)
    if cb is not None:
        cb(text)


def parse_retry_message(msg):
    """Traduce un aviso de reintento de la librería a texto para la UI (o None)."""
    m = _RE_RECOVER.match(msg)
    if m:
        kind, detail, n, total = m.groups()
        detail = detail.strip()
        if "503" in detail or "429" in detail:
            motivo = f"servidor saturado ({detail})"
        elif kind == "HTTP":
            motivo = f"error del servidor ({detail})"
        else:
            motivo = f"error de conexión ({detail[:60]})"
        return f"{motivo}, reintento {n} de {total}"
    m = _RE_RETRY.match(msg)
    if m:
        try:
            return f"reintento en {float(m.group(1)):.0f} s"
        except ValueError:
            return None
    return None


class _RetryBridge(logging.Handler):
    def emit(self, record):
        try:
            text = parse_retry_message(record.getMessage())
        except Exception:
            return
        if text:
            _status(text)


def _cancellable_sleep(seconds):
    """Reemplazo de `multiurl.retry._logged_sleep`: cuenta regresiva en la UI
    y corte inmediato si el usuario cancela."""
    cancel = getattr(_ctx, "cancel", None)
    end = time.monotonic() + float(seconds)
    while True:
        left = end - time.monotonic()
        if left <= 0:
            return
        if cancel is not None and cancel():
            raise DownloadCancelled()
        _status(f"servidor saturado: reintento en {left:.0f} s")
        time.sleep(min(1.0, left))


_hooked = False


def _install_hooks():
    global _hooked
    if _hooked:
        return
    try:
        import multiurl.retry as R
    except Exception:
        return
    R._logged_sleep = _cancellable_sleep
    for name in ("multiurl.retry", "multiurl.http", "multiurl.multipart"):
        logging.getLogger(name).addHandler(_RetryBridge())
    _hooked = True


class _retry_context:
    """Activa el puente para el hilo actual mientras dura la descarga."""

    def __init__(self, status_cb, cancel):
        self.status_cb, self.cancel = status_cb, cancel

    def __enter__(self):
        _ctx.status_cb, _ctx.cancel = self.status_cb, self.cancel

    def __exit__(self, *exc):
        _ctx.status_cb = _ctx.cancel = None


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
        Param("reintentos", "Reintentos ante «503 Slow Down»", "int", DEFAULT_RETRIES, lo=1, hi=100,
              help="Cuántas veces vuelve a pedir cada tramo cuando el servidor responde 503 Slow "
                   "Down, 429 u otro error 5xx. La librería trae 500; con 10 la descarga se "
                   "rinde en unos minutos y avisa."),
        Param("espera_s", "Espera entre reintentos (s)", "int", DEFAULT_WAIT_S, lo=5, hi=600,
              help="Segundos entre reintentos (la librería trae 120). Si el servidor manda "
                   "Retry-After se respeta ese valor. La espera se ve en la ventana de avance y "
                   "se puede cancelar."),
    ]
    variables = ECMWF_VARIABLES
    default_variables = ["u", "v", "t"]
    levels = ECMWF_LEVELS
    viewer_levels = [850, 700, 600, 500, 400, 300, 250, 200, 150, 100]
    cycles = [0, 6, 12, 18]
    availability_lag_h = 8.0
    region_filter = "local"
    grid_resolution_deg = 0.25

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
        # La política de reintentos viaja aparte del URL para no alterar la clave de caché.
        return [Request(q, expect="grib", headers={"reintentos": p["reintentos"],
                                                   "espera_s": p["espera_s"]})]

    def _request_dict(self, job, step):
        return dict(type="fc", stream=None, date=job.run_date.strftime("%Y%m%d"),
                    time=job.cycle, step=step, param=list(job.variables),
                    levelist=list(job.levels), levtype="pl")

    def fetch_request(self, req, fetch_fn, chunk_cb=None, cancel=None, retry_wait=1.5,
                      max_bytes=None, status_cb=None):
        """Descarga con la librería a un archivo temporal y devuelve los bytes.
        Los reintentos de la librería se muestran por `status_cb` y la espera
        entre ellos respeta `cancel`."""
        from urllib.parse import urlparse, parse_qs
        u = urlparse(req.url)
        q = parse_qs(u.query)
        _, date, cyc, step = u.path.split("/")
        h = req.headers or {}
        client = _client(u.netloc, h.get("reintentos", DEFAULT_RETRIES),
                         h.get("espera_s", DEFAULT_WAIT_S))
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
                with _retry_context(status_cb, cancel):
                    client.retrieve(**kw)
            except DownloadCancelled:
                raise
            except Exception as exc:
                status, msg = classify_exception(exc)
                text = str(exc)
                if "No index" in text or "404" in text or "not found" in text.lower():
                    status = "no_publicado"
                elif "503" in text or "429" in text or "Slow Down" in text:
                    n = h.get("reintentos", DEFAULT_RETRIES)
                    raise DownloadError(
                        f"ECMWF Open Data: el servidor está saturado (503 Slow Down) y siguió "
                        f"rechazando el pedido tras {n} reintentos. Esperá unos minutos y volvé "
                        f"a intentar, o subí los reintentos en la configuración de la fuente.",
                        "error") from exc
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
            client = _client(p["servidor"], 2, 5)      # probar no debe demorar minutos
            latest = client.latest(type="fc", step=6, param="t", levtype="pl", levelist=500)
            return TestResult("ok", f"{self.name}: última corrida publicada {latest:%Y-%m-%d %H}Z "
                                    f"(servidor {p['servidor']})")
        except DownloadError as exc:
            return TestResult(exc.status, str(exc))
        except Exception as exc:
            status, msg = classify_exception(exc)
            return TestResult(status, msg)
