# -*- coding: utf-8 -*-
"""Conversión de los límites de FIR del AIP (ENR 2.1) a GeoJSON.

En el AIP Argentina (AIS de EANA / ANAC) los límites laterales están como
listas de vértices en texto: «2215S06240W - 2230S06100W - … siguiendo el
límite internacional hasta …». Esta utilidad toma ese texto (pegado del
PDF o leído de un archivo), reconoce los formatos de coordenadas
habituales en los AIP y arma un polígono GeoJSON. Los tramos descriptos
con palabras («a lo largo del límite internacional», «por la costa», un
arco) no se inventan: quedan como marcadores en la propiedad
`tramos_pendientes` para que el usuario complete el tramo a mano o lo tome
de otra fuente.

Formatos reconocidos (lat y lon en cualquier orden, separados por espacio,
guion, coma o nada):

* compactos: 2215S06240W · 221530S0624015W · 2215.5S06240.2W · S2215 W06240
* con símbolos: 22°15'S 062°40'W · 22°15'30"S 062°40'15"W · 22º 15' 30'' S
* con espacios: 22 15 S 062 40 W · 22 15 30 S 062 40 15 W
* decimales con hemisferio: 22.25S 62.6667W
* decimales con signo (una pareja por línea): -22.25, -62.6667

Uso por línea de comandos:
    python -m app.fir_aip limites.txt --codigo SAVF --nombre "Comodoro Rivadavia" -o savf.geojson
"""
import argparse
import json
import re
import sys
import unicodedata

from .fir import FIR_NAMES

AIP_SOURCE = "AIP Argentina ENR 2.1 (AIS EANA/ANAC)"

# Frases que describen un tramo que no es una recta entre dos vértices
GAP_PATTERNS = [
    r"a lo largo", r"siguiendo", r"por la costa", r"por el l[ií]mite", r"costa",
    r"l[ií]mite\s+(?:internacional|pol[ií]tico|fronterizo|con|de|entre)", r"frontera",
    r"along", r"border", r"boundary", r"coast", r"shoreline",
    r"arco", r"c[ií]rculo", r"radio\s+de", r"paralelo\s+\d", r"meridiano\s+\d",
]
_GAP_RE = re.compile("|".join(f"(?:{p})" for p in GAP_PATTERNS), re.IGNORECASE)

_MIN = r"\d{1,2}(?:[.,]\d+)?"
_SEC = r"\d{1,2}(?:[.,]\d+)?"
_HEM = r"[NSEW]"          # sólo mayúsculas: en texto corrido «s», «e» y «n» son letras comunes


def _body(sfx):
    """Cuerpo de un valor angular en las cuatro notaciones; los grupos
    llevan el sufijo para poder usarlo dos veces en una alternancia."""
    return (
        r"(?:"
        # 22°15'30"S  ·  22º 15' S  ·  22°S
        r"(?P<deg_s" + sfx + r">\d{1,3})\s*[°º]\s*(?:(?P<min_s" + sfx + r">" + _MIN + r")\s*['′’]?\s*"
        r"(?:(?P<sec_s" + sfx + r">" + _SEC + r")\s*(?:[\"″”]|''|′′)?)?)?"
        r"|"
        # 22 15 30 S  ·  22 15 S
        r"(?P<deg_b" + sfx + r">\d{1,3})\s+(?P<min_b" + sfx + r">\d{1,2}(?:[.,]\d+)?)"
        r"(?:\s+(?P<sec_b" + sfx + r">\d{1,2}(?:[.,]\d+)?))?"
        r"|"
        # 2215S · 221530S · 2215.5S · 0624015W
        r"(?P<compact" + sfx + r">\d{4,7}(?:[.,]\d+)?)"
        r"|"
        # 22.25S · 62.6667W
        r"(?P<dec" + sfx + r">\d{1,3}[.,]\d+)"
        r")"
    )


# Un valor angular con su hemisferio antes (S2215) o después (2215S); nunca
# los dos, así «S2215 W06240» no le roba la W al valor siguiente
_HALF_RE = re.compile(
    r"(?:(?P<h1>" + _HEM + r")\s*" + _body("1") + r"(?![\d°º'\"]))"
    r"|"
    r"(?:" + _body("2") + r"\s*(?P<h2>" + _HEM + r"))"
)
_SIGNED_LINE_RE = re.compile(
    r"^\s*(?P<lat>[-+]?\d{1,2}(?:[.,]\d+)?)\s*[,;\s]\s*(?P<lon>[-+]?\d{1,3}(?:[.,]\d+)?)\s*$")


class AipParseError(ValueError):
    pass


def _f(s):
    return float(s.replace(",", "."))


