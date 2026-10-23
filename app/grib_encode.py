# -*- coding: utf-8 -*-
"""Recodificación de un GRIB2 según el bloque «Archivo a guardar»: viento en
U/V o en dirección y velocidad, decimales del viento y de la temperatura,
etiqueta de capa (en un archivo por Nivel), empaquetado y centro generador.
La usan la descarga, la conversión al abrir, Generar GRIB y Guardar como…

Opciones (`opts`, claves de config sin el prefijo o con él):
  wind     'uv' | 'dirspeed'
  dec_wind None (como el origen) | 0 | 1 | 2      decimales de U, V, WDIR y WIND
  dec_temp None | 0 | 1 | 2                       decimales de TMP
  label    'modo' | 'nominal' | 'isa' | 'isa_int' etiqueta de capa; sólo por Nivel
  packing  'origen' | 'simple' | 'ieee'
  centre   'origen' | 'missing'                   65535 = «Missing value» (C-11)

Los decimales se fijan con `changeDecimalPrecision` de ecCodes: factor
decimal D con escala binaria E = 0 y los bits por valor recalculados, así
el archivo respeta exactamente los decimales pedidos. Un campo constante se
deja como está (0 bits, la referencia es el dato exacto; con D ≠ 0 wgrib2
avisaría de la codificación).
"""
import numpy as np

from . import fl_table as flt
from . import wind_format as wfm

try:
    import pyproj  # noqa: F401
except Exception:  # pragma: no cover
    pass
try:
    import eccodes as ec
except Exception:  # pragma: no cover
    ec = None

CENTRE_MISSING = 65535
_WIND_SHORT = {"u", "v", "wdir", "ws", "10u", "10v"}
_TEMP_SHORT = {"t", "2t"}
DECIMALS = [(None, "Como el origen"), (0, "0 (enteros)"), (1, "1"), (2, "2")]
PACKINGS = [("origen", "Como el origen"), ("simple", "Simple (bits por valor)"),
            ("ieee", "Un valor por celda (IEEE 32 bits)")]
CENTRES = [("origen", "El del origen"), ("missing", "Sin centro (65535)")]
KEYS = ("wind", "dec_wind", "dec_temp", "label", "packing", "centre")


def options_from_config(cfg, prefix="save_"):
    """{wind, dec_wind, dec_temp, label, packing, centre} desde la config."""
    cfg = cfg or {}
    return normalize({k: cfg.get(prefix + k) for k in KEYS})


def normalize(opts):
    o = dict(opts or {})
    out = {"wind": wfm.normalize(o.get("wind") or o.get("save_wind") or "uv")}
    for k in ("dec_wind", "dec_temp"):
        v = o.get(k, o.get("save_" + k))
        out[k] = None if v in (None, "", "origen", -1) else max(0, min(2, int(v)))
    lab = o.get("label") or o.get("save_label") or "modo"
    out["label"] = lab if lab in dict(flt.LABELS) else "modo"
    pk = o.get("packing") or o.get("save_packing") or "origen"
    out["packing"] = pk if pk in dict(PACKINGS) else "origen"
    ce = o.get("centre") or o.get("save_centre") or "origen"
    out["centre"] = ce if ce in dict(CENTRES) else "origen"
    return out


def is_default(opts):
    """True si el bloque no cambia nada respecto del origen (salvo el viento U/V)."""
    o = normalize(opts)
    return (o["wind"] == "uv" and o["dec_wind"] is None and o["dec_temp"] is None
            and o["label"] == "modo" and o["packing"] == "origen" and o["centre"] == "origen")


def describe(opts):
    """Texto corto para la procedencia y el inventario."""
    o = normalize(opts)
    parts = ["viento " + ("dirección y velocidad" if o["wind"] == "dirspeed" else "U/V")]
    if o["dec_wind"] is not None:
        parts.append(f"viento con {o['dec_wind']} decimales")
    if o["dec_temp"] is not None:
        parts.append(f"temperatura con {o['dec_temp']} decimales")
    if o["label"] != "modo":
        parts.append("etiqueta " + dict(flt.LABELS)[o["label"]].split(" (")[0].lower())
    if o["packing"] != "origen":
        parts.append("empaquetado " + ("IEEE" if o["packing"] == "ieee" else "simple"))
    if o["centre"] == "missing":
        parts.append("sin centro (65535)")
    return ", ".join(parts)


