# -*- coding: utf-8 -*-
"""Generador de GRIB2 a mano: un perfil vertical (FL → temperatura, viento)
uniforme sobre una grilla regular lat/lon, etiquetado por FL en el modo
elegido (INDRA, OACI, OACI56 o WAFS), listo para abrir en el visor o para
alimentar otro sistema.

* ``isa_temp_c``: temperatura ISA de un FL (para rellenar la tabla).
* ``grid_axes``: latitudes y longitudes de la grilla para una zona y una
  resolución (la zona se redondea hacia afuera a la resolución).
* ``generate_grib``: filas [{fl, t_c, spd_kt, dir_deg}] → bytes GRIB2 con
  TMP y UGRD/VGRD (o WDIR/WIND) por nivel, el mismo perfil en cada plazo.
* ``write_generated``: escribe el archivo con su `.json` de procedencia.
"""
import datetime as dt
import json
import os

import numpy as np

from . import fl_table as flt
from . import areas as A

try:
    import pyproj  # noqa: F401  (pyproj antes que ecCodes, ver main.py)
except Exception:  # pragma: no cover
    pass
try:
    import eccodes as ec
except Exception:  # pragma: no cover
    ec = None

RESOLUTIONS = [(0.25, "0,25°"), (0.5, "0,50°"), (1.0, "1,00°")]
KT_TO_MS = 0.514444
KELVIN = 273.15
CENTRE_MISSING = 255            # centro generador «desconocido»: el archivo no es de un modelo

# (disciplina, categoría, número) y unidad de cada campo que se escribe
_PARAM = {"t": (0, 0, 0), "u": (0, 2, 2), "v": (0, 2, 3), "wdir": (0, 2, 0), "ws": (0, 2, 1)}


def isa_temp_c(fl):
    """Temperatura ISA (°C) a la altura del FL: −6,5 °C/km hasta 11 km,
    −56,5 °C constante por encima (hasta 20 km)."""
    h_m = float(fl) * 100.0 * 0.3048
    if h_m <= 11000.0:
        return 15.0 - 0.0065 * h_m
    return -56.5


def grid_axes(region, res_deg):
    """(lats descendentes, lons ascendentes, zona redondeada) de la grilla
    que cubre `region` = (top, bottom, left, right) a `res_deg`."""
    res = float(res_deg)
    top, bottom, left, right = A.round_outward(region, res)
    nj = int(round((top - bottom) / res)) + 1
    ni = int(round((right - left) / res)) + 1
    lats = np.round(top - res * np.arange(nj), 6)
    lons = np.round(left + res * np.arange(ni), 6)
    return lats, lons, (top, bottom, left, right)


def validate_rows(rows):
    """Normaliza y valida las filas: devuelve ([{fl, t_c, spd_kt, dir_deg}]
    ordenadas por FL descendente, error o None)."""
    out = []
    seen = set()
    for i, r in enumerate(rows or []):
        try:
            fl = int(round(float(r["fl"])))
            t_c = float(r["t_c"])
            spd = float(r["spd_kt"])
            direc = float(r["dir_deg"])
        except (KeyError, TypeError, ValueError):
            return [], f"fila {i + 1}: faltan valores o no son números"
        if fl not in flt.FL_TABLE:
            return [], (f"fila {i + 1}: FL{fl:03d} no está en la tabla (FL{flt.FL_LOWEST:03d} a "
                        f"FL{flt.FL_HIGHEST:03d}, de a {flt.FL_STEP})")
        if fl in seen:
            return [], f"fila {i + 1}: FL{fl:03d} repetido"
        if not (-120.0 <= t_c <= 60.0):
            return [], f"fila {i + 1}: temperatura {t_c:g} °C fuera de rango (−120 a 60)"
        if not (0.0 <= spd <= 400.0):
            return [], f"fila {i + 1}: velocidad {spd:g} kt fuera de rango (0 a 400)"
        if not (0.0 <= direc <= 360.0):
            return [], f"fila {i + 1}: dirección {direc:g}° fuera de rango (0 a 360)"
        seen.add(fl)
        out.append({"fl": fl, "t_c": t_c, "spd_kt": spd, "dir_deg": direc % 360.0})
    if not out:
        return [], "no hay niveles: agregá al menos un FL"
    out.sort(key=lambda r: -r["fl"])
    return out, None


