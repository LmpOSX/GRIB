# -*- coding: utf-8 -*-
"""Regrillado local de GRIB2 en grilla lat/lon regular: submuestreo (bilineal
en puntos coincidentes) o promedio ponderado por área, y recorte por zona.

Verificado contra los productos de NOAA: 0,50° y 1,00° son muestras puntuales
del campo de 0,25°, así que el submuestreo reproduce esos productos salvo la
cuantización del empaquetado; el promedio de área ("suavizado") da un campo
más representativo de la celda pero distinto del publicado.
"""
import os
import subprocess
import tempfile

import numpy as np

from .grib_engines import ec, find_wgrib2

SMOOTHING = [
    ("ninguno", "Ninguno (submuestreo = productos de NOAA)"),
    ("promedio", "Promedio de área (suavizado)"),
]


def _axis_1d(first, last, n):
    return np.linspace(first, last, n) if n > 1 else np.array([first])


def grid_axes(gid):
    """Ejes lat/lon 1D de un mensaje regular_ll en el orden del archivo,
    usando los incrementos y el sentido de barrido (las longitudes pueden
    seguir más allá de 360, por ejemplo 180 … 539,75 en ECMWF)."""
    ni, nj = ec.codes_get(gid, "Ni"), ec.codes_get(gid, "Nj")
    lat0 = ec.codes_get(gid, "latitudeOfFirstGridPointInDegrees")
    lon0 = ec.codes_get(gid, "longitudeOfFirstGridPointInDegrees")
    lat1 = ec.codes_get(gid, "latitudeOfLastGridPointInDegrees")
    lon1 = ec.codes_get(gid, "longitudeOfLastGridPointInDegrees")
    try:
        di = float(ec.codes_get(gid, "iDirectionIncrementInDegrees"))
        dj = float(ec.codes_get(gid, "jDirectionIncrementInDegrees"))
        i_neg = int(ec.codes_get(gid, "iScansNegatively"))
        j_pos = int(ec.codes_get(gid, "jScansPositively"))
        if di > 0 and dj > 0:
            lon1d = lon0 + (-1 if i_neg else 1) * di * np.arange(ni)
            lat1d = lat0 + (1 if j_pos else -1) * dj * np.arange(nj)
            return lat1d, lon1d
    except Exception:
        pass
    if lon1 < lon0:
        lon1 += 360.0
    return _axis_1d(lat0, lat1, nj), _axis_1d(lon0, lon1, ni)


def coarse_axes(lat1d, lon1d, factor):
    """Ejes gruesos tomando un punto cada `factor` a partir del primero que
    sea múltiplo del paso grueso (para que coincidan con los productos de
    NOAA, cuyos puntos son múltiplos de 0,50 / 1,00)."""
    d_lat = abs(lat1d[1] - lat1d[0]) if len(lat1d) > 1 else 1.0
    d_lon = abs(lon1d[1] - lon1d[0]) if len(lon1d) > 1 else 1.0
    step_lat, step_lon = d_lat * factor, d_lon * factor

    def pick(axis, step):
        idx = [i for i, v in enumerate(axis) if abs(v / step - round(v / step)) < 1e-6]
        return np.array(idx, dtype=int)
    return pick(lat1d, step_lat), pick(lon1d, step_lon)


def subsample(values2d, jj, ii):
    return np.ascontiguousarray(values2d[np.ix_(jj, ii)])


