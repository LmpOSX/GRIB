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

from .. import grib_encode as ge
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

    def __init__(self, key, label, kind, default, choices=None, lo=None, hi=None, help="",
                 group="fuente"):
        self.key, self.label, self.kind, self.default = key, label, kind, default
        self.choices = choices or []
        self.lo, self.hi, self.help = lo, hi, help
        self.group = group       # dónde va en el diálogo de descarga: 'fuente' o 'niveles'


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
                 dest_dir=".", basename=None, merge=True, params=None, suffix="",
                 area_mode="manual", area_codes=None, area_margin=0.0, wind_format="uv",
                 save_opts=None):
        self.run_date = run_date              # datetime.date UTC
        self.suffix = suffix                  # p. ej. '_wafs' cuando se convierte al bajar
        # Bloque «Archivo a guardar» (ver grib_encode): viento 'uv' (UGRD/VGRD,
        # como lo publica el modelo) o 'dirspeed' (WDIR/WIND, convertido al
        # bajar), decimales, etiqueta de capa, empaquetado y centro
        so = dict(save_opts or {})
        so["wind"] = so.get("wind") or wind_format
        self.save_opts = ge.normalize(so)
        self.wind_format = self.save_opts["wind"]
        # Área de descarga (ver app/areas.py): 'manual' o 'fir' con los códigos
        # de las áreas marcadas; `region` ya es la envolvente con el margen.
        self.area_mode = area_mode if area_mode in ("manual", "fir") else "manual"
        self.area_codes = list(area_codes or []) if self.area_mode == "fir" else []
        self.area_margin = float(area_margin or 0.0)
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

    @property
    def area_tag(self):
        """'SAEF+SACF' o 'MANUAL': va en el nombre del archivo y en la procedencia."""
        from .. import areas
        return areas.area_tag(self.area_codes, self.area_mode)

    def file_paths(self, source):
        """Rutas de salida. El nombre automático lleva la etiqueta del área
        (`..._SAEF+SACF_...` o `..._MANUAL`) salvo que la zona sea global, y
        `_a1p25` (o la que sea) si el bloque regrilla."""
        if self.basename:
            base = self.basename
        else:
            base = source.default_basename(self)
            if self.region is not None:
                base += "_" + self.area_tag
            res = ge.regrid_res(self.save_opts)
            if res is not None:
                base += f"_a{int(res)}p{int(round((res % 1) * 100)):02d}"
        base += (self.suffix or "")
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
    extra_levels_param = None  # parámetro bool que habilita niveles extra (GFS: intermedios)
    cycles = [0, 6, 12, 18]
    availability_lag_h = 4.0
    region_filter = "servidor"   # 'servidor', 'local' o 'ninguno'
    grid_resolution_deg = None   # resolución de la grilla entregada (grados) o None

    def grid_resolution(self, params=None):
        """Resolución (grados) de la grilla que entrega la fuente con estos
        parámetros, o None si no se conoce (fuente genérica). Sirve para
        redondear la zona hacia afuera y estimar el tamaño de la descarga."""
        return self.grid_resolution_deg

    def params_for_regrid(self, res_deg, params=None):
        """Parámetros de la fuente que entregan directamente la grilla de
        `res_deg` grados (lo que pide el bloque «Archivo a guardar»), o None
        si la fuente no tiene cómo. Lo usa Obtener datos al elegir un perfil
        con regrillado."""
        return None

    def server_region(self, job):
        """Zona que se le pide al servidor: la del trabajo redondeada hacia
        afuera a la grilla del modelo (nunca más chica que la pedida)."""
        from .. import areas
        if job.region is None:
            return None
        return areas.round_outward(job.region, self.grid_resolution(job.params))

    # ── Descripción ──────────────────────────────────────────────────────────

    def default_params(self):
        return {p.key: p.default for p in self.params}

    def merged_params(self, params):
        d = self.default_params()
        d.update({k: v for k, v in (params or {}).items() if k in d})
        return d

    def steps(self, params=None, cycle=None):
        """Plazos (horas) que ofrece la fuente (si dependen del ciclo, con
        cycle=None se devuelve la unión)."""
        return list(range(0, 121, 3))

    def credentials(self):
        """Secretos guardados en el llavero para esta fuente (o los pasados
        a download/test_connection)."""
        cur = getattr(self, "_creds", None)
        if cur:
            return cur
        if not self.needs_credentials:
            return {}
        from . import credentials as cr
        return cr.get_all(self.key)

    def fetch_request(self, req, fetch_fn, chunk_cb=None, cancel=None, retry_wait=1.5,
                      max_bytes=None, status_cb=None):
        """Obtiene los bytes de un Request. Por defecto HTTP(S) con reintentos;
        las fuentes con otro transporte o cliente lo redefinen. `status_cb(texto)`
        permite informar estados intermedios (reintentos, esperas) a la UI."""
        if max_bytes is not None:
            return fetch_fn(req.url, headers=req.headers, max_bytes=max_bytes)
        return fetch_with_retries(fetch_fn, req.url, headers=req.headers, chunk_cb=chunk_cb,
                                  cancel=cancel, retry_wait=retry_wait)

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
        offered = set(self.steps(job.params, job.cycle))
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

    def postprocess_step(self, data, job, step=None):
        """Recorte / regrillado / conversión local de los bytes de un plazo ya
        validado. Puede devolver (bytes, info) para la procedencia."""
        return data

    def provenance(self, job, effective=None):
        d = {"fuente": self.key, "nombre": self.name, "modelo": self.model, "tipo": self.kind,
             "corrida": job.run.strftime("%Y-%m-%dT%H:%MZ"), "plazos_h": job.steps,
             "variables": job.variables, "niveles_hpa": job.levels, "zona": job.region,
             "parametros": self.merged_params(job.params), "viento": job.wind_format,
             "descargado": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        if job.region is not None:
            from .. import areas
            d["area"] = areas.area_info(job.area_mode, job.area_codes, job.area_margin, job.region,
                                        self.server_region(job))
        d.update(effective or {})
        return d

    def check_region(self, data, job):
        """Comprueba que la grilla obtenida contenga la zona pedida. Devuelve
        un dict para la procedencia: zona_obtenida, cubre y, si quedó más
        chica, `aviso` con los lados que faltan."""
        if job.region is None or self.expect != "grib":
            return {}
        from .. import areas
        from ..regrid import grid_bbox
        try:
            bbox = grid_bbox(data)
        except Exception:
            return {}
        if bbox is None:
            return {}
        lonmin, lonmax, latmin, latmax = bbox
        missing = areas.check_coverage(job.region, bbox, tol=1e-3)
        info = {"zona_obtenida": [latmax, latmin, lonmin, lonmax], "cubre": not missing}
        if missing:
            info["aviso"] = ("La grilla obtenida es más chica que la zona pedida "
                             f"({job.area_tag}): " + "; ".join(missing)
                             + ". El servidor recortó distinto de lo pedido.")
        return info

    def test_connection(self, params=None, credentials=None, fetch_fn=None):
        """Verifica acceso; por defecto pide el primer plazo de la última
        corrida (sólo el comienzo) y clasifica el resultado."""
        from .. import gfs_download
        fetch_fn = fetch_fn or gfs_download.fetch
        self._creds = credentials or None
        day, cyc = self.latest_run()
        steps = self.steps(params, cyc)
        job = DownloadJob(day, cyc, [steps[0]], self.default_variables[:1],
                          self.viewer_levels[:1] or self.levels[:1], None, params=params)
        try:
            reqs = self.build_requests(job, job.steps[0])
            data = self.fetch_request(reqs[0], fetch_fn, max_bytes=4096)
            check_content(data, reqs[0].expect, "la prueba")
            return TestResult("ok", f"{self.name}: corrida {day:%Y-%m-%d} {cyc:02d}Z disponible")
        except DownloadError as exc:
            return TestResult(exc.status, str(exc).splitlines()[0])
        except Exception as exc:
            status, msg = classify_exception(exc)
            return TestResult(status, msg)

    # ── Descarga genérica ────────────────────────────────────────────────────

    def download(self, job, progress_cb=None, cancel=None, fetch_fn=None, cache=None,
                 retry_wait=1.5, write_provenance=True, credentials=None, wafs=None):
        """Baja todos los plazos del trabajo con caché, reintentos y
        validación; escribe los archivos y su procedencia. Devuelve las
        rutas escritas. Lanza DownloadError / DownloadCancelled.

        `wafs`: opciones de `wafs_format.convert_to_wafs` (fl_min, fl_max,
        extend, extrapolate) para convertir cada plazo al formato WAFS antes
        de escribirlo (sólo fuentes de altura; lo que ya viene en WAFS no se
        toca). None = sin conversión."""
        from .. import gfs_download
        fetch_fn = fetch_fn or gfs_download.fetch
        convert = wafs is not None and self.kind == "altura"
        if convert and not job.suffix:
            job.suffix = "_wafs"
        self._creds = credentials or None
        err = self.validate(job)
        if err:
            raise DownloadError(err)
        os.makedirs(job.dest_dir, exist_ok=True)
        paths = job.file_paths(self)
        n = len(job.steps)
        written = []
        out = None
        effective = {}
        seen = set()          # un mismo archivo puede cubrir varios plazos (WAFS)
        try:
            if job.merge:
                out = open(paths[0], "wb")
            for i, step in enumerate(job.steps):
                if cancel is not None and cancel():
                    raise DownloadCancelled()
                msg = f"Plazo +{step} h ({i + 1} de {n})"
                if progress_cb:
                    progress_cb(i, n, msg, i / n)
                reqs = [r for r in self.build_requests(job, step) if r.url not in seen]
                parts = []
                for k, req in enumerate(reqs):
                    if cancel is not None and cancel():
                        raise DownloadCancelled()
                    seen.add(req.url)
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
                    def status_cb(text, _i=i, _k=k, _m=len(reqs), _msg=sub):
                        if progress_cb:
                            progress_cb(_i, n, f"{_msg}: {text}", (_i + _k / _m) / n)
                    try:
                        data = self.fetch_request(req, fetch_fn, chunk_cb=chunk_cb, cancel=cancel,
                                                  retry_wait=retry_wait, status_cb=status_cb)
                    except DownloadCancelled:
                        raise
                    except DownloadError:
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
                if not data:
                    continue          # el plazo ya vino en un archivo anterior
                if progress_cb:
                    progress_cb(i, n, f"{msg}: procesando…", (i + 1) / n)
                try:
                    data, eff = self._post(data, job, step)
                except DownloadError:
                    raise
                except Exception as exc:
                    raise DownloadError(f"{self.name}: no se pudo procesar el plazo +{step} h: "
                                        f"{type(exc).__name__}: {exc}") from exc
                effective.update(eff)
                if i == 0:
                    cov = self.check_region(data, job)
                    if cov:
                        effective["area"] = dict(effective.get("area") or {}, **cov)
                if convert:
                    if progress_cb:
                        progress_cb(i, n, f"{msg}: convirtiendo a WAFS…", (i + 1) / n)
                    data, winfo = self._to_wafs(data, wafs, step)
                    effective.setdefault("wafs", {}).update(winfo)
                if data[:4] == b"GRIB" and not ge.is_default(job.save_opts):
                    # Archivo a guardar: viento como dirección y velocidad (al
                    # final, después de interpolar: la dirección no se
                    # interpola), decimales, etiqueta, empaquetado, centro
                    try:
                        data, ginfo = ge.recode(data, job.save_opts,
                                                labeled=bool(convert) or self.flight_levels,
                                                mode=(wafs or {}).get("mode"))
                    except Exception as exc:
                        raise DownloadError(f"{self.name}: no se pudo recodificar el plazo +{step} h "
                                            f"({ge.describe(job.save_opts)}): {exc}") from exc
                    effective["viento"] = job.wind_format
                    effective["guardado"] = dict({k: ginfo[k] for k in ge.KEYS},
                                                 descripcion=ge.describe(job.save_opts))
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
        self.last_provenance = None
        if write_provenance:
            area_eff = effective.pop("area", None)
            prov = self.provenance(job, effective)
            if area_eff:
                prov["area"] = dict(prov.get("area") or {}, **area_eff)
            self.last_provenance = prov
            for p in written:
                with open(p + ".json", "w", encoding="utf-8") as fh:
                    json.dump(prov, fh, ensure_ascii=False, indent=2)
        if cache is not None:
            cache.cleanup()
        if progress_cb:
            progress_cb(n, n, "Descarga completa", 1.0)
        return written

    def _post(self, data, job, step=None):
        """Envuelve postprocess_step devolviendo (bytes, info efectiva)."""
        res = self.postprocess_step(data, job, step)
        if isinstance(res, tuple):
            return res
        return res, {}

    def _to_wafs(self, data, opts, step=None):
        """Convierte los bytes de un plazo al formato WAFS (si hace falta).
        Devuelve (bytes, info resumida para la procedencia)."""
        from .. import wafs_format
        notes = []
        try:
            # Una fuente en niveles de presión crudos se convierte siempre: sus
            # niveles (850/700/500/250/100 hPa) coinciden con etiquetas
            # nominales y la detección los tomaría por un archivo por FL
            out, info = wafs_format.convert_if_needed(data, log=notes.append,
                                                      force=not self.flight_levels, **dict(opts))
        except Exception as exc:
            raise DownloadError(f"{self.name}: no se pudo convertir a WAFS el plazo +{step} h: "
                                f"{type(exc).__name__}: {exc}") from exc
        summary = {"formato": info.get("formato", "WAFS"), "convertido": bool(info.get("convertido")),
                   "fl_rango": info.get("fl_rango", ""), "modo": info.get("modo")}
        if info.get("convertido"):
            summary["niveles_origen_hpa"] = info.get("niveles_origen_hpa")
            if info.get("extrapolados"):
                summary["extrapolados"] = len(info["extrapolados"])
            if info.get("fl_omitidos"):
                summary["fl_omitidos"] = info["fl_omitidos"]
            if info.get("descartados"):
                summary["descartados"] = info["descartados"]
        if notes:
            summary["notas"] = notes[:20]
        return out, summary


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