def _new_message(var, lats, lons, pa, run, step_h, values, centre):
    gid = ec.codes_grib_new_from_samples("regular_ll_pl_grib2")
    try:
        d, c, n = _PARAM[var]
        ec.codes_set(gid, "centre", int(centre))
        ec.codes_set(gid, "discipline", d)
        ec.codes_set(gid, "parameterCategory", c)
        ec.codes_set(gid, "parameterNumber", n)
        ec.codes_set(gid, "typeOfFirstFixedSurface", 100)
        ec.codes_set(gid, "scaleFactorOfFirstFixedSurface", 0)
        ec.codes_set(gid, "scaledValueOfFirstFixedSurface", int(pa))
        ec.codes_set(gid, "dataDate", int(run.strftime("%Y%m%d")))
        ec.codes_set(gid, "dataTime", int(run.strftime("%H%M")))
        ec.codes_set(gid, "stepUnits", "h")
        ec.codes_set(gid, "forecastTime", int(step_h))
        ec.codes_set(gid, "Ni", len(lons))
        ec.codes_set(gid, "Nj", len(lats))
        ec.codes_set(gid, "latitudeOfFirstGridPointInDegrees", float(lats[0]))
        ec.codes_set(gid, "latitudeOfLastGridPointInDegrees", float(lats[-1]))
        ec.codes_set(gid, "longitudeOfFirstGridPointInDegrees", float(lons[0] % 360.0))
        ec.codes_set(gid, "longitudeOfLastGridPointInDegrees", float(lons[-1] % 360.0))
        res = abs(float(lons[1] - lons[0])) if len(lons) > 1 else abs(float(lats[1] - lats[0])) if len(lats) > 1 else 1.0
        ec.codes_set(gid, "iDirectionIncrementInDegrees", res)
        ec.codes_set(gid, "jDirectionIncrementInDegrees", res)
        ec.codes_set(gid, "jScansPositively", 0)
        # Campo constante: ecCodes lo graba con 0 bits por punto y sólo el valor
        # de referencia (float32). Con factor decimal 0 ese valor es el dato tal
        # cual; con otro factor wgrib2 avisa «simple encode/decode may differ
        # from WMO standard» en cada mensaje.
        ec.codes_set(gid, "decimalScaleFactor", 0)
        ec.codes_set_values(gid, np.asarray(values, dtype=float).ravel())
        return ec.codes_get_message(gid)
    finally:
        ec.codes_release(gid)


def steps_from(h_from, h_to, h_step):
    """Plazos [desde, hasta] cada `h_step` horas (como el diálogo de descarga)."""
    h_from, h_to, h_step = int(h_from), int(h_to), max(1, int(h_step))
    if h_to < h_from:
        h_from, h_to = h_to, h_from
    return list(range(h_from, h_to + 1, h_step))


