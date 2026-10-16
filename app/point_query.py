# -*- coding: utf-8 -*-
"""Consulta de un punto del mapa (clic derecho): formatos de entrada y de
salida al estilo del FDP, sin interfaz gráfica.

* geodesic_ddmm / parse_geodesic: `3125S06411W` (grados y minutos).
* parse_overflown_time / format_overflown_time: `YYMMDDHHMM` en UTC.
* report_text: el bloque de texto que se copia al portapapeles con la
  capa inferior, la superior y el valor en el FL pedido.
"""
import datetime as dt
import math
import re

from .grib_reader import KELVIN, fmt_dt

CELL_MODES = [("nearest", "nodo más cercano"),
              ("origin", "origen de celda (esquina SO)")]

_GEO_RE = re.compile(r"^\s*(\d{2})(\d{2})([NS])\s*(\d{3})(\d{2})([EW])\s*$", re.I)


def _ddmm(value, nd, neg, pos):
    a = abs(float(value))
    deg = int(math.floor(a + 1e-9))
    mn = int(round((a - deg) * 60.0))
    if mn >= 60:
        deg, mn = deg + 1, 0
    # Un valor que redondea a 0°00' no tiene hemisferio negativo (-0.0, -1e-12)
    hem = neg if (value < 0 and (deg or mn)) else pos
    return f"{deg:0{nd}d}{mn:02d}{hem}"


def geodesic_ddmm(lat, lon):
    """`3125S06411W`: grados y minutos enteros, latitud de dos cifras y
    longitud de tres, con el hemisferio al final."""
    return _ddmm(lat, 2, "S", "N") + _ddmm(lon, 3, "W", "E")


def parse_geodesic(text):
    """(lat, lon) en grados decimales a partir de `3125S06411W`, o None."""
    m = _GEO_RE.match(text or "")
    if not m:
        return None
    lat = int(m.group(1)) + int(m.group(2)) / 60.0
    lon = int(m.group(4)) + int(m.group(5)) / 60.0
    if int(m.group(2)) >= 60 or int(m.group(5)) >= 60 or lat > 90 or lon > 180:
        return None
    if m.group(3).upper() == "S":
        lat = -lat
    if m.group(6).upper() == "W":
        lon = -lon
    return lat, lon


def parse_overflown_time(text):
    """`YYMMDDHHMM` (o `YYYYMMDDHHMM`) → datetime UTC, o None si no vale."""
    s = re.sub(r"\D", "", text or "")
    fmt = {10: "%y%m%d%H%M", 12: "%Y%m%d%H%M"}.get(len(s))
    if fmt is None:
        return None
    try:
        return dt.datetime.strptime(s, fmt).replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def format_overflown_time(when):
    """datetime → `YYMMDDHHMM` (UTC)."""
    if when is None:
        return ""
    if when.tzinfo is not None:
        when = when.astimezone(dt.timezone.utc)
    return when.strftime("%y%m%d%H%M")


def _fmt(v, nd=0, unit=""):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return f"{v:.{nd}f}{unit}"


def layer_name(layer, reader=None):
    """`300 hPa (F300, 300.9 hPa ISA)` para una capa del archivo o
    `287.4 hPa ISA` para el FL pedido (sin etiqueta)."""
    if layer is None:
        return "—"
    if layer.get("label") is None:
        return f"{layer['p']:.1f} hPa ISA"
    txt = f"{layer['label']:g} hPa"
    fl = layer.get("fl")
    if fl is not None:
        txt += f" (F{fl:03d}"
        if abs(layer["p"] - layer["label"]) > 0.05:
            txt += f", {layer['p']:.1f} hPa ISA"
        txt += ")"
    return txt


def mode_text(res):
    """Cómo se obtuvo el valor en el FL pedido."""
    if res is None or res.get("value") is None:
        return "sin dato"
    if res["mode"] == "exact":
        return "nivel exacto del archivo"
    if res["mode"] == "nearest":
        near = res["lower"] or res["upper"]
        return f"fuera del rango del archivo: valor de la capa más cercana ({layer_name(near)})"
    w = res.get("w")
    return (f"interpolado en ln(p) entre {layer_name(res['lower'])} y {layer_name(res['upper'])}"
            + (f" (peso {w:.2f})" if w is not None else ""))


def wind_text(layer, variation=0.0):
    """`25 kt / 270°` (y `262°M` si hay variación magnética)."""
    if layer is None or layer.get("spd") is None:
        return "—"
    txt = f"{layer['spd']:.0f} kt / {layer['dir']:03.0f}°"
    if abs(variation) >= 0.05:
        txt += f" ({(layer['dir'] - variation) % 360.0:03.0f}°M)"
    return txt


def temp_text(layer):
    if layer is None or layer.get("t") is None:
        return "—"
    return f"{layer['t'] - KELVIN:.1f} °C"


def report_text(lat, lon, when_text, fl, step, step_idx, in_window, res, variation=0.0,
                cell="nearest"):
    """Bloque de texto (para copiar) con la consulta y sus resultados, al
    estilo del FDP. `res` es lo que devuelve GribReader.point_query."""
    lines = [f"Geodésico (grados y minutos): {geodesic_ddmm(lat, lon)}",
             f"Hora de sobrevuelo (YYMMDDHHMM): {when_text}",
             f"Nivel de sobrevuelo (banda, sin F): {int(fl)}"]
    if step is not None:
        h = step.hours
        hs = f"+{h:g} h" if h is not None else step.step_range
        txt = (f"Step: [{step_idx}] {hs}  validez {fmt_dt(step.valid)} UTC  "
               f"(ventana {fmt_dt(step.window_start, False)}–{fmt_dt(step.window_end, False)})")
        if not in_window:
            txt += "  · fuera de las ventanas: paso más cercano"
        lines.append(txt)
    else:
        lines.append("Step: —")
    if res is None:
        lines.append("Origen de celda: fuera de la grilla del archivo")
        return "\n".join(lines)
    cell_txt = dict(CELL_MODES).get(cell, cell)
    lines.append(f"Origen de celda: {geodesic_ddmm(res['lat'], res['lon'])}  "
                 f"(lat {res['lat']:.2f}, lon {res['lon']:.2f}; {cell_txt})")
    for name, layer in (("Capa superior", res.get("upper")),
                        (f"Nivel F{int(fl):03d}", res.get("value")),
                        ("Capa inferior", res.get("lower"))):
        if layer is None:
            lines.append(f"{name}: —")
            continue
        extra = f" · {mode_text(res)}" if name.startswith("Nivel") else ""
        lines.append(f"{name} {layer_name(layer)}{extra}")
        lines.append(f"  Viento (kt / grados): {wind_text(layer, variation)}")
        lines.append(f"  Temperatura (°C): {temp_text(layer)}")
    return "\n".join(lines)
