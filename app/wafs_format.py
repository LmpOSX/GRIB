# -*- coding: utf-8 -*-
"""Formato WAFS: el formato interno único del visor.

El producto OACI de viento y temperatura en altura (WAFS, World Area
Forecast System) es un GRIB2 en grilla regular lat/lon cuyos niveles son
niveles de vuelo cada 1000 ft (FL050…FL600) codificados como superficies
isobáricas (tipo 100) a la presión de la atmósfera estándar OACI de cada
FL, en Pa redondeada a 0,1 hPa (FL530 = 10040 Pa, FL340 = 25000 Pa, …).
Variables UGRD, VGRD, TMP (obligatorias), HGT y RH (RH sólo hasta FL180),
en K, m/s, gpm y %, con el viento referido al norte/este geográfico.

Referencia: código con el que NOAA produce el WAFS operativo,
https://github.com/NOAA-EMC/wafs (scripts/exwafs_grib2_0p25.sh, fix/wafs/).

Este módulo (sin Qt) reúne:

* ``isa_pa`` / ``wafs_pa`` / ``FL_TABLE``: la fórmula ISA y la tabla FL↔Pa;
* ``convert_to_wafs``: interpolación lineal en ln(p) desde los niveles de
  presión de origen a la presión ISA de cada FL, etiquetada según el modo
  (misma tabla y aritmética que el generador del servidor,
  ``docs/referencia/gfs_to_wafs.py``);
* ``is_wafs``: detección de archivos que ya vienen en WAFS (no se reconvierten);
* ``validate_wafs``: validador (avisa, no bloquea);
* ``write_idx``: inventario ``.idx`` tipo ``wgrib2 -s``;
* ``export_wafs``: exportación con selección, recorte, regrillado y
  verificación, usada por «Exportar a WAFS…»;
* línea de comandos: ``python -m app.wafs_format entrada.grib2 salida.grib2``.
"""
import datetime as dt
import json
import math
import os
import sys

import numpy as np

from .grib_engines import ec

# ── Tabla FL ↔ presión ───────────────────────────────────────────────────────
# La tabla vive en fl_table.py (copiada literal del generador del servidor):
# ISA_Pa exacta (donde se interpola el dato) y etiqueta nominal OACI56;
# OACI17 e INDRA14 son los subconjuntos nominales.

from . import fl_table as flt                      # noqa: E402
from .fl_table import (                            # noqa: E402,F401
    FL_STEP, FL_LOWEST, FL_HIGHEST, MODES, MODE_LABELS, DEFAULT_MODE, OACI17, INDRA14,
    mode_fls, normalize_mode, label_pa, label_text, table_rows,
)

DEFAULT_FL_MIN, DEFAULT_FL_MAX = 50, 530      # lo que cubre el GFS 850–100 hPa
LEVEL_TOL_PA = flt.ISA_TOL_PA  # tolerancia para reconocer un nivel por la columna ISA
RH_FL_MAX = 180              # la humedad relativa sólo va en niveles bajos

FL_TABLE = {fl: pa for fl, (pa, _h) in flt.FL_TABLE.items()}   # FL → ISA_Pa


def isa_pa(fl):
    """Presión ISA exacta (Pa) del FL según la tabla del servidor."""
    return flt.isa_pa(fl)


def wafs_pa(fl):
    """Alias histórico: la presión que NOAA codifica en el WAFS (= ISA_Pa)."""
    return flt.isa_pa(fl)


def fl_from_pa(pa, tol=LEVEL_TOL_PA):
    """FL cuya presión está a ≤ tol Pa de la columna ISA o coincide con la
    etiqueta nominal ×100, o None."""
    return flt.fl_from_pa(pa, tol)[0]


def fl_from_pa_col(pa, tol=LEVEL_TOL_PA):
    """(FL, 'isa' | 'nominal') o (None, None)."""
    return flt.fl_from_pa(pa, tol)


def fl_from_hpa(hpa, tol=LEVEL_TOL_PA):
    return fl_from_pa(hpa * 100.0, tol)


def fl_label(fl):
    return f"FL{fl:03d}"


def wafs_filename(cycle, step, model="gfs", res="0p25"):
    """Nombre del producto operativo: gfs.tHHz.wafs_0p25.fFFF.grib2."""
    return f"{model}.t{int(cycle):02d}z.wafs_{res}.f{int(round(step)):03d}.grib2"


# ── Lectura de mensajes ──────────────────────────────────────────────────────

WAFS_SHORTNAMES = {"u": "UGRD", "v": "VGRD", "t": "TMP", "gh": "HGT", "r": "RH",
                   "z": "HGT", "icaht": "ICAHT"}
WAFS_UNITS = {"u": ("m s**-1",), "v": ("m s**-1",), "t": ("K",), "gh": ("gpm",),
              "r": ("%",), "icaht": ("m",), "wdir": ("Degree true",), "ws": ("m s**-1",)}
# Viento como dirección y velocidad: el visor lo lee, pero el WAFS operativo lleva U/V
WIND_DS_SHORTNAMES = {"wdir": "WDIR", "ws": "WIND"}
WAFS_2D_LEVELS = ("maxWind", "tropopause")
REQUIRED = ("u", "v", "t")


def _load(src):
    """bytes o ruta → bytes."""
    if isinstance(src, (bytes, bytearray)):
        return bytes(src)
    with open(src, "rb") as fh:
        return fh.read()


