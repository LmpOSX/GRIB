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
  scan     'origen' | 'ns_we' | 'ns_ew' | 'sn_we' | 'sn_ew'
           orden de las celdas (modo de barrido de la sección 3): filas de
           norte a sur o de sur a norte, y dentro de cada fila de oeste a
           este o de este a oeste
  rows     'origen' | 'consecutivas' | 'intercaladas'
           filas todas en el mismo sentido, o alternadas (bustrofedón: la
           segunda fila corre al revés que la primera, y así)

El orden de las celdas se cambia con `swapScanningX` / `swapScanningY` de
ecCodes (reordenan los valores y actualizan los bits y las esquinas); las
filas intercaladas se arman a mano porque ecCodes no las reordena ni las
tiene en cuenta en su iterador (el lector las deshace al leer).

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
SCANS = [("origen", "Como el origen"), ("ns_we", "N→S, O→E (GFS, WAFC Washington)"),
         ("ns_ew", "N→S, E→O"), ("sn_we", "S→N, O→E (WAFC London)"), ("sn_ew", "S→N, E→O")]
ROWS = [("origen", "Como el origen"), ("consecutivas", "Todas en el mismo sentido"),
        ("intercaladas", "Intercaladas (bustrofedón)")]
KEYS = ("wind", "dec_wind", "dec_temp", "label", "packing", "centre", "scan", "rows")


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
    sc = o.get("scan") or o.get("save_scan") or "origen"
    out["scan"] = sc if sc in dict(SCANS) else "origen"
    rw = o.get("rows") or o.get("save_rows") or "origen"
    out["rows"] = rw if rw in dict(ROWS) else "origen"
    return out


def is_default(opts):
    """True si el bloque no cambia nada respecto del origen (salvo el viento U/V)."""
    o = normalize(opts)
    return (o["wind"] == "uv" and o["dec_wind"] is None and o["dec_temp"] is None
            and o["label"] == "modo" and o["packing"] == "origen" and o["centre"] == "origen"
            and o["scan"] == "origen" and o["rows"] == "origen")


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
    if o["scan"] != "origen":
        parts.append("celdas " + dict(SCANS)[o["scan"]].split(" (")[0])
    if o["rows"] != "origen":
        parts.append("filas " + ("intercaladas" if o["rows"] == "intercaladas" else "en el mismo sentido"))
    return ", ".join(parts)


def scan_text(i_neg, j_pos, alt):
    """«N→S, O→E» (más «, filas intercaladas») a partir de los bits del
    modo de barrido; lo usan el inventario y el hexadecimal."""
    txt = ("S→N" if j_pos else "N→S") + ", " + ("E→O" if i_neg else "O→E")
    return txt + (", filas intercaladas" if alt else "")


def _apply_scan(gid, o):
    """Deja el mensaje con el orden de celdas pedido. Devuelve True si cambió."""
    want_scan, want_rows = o["scan"], o["rows"]
    if want_scan == "origen" and want_rows == "origen":
        return False
    i_neg = bool(_get(gid, "iScansNegatively", as_long=True))
    j_pos = bool(_get(gid, "jScansPositively", as_long=True))
    alt = bool(_get(gid, "alternativeRowScanning", as_long=True))
    ni, nj = _get(gid, "Ni", as_long=True), _get(gid, "Nj", as_long=True)
    if not ni or not nj or _get(gid, "bitmapPresent", as_long=True):
        return False
    if want_scan == "origen":
        w_j_pos, w_i_neg = j_pos, i_neg
    else:
        w_j_pos, w_i_neg = want_scan.startswith("sn"), want_scan.endswith("ew")
    w_alt = alt if want_rows == "origen" else want_rows == "intercaladas"
    if (w_j_pos, w_i_neg, w_alt) == (j_pos, i_neg, alt):
        return False
    # 1. Filas todas en el mismo sentido (ecCodes no entiende las intercaladas)
    if alt:
        v = np.asarray(ec.codes_get_values(gid), dtype=float).reshape(nj, ni).copy()
        v[1::2] = v[1::2, ::-1]
        ec.codes_set(gid, "alternativeRowScanning", 0)
        ec.codes_set_values(gid, v.ravel())
    # 2. Sentido de las filas y de las columnas: ecCodes reordena los valores
    #    y corrige los bits y las esquinas
    if w_j_pos != j_pos:
        ec.codes_set(gid, "swapScanningY", 1)
    if w_i_neg != i_neg:
        ec.codes_set(gid, "swapScanningX", 1)
    # 3. Filas intercaladas: las impares al revés, con el bit 4 del barrido
    if w_alt:
        v = np.asarray(ec.codes_get_values(gid), dtype=float).reshape(nj, ni).copy()
        v[1::2] = v[1::2, ::-1]
        ec.codes_set(gid, "alternativeRowScanning", 1)
        ec.codes_set_values(gid, v.ravel())
    return True


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
             or o["centre"] == "missing" or (labeled and o["label"] != "modo")
             or o["scan"] != "origen" or o["rows"] != "origen")
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
            # Orden de las celdas antes de los decimales: así el redondeo y la
            # precisión decimal quedan sobre los valores ya reordenados
            if _apply_scan(gid, o):
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