def _split_compact(digits, hem):
    """'221530' con S → (22, 15, 30); '0624015' con W → (62, 40, 15);
    '2215.5' → (22, 15.5, 0)."""
    digits = digits.replace(",", ".")
    intpart, _, frac = digits.partition(".")
    nd = 2 if hem in "NS" else 3
    if len(intpart) < nd:
        raise AipParseError(f"coordenada compacta demasiado corta: {digits}{hem}")
    rest = intpart[nd:]
    if len(rest) not in (0, 2, 4):
        raise AipParseError(f"coordenada compacta con cantidad de dígitos inválida: {digits}{hem}")
    deg, mn, sec = float(intpart[:nd]), 0.0, 0.0
    if len(rest) >= 2:
        mn = float(rest[:2])
    if len(rest) == 4:
        sec = float(rest[2:4])
    if frac:
        add = float("0." + frac)
        if len(rest) == 4:
            sec += add
        elif len(rest) == 2:
            mn += add
        else:
            deg += add
    return deg, mn, sec


def _to_decimal(deg, mn, sec, hem):
    if mn >= 60 or sec >= 60:
        raise AipParseError(f"minutos o segundos fuera de rango: {deg} {mn} {sec} {hem}")
    val = deg + mn / 60.0 + sec / 3600.0
    if hem in "NS" and val > 90.0:
        raise AipParseError(f"latitud fuera de rango: {val}")
    if hem in "EW" and val > 180.0:
        raise AipParseError(f"longitud fuera de rango: {val}")
    return -val if hem in "SW" else val


def parse_half(match):
    """(valor decimal, 'lat'|'lon') de un match de _HALF_RE."""
    hem = (match.group("h1") or match.group("h2") or "").upper()
    sfx = "1" if match.group("h1") else "2"
    g = lambda name: match.group(name + sfx)   # noqa: E731
    if g("compact") is not None:
        deg, mn, sec = _split_compact(g("compact"), hem)
    elif g("dec") is not None:
        deg, mn, sec = _f(g("dec")), 0.0, 0.0
    elif g("deg_s") is not None:
        deg = float(g("deg_s"))
        mn = _f(g("min_s")) if g("min_s") else 0.0
        sec = _f(g("sec_s")) if g("sec_s") else 0.0
    else:
        deg = float(g("deg_b"))
        mn = _f(g("min_b"))
        sec = _f(g("sec_b")) if g("sec_b") else 0.0
    return _to_decimal(deg, mn, sec, hem), ("lat" if hem in "NS" else "lon")


def parse_aip_coord(text):
    """Un vértice en texto → (lat, lon). Acepta todas las notaciones de la
    cabecera del módulo. Lanza AipParseError si no hay lat y lon."""
    text = text.strip()
    m = _SIGNED_LINE_RE.match(text)
    if m:
        return _f(m.group("lat")), _f(m.group("lon"))
    lat = lon = None
    for mm in _HALF_RE.finditer(text):
        val, kind = parse_half(mm)
        if kind == "lat" and lat is None:
            lat = val
        elif kind == "lon" and lon is None:
            lon = val
    if lat is None or lon is None:
        raise AipParseError(f"no se reconoce una coordenada lat/lon en: {text!r}")
    return lat, lon


def _strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def parse_aip_text(text):
    """Recorre el texto y devuelve una lista de ítems en orden:
    {'tipo': 'vertice', 'lat', 'lon', 'texto'} y
    {'tipo': 'tramo', 'texto', 'despues_de': índice del vértice anterior o -1}
    para los tramos descriptos con palabras (límite internacional, costa,
    arco…). Una coordenada suelta (p. ej. «paralelo 46°00'S») forma parte
    de la descripción del tramo. Lo que no se puede interpretar se devuelve
    como {'tipo': 'error', 'texto'}."""
    items = []
    n_vert = 0
    gap_buf = []        # texto entre el último vértice y el siguiente

    def flush_gap():
        seg = " ".join(" ".join(gap_buf).split()).strip(" -–—,;:.·")
        gap_buf.clear()
        if seg and _GAP_RE.search(_strip_accents(seg)):
            items.append({"tipo": "tramo", "texto": seg, "despues_de": n_vert - 1})

    pending = None      # (valor, tipo, texto) a la espera de su pareja
    for line in text.splitlines():
        m = _SIGNED_LINE_RE.match(line)
        if m:
            flush_gap()
            items.append({"tipo": "vertice", "lat": _f(m.group("lat")), "lon": _f(m.group("lon")),
                          "texto": line.strip()})
            n_vert += 1
            continue
        last_end = 0
        for mm in _HALF_RE.finditer(line):
            try:
                val, kind = parse_half(mm)
            except AipParseError as exc:
                items.append({"tipo": "error", "texto": str(exc)})
                last_end = mm.end()
                continue
            between = line[last_end:mm.start()]
            if pending is not None and pending[1] != kind:
                flush_gap()
                lat, lon = (pending[0], val) if pending[1] == "lat" else (val, pending[0])
                items.append({"tipo": "vertice", "lat": lat, "lon": lon,
                              "texto": " ".join((pending[2] + between + mm.group(0)).split())})
                n_vert += 1
                pending = None
            else:
                if pending is not None:
                    # dos latitudes seguidas: la anterior era parte de la descripción
                    gap_buf.append(pending[2])
                gap_buf.append(between)
                pending = (val, kind, mm.group(0))
            last_end = mm.end()
        if pending is not None:
            # queda a la espera de su pareja en la línea siguiente
            gap_buf.append(line[last_end:])
            continue
        gap_buf.append(line[last_end:])
    if pending is not None:
        gap_buf.append(pending[2])
        pending = None
    flush_gap()
    return items


