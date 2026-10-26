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
  packing  'origen' | 'simple' | 'ieee' | 'jpeg'    jpeg: JPEG 2000 sin pérdida (plantilla 5.40)
  centre   'origen' | 'missing' | '74' …          65535 = «Missing value»; un código de la C-11
  sub_centre None (como el origen) | 0…65535
  scan     'origen' | 'ns_we' | 'ns_ew' | 'sn_we' | 'sn_ew'
           orden de las celdas (modo de barrido de la sección 3): filas de
           norte a sur o de sur a norte, y dentro de cada fila de oeste a
           este o de este a oeste
  rows     'origen' | 'consecutivas' | 'intercaladas'
           filas todas en el mismo sentido, o alternadas (bustrofedón: la
           segunda fila corre al revés que la primera, y así)
  lons     'origen' | 'm180' | '0_360'                primera longitud de una grilla global
  regrid   'origen' | '0.25' | '0.5' | '1.0' | '1.25' regrillado bilineal (antes que todo)
  tables   'origen' | '4' | '25'                     versión de la tabla maestra (sección 1)

Además pasan sin tocarse `engine` y `wgrib2_path` (Preferencias ▸ motor):
con «wgrib2» y un wgrib2 con la interpolación se regrilla con -new_grid;
si no, con el bilineal propio.

`PROFILES` son juegos de valores con nombre (NOAA GFS, WAFC Washington,
WAFC London clásico) que el bloque ofrece para no elegir uno por uno.

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
            ("jpeg", "JPEG 2000 sin pérdida (boletines GTS)"),
            ("ieee", "Un valor por celda (IEEE 32 bits)")]
_PACKING_TYPE = {"simple": "grid_simple", "ieee": "grid_ieee", "jpeg": "grid_jpeg"}
CENTRES = [("origen", "El del origen"), ("missing", "Sin centro (65535)")]
SCANS = [("origen", "Como el origen"), ("ns_we", "N→S, O→E (GFS, WAFC Washington)"),
         ("ns_ew", "N→S, E→O"), ("sn_we", "S→N, O→E (WAFC London)"), ("sn_ew", "S→N, E→O")]
ROWS = [("origen", "Como el origen"), ("consecutivas", "Todas en el mismo sentido"),
        ("intercaladas", "Intercaladas (bustrofedón)")]
# Primera longitud de una grilla que da la vuelta al mundo: en GRIB2 las
# longitudes se graban siempre de 0 a 360, así que en una grilla regional
# no cambia nada; en una global se rotan las columnas
LONS = [("origen", "Como el origen"), ("m180", "Desde 180°W (−180…180)"),
        ("0_360", "Desde Greenwich (0…360, WAFC London)")]
# Regrillado bilineal a puntos múltiplos de la resolución (la vuelta
# completa en una grilla global). Va primero: lo demás se aplica sobre la
# grilla nueva
REGRIDS = [("origen", "Sin regrillar (como el origen)"),
           ("0.25", "0,25° (GFS, WAFS actual)"),
           ("0.5", "0,50°"),
           ("1.0", "1,00° (GFS 1°, FDP)"),
           ("1.25", "1,25° (WAFS clásico, WAFC London)")]
# Versión de la tabla maestra (sección 1, octeto 10): sólo dice con qué
# edición de las tablas OMM se codificó; U, V y T son los mismos desde la 2.
# Al fijarla, un parámetro estándar deja de apuntar a tablas locales (0)
TABLES = [("origen", "Como el origen"), ("4", "4 (WAFC London clásico)"),
          ("25", "25 (la de Exportar a WAFS)")]
KEYS = ("wind", "dec_wind", "dec_temp", "label", "packing", "centre", "sub_centre", "scan", "rows",
        "lons", "regrid", "tables")
_PASS = ("engine", "wgrib2_path")       # motor del regrillado (Preferencias), sin prefijo

# Perfiles: juegos completos de valores. Lo que no se nombra queda «como el
# origen»; la etiqueta «modo» sigue al modo de etiquetado elegido
_BASE = {"wind": "uv", "dec_wind": None, "dec_temp": None, "label": "modo", "packing": "origen",
         "centre": "origen", "sub_centre": None, "scan": "origen", "rows": "origen", "lons": "origen", "regrid": "origen",
         "tables": "origen"}
