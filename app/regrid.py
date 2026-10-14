# -*- coding: utf-8 -*-
"""Regrillado local de GRIB2 en grilla lat/lon regular: submuestreo (bilineal
en puntos coincidentes) o promedio ponderado por área, y recorte por zona.

Verificado contra los productos de NOAA: 0,50° y 1,00° son muestras puntuales
del campo de 0,25°, así que el submuestreo reproduce esos productos salvo la
cuantización del empaquetado; el promedio de área ("suavizado") da un campo
más representativo de la celda pero distinto del publicado.
"""
import numpy as np

from .grib_engines import ec

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


def crop_grib(data, region):
    """Recorta cada mensaje (grilla lat/lon regular) a la zona
    (top, bottom, left, right) en grados; las longitudes del archivo pueden
    estar en 0…360. Devuelve los bytes del nuevo GRIB2."""
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
            if l_ <= r_:
                sel_i = np.where((lon_norm >= l_ - 1e-9) & (lon_norm <= r_ + 1e-9))[0]
            else:   # cruza el antimeridiano
                sel_i = np.where((lon_norm >= l_ - 1e-9) | (lon_norm <= r_ + 1e-9))[0]
            sel_j = np.where((lat1d >= bottom - 1e-9) & (lat1d <= top + 1e-9))[0]
            if len(sel_i) == 0 or len(sel_j) == 0:
                raise ValueError("La zona pedida no contiene puntos de la grilla.")
            # Sólo bloques contiguos (sin cruce del antimeridiano) se recortan
            if np.any(np.diff(sel_i) != 1) or np.any(np.diff(sel_j) != 1):
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