def box_average(values2d, jj, ii, factor):
    """Promedio ponderado por área: la celda gruesa centrada en cada punto
    grueso cubre `factor` celdas finas; las de los bordes pesan la mitad.
    Vectorizado por desplazamientos; en los bordes del dominio se normaliza
    con los pesos disponibles."""
    half = factor // 2 if factor % 2 == 0 else factor // 2
    offs = np.arange(-half, half + 1)
    # pesos: solapamiento de la celda fina [o−½, o+½] con [−factor/2, factor/2]
    w = np.clip(np.minimum(offs + 0.5, factor / 2) - np.maximum(offs - 0.5, -factor / 2), 0, None)
    nj, ni = values2d.shape
    acc = np.zeros((len(jj), len(ii)))
    tot = np.zeros_like(acc)
    valid = ~np.isnan(values2d)
    vals = np.where(valid, values2d, 0.0)
    for a, wa in zip(offs, w):
        ja = jj + a
        okj = (ja >= 0) & (ja < nj)
        for b, wb in zip(offs, w):
            ib = ii + b
            oki = (ib >= 0) & (ib < ni)
            if not okj.any() or not oki.any():
                continue
            sub_j = np.where(okj, ja, 0)
            sub_i = np.where(oki, ib, 0)
            mask = np.outer(okj, oki)
            v = vals[np.ix_(sub_j, sub_i)] * mask
            m = valid[np.ix_(sub_j, sub_i)] * mask
            acc += wa * wb * v
            tot += wa * wb * m
    out = np.where(tot > 0, acc / np.where(tot > 0, tot, 1), np.nan)
    return out


def regrid_grib(data, factor, method="ninguno"):
    """Toma los bytes de un GRIB2 (grilla lat/lon regular) y devuelve otro
    con un punto cada `factor` (1 = sin cambio). `method`: 'ninguno'
    (submuestreo) o 'promedio' (área). Conserva metadatos y empaquetado."""
    if ec is None:
        raise RuntimeError("regrillar requiere eccodes")
    if factor <= 1 and method != "promedio":
        return data
    out = bytearray()
    pos = 0
    while True:
        gid = ec.codes_new_from_message(data[pos:]) if pos < len(data) else None
        if gid is None:
            break
        try:
            total = ec.codes_get_message_size(gid)
            if ec.codes_get(gid, "gridType") != "regular_ll":
                out += data[pos:pos + total]
                continue
            ni, nj = ec.codes_get(gid, "Ni"), ec.codes_get(gid, "Nj")
            lat1d, lon1d = grid_axes(gid)
            vals = np.asarray(ec.codes_get_double_array(gid, "values"), dtype=float).reshape(nj, ni)
            if ec.codes_get(gid, "bitmapPresent"):
                vals = np.where(vals == ec.codes_get(gid, "missingValue"), np.nan, vals)
            if factor > 1:
                jj, ii = coarse_axes(lat1d, lon1d, factor)
            else:
                jj, ii = np.arange(nj), np.arange(ni)
            if method == "promedio":
                new = box_average(vals, jj, ii, max(factor, 3) if factor == 1 else factor)
            else:
                new = subsample(vals, jj, ii)
            ec.codes_set(gid, "Ni", len(ii))
            ec.codes_set(gid, "Nj", len(jj))
            ec.codes_set(gid, "latitudeOfFirstGridPointInDegrees", float(lat1d[jj[0]]))
            ec.codes_set(gid, "latitudeOfLastGridPointInDegrees", float(lat1d[jj[-1]]))
            ec.codes_set(gid, "longitudeOfFirstGridPointInDegrees", float(lon1d[ii[0]] % 360))
            ec.codes_set(gid, "longitudeOfLastGridPointInDegrees", float(lon1d[ii[-1]] % 360))
            if len(ii) > 1:
                ec.codes_set(gid, "iDirectionIncrementInDegrees", float(abs(lon1d[ii[1]] - lon1d[ii[0]])))
            if len(jj) > 1:
                ec.codes_set(gid, "jDirectionIncrementInDegrees", float(abs(lat1d[jj[1]] - lat1d[jj[0]])))
            if np.isnan(new).any():
                ec.codes_set(gid, "missingValue", 9999.0)
                ec.codes_set(gid, "bitmapPresent", 1)
                new = np.where(np.isnan(new), 9999.0, new)
            ec.codes_set_values(gid, new.ravel())
            ec.codes_set(gid, "generatingProcessIdentifier", 255)
            out += ec.codes_get_message(gid)
        finally:
            pos += total
            ec.codes_release(gid)
    return bytes(out)