def iter_messages(data):
    """Itera (gid, offset, tamaño) sobre los mensajes de un GRIB2 en memoria.
    El llamador debe liberar el gid (o usar `with_messages`)."""
    pos = 0
    n = len(data)
    while pos < n:
        try:
            gid = ec.codes_new_from_message(data[pos:])
        except Exception:
            # bytes que no son un GRIB completo: se termina en lo que se pudo leer
            break
        if gid is None:
            break
        try:
            size = int(ec.codes_get_message_size(gid))
        except Exception:
            ec.codes_release(gid)
            break
        if size <= 0:
            ec.codes_release(gid)
            break
        yield gid, pos, size
        pos += size


def _get(gid, key, default=None):
    try:
        return ec.codes_get(gid, key)
    except Exception:
        return default


def level_pa(gid):
    """Presión del primer nivel fijo en Pa (exacta, desde el valor escalado),
    o None si no es una superficie isobárica."""
    tol = _get(gid, "typeOfLevel", "")
    if tol not in ("isobaricInhPa", "isobaricInPa"):
        return None
    scaled = _get(gid, "scaledValueOfFirstFixedSurface")
    factor = _get(gid, "scaleFactorOfFirstFixedSurface")
    if scaled is None or factor is None:
        lev = float(_get(gid, "level", 0))
        return lev * 100.0 if tol == "isobaricInhPa" else lev
    return float(scaled) * 10.0 ** (-int(factor))


def _step_hours(gid):
    try:
        return float(_get(gid, "endStep", 0))
    except Exception:
        return 0.0


# ── Detección ────────────────────────────────────────────────────────────────

def level_pas(src):
    """Presiones de nivel (Pa, enteros) distintas que trae el archivo."""
    if ec is None:
        raise RuntimeError("se requiere eccodes")
    data = _load(src)
    pas = set()
    for gid, _pos, _size in iter_messages(data):
        try:
            pa = level_pa(gid)
        finally:
            ec.codes_release(gid)
        if pa is not None:
            pas.add(int(round(pa)))
    return sorted(pas, reverse=True)


def detect_mode(src):
    """Clasificación de los niveles del archivo (ver fl_table.classify):
    modo que los explica, si cuenta como etiquetado por FL, {Pa: FL} y los
    no reconocidos."""
    return flt.classify(level_pas(src))


def is_wafs(src, tol=LEVEL_TOL_PA):
    """True si el archivo ya está etiquetado por FL en alguno de los cuatro
    modos (no hay que convertirlo)."""
    return bool(detect_mode(src)["labeled"])


# ── Conversión ───────────────────────────────────────────────────────────────

class ConversionResult:
    """Bytes del WAFS y resumen de la conversión (para la procedencia y el log)."""

    def __init__(self, data, info):
        self.data = data
        self.info = info

    def __bytes__(self):
        return self.data


def fl_range(source_levels_hpa, fl_min=DEFAULT_FL_MIN, fl_max=DEFAULT_FL_MAX, extend=True):
    """Rango de FL a generar: el configurado y, con `extend`, ampliado por
    abajo si la fuente trae niveles por debajo de 850 hPa y por arriba si
    trae niveles por encima de 100 hPa (hasta FL600), sin extrapolar."""
    lo, hi = int(fl_min), int(fl_max)
    if extend and source_levels_hpa:
        p_max = max(source_levels_hpa) * 100.0
        p_min = min(source_levels_hpa) * 100.0
        covered = [fl for fl, pa in FL_TABLE.items() if p_min <= pa <= p_max]
        # Sólo se amplía más allá de la banda 850–100 hPa del GFS (FL050–FL530)
        if covered and min(covered) < DEFAULT_FL_MIN:
            lo = min(lo, min(covered))
        if covered and max(covered) > DEFAULT_FL_MAX:
            hi = max(hi, max(covered))
    lo = max(FL_LOWEST, lo - lo % FL_STEP)
    hi = min(FL_HIGHEST, hi - hi % FL_STEP)
    return lo, hi


