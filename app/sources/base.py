# -*- coding: utf-8 -*-
"""Esquema común de las fuentes de datos del visor.

Una fuente describe qué ofrece (modelo, tipo altura/superficie, corridas,
plazos, variables, niveles, parámetros propios, si necesita credenciales y
si publica niveles por FL) y sabe armar los pedidos HTTP de una descarga.
Todo lo demás es genérico y vive acá: caché, reintentos, validación del
contenido, recorte/regrillado posterior, escritura de archivos y de la
procedencia (un JSON junto al archivo para que el visor muestre de qué
fuente, modelo, corrida y plazo es lo que está en pantalla).

Para agregar una fuente: subclase de `Source`, completar los atributos de
clase y `build_requests`; opcionalmente `postprocess_step` y
`test_connection`. Registrarla en `sources/__init__.py`. Los diálogos se
arman solos a partir de `params`.
"""
import datetime as dt
import json
import os
import socket
import time
import urllib.error

from .cache import DownloadCache

GRIB_MAGIC = b"GRIB"
NETCDF_MAGICS = (b"CDF\x01", b"CDF\x02", b"\x89HDF")

MAGICS = {"grib": (GRIB_MAGIC,), "netcdf": NETCDF_MAGICS, "any": (GRIB_MAGIC,) + NETCDF_MAGICS}


class DownloadError(Exception):
    """Error explicable al usuario. `status`: 'no_publicado', 'credenciales',
    'sin_red', 'contenido' o 'error'."""

    def __init__(self, message, status="error"):
        super().__init__(message)
        self.status = status


class DownloadCancelled(Exception):
    pass


class Param:
    """Parámetro propio de una fuente; el formulario se arma a partir de esto.
    kind: 'choice' (choices = [(valor, texto)]), 'bool', 'int', 'float', 'text'."""

    def __init__(self, key, label, kind, default, choices=None, lo=None, hi=None, help=""):
        self.key, self.label, self.kind, self.default = key, label, kind, default
        self.choices = choices or []
        self.lo, self.hi, self.help = lo, hi, help


class Request:
    def __init__(self, url, tag="", headers=None, expect="grib"):
        self.url, self.tag, self.headers, self.expect = url, tag, dict(headers or {}), expect


class TestResult:
    """Resultado de «Probar conexión». status: 'ok', 'sin_red', 'credenciales',
    'no_publicado', 'error'."""

    LABELS = {"ok": "Conexión OK", "sin_red": "Sin red", "credenciales": "Credenciales inválidas",
              "no_publicado": "Dato todavía no publicado", "error": "Error"}

    def __init__(self, status, message=""):
        self.status, self.message = status, message

    @property
    def ok(self):
        return self.status == "ok"

    def __str__(self):
        return f"{self.LABELS.get(self.status, self.status)}: {self.message}" if self.message \
            else self.LABELS.get(self.status, self.status)


class DownloadJob:
    """Qué bajar de una fuente."""

    def __init__(self, run_date, cycle, steps, variables=None, levels=None, region=None,
                 dest_dir=".", basename=None, merge=True, params=None):
        self.run_date = run_date              # datetime.date UTC
        self.cycle = int(cycle)
        self.steps = sorted({int(s) for s in steps})
        self.variables = list(variables or [])
        self.levels = sorted({int(lv) for lv in (levels or [])}, reverse=True)
        self.region = region                  # (top, bottom, left, right) o None = global
        self.dest_dir = dest_dir
        self.basename = basename
        self.merge = bool(merge)
        self.params = dict(params or {})

    @property
    def run(self):
        return dt.datetime(self.run_date.year, self.run_date.month, self.run_date.day,
                           self.cycle, tzinfo=dt.timezone.utc)

    def file_paths(self, source):
        base = self.basename or source.default_basename(self)
        if self.merge:
            return [os.path.join(self.dest_dir, base + source.file_ext)]
        return [os.path.join(self.dest_dir, f"{base}_f{h:03d}{source.file_ext}") for h in self.steps]