def _enclosing(axis, lo, hi, eps=1e-9):
    """Índices (en el orden del eje) de los puntos que encierran el
    intervalo [lo, hi]: se toma desde el último punto ≤ lo hasta el primero
    ≥ hi, así la zona recortada nunca queda más chica que la pedida
    (redondeo hacia afuera). Vacío si el eje no toca el intervalo."""
    axis = np.asarray(axis, dtype=float)
    inside = (axis >= lo - eps) & (axis <= hi + eps)
    below = axis <= lo + eps
    above = axis >= hi - eps
    if not inside.any():
        # ¿el intervalo cae entre dos puntos? → los dos vecinos
        if below.any() and above.any():
            lo_i = int(np.argmax(np.where(below, axis, -np.inf)))
            hi_i = int(np.argmin(np.where(above, axis, np.inf)))
            return np.array(sorted({lo_i, hi_i}))
        return np.array([], dtype=int)
    lo_eff = float(np.max(axis[below])) if below.any() else float(np.min(axis))
    hi_eff = float(np.min(axis[above])) if above.any() else float(np.max(axis))
    return np.where((axis >= lo_eff - eps) & (axis <= hi_eff + eps))[0]


def crop_grib(data, region):
    """Recorta cada mensaje (grilla lat/lon regular) a la zona
    (top, bottom, left, right) en grados, **hacia afuera**: se conservan los
    puntos de grilla que encierran la zona, nunca menos. Las longitudes del
    archivo pueden estar en 0…360; una zona que cruza Greenwich (oeste
    negativo, este positivo) sobre una grilla 0…360 se reordena para que el
    recorte sea contiguo. Devuelve los bytes del nuevo GRIB2."""
    if ec is None:
        raise RuntimeError("recortar requiere eccodes")
    top, bottom, left, right = region
    out = bytearray()
    pos = 0
    while pos < len(data):
        gid = ec.codes_new_from_message(data[pos:])
        if gid is None:
            break
        try:
            total = ec.codes_get_message_size(gid)
            if ec.codes_get(gid, "gridType") != "regular_ll":
                out += data[pos:pos + total]
                continue
            ni, nj = ec.codes_get(gid, "Ni"), ec.codes_get(gid, "Nj")
            lat1d, lon1d = grid_axes(gid)
            lon_norm = ((lon1d + 180) % 360) - 180
            l_, r_ = ((left + 180) % 360) - 180, ((right + 180) % 360) - 180
            if right - left >= 360 - 1e-9:
                sel_i = np.arange(ni)
            elif l_ <= r_:
                # Orden por longitud normalizada: una grilla 0…360 con la zona
                # a caballo de Greenwich queda contigua (…, 359.75, 0, 0.25, …)
                order = np.argsort(lon_norm, kind="stable")
                sel = _enclosing(lon_norm[order], l_, r_)
                sel_i = order[sel]
            else:   # cruza el antimeridiano
                sel_i = np.where((lon_norm >= l_ - 1e-9) | (lon_norm <= r_ + 1e-9))[0]
            sel_j = _enclosing(lat1d, bottom, top)
            if len(sel_i) == 0 or len(sel_j) == 0:
                raise ValueError("La zona pedida no contiene puntos de la grilla.")
            contiguous_j = not np.any(np.diff(sel_j) != 1)
            steps_i = np.diff(sel_i)
            contiguous_i = len(sel_i) == 1 or np.all(steps_i == 1) or \
                (np.sum(steps_i != 1) == 1 and np.all((steps_i == 1) | (steps_i == 1 - ni)))
            if not (contiguous_i and contiguous_j):
                out += data[pos:pos + total]
                continue
            vals = np.asarray(ec.codes_get_double_array(gid, "values"), dtype=float).reshape(nj, ni)
            new = vals[np.ix_(sel_j, sel_i)]
            ec.codes_set(gid, "Ni", len(sel_i))
            ec.codes_set(gid, "Nj", len(sel_j))
            ec.codes_set(gid, "latitudeOfFirstGridPointInDegrees", float(lat1d[sel_j[0]]))
            ec.codes_set(gid, "latitudeOfLastGridPointInDegrees", float(lat1d[sel_j[-1]]))
            ec.codes_set(gid, "longitudeOfFirstGridPointInDegrees", float(lon1d[sel_i[0]] % 360))
            ec.codes_set(gid, "longitudeOfLastGridPointInDegrees", float(lon1d[sel_i[-1]] % 360))
            ec.codes_set_values(gid, new.ravel())
            out += ec.codes_get_message(gid)
        finally:
            pos += total
            ec.codes_release(gid)
    return bytes(out)