def convert_to_wafs(src, fl_min=DEFAULT_FL_MIN, fl_max=DEFAULT_FL_MAX, extend=True,
                    extrapolate=False, tables_version=None, centre=None, sub_centre=None,
                    log=None, mode=DEFAULT_MODE):
    """GRIB2 en niveles de presión → GRIB2 etiquetado por FL (bytes).

    Para cada (plazo, variable) se apilan los niveles de presión del origen y
    se interpola linealmente en ln(p) a la presión ISA exacta de cada FL del
    rango que abarca el `mode` (INDRA, OACI, OACI56 o WAFS); el nivel del
    mensaje se graba con la etiqueta del modo (nominal hPa×100, o la ISA en
    Pa en el modo WAFS), igual que el generador del servidor.
    Los FL fuera del rango de niveles del origen se omiten, salvo
    `extrapolate`, que usa el nivel más cercano y lo anota en `info`.
    Los mensajes que no están en niveles de presión se descartan, excepto
    los campos 2D del WAFS (viento máximo, tropopausa) que pasan tal cual.
    Con los valores por defecto reproduce byte a byte el conversor de
    referencia. Devuelve ConversionResult."""
    if ec is None:
        raise RuntimeError("la conversión requiere eccodes")
    data = _load(src)
    log = log or (lambda msg: None)
    # Viento como dirección y velocidad: se interpola en U/V (la dirección no
    # se puede interpolar) y al final se vuelve al formato del origen
    from . import wind_format as wfm
    wind_fmt = wfm.detect(data)
    if wind_fmt in ("dirspeed", "mixto"):
        data, _winfo = wfm.convert(data, "uv")
        log("viento en dirección/velocidad: se interpola en U/V y se vuelve a dir/vel al final")

    # 1) leer todo, agrupado por (plazo, variable)
    fields, tmpl, order = {}, {}, []
    passthrough = bytearray()
    n_pass = n_drop = 0
    dropped = {}
    for gid, pos, size in iter_messages(data):
        try:
            pa = level_pa(gid)
            short = _get(gid, "shortName", "?")
            if pa is None:
                tol = _get(gid, "typeOfLevel", "?")
                if tol in WAFS_2D_LEVELS:
                    passthrough += data[pos:pos + size]
                    n_pass += 1
                else:
                    n_drop += 1
                    dropped[(short, tol)] = dropped.get((short, tol), 0) + 1
                continue
            k = (str(_get(gid, "stepRange", "0")), short)
            lev = pa / 100.0                     # hPa
            fields.setdefault(k, {})[lev] = np.asarray(ec.codes_get_values(gid), dtype=float)
            if k not in tmpl:
                tmpl[k] = ec.codes_clone(gid)
                order.append(k)
        finally:
            ec.codes_release(gid)

    mode = normalize_mode(mode)
    all_levels = sorted({lv for levs in fields.values() for lv in levs})
    lo, hi = fl_range(all_levels, fl_min, fl_max, extend)
    fls = [fl for fl in mode_fls(mode) if lo <= fl <= hi]
    extrapolated = []
    omitted = {}
    out = bytearray()
    n = 0
    try:
        # 2) interpolar en ln(p) a cada FL y escribir
        for (step, var) in order:
            levs = fields[(step, var)]
            p = np.array(sorted(levs))           # hPa ascendente
            lnp = np.log(p)
            stack = np.stack([levs[x] for x in p])   # (nlev, npts)
            var_fls = [fl for fl in fls if fl <= RH_FL_MAX] if var == "r" else fls
            for fl in var_fls:
                pa = isa_pa(fl)                      # el dato va siempre a la ISA exacta
                lp = math.log(pa / 100.0)
                if lp < lnp[0] or lp > lnp[-1]:
                    if not extrapolate or len(p) == 0:
                        omitted[fl] = omitted.get(fl, 0) + 1
                        continue
                    nearest = float(p[0] if lp < lnp[0] else p[-1])
                    vals = stack[0] if lp < lnp[0] else stack[-1]
                    extrapolated.append({"plazo": step, "variable": var, "fl": fl,
                                         "nivel_hpa": nearest})
                    log(f"FL{fl:03d} {var} +{step} h: fuera del rango del origen, "
                        f"se usa el nivel más cercano ({nearest:g} hPa)")
                else:
                    j = np.searchsorted(lnp, lp)
                    j = min(max(j, 1), len(p) - 1)
                    w = (lp - lnp[j - 1]) / (lnp[j] - lnp[j - 1])
                    vals = (1 - w) * stack[j - 1] + w * stack[j]
                g = ec.codes_clone(tmpl[(step, var)])
                try:
                    ec.codes_set(g, "typeOfFirstFixedSurface", 100)
                    ec.codes_set(g, "scaleFactorOfFirstFixedSurface", 0)
                    # Etiqueta del modo: nominal hPa×100 (85000 = FL050) o ISA Pa (84310)
                    ec.codes_set(g, "scaledValueOfFirstFixedSurface", int(label_pa(fl, mode)))
                    _set_identity(g, tables_version, centre, sub_centre)
                    ec.codes_set_values(g, vals)
                    out += ec.codes_get_message(g)
                finally:
                    ec.codes_release(g)
                n += 1
    finally:
        for g in tmpl.values():
            ec.codes_release(g)
    out += passthrough
    info = {
        "formato": "WAFS",
        "modo": mode,
        "mensajes": n + n_pass,
        "fl_min": fls[0] if n else None,
        "fl_max": fls[-1] if n else None,
        "fl_rango": f"FL{fls[0]:03d}–FL{fls[-1]:03d}" if n else "",
        "niveles_origen_hpa": all_levels,
        "fl_omitidos": sorted(omitted),
        "extrapolados": extrapolated,
        "campos_2d": n_pass,
        "descartados": n_drop,
        "descartados_detalle": {f"{k[0]} @ {k[1]}": v for k, v in dropped.items()},
        "variables": sorted({var for _s, var in order}),
        "plazos": list(dict.fromkeys(step for step, _v in order)),
        "viento": "dirspeed" if wind_fmt in ("dirspeed", "mixto") else ("uv" if wind_fmt else None),
    }
    if n and wind_fmt in ("dirspeed", "mixto"):
        out, _winfo = wfm.convert(bytes(out), "dirspeed")
        out = bytearray(out)
    if omitted:
        log(f"FL omitidos por estar fuera de los niveles del origen: "
            + ", ".join(f"FL{fl:03d}" for fl in sorted(omitted)))
    if n_drop:
        log(f"{n_drop} mensaje(s) fuera de niveles de presión descartados: "
            + ", ".join(f"{k} ({v})" for k, v in info["descartados_detalle"].items()))
    return ConversionResult(bytes(out), info)


def _set_identity(gid, tables_version=None, centre=None, sub_centre=None):
    """Tabla maestra y centro/subcentro, si se pidieron y ecCodes los acepta."""
    for key, val in (("tablesVersion", tables_version), ("centre", centre),
                     ("subCentre", sub_centre)):
        if val is None:
            continue
        try:
            ec.codes_set(gid, key, val)
        except Exception:
            pass