PROFILES = [
    ("origen", "Como el origen (sin cambios)", dict(_BASE)),
    ("gfs", "NOAA GFS (U/V, N→S, O→E, desde Greenwich)",
     dict(_BASE, scan="ns_we", rows="consecutivas", lons="0_360")),
    ("wafc_washington", "WAFS WAFC Washington (0,25°, N→S, O→E, etiqueta ISA)",
     dict(_BASE, regrid="0.25", label="isa", scan="ns_we", rows="consecutivas", lons="0_360")),
    ("wafc_london", "WAFC London clásico (1,25°, S→N, O→E, 1 decimal; boletín GTS)",
     dict(_BASE, regrid="1.25", dec_wind=1, dec_temp=1, label="nominal", packing="jpeg",
          scan="sn_we", rows="consecutivas", lons="0_360", tables="4")),
]


def options_from_config(cfg, prefix="save_"):
    """El bloque desde la config, con el motor del regrillado."""
    cfg = cfg or {}
    o = {k: cfg.get(prefix + k) for k in KEYS}
    o.update({k: cfg.get(k) for k in _PASS})
    return normalize(o)


def profile_of(opts):
    """Clave del perfil que coincide con `opts`, o None (personalizado)."""
    o = normalize(opts)
    for key, _text, vals in PROFILES:
        if all(o[k] == vals[k] for k in KEYS):
            return key
    return None


def profile_values(key):
    for k, _text, vals in PROFILES:
        if k == key:
            return dict(vals)
    return None


def regrid_res(opts):
    """Resolución pedida en grados, o None si no se regrilla."""
    r = normalize(opts)["regrid"]
    return None if r == "origen" else float(r)


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
    ce = str(o.get("centre") or o.get("save_centre") or "origen")
    out["centre"] = ce if ce in dict(CENTRES) or (ce.isdigit() and int(ce) < CENTRE_MISSING) else "origen"
    sc = o.get("sub_centre", o.get("save_sub_centre"))
    try:
        sc = None if sc in (None, "", "origen") or int(sc) < 0 else min(int(sc), 65535)
    except (TypeError, ValueError):
        sc = None
    out["sub_centre"] = sc
    sc = o.get("scan") or o.get("save_scan") or "origen"
    out["scan"] = sc if sc in dict(SCANS) else "origen"
    rw = o.get("rows") or o.get("save_rows") or "origen"
    out["rows"] = rw if rw in dict(ROWS) else "origen"
    ln = o.get("lons") or o.get("save_lons") or "origen"
    out["lons"] = ln if ln in dict(LONS) else "origen"
    rg = o.get("regrid") or o.get("save_regrid") or "origen"
    rg = {"ninguno": "origen"}.get(str(rg), str(rg))
    out["regrid"] = rg if rg in dict(REGRIDS) else "origen"
    tb = str(o.get("tables") or o.get("save_tables") or "origen")
    out["tables"] = tb if tb in dict(TABLES) else "origen"
    for k in _PASS:
        if o.get(k):
            out[k] = o[k]
    return out


def is_default(opts):
    """True si el bloque no cambia nada respecto del origen (salvo el viento U/V)."""
    o = normalize(opts)
    return (o["wind"] == "uv" and o["dec_wind"] is None and o["dec_temp"] is None
            and o["label"] == "modo" and o["packing"] == "origen" and o["centre"] == "origen"
            and o["sub_centre"] is None
            and o["scan"] == "origen" and o["rows"] == "origen" and o["lons"] == "origen"
            and o["regrid"] == "origen" and o["tables"] == "origen")