def grid_bbox(data):
    """(lonmin, lonmax, latmin, latmax) de la primera grilla regular lat/lon
    del GRIB2 (bytes o ruta), con las longitudes en −180…180 (si el dominio
    cruza el antimeridiano se informa toda la vuelta). None si no hay."""
    if ec is None:
        return None
    if isinstance(data, str):
        with open(data, "rb") as fh:
            data = fh.read()
    pos = 0
    while pos < len(data):
        gid = ec.codes_new_from_message(data[pos:])
        if gid is None:
            return None
        try:
            total = ec.codes_get_message_size(gid)
            if ec.codes_get(gid, "gridType") != "regular_ll":
                continue
            lat1d, lon1d = grid_axes(gid)
            lon_norm = ((lon1d + 180.0) % 360.0) - 180.0
            lonmin, lonmax = float(lon_norm.min()), float(lon_norm.max())
            if len(lon1d) > 1 and (lon1d.max() - lon1d.min()) > 180.0 and \
                    float(np.max(np.diff(np.sort(lon_norm)))) > 2.0 * float(abs(lon1d[1] - lon1d[0])):
                lonmin, lonmax = -180.0, 180.0     # cruza el antimeridiano: toda la vuelta
            return (lonmin, lonmax, float(lat1d.min()), float(lat1d.max()))
        finally:
            pos += total
            ec.codes_release(gid)
    return None


def filter_grib(data, keep_levels_hpa=None, keep_vars=None, tol=0.6):
    """Conserva sólo los mensajes cuyo nivel (en hPa según level_to_hpa) esté
    a menos de `tol` hPa de alguno pedido y cuya variable (u/v/t/…) esté en
    keep_vars (claves cortas de ecCodes). None = sin filtro."""
    from .grib_engines import level_to_hpa
    if ec is None:
        raise RuntimeError("filtrar requiere eccodes")
    out = bytearray()
    pos = 0
    while pos < len(data):
        gid = ec.codes_new_from_message(data[pos:])
        if gid is None:
            break
        try:
            total = ec.codes_get_message_size(gid)
            keep = True
            if keep_vars is not None:
                keep = ec.codes_get(gid, "shortName") in keep_vars
            if keep and keep_levels_hpa is not None:
                try:
                    lv = level_to_hpa(ec.codes_get(gid, "typeOfLevel"), ec.codes_get(gid, "level"))
                except Exception:
                    lv = None
                keep = lv is not None and any(abs(lv - k) <= tol for k in keep_levels_hpa)
            if keep:
                out += data[pos:pos + total]
        finally:
            pos += total
            ec.codes_release(gid)
    return bytes(out)


def _interp_axis(values, x_src, x_dst, axis):
    """Interpolación lineal 1D a lo largo de `axis` (x_src ascendente); los
    puntos destino fuera del rango toman el valor del borde. NaN se propaga."""
    x_src = np.asarray(x_src, dtype=float)
    x_dst = np.asarray(x_dst, dtype=float)
    if len(x_src) == 1:
        shape = list(values.shape)
        shape[axis] = len(x_dst)
        return np.broadcast_to(np.take(values, [0] * len(x_dst), axis=axis), shape).copy()
    j = np.clip(np.searchsorted(x_src, x_dst), 1, len(x_src) - 1)
    x0, x1 = x_src[j - 1], x_src[j]
    w = np.clip((x_dst - x0) / (x1 - x0), 0.0, 1.0)
    a = np.take(values, j - 1, axis=axis)
    b = np.take(values, j, axis=axis)
    shape = [1] * values.ndim
    shape[axis] = len(x_dst)
    w = w.reshape(shape)
    return (1.0 - w) * a + w * b