def convert_if_needed(src, force=False, **opts):
    """Convierte salvo que el archivo ya esté etiquetado por FL (se devuelve
    igual, con su modo) o no tenga niveles de presión. `force` convierte
    aunque los niveles parezcan etiquetados: se usa con lo que baja de una
    fuente en niveles de presión crudos (un GFS con 850/700/500/250/100 hPa
    coincide con etiquetas nominales y no es un archivo por FL). Devuelve
    (bytes, info); info['convertido'] dice si se tocó."""
    data = _load(src)
    det = detect_mode(data)
    if det["labeled"] and not force:
        return data, {"formato": "WAFS", "modo": det["mode"], "convertido": False,
                      "fl_rango": describe_levels(data)}
    log = opts.pop("log", None)
    res = convert_to_wafs(data, log=log, **opts)
    if res.info["mensajes"] == 0:
        return data, {"formato": "origen", "convertido": False,
                      "aviso": "sin niveles de presión que convertir"}
    info = dict(res.info)
    info["convertido"] = True
    return res.data, info


def describe_levels(src):
    """'FL050–FL530' según los niveles isobáricos presentes."""
    fls = sorted(set(detect_mode(src)["fls"].values()))
    return f"FL{fls[0]:03d}–FL{fls[-1]:03d}" if fls else ""


def relabel(src, mode):
    """Reetiqueta un archivo ya etiquetado por FL a otro modo: el dato no se
    toca (ya está en la ISA exacta); se cambia la presión grabada en cada
    mensaje y se descartan los FL que el modo no abarca. Devuelve bytes."""
    if ec is None:
        raise RuntimeError("se requiere eccodes")
    mode = normalize_mode(mode)
    keep = set(mode_fls(mode))
    data = _load(src)
    out = bytearray()
    for gid, pos, size in iter_messages(data):
        try:
            pa = level_pa(gid)
            if pa is None:
                out += data[pos:pos + size]
                continue
            fl = fl_from_pa(pa)
            if fl is None or fl not in keep:
                continue
            ec.codes_set(gid, "scaleFactorOfFirstFixedSurface", 0)
            ec.codes_set(gid, "scaledValueOfFirstFixedSurface", int(label_pa(fl, mode)))
            out += ec.codes_get_message(gid)
        finally:
            ec.codes_release(gid)
    return bytes(out)


def level_pa_or_none(gid):
    try:
        return level_pa(gid)
    finally:
        ec.codes_release(gid)


def _gids(data):
    for gid, _pos, _size in iter_messages(data):
        yield gid


def options_from_config(cfg):
    """Opciones de conversión según Preferencias ▸ WAFS, o None si está
    desactivada la conversión al descargar."""
    if not cfg.get("wafs_convert", True):
        return None
    return {"fl_min": int(cfg.get("wafs_fl_min", DEFAULT_FL_MIN)),
            "fl_max": int(cfg.get("wafs_fl_max", DEFAULT_FL_MAX)),
            "extend": bool(cfg.get("wafs_fl_extend", True)),
            "extrapolate": bool(cfg.get("wafs_extrapolate", False)),
            "mode": normalize_mode(cfg.get("wafs_mode", DEFAULT_MODE))}