def aip_to_feature(text, code, name=None, source=AIP_SOURCE, close=True):
    """GeoJSON Feature (Polygon) con los vértices del texto. Propiedades:
    id, name, fuente, oficial=True, verificado=False, n_vertices,
    tramos_pendientes (lista de {despues_del_vertice, texto}) y errores."""
    items = parse_aip_text(text)
    verts = [(it["lon"], it["lat"]) for it in items if it["tipo"] == "vertice"]
    if len(verts) < 3:
        raise AipParseError(f"se reconocieron {len(verts)} vértices; un polígono necesita al menos 3")
    ring = [[float(x), float(y)] for x, y in verts]
    if close and ring[0] != ring[-1]:
        ring.append(list(ring[0]))
    gaps = [{"despues_del_vertice": it["despues_de"], "texto": it["texto"]}
            for it in items if it["tipo"] == "tramo"]
    errors = [it["texto"] for it in items if it["tipo"] == "error"]
    code = (code or "").strip().upper()
    props = {
        "id": code,
        "name": name or FIR_NAMES.get(code, code),
        "fuente": source,
        "oficial": True,
        "verificado": False,
        "n_vertices": len(verts),
        "tramos_pendientes": gaps,
    }
    if errors:
        props["errores"] = errors
    return {"type": "Feature", "properties": props,
            "geometry": {"type": "Polygon", "coordinates": [ring]}}


def aip_to_geojson(text, code, name=None, source=AIP_SOURCE):
    """FeatureCollection con una sola FIR (lo que espera «Cargar archivo propio»)."""
    feat = aip_to_feature(text, code, name, source)
    return {"type": "FeatureCollection", "features": [feat],
            "_visor": {"fuente": source, "oficial": True,
                       "aviso": "Convertido del texto del AIP; revisar los tramos pendientes."}}


def report(feature):
    """Resumen legible de una feature convertida."""
    p = feature["properties"]
    lines = [f"FIR {p['id']} {p['name']}: {p['n_vertices']} vértices reconocidos."]
    gaps = p.get("tramos_pendientes") or []
    if gaps:
        lines.append(f"{len(gaps)} tramo(s) descriptos con palabras quedaron como rectas; completalos a mano:")
        for g in gaps:
            after = g["despues_del_vertice"]
            where = f"después del vértice {after + 1}" if after >= 0 else "antes del primer vértice"
            lines.append(f"  • {where}: «{g['texto']}»")
    else:
        lines.append("Sin tramos pendientes: todos los lados unen vértices con coordenadas.")
    for e in p.get("errores") or []:
        lines.append(f"  ! {e}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Convierte los vértices de una FIR del AIP (ENR 2.1) a GeoJSON.")
    ap.add_argument("entrada", help="archivo de texto con los vértices ('-' = entrada estándar)")
    ap.add_argument("--codigo", required=True, help="código OACI de la FIR (p. ej. SAVF)")
    ap.add_argument("--nombre", default=None, help="nombre de la FIR (por defecto, según el código)")
    ap.add_argument("-o", "--salida", default=None, help="archivo GeoJSON de salida (por defecto, pantalla)")
    args = ap.parse_args(argv)
    if args.entrada == "-":
        text = sys.stdin.read()
    else:
        with open(args.entrada, "r", encoding="utf-8") as fh:
            text = fh.read()
    try:
        obj = aip_to_geojson(text, args.codigo, args.nombre)
    except AipParseError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print(report(obj["features"][0]), file=sys.stderr)
    out = json.dumps(obj, ensure_ascii=False, indent=1)
    if args.salida:
        with open(args.salida, "w", encoding="utf-8") as fh:
            fh.write(out)
        print(f"Guardado en {args.salida}", file=sys.stderr)
    else:
        print(out)
    return 0


if __name__ == "__main__":      # pragma: no cover
    sys.exit(main())