def is_global_lon(lon1d):
    """True si el eje de longitudes da la vuelta completa (n × paso = 360)."""
    lon1d = np.asarray(lon1d, dtype=float)
    if len(lon1d) < 2:
        return False
    d = abs(float(lon1d[1] - lon1d[0]))
    return d > 0 and abs(len(lon1d) * d - 360.0) < 1e-4


def bilinear_regrid(values2d, lat1d, lon1d, lat_out, lon_out):
    """Regrillado bilineal de un campo (nj, ni) con ejes `lat1d`/`lon1d` (en
    cualquier sentido) a los ejes `lat_out`/`lon_out`. En una grilla global
    las longitudes destino entre la última columna y la primera se
    interpolan cruzando el meridiano de corte (la grilla se cierra)."""
    lat1d = np.asarray(lat1d, dtype=float)
    lon1d = np.asarray(lon1d, dtype=float)
    vals = np.asarray(values2d, dtype=float)
    lon_out = np.asarray(lon_out, dtype=float)
    if len(lat1d) > 1 and lat1d[0] > lat1d[-1]:
        lat1d, vals = lat1d[::-1], vals[::-1, :]
    if len(lon1d) > 1 and lon1d[0] > lon1d[-1]:
        lon1d, vals = lon1d[::-1], vals[:, ::-1]
    if is_global_lon(lon1d):
        # Se agrega la primera columna 360° más allá y los destinos se llevan
        # al rango [primera, primera + 360)
        lon1d = np.append(lon1d, lon1d[0] + 360.0)
        vals = np.concatenate([vals, vals[:, :1]], axis=1)
        lon_out = lon1d[0] + np.mod(lon_out - lon1d[0], 360.0)
    tmp = _interp_axis(vals, lon1d, lon_out, axis=1)
    return _interp_axis(tmp, lat1d, lat_out, axis=0)


def target_axis(axis, res, wrap=False):
    """Múltiplos de `res` dentro del rango del eje, en el sentido del eje.
    Con `wrap` (longitudes de una grilla global) el destino también da la
    vuelta completa: 360/res puntos desde el primer múltiplo."""
    lo, hi = float(np.min(axis)), float(np.max(axis))
    start = np.ceil(lo / res - 1e-9) * res
    if wrap:
        out = np.round(start + res * np.arange(int(round(360.0 / res))), 6)
    else:
        out = np.round(np.arange(start, hi + 1e-9, res), 6)
    if len(axis) > 1 and axis[0] > axis[-1]:
        out = out[::-1]
    return out


def regrid_bilinear_grib(data, res_deg):
    """Regrilla cada mensaje (grilla lat/lon regular) a una grilla de
    `res_deg` grados con puntos en múltiplos de esa resolución, por
    interpolación bilineal (como el producto WAFS operativo). Si la grilla ya
    coincide, el mensaje pasa sin cambios."""
    if ec is None:
        raise RuntimeError("regrillar requiere eccodes")
    out = bytearray()
    pos = 0
    while pos < len(data):
        gid = ec.codes_new_from_message(data[pos:])
        if gid is None:
            break
        try:
            total = ec.codes_get_message_size(gid)
            if ec.codes_get(gid, "gridType") != "regular_ll":
                out += data[pos:pos + total]
                continue
            ni, nj = ec.codes_get(gid, "Ni"), ec.codes_get(gid, "Nj")
            lat1d, lon1d = grid_axes(gid)
            lat_out = target_axis(lat1d, res_deg)
            lon_out = target_axis(lon1d, res_deg, wrap=is_global_lon(lon1d))
            if len(lat_out) == 0 or len(lon_out) == 0:
                raise ValueError(f"La grilla no contiene puntos múltiplos de {res_deg:g}°.")
            same = (len(lat_out) == nj and len(lon_out) == ni
                    and np.allclose(lat_out, lat1d, atol=1e-6) and np.allclose(lon_out, lon1d, atol=1e-6))
            if same:
                out += data[pos:pos + total]
                continue
            vals = np.asarray(ec.codes_get_double_array(gid, "values"), dtype=float).reshape(nj, ni)
            if ec.codes_get(gid, "bitmapPresent"):
                vals = np.where(vals == ec.codes_get(gid, "missingValue"), np.nan, vals)
            new = bilinear_regrid(vals, lat1d, lon1d, lat_out, lon_out)
            ec.codes_set(gid, "Ni", len(lon_out))
            ec.codes_set(gid, "Nj", len(lat_out))
            ec.codes_set(gid, "latitudeOfFirstGridPointInDegrees", float(lat_out[0]))
            ec.codes_set(gid, "latitudeOfLastGridPointInDegrees", float(lat_out[-1]))
            ec.codes_set(gid, "longitudeOfFirstGridPointInDegrees", float(lon_out[0] % 360))
            ec.codes_set(gid, "longitudeOfLastGridPointInDegrees", float(lon_out[-1] % 360))
            ec.codes_set(gid, "iDirectionIncrementInDegrees", float(res_deg))
            ec.codes_set(gid, "jDirectionIncrementInDegrees", float(res_deg))
            if np.isnan(new).any():
                ec.codes_set(gid, "missingValue", 9999.0)
                ec.codes_set(gid, "bitmapPresent", 1)
                new = np.where(np.isnan(new), 9999.0, new)
            ec.codes_set_values(gid, new.ravel())
            out += ec.codes_get_message(gid)
        finally:
            pos += total
            ec.codes_release(gid)
    return bytes(out)