def classify_exception(exc):
    """Traduce una excepción de red a (status, mensaje)."""
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 404:
            return "no_publicado", f"HTTP 404: el servidor no tiene ese archivo todavía"
        if exc.code in (401, 403):
            return "credenciales", f"HTTP {exc.code}: acceso denegado"
        return "error", f"HTTP {exc.code}: {exc.reason}"
    if isinstance(exc, (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError)):
        return "sin_red", f"no se pudo conectar: {getattr(exc, 'reason', exc)}"
    return "error", f"{type(exc).__name__}: {exc}"


def fetch_with_retries(fetch_fn, url, headers=None, chunk_cb=None, cancel=None,
                       attempts=3, retry_wait=1.5):
    """Reintenta ante fallos de red o errores 5xx; no reintenta 404/401/403."""
    last = None
    for i in range(attempts):
        if cancel is not None and cancel():
            raise DownloadCancelled()
        try:
            return fetch_fn(url, headers=headers, chunk_cb=chunk_cb, cancel=cancel)
        except DownloadCancelled:
            raise
        except urllib.error.HTTPError as exc:
            if exc.code < 500:
                raise
            last = exc
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
            last = exc
        if i < attempts - 1 and retry_wait:
            time.sleep(retry_wait * (2 ** i))
    raise last


def check_content(data, expect, what):
    """Lanza DownloadError si los bytes no son del tipo esperado."""
    if any(data.startswith(m) for m in MAGICS.get(expect, MAGICS["any"])):
        return
    texto = data[:300].decode("utf-8", "replace").strip()
    kind = {"grib": "un GRIB2", "netcdf": "un NetCDF"}.get(expect, "un archivo de datos")
    raise DownloadError(
        f"La respuesta de {what} no es {kind} (¿plazo todavía no publicado, variables o "
        f"niveles sin datos, o zona fuera de rango?).\n{texto}", status="contenido")