def generate_grib(rows, region, res_deg, mode=flt.DEFAULT_MODE, run=None, step_h=0,
                  wind_format="uv", centre=CENTRE_MISSING, steps=None):
    """Bytes GRIB2 con, por cada plazo y cada fila (FL), TMP en K y el viento
    como U/V en m/s (o WDIR en grados y WIND en m/s), uniformes en toda la
    grilla y iguales en todos los plazos. `steps` (horas) o, si no, el único
    `step_h`. El nivel se graba con la etiqueta del modo (nominal hPa×100, o
    la ISA en Pa en WAFS). Devuelve (bytes, info)."""
    if ec is None:
        raise RuntimeError("generar un GRIB requiere eccodes")
    rows, err = validate_rows(rows)
    if err:
        raise ValueError(err)
    mode = flt.normalize_mode(mode)
    lats, lons, zone = grid_axes(region, res_deg)
    run = run or dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
    wind_format = "dirspeed" if wind_format == "dirspeed" else "uv"
    steps = sorted({int(s) for s in (steps if steps else [step_h])})
    if not steps:
        raise ValueError("no hay plazos")
    npts = len(lats) * len(lons)
    out = bytearray()
    n = 0
    for step in steps:
        for r in rows:
            pa = flt.label_pa(r["fl"], mode)
            spd_ms = r["spd_kt"] * KT_TO_MS
            rad = np.radians(r["dir_deg"])
            fields = [("t", r["t_c"] + KELVIN)]
            if wind_format == "uv":
                fields += [("u", -spd_ms * np.sin(rad)), ("v", -spd_ms * np.cos(rad))]
            else:
                fields += [("wdir", r["dir_deg"]), ("ws", spd_ms)]
            for var, val in fields:
                out += _new_message(var, lats, lons, pa, run, step, np.full(npts, float(val)), centre)
                n += 1
    info = {"mensajes": n, "niveles": len(rows), "fls": [r["fl"] for r in rows],
            "modo": mode, "viento": wind_format, "grilla": {"ni": len(lons), "nj": len(lats),
            "resolucion_deg": float(res_deg)}, "zona": list(zone),
            "corrida": run.strftime("%Y-%m-%dT%H:%MZ"), "plazos_h": steps, "plazo_h": steps[0]}
    return bytes(out), info


def default_basename(run, step_h, res_deg, area_tag, wind_format="uv", mode=flt.DEFAULT_MODE,
                     steps=None):
    """`generado_20261021_12z_f006_0p25_SAEF+SACF_OACI[_dirvel]`; con varios
    plazos, `f006-f024`."""
    res = {0.25: "0p25", 0.5: "0p50", 1.0: "1p00"}.get(float(res_deg), f"{float(res_deg):g}".replace(".", "p"))
    steps = sorted({int(s) for s in (steps if steps else [step_h])})
    f = f"f{steps[0]:03d}" if len(steps) == 1 else f"f{steps[0]:03d}-f{steps[-1]:03d}"
    base = f"generado_{run:%Y%m%d}_{run:%H}z_{f}_{res}_{area_tag}_{flt.normalize_mode(mode)}"
    if wind_format == "dirspeed":
        base += "_dirvel"
    return base


def provenance(rows, info, area_mode="manual", area_codes=None, area_margin=0.0, region=None):
    """Procedencia (`archivo.json`) de un GRIB generado: lo que la ventana
    muestra en FUENTE más la tabla con la que se generó."""
    d = {"fuente": "generado", "nombre": "Generado a mano", "modelo": "perfil uniforme",
         "tipo": "altura", "corrida": info["corrida"],
         "plazos_h": list(info.get("plazos_h") or [info["plazo_h"]]),
         "variables": ["TMP", "WDIR", "WIND"] if info["viento"] == "dirspeed" else ["TMP", "UGRD", "VGRD"],
         "niveles_fl": info["fls"], "zona": info["zona"],
         "resolucion_final": {0.25: "0p25", 0.5: "0p50", 1.0: "1p00"}.get(
             float(info["grilla"]["resolucion_deg"]), f"{info['grilla']['resolucion_deg']:g}"),
         "viento": info["viento"],
         "wafs": {"formato": "WAFS", "modo": info["modo"], "convertido": False,
                  "fl_rango": f"FL{min(info['fls']):03d}–FL{max(info['fls']):03d}", "generado": True},
         "tabla": [dict(r) for r in rows],
         "generado": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if region is not None:
        d["area"] = A.area_info(area_mode, area_codes or [], area_margin, region, tuple(info["zona"]))
    return d


def write_generated(path, data, prov=None, idx=True):
    """Escribe el GRIB2 y, si se da, su procedencia (`path.json`) y el `.idx`."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    if prov is not None:
        with open(path + ".json", "w", encoding="utf-8") as fh:
            json.dump(prov, fh, ensure_ascii=False, indent=2)
    if idx:
        try:
            from .wafs_format import write_idx
            write_idx(path)
        except Exception:
            pass
    return path