# ── Regrillado con wgrib2 (-new_grid, NCEPLIBS-ip) ───────────────────────────

REGRID_ENGINES = [("eccodes", "Bilineal propio (ecCodes)"),
                  ("wgrib2", "wgrib2 -new_grid (NCEPLIBS-ip)")]
_IPOLATES = {}


def wgrib2_can_regrid(wgrib2_path=""):
    """True si hay un wgrib2 compilado con la interpolación (IPOLATES):
    `wgrib2 -config` no dice «IPOLATES package is not installed»."""
    exe = find_wgrib2(wgrib2_path or "")
    if not exe:
        return False
    if exe not in _IPOLATES:
        try:
            out = subprocess.run([exe, "-config"], capture_output=True, text=True, timeout=10)
            text = (out.stdout or "") + (out.stderr or "")
            _IPOLATES[exe] = "IPOLATES" in text and "IPOLATES package is not installed" not in text
        except Exception:
            _IPOLATES[exe] = False
    return _IPOLATES[exe]


def _uv_paired(data):
    """True si cada U del archivo va seguida de su V (mismo nivel y plazo) y
    no hay V sueltas: así wgrib2 puede interpolarlas como vector."""
    seq = []
    pos = 0
    while pos < len(data):
        gid = ec.codes_new_from_message(data[pos:])
        if gid is None:
            break
        try:
            total = ec.codes_get_message_size(gid)
            seq.append((ec.codes_get(gid, "shortName"), ec.codes_get(gid, "level"),
                        ec.codes_get(gid, "stepRange")))
        finally:
            pos += total
            ec.codes_release(gid)
    us = [k for k, m in enumerate(seq) if m[0] == "u"]
    vs = [k for k, m in enumerate(seq) if m[0] == "v"]
    if not us or len(us) != len(vs):
        return False
    return all(k + 1 < len(seq) and seq[k + 1][0] == "v" and seq[k + 1][1:] == seq[k][1:] for k in us)


