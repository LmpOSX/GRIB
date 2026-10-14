# -*- coding: utf-8 -*-
"""Conversión de NetCDF de superficie (WRF del SMN) a GRIB2 en grilla lat/lon
regular, que es lo que abre el visor.

El WRF del SMN viene en proyección Lambert 4 km con lat/lon 2D. Se regrilla
por «binning»: cada punto fuente cae en la celda destino más cercana y las
celdas con varios puntos se promedian; los huecos que queden (pocos, porque
la celda destino es del tamaño de la fuente) se rellenan con el promedio de
los vecinos.
"""
import os
import tempfile

import numpy as np

from .grib_engines import ec

# Variables del WRF SMN → (discipline, category, number, typeOfLevel, level, conversión)
SMN_VARIABLES = [
    ("viento10", "Viento a 10 m (U/V desde magnitud y dirección)"),
    ("T2", "Temperatura a 2 m"),
    ("HR2", "Humedad relativa a 2 m"),
]


def bin_regrid(lat2d, lon2d, field, lat1d, lon1d):
    """Promedio por celda destino de los puntos fuente; huecos rellenados
    con vecinos (hasta 4 pasadas)."""
    nj, ni = len(lat1d), len(lon1d)
    dlat = lat1d[1] - lat1d[0]
    dlon = lon1d[1] - lon1d[0]
    j = np.rint((lat2d - lat1d[0]) / dlat).astype(int)
    i = np.rint((lon2d - lon1d[0]) / dlon).astype(int)
    ok = (j >= 0) & (j < nj) & (i >= 0) & (i < ni) & np.isfinite(field)
    acc = np.zeros((nj, ni))
    cnt = np.zeros((nj, ni))
    np.add.at(acc, (j[ok], i[ok]), field[ok])
    np.add.at(cnt, (j[ok], i[ok]), 1.0)
    out = np.where(cnt > 0, acc / np.where(cnt > 0, cnt, 1), np.nan)
    # Relleno de huecos por vecinos (sólo dentro de la zona cubierta)
    for _ in range(4):
        holes = np.isnan(out)
        if not holes.any():
            break
        pad = np.pad(out, 1, constant_values=np.nan)
        stack = np.stack([pad[1 + dy:1 + dy + nj, 1 + dx:1 + dx + ni]
                          for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dy, dx) != (0, 0)])
        with np.errstate(all="ignore"):
            mean = np.nanmean(stack, axis=0)
        n_ok = np.sum(~np.isnan(stack), axis=0)
        fill = holes & (n_ok >= 3)
        out[fill] = mean[fill]
    return out


def _write_message(out, values2d, lat1d, lon1d, disc, cat, num, type_of_level, level,
                   date_int, time_int, step_h):
    gid = ec.codes_grib_new_from_samples("regular_ll_pl_grib2")
    try:
        ec.codes_set(gid, "discipline", disc)
        ec.codes_set(gid, "parameterCategory", cat)
        ec.codes_set(gid, "parameterNumber", num)
        ec.codes_set(gid, "typeOfLevel", type_of_level)
        ec.codes_set(gid, "level", level)
        ec.codes_set(gid, "dataDate", int(date_int))
        ec.codes_set(gid, "dataTime", int(time_int))
        ec.codes_set(gid, "stepUnits", "h")
        ec.codes_set(gid, "forecastTime", int(step_h))
        ec.codes_set(gid, "Ni", len(lon1d))
        ec.codes_set(gid, "Nj", len(lat1d))
        ec.codes_set(gid, "latitudeOfFirstGridPointInDegrees", float(lat1d[0]))
        ec.codes_set(gid, "latitudeOfLastGridPointInDegrees", float(lat1d[-1]))
        ec.codes_set(gid, "longitudeOfFirstGridPointInDegrees", float(lon1d[0] % 360))
        ec.codes_set(gid, "longitudeOfLastGridPointInDegrees", float(lon1d[-1] % 360))
        ec.codes_set(gid, "iDirectionIncrementInDegrees", float(lon1d[1] - lon1d[0]))
        ec.codes_set(gid, "jDirectionIncrementInDegrees", float(abs(lat1d[1] - lat1d[0])))
        ec.codes_set(gid, "jScansPositively", 1)
        ec.codes_set(gid, "generatingProcessIdentifier", 255)
        vals = np.asarray(values2d, dtype=float)
        if np.isnan(vals).any():
            ec.codes_set(gid, "missingValue", 9999.0)
            ec.codes_set(gid, "bitmapPresent", 1)
            vals = np.where(np.isnan(vals), 9999.0, vals)
        ec.codes_set_values(gid, vals.ravel())
        out += ec.codes_get_message(gid)
    finally:
        ec.codes_release(gid)