def recode(data, opts, labeled=False, mode=None):
    """Aplica el bloque a todos los mensajes. `labeled` dice si el archivo
    está por Nivel (sólo entonces se cambia la etiqueta de capa). Devuelve
    (bytes, info) con lo que efectivamente se hizo."""
    if ec is None:
        raise RuntimeError("recodificar requiere eccodes")
    o = normalize(opts)
    data = bytes(data)
    info = dict(o)
    info["etiqueta_aplicada"] = False
    if data[:4] != b"GRIB":
        return data, info
    # 1. Viento: por pares, después de todo lo demás no (la conversión clona
    #    los mensajes y conserva el empaquetado, así que va primero)
    if wfm.detect(data) not in (None, o["wind"]):
        data, winfo = wfm.convert(data, o["wind"])
        info["pares_viento"] = winfo.get("pares", 0)
    # 2. Por mensaje: etiqueta, decimales, empaquetado, centro
    touch = (o["dec_wind"] is not None or o["dec_temp"] is not None or o["packing"] != "origen"
             or o["centre"] == "missing" or (labeled and o["label"] != "modo"))
    if not touch:
        return data, info
    from .wafs_format import iter_messages, level_pa
    out = bytearray()
    for gid, pos, size in iter_messages(data):
        try:
            changed = False
            short = _short(gid)
            if labeled and o["label"] != "modo":
                pa = level_pa(gid)
                fl, _col = flt.fl_from_pa(pa) if pa is not None else (None, None)
                if fl is not None:
                    new_pa = flt.label_pa_for(fl, o["label"], mode or flt.DEFAULT_MODE)
                    if int(new_pa) != int(round(pa)):
                        ec.codes_set(gid, "scaleFactorOfFirstFixedSurface", 0)
                        ec.codes_set(gid, "scaledValueOfFirstFixedSurface", int(new_pa))
                        changed = True
                    info["etiqueta_aplicada"] = True
            if o["packing"] != "origen":
                want = "grid_ieee" if o["packing"] == "ieee" else "grid_simple"
                if _get(gid, "packingType") != want:
                    # Al cambiar el empaquetado ecCodes no arrastra los valores
                    # (la referencia y las escalas son de la plantilla vieja):
                    # se leen antes y se vuelven a cargar después
                    vals = ec.codes_get_values(gid)
                    ec.codes_set(gid, "packingType", want)
                    ec.codes_set_values(gid, vals)
                    changed = True
            dec = o["dec_wind"] if short in _WIND_SHORT else o["dec_temp"] if short in _TEMP_SHORT else None
            if dec is not None and o["packing"] != "ieee" and _get(gid, "packingType") == "grid_simple":
                vals = ec.codes_get_values(gid)
                if np.ptp(vals) > 0:
                    # Redondeados antes: así la referencia R es un múltiplo de
                    # 10^−D y cada valor queda exacto con esos decimales
                    ec.codes_set_values(gid, np.round(vals, int(dec)))
                    ec.codes_set(gid, "changeDecimalPrecision", int(dec))
                    changed = True
            if o["centre"] == "missing" and _get(gid, "centre", as_long=True) != CENTRE_MISSING:
                ec.codes_set(gid, "centre", CENTRE_MISSING)
                changed = True
            out += ec.codes_get_message(gid) if changed else data[pos:pos + size]
        finally:
            ec.codes_release(gid)
    return bytes(out), info


def _short(gid):
    try:
        return str(ec.codes_get(gid, "shortName"))
    except Exception:
        return ""


def _get(gid, key, as_long=False):
    try:
        return ec.codes_get_long(gid, key) if as_long else ec.codes_get(gid, key)
    except Exception:
        return None