def regrid_wgrib2_grib(data, res_deg, wgrib2_path="", method="bilinear"):
    """Regrilla con `wgrib2 -new_grid latlon` a `res_deg` grados, con los
    mismos puntos destino que el bilineal propio (múltiplos de la
    resolución, la vuelta completa en una grilla global). wgrib2 escribe de
    sur a norte: si el origen iba de norte a sur se vuelve a ese orden. Si
    cada U va seguida de su V se interpolan como vector (en el polo el
    viento queda bien definido); si no (una sola componente, otro orden) se
    interpolan como escalares, que de lat/lon a lat/lon da lo mismo salvo
    en las filas de los polos."""
    if ec is None:
        raise RuntimeError("regrillar requiere eccodes")
    exe = find_wgrib2(wgrib2_path or "")
    if not exe:
        raise RuntimeError("no se encontró wgrib2")
    if not wgrib2_can_regrid(exe):
        raise RuntimeError("este wgrib2 no tiene la interpolación (IPOLATES): no puede regrillar")
    gid = ec.codes_new_from_message(bytes(data))
    try:
        lat1d, lon1d = grid_axes(gid)
        j_pos = int(ec.codes_get(gid, "jScansPositively"))
    finally:
        ec.codes_release(gid)
    res = float(res_deg)
    lat_out = target_axis(lat1d, res)
    lon_out = target_axis(lon1d, res, wrap=is_global_lon(lon1d))
    if len(lat_out) == 0 or len(lon_out) == 0:
        raise ValueError(f"La grilla no contiene puntos múltiplos de {res:g}°.")
    lat_s, lon_w = float(np.min(lat_out)), float(np.min(lon_out)) % 360.0
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = os.path.join(tmp, "in.grib2"), os.path.join(tmp, "out.grib2")
        with open(src, "wb") as fh:
            fh.write(bytes(data))
        vectors = "UGRD:VGRD" if _uv_paired(bytes(data)) else "none"
        cmd = [exe, src, "-new_grid_winds", "earth", "-new_grid_vectors", vectors,
               "-new_grid_interpolation", method,
               "-new_grid", "latlon", f"{lon_w:g}:{len(lon_out)}:{res:g}",
               f"{lat_s:g}:{len(lat_out)}:{res:g}", dst]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if out.returncode != 0 or not os.path.isfile(dst) or os.path.getsize(dst) == 0:
            msg = (out.stderr or out.stdout or "").strip().splitlines()
            raise RuntimeError("wgrib2 -new_grid falló: " + (msg[-1] if msg else f"código {out.returncode}"))
        with open(dst, "rb") as fh:
            new = fh.read()
    if j_pos:
        return new
    # De vuelta a norte → sur, como el origen
    res_out = bytearray()
    pos = 0
    while pos < len(new):
        gid = ec.codes_new_from_message(new[pos:])
        if gid is None:
            break
        try:
            total = ec.codes_get_message_size(gid)
            if int(ec.codes_get(gid, "jScansPositively")):
                ec.codes_set(gid, "swapScanningY", 1)
                res_out += ec.codes_get_message(gid)
            else:
                res_out += new[pos:pos + total]
        finally:
            pos += total
            ec.codes_release(gid)
    return bytes(res_out)


def already_on_grid(data, res_deg):
    """True si todos los mensajes ya están en la grilla destino de
    `res_deg` (o no son lat/lon regulares): no hay nada que regrillar."""
    pos = 0
    while pos < len(data):
        gid = ec.codes_new_from_message(data[pos:])
        if gid is None:
            break
        try:
            pos += ec.codes_get_message_size(gid)
            if ec.codes_get(gid, "gridType") != "regular_ll":
                continue
            lat1d, lon1d = grid_axes(gid)
            lat_out = target_axis(lat1d, res_deg)
            lon_out = target_axis(lon1d, res_deg, wrap=is_global_lon(lon1d))
            if not (len(lat_out) == len(lat1d) and len(lon_out) == len(lon1d)
                    and np.allclose(lat_out, lat1d, atol=1e-6) and np.allclose(lon_out, lon1d, atol=1e-6)):
                return False
        finally:
            ec.codes_release(gid)
    return True


def regrid_to(data, res_deg, engine="eccodes", wgrib2_path=""):
    """Regrilla a `res_deg` con el motor elegido: «wgrib2» usa -new_grid
    (bilineal de NCEPLIBS-ip); cualquier otro, el bilineal propio. Si el
    archivo ya está en esa grilla pasa sin cambios."""
    if ec is not None and already_on_grid(bytes(data), float(res_deg)):
        return bytes(data)
    if engine == "wgrib2":
        return regrid_wgrib2_grib(data, res_deg, wgrib2_path)
    return regrid_bilinear_grib(data, res_deg)
