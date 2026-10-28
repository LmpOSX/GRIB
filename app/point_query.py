# -*- coding: utf-8 -*-
"""Consulta de un punto del mapa (ficha del clic): formatos de entrada y de
salida al estilo del FDP, sin interfaz gráfica.

* geodesic_ddmm / parse_geodesic: `3125S06411W` (grados y minutos).
* parse_overflown_time / format_overflown_time: `YYMMDDHHMM` en UTC.
* report_text: el bloque de texto que se copia al portapapeles con la
  capa inferior, la superior y el valor en el FL pedido.
* fdp_query / fdp_text: lo que respondería el FDP de INDRA para un FL
  (sacado de su binario: P_VALIDATE_GRIB_LEVEL y F_GET_TEMPERATURE).
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


# ── El FDP de INDRA (proceso m_323_grib) ─────────────────────────────────────
# Lee sólo estas capas, por la etiqueta en hPa del inventario de wgrib2
# («NNN mb»), cada una con su FL
FDP_LAYERS = {850: 50, 700: 100, 600: 140, 500: 180, 400: 240, 350: 270, 300: 300,
              275: 320, 250: 340, 225: 360, 200: 390, 175: 410, 150: 450, 100: 530}
# Bandas de consulta (desde, hasta, capa inferior, capa superior): el viento
# es el de la capa superior y la temperatura el promedio entero (truncado)
# de las dos, 0 si falta alguna. Tal cual el binario: 271–300 promedia F240
# con F300 (saltea F270) y F410 no se usa nunca
FDP_BANDS = [(1, 50, 50, 50), (51, 100, 50, 100), (101, 140, 100, 140), (141, 180, 140, 180),
             (181, 240, 180, 240), (241, 270, 240, 270), (271, 300, 240, 300),
             (301, 320, 300, 320), (321, 340, 320, 340), (341, 360, 340, 360),
             (361, 390, 360, 390), (391, 450, 390, 450), (451, 530, 450, 530)]
# Grilla fija del FDP: 1°, 51 × 36 puntos desde 55°S 75°W
FDP_BOX = (-55.0, -20.0, -75.0, -25.0)       # lat S, lat N, lon W, lon E (areas.FDP_REGION)
FDP_RES = 1.0


def _ada_int(x):
    """Conversión de Ada a entero: redondea, y las mitades se alejan del 0."""
    return int(math.copysign(math.floor(abs(float(x)) + 0.5), float(x)))


def fdp_band(fl):
    """(desde, hasta, FL inferior, FL superior) de la banda del FL, o None."""
    fl = int(fl)
    return next((b for b in FDP_BANDS if b[0] <= fl <= b[1]), None)


def fdp_layer_fl(layer):
    """FL del FDP de una capa del archivo (por su etiqueta en hPa), o None."""
    lab = None if layer is None else layer.get("label")
    if lab is None or abs(lab - round(lab)) > 1e-6:
        return None
    return FDP_LAYERS.get(int(round(lab)))


def fdp_grid_note(lats, lons):
    """None si la grilla le sirve al FDP (1°, en grados enteros, cubriendo
    su caja); si no, por qué la rechazaría o le faltarían puntos."""
    if lats is None or lons is None or len(lats) < 2 or len(lons) < 2:
        return "grilla desconocida"
    dlat, dlon = abs(float(lats[1]) - float(lats[0])), abs(float(lons[1]) - float(lons[0]))
    if abs(dlat - FDP_RES) > 1e-6 or abs(dlon - FDP_RES) > 1e-6:
        return f"el FDP sólo lee 1° (este archivo es de {dlon:g}°)"
    if abs(float(lats[0]) - round(float(lats[0]))) > 1e-6 or abs(float(lons[0]) - round(float(lons[0]))) > 1e-6:
        return "el FDP necesita los puntos en grados enteros"
    s, n, w, e = FDP_BOX
    lo = [((float(x) + 180.0) % 360.0) - 180.0 for x in lons]
    if min(lats) > s or max(lats) < n or not (any(abs(x - w) < 1e-6 for x in lo) and any(abs(x - e) < 1e-6 for x in lo)):
        return "el archivo no cubre la caja del FDP (75°W–25°W, 55°S–20°S)"
    return None


def fdp_query(column, fl, lat=None, lon=None):
    """Lo que mostraría el FDP para el FL en esta celda, a partir de la
    columna del archivo (column_query): {'band', 'spd', 'dir', 't' (°C
    entero), 't_missing', 'wind_missing', 'inside'}, o None si el FL está
    fuera de las bandas (0 o más de 530)."""
    band = fdp_band(fl)
    if band is None:
        return None
    by_fl = {}
    for layer in column or []:
        f = fdp_layer_fl(layer)
        if f is not None:
            by_fl[f] = layer
    lower, upper = by_fl.get(band[2]), by_fl.get(band[3])
    out = {"band": band, "spd": None, "dir": None, "t": 0, "t_missing": True, "wind_missing": True,
           "inside": True}
    if lat is not None and lon is not None:
        s, n, w, e = FDP_BOX
        x = ((float(lon) + 180.0) % 360.0) - 180.0
        out["inside"] = s <= float(lat) <= n and w <= x <= e
    if upper is not None and upper.get("spd") is not None:
        out.update(spd=_ada_int(upper["spd"]), dir=_ada_int(upper["dir"]) % 360, wind_missing=False)
    if (lower is not None and upper is not None and lower.get("t") is not None
            and upper.get("t") is not None):
        ta, tb = _ada_int(lower["t"] - KELVIN), _ada_int(upper["t"] - KELVIN)
        out.update(t=int((ta + tb) / 2), t_missing=False)
    return out


def fdp_text(q, band=True):
    """`35 kt 175°  32 °C` (y la banda: `181–240: F180+F240 → …`)."""
    if q is None:
        return "fuera de las bandas del FDP"
    lo, hi, a, b = q["band"]
    wind = "—" if q["wind_missing"] else f"{q['spd']} kt {q['dir']:03d}°"
    temp = f"{q['t']} °C" + (" (falta una capa)" if q["t_missing"] else "")
    txt = f"{wind}  {temp}"
    if band:
        layers = f"F{a:03d}" if a == b else f"F{a:03d}+F{b:03d}"
        txt = f"banda {lo}–{hi} ({layers}): {txt}"
    if not q["inside"]:
        txt += " · fuera de la caja del FDP"
    return txt


def report_text(lat, lon, when_text, fl, step, step_idx, in_window, res, variation=0.0,
                cell="nearest", column=None, fdp_note=None):
    """Bloque de texto (para copiar) con la consulta y sus resultados, al
    estilo del FDP. `res` es lo que devuelve GribReader.point_query;
    `column`, si se da, es la columna completa de la celda (column_query)
    y va al final como perfil, de arriba hacia abajo."""
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
    if column:
        q = fdp_query(column, fl, lat, lon)
        lines.append(f"FDP F{int(fl):03d}: {fdp_text(q)}" + (f" · {fdp_note}" if fdp_note else ""))
    if column:
        lines.append("Perfil de la celda (de arriba hacia abajo):")
        w = max(len(layer_name(l)) for l in column)
        for layer in sorted(column, key=lambda l: l["p"]):
            lines.append(f"  {layer_name(layer):<{w}}  {wind_text(layer, variation)}  {temp_text(layer)}")
    return "\n".join(lines)