def convert_file(src_path, dst_path, provenance=None, idx=True, force=False, save_opts=None, **opts):
    """Convierte un archivo a WAFS, escribe el .idx y un JSON de procedencia
    junto a la salida (de qué fuente, modelo y archivo original salió).
    `force` convierte aunque los niveles parezcan etiquetados por FL;
    `save_opts` es el bloque «Archivo a guardar» (grib_encode) que se aplica
    al convertido. Devuelve (dst_path, info)."""
    data, info = convert_if_needed(src_path, force=force, **opts)
    if info.get("convertido") and save_opts:
        from . import grib_encode as ge
        if not ge.is_default(save_opts):
            data, ginfo = ge.recode(data, save_opts, labeled=True, mode=info.get("modo"))
            info["guardado"] = dict({k: ginfo[k] for k in ge.KEYS}, descripcion=ge.describe(save_opts))
    with open(dst_path, "wb") as fh:
        fh.write(data)
    prov = dict(provenance or {})
    prov.setdefault("fuente", "archivo local")
    prov.setdefault("nombre", "archivo local")
    prov.setdefault("tipo", "altura")
    run, steps = run_and_steps(data)
    if run is not None:
        prov.setdefault("corrida", run.strftime("%Y-%m-%dT%H:%MZ"))
    if steps:
        prov.setdefault("plazos_h", steps)
    prov["archivo_original"] = os.path.abspath(src_path)
    prov["wafs"] = info
    if info.get("guardado"):
        prov["guardado"] = info["guardado"]
        prov["viento"] = info["guardado"]["wind"]
    prov["convertido"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(dst_path + ".json", "w", encoding="utf-8") as fh:
        json.dump(prov, fh, ensure_ascii=False, indent=2)
    if idx:
        write_idx(dst_path)
    return dst_path, info


def run_and_steps(src):
    """(datetime UTC de la corrida, plazos en horas) según los mensajes."""
    run, steps = None, set()
    for gid, _pos, _size in iter_messages(_load(src)):
        try:
            if run is None:
                d, t = int(_get(gid, "dataDate", 0)), int(_get(gid, "dataTime", 0))
                if d:
                    run = dt.datetime(d // 10000, (d // 100) % 100, d % 100, t // 100, t % 100,
                                      tzinfo=dt.timezone.utc)
            steps.add(_step_hours(gid))
        finally:
            ec.codes_release(gid)
    return run, sorted(steps)


def converted_path_for(path):
    """Nombre del WAFS que se escribe junto a un archivo local convertido."""
    base, ext = os.path.splitext(path)
    if base.endswith("_wafs"):
        return path
    return f"{base}_wafs{ext or '.grib2'}"


# ── Validación ───────────────────────────────────────────────────────────────

def validate_wafs(src, tol=LEVEL_TOL_PA):
    """Comprueba que el archivo cumpla el formato WAFS. Devuelve un dict con
    `ok` (sin avisos), `avisos` (lista de textos), `mensajes`, `niveles`
    ({FL: Pa}), `variables`, `plazos` y `grilla`. Nunca lanza por desvíos."""
    if ec is None:
        raise RuntimeError("se requiere eccodes")
    data = _load(src)
    det = detect_mode(data)
    avisos = []
    levels = {}
    variables = {}
    steps = set()
    grids = set()
    n = 0
    per_step_vars = {}
    for gid, _pos, _size in iter_messages(data):
        try:
            n += 1
            short = _get(gid, "shortName", "?")
            tol_name = _get(gid, "typeOfLevel", "?")
            units = _get(gid, "units", "")
            step = str(_get(gid, "stepRange", "0"))
            steps.add(step)
            grids.add((_get(gid, "gridType"), _get(gid, "Ni"), _get(gid, "Nj"),
                       round(float(_get(gid, "latitudeOfFirstGridPointInDegrees", 0)), 3),
                       round(float(_get(gid, "longitudeOfFirstGridPointInDegrees", 0)), 3)))
            if _get(gid, "gridType") != "regular_ll":
                avisos.append(f"mensaje {n}: grilla {_get(gid, 'gridType')} (se espera regular lat/lon)")
            pa = level_pa(gid)
            if pa is not None:
                fl = det["fls"].get(int(round(pa)))
                if fl is None:
                    avisos.append(f"mensaje {n}: nivel {pa:.0f} Pa no es la presión ISA ni la "
                                  f"etiqueta nominal de un FL")
                else:
                    levels[fl] = int(round(pa))
                    if short == "r" and fl > RH_FL_MAX:
                        avisos.append(f"mensaje {n}: RH en FL{fl:03d}, el WAFS la lleva sólo hasta "
                                      f"FL{RH_FL_MAX}")
            elif tol_name not in WAFS_2D_LEVELS:
                avisos.append(f"mensaje {n}: {short} en nivel '{tol_name}' no pertenece al WAFS")
            if short in WIND_DS_SHORTNAMES:
                if short == "wdir":
                    avisos.append(f"mensaje {n}: viento como dirección y velocidad (WDIR/WIND); "
                                  "el WAFS operativo lleva U/V (UGRD/VGRD)")
                expected = WAFS_UNITS.get(short)
                if expected and units not in expected:
                    avisos.append(f"mensaje {n}: {short} en '{units}', se espera {expected[0]}")
            elif short not in WAFS_SHORTNAMES:
                avisos.append(f"mensaje {n}: variable '{short}' no es una variable WAFS "
                              "(UGRD, VGRD, TMP, HGT, RH, ICAHT)")
            else:
                expected = WAFS_UNITS.get(short)
                if expected and units not in expected:
                    avisos.append(f"mensaje {n}: {short} en '{units}', se espera {expected[0]}")
            if short in ("u", "v"):
                if int(_get(gid, "uvRelativeToGrid", 0) or 0) != 0:
                    avisos.append(f"mensaje {n}: viento relativo a la grilla (se espera norte/este "
                                  "geográfico)")
            variables[short] = variables.get(short, 0) + 1
            per_step_vars.setdefault(step, set()).add(short)
        finally:
            ec.codes_release(gid)
    if n == 0:
        avisos.append("el archivo no contiene mensajes GRIB")
    if "wdir" in variables and "ws" in variables:
        # dirección y velocidad cubren el viento (el lector deriva U/V)
        variables.setdefault("u", variables["wdir"])
        variables.setdefault("v", variables["ws"])
        for vs in per_step_vars.values():
            if "wdir" in vs and "ws" in vs:
                vs.update(("u", "v"))
    for req in REQUIRED:
        if n and req not in variables:
            avisos.append(f"falta la variable obligatoria {WAFS_SHORTNAMES[req]}")
    for step, vs in per_step_vars.items():
        missing = [WAFS_SHORTNAMES[r] for r in REQUIRED if r not in vs and r in variables]
        if missing:
            avisos.append(f"plazo {step}: sin {', '.join(missing)}")
    if len(grids) > 1:
        avisos.append(f"{len(grids)} grillas distintas en el mismo archivo")
    # Deduplicar avisos repetidos por mensaje (mismo texto sin el número)
    seen, uniq = {}, []
    for a in avisos:
        key = a.split(": ", 1)[1] if a.startswith("mensaje ") else a
        if key in seen:
            seen[key] += 1
            continue
        seen[key] = 1
        uniq.append(a)
    uniq = [a + (f" (×{seen[a.split(': ', 1)[1] if a.startswith('mensaje ') else a]})"
                 if seen[a.split(": ", 1)[1] if a.startswith("mensaje ") else a] > 1 else "")
            for a in uniq]
    if n and levels and not det["labeled"] and not det["unrecognized"]:
        uniq.append(f"los niveles coinciden con etiquetas del modo {det['mode']} pero no "
                    "alcanzan para tomarlo por un archivo etiquetado por FL (faltan FL de INDRA)")
    g = sorted(grids)[0] if grids else None
    return {"ok": not uniq, "avisos": uniq, "mensajes": n, "niveles": dict(sorted(levels.items())),
            "variables": variables, "plazos": sorted(steps, key=_step_key),
            "grilla": {"tipo": g[0], "ni": g[1], "nj": g[2]} if g else None,
            "modo": det["mode"], "etiquetado": det["labeled"]}


def _step_key(s):
    try:
        return float(str(s).split("-")[-1])
    except ValueError:
        return 0.0


# ── Inventario .idx ──────────────────────────────────────────────────────────

def _idx_level(gid):
    tol = _get(gid, "typeOfLevel", "?")
    pa = level_pa(gid)
    if pa is not None:
        return f"{pa / 100.0:g} mb"
    if tol == "maxWind":
        return "max wind"
    if tol == "tropopause":
        return "tropopause"
    if tol == "heightAboveGround":
        return f"{float(_get(gid, 'level', 0)):g} m above ground"
    if tol == "heightAboveSea":
        return f"{float(_get(gid, 'level', 0)):g} m above mean sea level"
    if tol == "surface":
        return "surface"
    return tol


def inventory_lines(src):
    """Líneas tipo `wgrib2 -s`: n:offset:d=YYYYMMDDHH:VAR:nivel:plazo:"""
    data = _load(src)
    lines = []
    for i, (gid, pos, _size) in enumerate(iter_messages(data), 1):
        try:
            short = _get(gid, "shortName", "?")
            var = WAFS_SHORTNAMES.get(short, str(short).upper())
            d = f"{int(_get(gid, 'dataDate', 0)):08d}{int(_get(gid, 'dataTime', 0)) // 100:02d}"
            h = _step_hours(gid)
            rng = str(_get(gid, "stepRange", "0"))
            if "-" in rng:
                ft = f"{rng} hour fcst"
            else:
                ft = "anl" if h == 0 else f"{h:g} hour fcst"
            lines.append(f"{i}:{pos}:d={d}:{var}:{_idx_level(gid)}:{ft}:")
        finally:
            ec.codes_release(gid)
    return lines


def write_idx(path):
    """Escribe `path.idx` junto al archivo y devuelve su ruta."""
    idx = path + ".idx"
    with open(idx, "w", encoding="ascii") as fh:
        fh.write("\n".join(inventory_lines(path)) + "\n")
    return idx


# ── Exportación ──────────────────────────────────────────────────────────────

BASIC_VARS = ("u", "v", "t", "wdir", "ws")   # el viento, en U/V o en dirección y velocidad
EXPORT_REGRID = [("ninguno", "Sin regrillar (grilla del archivo)"),
                 ("0.25", "0,25° bilineal (como el producto operativo)"),
                 ("0.5", "0,50° bilineal"),
                 ("1.0", "1,00° bilineal (para el FDP)"),
                 ("1.25", "1,25° bilineal (WAFS clásico, WAFC London)")]
_REGRID_LABELS = {"0.25": "0p25", "0.5": "0p50", "1.0": "1p00", "1.25": "1p25"}


def export_wafs(src, dest_dir, steps=None, fls=None, variables="basicas", region=None,
                regrid="ninguno", per_step=True, model="gfs", basename=None,
                tables_version=25, centre=None, sub_centre=None, idx=True, convert_opts=None,
                progress_cb=None, provenance=None, mode=None, regrid_engine="eccodes",
                wgrib2_path="", save_opts=None):
    """Escribe lo cargado como WAFS.

    src        ruta (o bytes) del archivo abierto en el visor; si no está en
               WAFS se convierte primero (convert_opts).
    steps      plazos a incluir (horas, float/int) o None = todos.
    fls        FL a incluir (lista) o None = todos los del archivo.
    variables  'basicas' (UGRD/VGRD o WDIR/WIND, y TMP) o 'todas'.
    region     (top, bottom, left, right) para recortar, o None.
    regrid     'ninguno', '0.25', '0.5', '1.0' o '1.25' (bilineal).
    regrid_engine 'eccodes' (bilineal propio) o 'wgrib2' (`-new_grid`, si
               ese wgrib2 tiene la interpolación; si no, el propio, avisado).
    per_step   True: un archivo por plazo con nombre gfs.tHHz.wafs_0p25.fFFF.grib2;
               False: un único archivo multi-plazo (`basename` o
               model.tHHz.wafs_RES.fFFF-FFF.grib2).
    save_opts  bloque «Archivo a guardar» (grib_encode) o None: si trae
               `regrid` manda sobre `regrid` (y su motor sobre `regrid_engine`);
               el resto (viento, decimales, orden de las celdas, longitudes…)
               se aplica a cada plazo después de regrillar.
    provenance procedencia del archivo de origen (dict) o None: si se da, se
               escribe `archivo.json` junto a cada salida (conserva fuente,
               corrida y el área de descarga con sus códigos de FIR).
    Devuelve un dict con 'archivos', 'verificacion' (por archivo) y 'avisos'
    del validador."""
    from .regrid import crop_grib, regrid_to, wgrib2_can_regrid
    from . import grib_encode as ge
    if ec is None:
        raise RuntimeError("la exportación requiere eccodes")
    if save_opts is not None:
        save_opts = ge.normalize(save_opts)
        if save_opts["regrid"] != "origen":
            regrid = save_opts["regrid"]
        if save_opts.get("engine"):
            regrid_engine = save_opts["engine"]
            wgrib2_path = save_opts.get("wgrib2_path", wgrib2_path)
        if save_opts["tables"] != "origen":
            tables_version = None                          # manda la del bloque
        save_opts = dict(save_opts, regrid="origen")      # el regrillado va aparte, por plazo
        if ge.is_default(save_opts):
            save_opts = None
    progress_cb = progress_cb or (lambda frac, msg: None)
    data = _load(src)
    convert_opts = dict(convert_opts or {})
    mode = normalize_mode(mode or convert_opts.get("mode") or DEFAULT_MODE)
    convert_opts["mode"] = mode
    det = detect_mode(data)
    crude = flt.labeled_by_provenance(provenance) is False
    if crude or not det["labeled"]:
        progress_cb(0.05, f"Convirtiendo a WAFS (modo {mode})…")
        data = convert_to_wafs(data, **convert_opts).data
    elif det["mode"] != mode or (mode in ("INDRA", "OACI") and
                                 set(det["fls"].values()) - set(mode_fls(mode))):
        progress_cb(0.05, f"Reetiquetando al modo {mode}…")
        data = relabel(data, mode)
    keep_vars = set(BASIC_VARS) if variables == "basicas" else None
    want_steps = {float(s) for s in steps} if steps is not None else None
    want_fls = {int(f) for f in fls} if fls is not None else None

    progress_cb(0.15, "Seleccionando mensajes…")
    groups = {}            # horas → bytearray
    for gid, pos, size in iter_messages(data):
        try:
            short = _get(gid, "shortName", "?")
            if keep_vars is not None and short not in keep_vars:
                continue
            h = _step_hours(gid)
            if want_steps is not None and h not in want_steps:
                continue
            pa = level_pa(gid)
            if want_fls is not None:
                fl = fl_from_pa(pa) if pa is not None else None
                if fl is None or fl not in want_fls:
                    continue
            groups.setdefault(h, bytearray()).extend(data[pos:pos + size])
        finally:
            ec.codes_release(gid)
    if not groups:
        raise ValueError("No queda ningún mensaje con la selección pedida.")

    res_label = _REGRID_LABELS.get(str(regrid))
    notes = []
    engine_used = None
    if res_label is not None:
        engine_used = "eccodes"
        if regrid_engine == "wgrib2":
            if wgrib2_can_regrid(wgrib2_path):
                engine_used = "wgrib2"
            else:
                notes.append("wgrib2 sin interpolación (IPOLATES) o no encontrado: se regrilló con el "
                             "bilineal propio.")
    cycle = None
    files = []
    hours = sorted(groups)
    os.makedirs(dest_dir, exist_ok=True)
    processed = {}
    for k, h in enumerate(hours):
        progress_cb(0.2 + 0.5 * k / len(hours), f"Procesando plazo +{h:g} h…")
        part = bytes(groups[h])
        if region is not None:
            part = crop_grib(part, region)
        if engine_used is not None:
            part = regrid_to(part, float(regrid), engine_used, wgrib2_path)
        if save_opts is not None:
            part, _ginfo = ge.recode(part, save_opts, labeled=True, mode=mode)
        if tables_version is not None or centre is not None or sub_centre is not None:
            part = _apply_identity(part, tables_version, centre, sub_centre)
        if cycle is None:
            cycle = _cycle_of(part)
        processed[h] = part
    if res_label is None:
        res_label = _res_label(next(iter(processed.values())))

    if per_step:
        for h in hours:
            name = wafs_filename(cycle or 0, h, model, res_label)
            files.append((os.path.join(dest_dir, name), processed[h], [h]))
    else:
        if basename:
            name = basename if basename.lower().endswith(".grib2") else basename + ".grib2"
        else:
            name = (f"{model}.t{(cycle or 0):02d}z.wafs_{res_label}."
                    f"f{int(hours[0]):03d}-f{int(hours[-1]):03d}.grib2")
        files.append((os.path.join(dest_dir, name), b"".join(processed[h] for h in hours), hours))

    written = []
    verification = []
    for k, (path, blob, hs) in enumerate(files):
        progress_cb(0.7 + 0.3 * k / len(files), f"Escribiendo {os.path.basename(path)}…")
        with open(path, "wb") as fh:
            fh.write(blob)
        if idx:
            write_idx(path)
        if provenance:
            prov = dict(provenance)
            prov["exportado"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            prov["plazos_h"] = list(hs)
            prov["wafs"] = dict(prov.get("wafs") or {}, formato="WAFS", modo=mode,
                                convertido=bool(crude or not det["labeled"]
                                                or (prov.get("wafs") or {}).get("convertido")))
            if region is not None:
                prov["zona_exportada"] = list(region)
            if save_opts is not None or engine_used is not None:
                g = dict(save_opts or ge.normalize({}), regrid=str(regrid) if engine_used else "origen")
                prov["guardado"] = dict({k: g[k] for k in ge.KEYS}, descripcion=ge.describe(g))
                prov["viento"] = g["wind"]
            with open(path + ".json", "w", encoding="utf-8") as fh:
                json.dump(prov, fh, ensure_ascii=False, indent=2)
        written.append(path)
        verification.append(verify_written(path, blob))
    val = validate_wafs(written[0]) if written else {"avisos": []}
    return {"archivos": written, "verificacion": verification, "avisos": notes + list(val["avisos"]),
            "plazos": hours, "resolucion": res_label, "ciclo": cycle, "modo": mode,
            "regrillado_con": engine_used,
            "guardado": ge.describe(save_opts) if save_opts is not None else None}


def _cycle_of(data):
    for gid in _gids(data):
        try:
            return int(_get(gid, "dataTime", 0)) // 100
        finally:
            ec.codes_release(gid)
    return None


def _res_label(data):
    for gid in _gids(data):
        try:
            di = float(_get(gid, "iDirectionIncrementInDegrees", 0) or 0)
        finally:
            ec.codes_release(gid)
        return f"{int(di):d}p{int(round((di % 1) * 100)):02d}" if di else "grid"
    return "grid"


def _apply_identity(data, tables_version, centre, sub_centre):
    out = bytearray()
    for gid, _pos, _size in iter_messages(data):
        try:
            _set_identity(gid, tables_version, centre, sub_centre)
            out += ec.codes_get_message(gid)
        finally:
            ec.codes_release(gid)
    return bytes(out)


def verify_written(path, expected_data):
    """Reabre el archivo escrito y lo compara con lo que se tenía en memoria:
    cantidad de mensajes, niveles y valores (dentro de la precisión del
    empaquetado). Devuelve un dict con 'ok', 'mensajes', 'niveles',
    'max_dif' por variable y 'detalle'."""
    exp = []
    for gid, _pos, _size in iter_messages(expected_data):
        try:
            exp.append((_get(gid, "shortName"), level_pa(gid), str(_get(gid, "stepRange")),
                        np.asarray(ec.codes_get_values(gid), dtype=float)))
        finally:
            ec.codes_release(gid)
    got = []
    with open(path, "rb") as fh:
        while True:
            gid = ec.codes_grib_new_from_file(fh)
            if gid is None:
                break
            try:
                bits = int(_get(gid, "bitsPerValue", 16) or 16)
                got.append((_get(gid, "shortName"), level_pa(gid), str(_get(gid, "stepRange")),
                            np.asarray(ec.codes_get_values(gid), dtype=float), bits))
            finally:
                ec.codes_release(gid)
    detalle = []
    ok = len(exp) == len(got)
    if not ok:
        detalle.append(f"mensajes: {len(got)} escritos, {len(exp)} esperados")
    lv_exp = sorted({fl_from_pa(e[1]) for e in exp if e[1] is not None} - {None})
    lv_got = sorted({g[1] and fl_from_pa(g[1]) for g in got if g[1] is not None} - {None})
    if lv_exp != lv_got:
        ok = False
        detalle.append(f"niveles: {len(lv_got)} escritos, {len(lv_exp)} esperados")
    max_dif = {}
    for e, g in zip(exp, got):
        if (e[0], e[1], e[2]) != (g[0], g[1], g[2]):
            ok = False
            detalle.append(f"orden distinto: {e[:3]} vs {g[:3]}")
            break
        a, b = e[3], g[3]
        if a.shape != b.shape:
            ok = False
            detalle.append(f"{e[0]}: tamaño {b.shape} vs {a.shape}")
            continue
        finite = np.isfinite(a) & np.isfinite(b)
        d = float(np.max(np.abs(a[finite] - b[finite]))) if finite.any() else 0.0
        rng = float(np.nanmax(a) - np.nanmin(a)) if finite.any() else 0.0
        step = rng / (2 ** g[4] - 1) if g[4] < 64 else 0.0
        if d > step * 1.01 + 1e-6:
            ok = False
            detalle.append(f"{e[0]} {e[1] and e[1] / 100:g} hPa +{e[2]} h: diferencia {d:.4g} "
                           f"> precisión {step:.4g}")
        max_dif[e[0]] = max(max_dif.get(e[0], 0.0), d)
    return {"ok": ok, "archivo": path, "mensajes": len(got), "niveles": len(lv_got),
            "max_dif": max_dif, "detalle": detalle}


# ── Línea de comandos ────────────────────────────────────────────────────────

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m app.wafs_format",
        description="Convierte un GRIB2 en niveles de presión al formato WAFS (FL cada 1000 ft "
                    "codificados como presión ISA en Pa). Si la entrada ya está en WAFS se "
                    "copia sin cambios.")
    ap.add_argument("entrada")
    ap.add_argument("salida", nargs="?", help="por defecto <entrada>_wafs.grib2")
    ap.add_argument("--fl-min", type=int, default=DEFAULT_FL_MIN)
    ap.add_argument("--fl-max", type=int, default=DEFAULT_FL_MAX)
    ap.add_argument("--sin-extender", action="store_true",
                    help="no ampliar el rango de FL aunque el origen cubra más niveles")
    ap.add_argument("--extrapolar", action="store_true",
                    help="FL fuera del rango del origen: usar el nivel más cercano")
    ap.add_argument("--tabla", type=int, default=None, help="tablesVersion (p. ej. 25)")
    ap.add_argument("--centro", type=int, default=None)
    ap.add_argument("--sin-idx", action="store_true")
    ap.add_argument("--modo", default=DEFAULT_MODE, choices=MODES,
                    help="etiquetado de los niveles: INDRA, OACI (17 FL, por defecto), OACI56 o WAFS")
    ap.add_argument("--forzar", action="store_true",
                    help="convertir aunque los niveles parezcan etiquetados por FL (p. ej. un GFS "
                         "crudo con 850/700/500/250/100 hPa)")
    ap.add_argument("--validar", action="store_true", help="sólo validar la entrada")
    args = ap.parse_args(argv)
    if args.validar:
        rep = validate_wafs(args.entrada)
        print(f"{args.entrada}: {rep['mensajes']} mensajes, niveles "
              f"{', '.join(fl_label(f) for f in rep['niveles'])}")
        for a in rep["avisos"]:
            print("  aviso:", a)
        print("OK" if rep["ok"] else f"{len(rep['avisos'])} aviso(s)")
        return 0
    dst = args.salida or converted_path_for(args.entrada)
    _dst, info = convert_file(args.entrada, dst, idx=not args.sin_idx, force=args.forzar,
                              fl_min=args.fl_min, fl_max=args.fl_max, extend=not args.sin_extender,
                              extrapolate=args.extrapolar, tables_version=args.tabla,
                              centre=args.centro, mode=args.modo, log=lambda m: print("  " + m))
    if info.get("convertido"):
        print(f"{info['mensajes']} mensajes escritos en {dst}; {info['fl_rango']}")
    else:
        print(f"{args.entrada} ya está etiquetado por FL (modo {info.get('modo')}, "
              f"{info.get('fl_rango', '')}); copiado a {dst}")
    rep = validate_wafs(dst)
    for a in rep["avisos"]:
        print("  aviso:", a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
