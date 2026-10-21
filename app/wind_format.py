# -*- coding: utf-8 -*-
"""Formato del viento en un GRIB2: componentes U/V (UGRD/VGRD, 0-2-2 y
0-2-3) o dirección y velocidad (WDIR/WIND, 0-2-0 y 0-2-1).

Los modelos publican U y V; la dirección es la meteorológica (de dónde
sopla, grados verdaderos) y la velocidad en m/s. La conversión se hace por
pares de mensajes del mismo plazo y nivel: cada U se reemplaza por WDIR y
cada V por WIND (o al revés), clonando el mensaje original para conservar
grilla, tiempo, nivel y empaquetado. El resto de los mensajes pasa tal cual.

* ``uv_to_dirspeed`` / ``dirspeed_to_uv``: las fórmulas, sobre arreglos.
* ``detect``: 'uv', 'dirspeed', 'mixto' o None según los mensajes de viento.
* ``convert``: bytes GRIB2 → bytes GRIB2 en el formato pedido.
"""
import numpy as np

try:
    import pyproj  # noqa: F401  (pyproj antes que ecCodes, ver main.py)
except Exception:  # pragma: no cover
    pass
try:
    import eccodes as ec
except Exception:  # pragma: no cover
    ec = None

FORMATS = [("uv", "Componentes U y V (UGRD/VGRD)"),
           ("dirspeed", "Dirección y velocidad (WDIR/WIND)")]
FORMAT_LABELS = dict(FORMATS)
FORMAT_SHORT = {"uv": "U/V", "dirspeed": "dir/vel"}

# (disciplina, categoría, número) GRIB2 de cada variable de viento
PARAM = {"u": (0, 2, 2), "v": (0, 2, 3), "wdir": (0, 2, 0), "ws": (0, 2, 1)}
_UV, _DS = {"u", "v"}, {"wdir", "ws"}


def normalize(fmt):
    return fmt if fmt in FORMAT_LABELS else "uv"


# ── Fórmulas ─────────────────────────────────────────────────────────────────

def uv_to_dirspeed(u, v):
    """(dirección meteorológica en grados [0, 360), velocidad) a partir de
    U (hacia el este) y V (hacia el norte), en las unidades de entrada."""
    u = np.asarray(u, dtype=float)
    v = np.asarray(v, dtype=float)
    spd = np.hypot(u, v)
    direc = (270.0 - np.degrees(np.arctan2(v, u))) % 360.0
    # Calma: dirección 0 por convención (no NaN)
    direc = np.where(spd > 0, direc, 0.0)
    return direc, spd


def dirspeed_to_uv(direc, spd):
    """U y V a partir de dirección meteorológica (grados) y velocidad."""
    rad = np.radians(np.asarray(direc, dtype=float))
    spd = np.asarray(spd, dtype=float)
    return -spd * np.sin(rad), -spd * np.cos(rad)


# ── Mensajes ─────────────────────────────────────────────────────────────────

def _var_of(gid):
    """'u', 'v', 'wdir', 'ws' u otra cosa según disciplina/categoría/número."""
    try:
        key = (int(ec.codes_get(gid, "discipline")), int(ec.codes_get(gid, "parameterCategory")),
               int(ec.codes_get(gid, "parameterNumber")))
    except Exception:
        return None
    for name, k in PARAM.items():
        if k == key:
            return name
    return None


def _pair_key(gid):
    """Lo que identifica a un par U/V (o WDIR/WIND): plazo, nivel y grilla."""
    def g(k, d=""):
        try:
            return ec.codes_get(gid, k)
        except Exception:
            return d
    return (str(g("stepRange", "0")), str(g("typeOfFirstFixedSurface", "")),
            int(g("scaledValueOfFirstFixedSurface", 0) or 0), int(g("scaleFactorOfFirstFixedSurface", 0) or 0),
            int(g("Ni", 0) or 0), int(g("Nj", 0) or 0), str(g("dataDate", "")), str(g("dataTime", "")))


def _messages(data):
    """[(offset, tamaño, var, clave de par)] de todos los mensajes."""
    from .wafs_format import iter_messages
    out = []
    for gid, pos, size in iter_messages(data):
        try:
            out.append((pos, size, _var_of(gid), _pair_key(gid)))
        finally:
            ec.codes_release(gid)
    return out


def detect(data):
    """'uv' si el viento viene como U/V, 'dirspeed' si viene como dirección y
    velocidad, 'mixto' si hay de los dos, None si no hay viento."""
    if ec is None:
        return None
    vars_ = {m[2] for m in _messages(data) if m[2]}
    has_uv, has_ds = bool(vars_ & _UV), bool(vars_ & _DS)
    if has_uv and has_ds:
        return "mixto"
    if has_uv:
        return "uv"
    if has_ds:
        return "dirspeed"
    return None


def convert(data, target="dirspeed", log=None):
    """Devuelve (bytes, info) con el viento en `target` ('uv' | 'dirspeed').
    Los pares incompletos (U sin V, WDIR sin WIND) quedan como están y se
    cuentan en info['sin_par']. info: viento, pares (convertidos), sin_par."""
    if ec is None:
        raise RuntimeError("la conversión del viento requiere eccodes")
    target = normalize(target)
    log = log or (lambda msg: None)
    data = bytes(data)
    msgs = _messages(data)
    src_vars = _DS if target == "uv" else _UV
    first, second = (("wdir", "ws") if target == "uv" else ("u", "v"))
    out_first, out_second = (("u", "v") if target == "uv" else ("wdir", "ws"))
    # Parejas: por clave de par, el índice del primer y segundo componente
    pairs = {}
    for i, (_pos, _size, var, key) in enumerate(msgs):
        if var in src_vars:
            pairs.setdefault(key, {})[var] = i
    replacements = {}       # índice de mensaje → bytes nuevos
    n_pairs = n_single = 0
    for key, d in pairs.items():
        if first not in d or second not in d:
            n_single += 1
            log(f"viento sin par en plazo {key[0]}: se deja como está")
            continue
        i1, i2 = d[first], d[second]
        g1 = ec.codes_new_from_message(data[msgs[i1][0]:msgs[i1][0] + msgs[i1][1]])
        g2 = ec.codes_new_from_message(data[msgs[i2][0]:msgs[i2][0] + msgs[i2][1]])
        try:
            a = np.asarray(ec.codes_get_values(g1), dtype=float)
            b = np.asarray(ec.codes_get_values(g2), dtype=float)
            if target == "uv":
                x, y = dirspeed_to_uv(a, b)
            else:
                x, y = uv_to_dirspeed(a, b)
            for gid, var, vals in ((g1, out_first, x), (g2, out_second, y)):
                disc, cat, num = PARAM[var]
                ec.codes_set(gid, "discipline", disc)
                ec.codes_set(gid, "parameterCategory", cat)
                ec.codes_set(gid, "parameterNumber", num)
                ec.codes_set_values(gid, vals)
            replacements[i1] = ec.codes_get_message(g1)
            replacements[i2] = ec.codes_get_message(g2)
            n_pairs += 1
        finally:
            ec.codes_release(g1)
            ec.codes_release(g2)
    if not replacements:
        return data, {"viento": detect(data), "pares": 0, "sin_par": n_single}
    out = bytearray()
    for i, (pos, size, _var, _key) in enumerate(msgs):
        out += replacements.get(i, data[pos:pos + size])
    return bytes(out), {"viento": target, "pares": n_pairs, "sin_par": n_single}