class Source:
    key = "base"
    name = "Fuente"
    model = ""
    kind = "altura"            # 'altura' (niveles de presión) o 'superficie'
    flight_levels = False      # ✓ FL: niveles isobáricos de la OACI por nivel de vuelo
    needs_credentials = False
    auth_kinds = []            # ('ninguna' | 'usuario' | 'token') que admite
    doc_url = ""
    description = ""
    enabled_default = True
    file_ext = ".grib2"
    expect = "grib"
    params = []                # lista de Param
    variables = []             # [(clave, texto)]
    default_variables = []
    levels = []                # niveles de presión disponibles (hPa)
    viewer_levels = []         # subconjunto sugerido
    cycles = [0, 6, 12, 18]
    availability_lag_h = 4.0
    region_filter = "servidor"   # 'servidor', 'local' o 'ninguno'

    # ── Descripción ──────────────────────────────────────────────────────────

    def default_params(self):
        return {p.key: p.default for p in self.params}

    def merged_params(self, params):
        d = self.default_params()
        d.update({k: v for k, v in (params or {}).items() if k in d})
        return d

    def steps(self, params=None):
        """Plazos (horas) que ofrece la fuente."""
        return list(range(0, 121, 3))

    def latest_run(self, now=None):
        now = now or dt.datetime.now(dt.timezone.utc)
        ref = now - dt.timedelta(hours=self.availability_lag_h)
        cycles = sorted(self.cycles)
        day = ref.date()
        cyc = max([c for c in cycles if c <= ref.hour] or [None]) if cycles else 0
        if cyc is None:
            day = day - dt.timedelta(days=1)
            cyc = cycles[-1]
        return day, cyc

    def available_runs(self, now=None, count=8):
        """Últimas `count` corridas (fecha, ciclo), la más nueva primero."""
        day, cyc = self.latest_run(now)
        runs = []
        cycles = sorted(self.cycles)
        while len(runs) < count:
            runs.append((day, cyc))
            i = cycles.index(cyc)
            if i == 0:
                day = day - dt.timedelta(days=1)
                cyc = cycles[-1]
            else:
                cyc = cycles[i - 1]
        return runs

    def default_basename(self, job):
        return f"{self.key}_{job.run_date:%Y%m%d}_{job.cycle:02d}z"

    def level_enabled(self, level, params):
        """Si un nivel se puede pedir con estos parámetros (el diálogo
        deshabilita los que no)."""
        return True

    def validate(self, job):
        """Mensaje de error o None."""
        if job.cycle not in self.cycles:
            return "Ciclo no ofrecido por la fuente: " + ", ".join(f"{c:02d}Z" for c in self.cycles)
        if not job.steps:
            return "Elegí al menos un plazo."
        offered = set(self.steps(job.params))
        bad = [s for s in job.steps if s not in offered]
        if bad:
            return f"Plazos que la fuente no ofrece: {', '.join(str(b) for b in bad)}"
        if self.variables and not job.variables:
            return "Elegí al menos una variable."
        if self.kind == "altura" and self.levels and not job.levels:
            return "Elegí al menos un nivel."
        if job.region is not None:
            top, bottom, left, right = job.region
            if not (-90 <= bottom < top <= 90):
                return "Latitud: el norte debe ser mayor que el sur (−90…90)."
            if not (-180 <= left <= 360 and -180 <= right <= 360) or left == right:
                return "Longitud: valores entre −180 y 180 (o 0 y 360), distintos entre sí."
        base = job.basename or self.default_basename(job)
        if not base or any(c in base for c in '/\\:*?"<>|'):
            return "Nombre de archivo inválido."
        return None

    # ── Pedidos ──────────────────────────────────────────────────────────────

    def build_requests(self, job, step):
        """Lista de Request para un plazo (varios si la fuente parte el
        producto). Debe implementarse en cada fuente."""
        raise NotImplementedError

    def postprocess_step(self, data, job):
        """Recorte / regrillado local de los bytes de un plazo ya validado."""
        return data

    def provenance(self, job, effective=None):
        d = {"fuente": self.key, "nombre": self.name, "modelo": self.model, "tipo": self.kind,
             "corrida": job.run.strftime("%Y-%m-%dT%H:%MZ"), "plazos_h": job.steps,
             "variables": job.variables, "niveles_hpa": job.levels, "zona": job.region,
             "parametros": self.merged_params(job.params), "descargado": dt.datetime.now(
                 dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        d.update(effective or {})
        return d

    def test_connection(self, params=None, credentials=None, fetch_fn=None):
        """Verifica acceso; por defecto pide el primer plazo de la última
        corrida (sólo cabecera) y clasifica el resultado."""
        from .. import gfs_download
        fetch_fn = fetch_fn or gfs_download.fetch
        day, cyc = self.latest_run()
        job = DownloadJob(day, cyc, [self.steps(params)[0]], self.default_variables[:1],
                          self.viewer_levels[:1] or self.levels[:1], None, params=params)
        try:
            reqs = self.build_requests(job, job.steps[0])
            data = fetch_fn(reqs[0].url, headers=reqs[0].headers, max_bytes=4096)
            check_content(data, reqs[0].expect, "la prueba")
            return TestResult("ok", f"{self.name}: corrida {day:%Y-%m-%d} {cyc:02d}Z disponible")
        except DownloadError as exc:
            return TestResult(exc.status, str(exc).splitlines()[0])
        except Exception as exc:
            status, msg = classify_exception(exc)
            return TestResult(status, msg)

    # ── Descarga genérica ────────────────────────────────────────────────────

    def download(self, job, progress_cb=None, cancel=None, fetch_fn=None, cache=None,
                 retry_wait=1.5, write_provenance=True):
        """Baja todos los plazos del trabajo con caché, reintentos y
        validación; escribe los archivos y su procedencia. Devuelve las
        rutas escritas. Lanza DownloadError / DownloadCancelled."""
        from .. import gfs_download
        fetch_fn = fetch_fn or gfs_download.fetch
        err = self.validate(job)
        if err:
            raise DownloadError(err)
        os.makedirs(job.dest_dir, exist_ok=True)
        paths = job.file_paths(self)
        n = len(job.steps)
        written = []
        out = None
        effective = {}
        try:
            if job.merge:
                out = open(paths[0], "wb")
            for i, step in enumerate(job.steps):
                if cancel is not None and cancel():
                    raise DownloadCancelled()
                msg = f"Plazo +{step} h ({i + 1} de {n})"
                if progress_cb:
                    progress_cb(i, n, msg, i / n)
                reqs = self.build_requests(job, step)
                parts = []
                for k, req in enumerate(reqs):
                    if cancel is not None and cancel():
                        raise DownloadCancelled()
                    sub = f"{msg}{' · ' + req.tag if req.tag else ''}"
                    cached = cache.get(req.url) if cache is not None else None
                    if cached is not None:
                        if progress_cb:
                            progress_cb(i, n, f"{sub}: en caché", (i + (k + 1) / len(reqs)) / n)
                        parts.append(cached)
                        continue

                    def chunk_cb(got, total, _i=i, _k=k, _m=len(reqs), _msg=sub):
                        if progress_cb:
                            frac = (got / total) if total else 0.0
                            progress_cb(_i, n, f"{_msg}: {got / 1e6:.1f} MB", (_i + (_k + frac) / _m) / n)
                    try:
                        data = fetch_with_retries(fetch_fn, req.url, headers=req.headers,
                                                  chunk_cb=chunk_cb, cancel=cancel,
                                                  retry_wait=retry_wait)
                    except DownloadCancelled:
                        raise
                    except Exception as exc:
                        status, detail = classify_exception(exc)
                        if status == "no_publicado":
                            raise DownloadError(
                                f"El servidor no tiene el plazo +{step} h de la corrida "
                                f"{job.run_date:%Y-%m-%d} {job.cycle:02d}Z de {self.name} ({detail}). "
                                "Puede que todavía no esté publicado: probá la corrida anterior "
                                "o un plazo menor.", status) from exc
                        if status == "credenciales":
                            raise DownloadError(
                                f"{self.name}: {detail}. Revisá usuario/clave o token en la "
                                "configuración de la fuente.", status) from exc
                        raise DownloadError(f"{self.name}: {detail} (plazo +{step} h, tras reintentos).",
                                            status) from exc
                    check_content(data, req.expect, f"{self.name}, plazo +{step} h"
                                  + (f" ({req.tag})" if req.tag else ""))
                    if cache is not None:
                        cache.put(req.url, data)
                    parts.append(data)
                data = b"".join(parts)
                if progress_cb:
                    progress_cb(i, n, f"{msg}: procesando…", (i + 1) / n)
                data, eff = self._post(data, job)
                effective.update(eff)
                if job.merge:
                    out.write(data)
                else:
                    with open(paths[i], "wb") as fh:
                        fh.write(data)
                    written.append(paths[i])
            if job.merge:
                out.close()
                out = None
                written.append(paths[0])
        except BaseException:
            if out is not None:
                out.close()
            for p in ([paths[0]] if job.merge else []):
                try:
                    os.remove(p)
                except OSError:
                    pass
            raise
        if write_provenance:
            prov = self.provenance(job, effective)
            for p in written:
                with open(p + ".json", "w", encoding="utf-8") as fh:
                    json.dump(prov, fh, ensure_ascii=False, indent=2)
        if cache is not None:
            cache.cleanup()
        if progress_cb:
            progress_cb(n, n, "Descarga completa", 1.0)
        return written

    def _post(self, data, job):
        """Envuelve postprocess_step devolviendo (bytes, info efectiva)."""
        res = self.postprocess_step(data, job)
        if isinstance(res, tuple):
            return res
        return res, {}


def read_provenance(path):
    """JSON de procedencia junto a un archivo, o None."""
    p = path + ".json"
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None