def describe(opts):
    """Texto corto para la procedencia y el inventario."""
    o = normalize(opts)
    parts = []
    if o["regrid"] != "origen":
        parts.append("regrillado a " + o["regrid"].replace(".", ",") + "°")
    parts.append("viento " + ("dirección y velocidad" if o["wind"] == "dirspeed" else "U/V"))
    if o["dec_wind"] is not None:
        parts.append(f"viento con {o['dec_wind']} decimales")
    if o["dec_temp"] is not None:
        parts.append(f"temperatura con {o['dec_temp']} decimales")
    if o["label"] != "modo":
        parts.append("etiqueta " + dict(flt.LABELS)[o["label"]].split(" (")[0].lower())
    if o["packing"] != "origen":
        parts.append("empaquetado " + {"ieee": "IEEE", "jpeg": "JPEG 2000"}.get(o["packing"], "simple"))
    if o["centre"] == "missing":
        parts.append("sin centro (65535)")
    elif o["centre"] != "origen":
        from .grib_centres import centre_text
        parts.append("centro " + centre_text(o["centre"]))
    if o["sub_centre"] is not None:
        parts.append(f"subcentro {o['sub_centre']}")
    if o["scan"] != "origen":
        parts.append("celdas " + dict(SCANS)[o["scan"]].split(" (")[0])
    if o["rows"] != "origen":
        parts.append("filas " + ("intercaladas" if o["rows"] == "intercaladas" else "en el mismo sentido"))
    if o["tables"] != "origen":
        parts.append("tablas versión " + o["tables"])
    if o["lons"] != "origen":
        parts.append("longitudes " + ("desde Greenwich (0…360)" if o["lons"] == "0_360" else "desde 180°W"))
    return ", ".join(parts)


def _apply_lons(gid, o):
    """En una grilla regular que da la vuelta completa, rota las columnas
    para que la más al oeste sea 0° («0_360») o 180°W («m180»), en el
    sentido de barrido que tenga. Devuelve True si cambió."""
    want = o.get("lons", "origen")
    if want == "origen" or _get(gid, "gridType") != "regular_ll":
        return False
    ni, nj = _get(gid, "Ni", as_long=True), _get(gid, "Nj", as_long=True)
    if not ni or not nj or _get(gid, "bitmapPresent", as_long=True):
        return False
    try:
        di = float(ec.codes_get(gid, "iDirectionIncrementInDegrees"))
        lon0 = float(ec.codes_get(gid, "longitudeOfFirstGridPointInDegrees"))
    except Exception:
        return False
    if di <= 0 or abs(ni * di - 360.0) > 1e-4:
        return False                                   # no da la vuelta: nada que rotar
    i_neg = bool(_get(gid, "iScansNegatively", as_long=True))
    alt = bool(_get(gid, "alternativeRowScanning", as_long=True))
    west = 0.0 if want == "0_360" else 180.0
    lons = (lon0 + (-di if i_neg else di) * np.arange(ni)) % 360.0
    hit = np.where(np.abs(((lons - west + 180.0) % 360.0) - 180.0) < 1e-4)[0]
    if len(hit) == 0:
        return False                                   # la grilla no pasa por ese meridiano
    k = int(hit[0])
    shift = -k if not i_neg else (ni - 1 - k)          # W→E: la del oeste primero; E→W: última
    if shift % ni == 0:
        return False
    v = np.asarray(ec.codes_get_values(gid), dtype=float).reshape(nj, ni).copy()
    if alt:
        v[1::2] = v[1::2, ::-1]
    v = np.roll(v, shift, axis=1)
    if alt:
        v[1::2] = v[1::2, ::-1]
    new = np.roll(lons, shift)
    ec.codes_set(gid, "longitudeOfFirstGridPointInDegrees", float(round(new[0], 6) % 360.0))
    ec.codes_set(gid, "longitudeOfLastGridPointInDegrees", float(round(new[-1], 6) % 360.0))
    ec.codes_set_values(gid, v.ravel())
    return True