def smn_wrf_to_grib(data, region=None, res_deg=0.04, variables=("viento10", "T2", "HR2")):
    """NetCDF (bytes) del WRF SMN → bytes GRIB2 regular lat/lon con viento a
    10 m (UGRD/VGRD, heightAboveGround 10), T a 2 m (TMP, K) y HR a 2 m.
    Devuelve (bytes, info)."""
    if ec is None:
        raise RuntimeError("la conversión requiere eccodes")
    try:
        import netCDF4
    except Exception as exc:
        raise RuntimeError("la conversión requiere netCDF4 (pip install netCDF4)") from exc
    fd, tmp = tempfile.mkstemp(prefix="smn_", suffix=".nc")
    os.close(fd)
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
        ds = netCDF4.Dataset(tmp)
        try:
            lat2d = np.asarray(ds.variables["lat"][:], dtype=float)
            lon2d = np.asarray(ds.variables["lon"][:], dtype=float)
            tvar = ds.variables["time"]
            units = getattr(tvar, "units", "")        # "hours since 2026-10-14 06:00:00"
            step_h = float(np.asarray(tvar[:]).ravel()[0])
            run = units.split("since", 1)[1].strip().replace("T", " ")
            date_int = int(run[:10].replace("-", ""))
            time_int = int(run[11:13]) * 100 + int(run[14:16])
            fields = {}
            if "viento10" in variables:
                spd = np.asarray(ds.variables["magViento10"][0], dtype=float)
                direc = np.asarray(ds.variables["dirViento10"][0], dtype=float)
                rad = np.radians(direc)
                fields["u"] = -spd * np.sin(rad)
                fields["v"] = -spd * np.cos(rad)
            if "T2" in variables:
                t2 = np.asarray(ds.variables["T2"][0], dtype=float)
                if "Celsius" in getattr(ds.variables["T2"], "units", "Celsius") or np.nanmax(t2) < 150:
                    t2 = t2 + 273.15
                fields["t"] = t2
            if "HR2" in variables:
                fields["rh"] = np.asarray(ds.variables["HR2"][0], dtype=float)
        finally:
            ds.close()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    lat_lo, lat_hi = float(np.nanmin(lat2d)), float(np.nanmax(lat2d))
    lon_lo, lon_hi = float(np.nanmin(lon2d)), float(np.nanmax(lon2d))
    if region is not None:
        top, bottom, left, right = region
        lat_lo, lat_hi = max(lat_lo, bottom), min(lat_hi, top)
        lon_lo, lon_hi = max(lon_lo, left), min(lon_hi, right)
        if lat_lo >= lat_hi or lon_lo >= lon_hi:
            raise ValueError("La zona pedida no se cruza con el dominio del WRF del SMN "
                             f"({np.nanmin(lat2d):.1f}…{np.nanmax(lat2d):.1f}, "
                             f"{np.nanmin(lon2d):.1f}…{np.nanmax(lon2d):.1f}).")
    lat1d = np.arange(np.ceil(lat_lo / res_deg) * res_deg, lat_hi + 1e-9, res_deg)
    lon1d = np.arange(np.ceil(lon_lo / res_deg) * res_deg, lon_hi + 1e-9, res_deg)
    lat1d = np.round(lat1d, 6)
    lon1d = np.round(lon1d, 6)
    out = bytearray()
    spec = {"u": (0, 2, 2, "heightAboveGround", 10), "v": (0, 2, 3, "heightAboveGround", 10),
            "t": (0, 0, 0, "heightAboveGround", 2), "rh": (0, 1, 1, "heightAboveGround", 2)}
    for name, field in fields.items():
        grid = bin_regrid(lat2d, lon2d, field, lat1d, lon1d)
        disc, cat, num, tol, lev = spec[name]
        _write_message(out, grid, lat1d, lon1d, disc, cat, num, tol, lev, date_int, time_int, step_h)
    info = {"resolucion_final": f"{res_deg:g}°", "grilla": f"{len(lon1d)}x{len(lat1d)}",
            "regrillado": "promedio por celda desde Lambert 4 km"}
    return bytes(out), info