def _apply_tables(gid, o):
    """Versión de la tabla maestra; si el parámetro es estándar (categoría y
    número por debajo de 192) también tablas locales 0. Devuelve True si cambió."""
    if o["tables"] == "origen":
        return False
    want = int(o["tables"])
    changed = False
    if _get(gid, "tablesVersion", as_long=True) != want:
        ec.codes_set(gid, "tablesVersion", want)
        changed = True
    cat, num = _get(gid, "parameterCategory", as_long=True), _get(gid, "parameterNumber", as_long=True)
    if (cat is not None and num is not None and cat < 192 and num < 192
            and _get(gid, "localTablesVersion", as_long=True)):
        ec.codes_set(gid, "localTablesVersion", 0)
        changed = True
    return changed


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
    # 0. Regrillado, sobre U/V (la dirección no se interpola): si el origen
    #    viene en dirección y velocidad se pasa a U/V y el paso 1 lo vuelve
    if o["regrid"] != "origen":
        from .regrid import regrid_to, wgrib2_can_regrid
        engine = "eccodes"
        if o.get("engine") == "wgrib2" and wgrib2_can_regrid(o.get("wgrib2_path", "")):
            engine = "wgrib2"
        if wfm.detect(data) == "dirspeed":
            data, _w = wfm.convert(data, "uv")
        data = regrid_to(data, float(o["regrid"]), engine, o.get("wgrib2_path", ""))
        info["regrillado_con"] = engine
    # 1. Viento: por pares, después de todo lo demás no (la conversión clona
    #    los mensajes y conserva el empaquetado, así que va primero)
    if wfm.detect(data) not in (None, o["wind"]):
        data, winfo = wfm.convert(data, o["wind"])
        info["pares_viento"] = winfo.get("pares", 0)
    # 2. Por mensaje: etiqueta, decimales, empaquetado, centro
    touch = (o["dec_wind"] is not None or o["dec_temp"] is not None or o["packing"] != "origen"
             or o["centre"] != "origen" or o["sub_centre"] is not None or (labeled and o["label"] != "modo")
             or o["scan"] != "origen" or o["rows"] != "origen" or o["lons"] != "origen"
             or o["tables"] != "origen")
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
                # JPEG 2000 se codifica al final (cada reescritura lo
                # comprime de nuevo): mientras tanto, simple
                want = _PACKING_TYPE[o["packing"]]
                cur = _get(gid, "packingType")
                if o["packing"] == "jpeg" and cur in ("grid_simple", "grid_jpeg"):
                    want = cur
                elif o["packing"] == "jpeg":
                    want = "grid_simple"
                if cur != want:
                    # Al cambiar el empaquetado ecCodes no arrastra los valores
                    # (la referencia y las escalas son de la plantilla vieja):
                    # se leen antes y se vuelven a cargar después
                    vals = ec.codes_get_values(gid)
                    ec.codes_set(gid, "packingType", want)
                    ec.codes_set_values(gid, vals)
                    changed = True
            # Orden de las celdas (y la primera longitud) antes de los
            # decimales: así el redondeo y la precisión decimal quedan sobre
            # los valores ya reordenados
            if _apply_lons(gid, o):
                changed = True
            if _apply_scan(gid, o):
                changed = True
            dec = o["dec_wind"] if short in _WIND_SHORT else o["dec_temp"] if short in _TEMP_SHORT else None
            if (dec is not None and o["packing"] != "ieee"
                    and _get(gid, "packingType") in ("grid_simple", "grid_jpeg")):
                vals = ec.codes_get_values(gid)
                if np.ptp(vals) > 0:
                    # Redondeados antes: así la referencia R es un múltiplo de
                    # 10^−D y cada valor queda exacto con esos decimales
                    ec.codes_set_values(gid, np.round(vals, int(dec)))
                    ec.codes_set(gid, "changeDecimalPrecision", int(dec))
                    changed = True
            if o["packing"] == "jpeg" and _get(gid, "packingType") != "grid_jpeg":
                # Sin pérdida (typeOfCompressionUsed 0), con el D y los bits
                # que quedaron: lo mismo que los boletines de WAFC London
                vals = ec.codes_get_values(gid)
                ec.codes_set(gid, "packingType", "grid_jpeg")
                ec.codes_set_values(gid, vals)
                changed = True
            if _apply_tables(gid, o):
                changed = True
            if o["centre"] != "origen":
                want_c = CENTRE_MISSING if o["centre"] == "missing" else int(o["centre"])
                if _get(gid, "centre", as_long=True) != want_c:
                    ec.codes_set(gid, "centre", want_c)
                    changed = True
            if o["sub_centre"] is not None and _get(gid, "subCentre", as_long=True) != o["sub_centre"]:
                ec.codes_set(gid, "subCentre", int(o["sub_centre"]))
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
