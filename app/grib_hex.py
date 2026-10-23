# -*- coding: utf-8 -*-
"""Estructura de un GRIB2 byte a byte, para el visor hexadecimal.

No usa ecCodes: lee las secciones 0 a 8 según el manual de la OMM (FM 92) y
arma un árbol de nodos, cada uno con su posición y tamaño en el archivo:

    mensaje → sección → campo (→ subcampo: bits de una bandera, derivados)

* ``scan_messages(data)``: [(offset, tamaño)] de cada mensaje (rápido, sólo
  lee la longitud total de la sección 0).
* ``parse_message(data, offset)``: el árbol de un mensaje.
* ``find_at(node, pos)``: el nodo más profundo que contiene esa posición.

Las plantillas desarrolladas son las que usan el GFS, el WAFS y el visor:
grilla 3.0 (lat/lon regular), producto 4.0 y 4.8, empaquetado 5.0 (simple),
5.2/5.3 (complejo), 5.4 (IEEE), 5.40 (JPEG 2000) y 5.41 (PNG). Con otra
plantilla se muestran los campos comunes y el resto como bytes.
"""
import struct

# ── Tablas de código (las entradas que aparecen en los archivos que se usan) ─

DISCIPLINE = {0: "productos meteorológicos", 1: "productos hidrológicos",
              2: "productos de superficie terrestre", 3: "productos satelitales",
              4: "productos de meteorología espacial", 10: "productos oceanográficos",
              255: "faltante"}

# Tabla común C-11 (centros generadores)
CENTRE = {0: "Secretaría de la OMM", 7: "NCEP (kwbc), Washington", 8: "NWS Telecommunications Gateway",
          9: "NWS, otros", 34: "Tokio (JMA)", 41: "Buenos Aires (SMN)", 46: "Brasilia (INPE/CPTEC)",
          54: "Montreal (CMC)", 57: "US Air Force (AFWA)", 58: "FNMOC, Monterey", 59: "NOAA FSL",
          60: "NCAR", 74: "Exeter (Met Office)", 78: "Offenbach (DWD)", 80: "Roma (CNMCA)",
          82: "Norrköping (SMHI)", 84: "Toulouse (Météo-France)", 85: "Toulouse (Météo-France)",
          86: "Helsinki (FMI)", 94: "Copenhague (DMI)", 97: "ESA", 98: "ECMWF, Reading",
          99: "De Bilt (KNMI)", 161: "NOAA OAR", 173: "NASA", 195: "Wisconsin (CIMSS)",
          255: "no usar", 65535: "faltante"}

SIGNIFICANCE_OF_RT = {0: "análisis", 1: "inicio del pronóstico", 2: "hora de validez",
                      3: "hora de la observación", 255: "faltante"}
PRODUCTION_STATUS = {0: "operativo", 1: "prueba operativa", 2: "investigación",
                     3: "reanálisis", 4: "TIGGE", 5: "prueba TIGGE", 6: "S2S", 7: "prueba S2S",
                     8: "UERRA", 9: "prueba UERRA", 255: "faltante"}
TYPE_OF_DATA = {0: "análisis", 1: "pronóstico", 2: "análisis y pronóstico",
                3: "pronóstico de control", 4: "pronóstico perturbado",
                5: "pronóstico de control y perturbado", 6: "observaciones procesadas",
                7: "observaciones satelitales procesadas", 8: "observaciones de radar procesadas",
                9: "pronóstico probabilístico", 10: "error del pronóstico", 11: "clase cuantil",
                255: "faltante"}
SOURCE_OF_GRID = {0: "plantilla de grilla", 1: "predeterminada del centro", 255: "sin grilla"}
GRID_TEMPLATE = {0: "lat/lon regular", 1: "lat/lon rotada", 10: "Mercator",
                 20: "polar estereográfica", 30: "Lambert conforme", 40: "gaussiana",
                 90: "vista espacial", 65535: "faltante"}
SHAPE_OF_EARTH = {0: "esfera, radio 6 367 470 m", 1: "esfera, radio especificado",
                  2: "elipsoide IAU 1965", 3: "elipsoide, ejes especificados (km)",
                  4: "elipsoide GRS80", 5: "WGS 84", 6: "esfera, radio 6 371 229 m",
                  7: "elipsoide, ejes especificados (m)", 8: "esfera 6 371 200 m (WGS 84)",
                  9: "Airy 1830 (OSGB)", 255: "faltante"}
PRODUCT_TEMPLATE = {0: "análisis o pronóstico en un instante", 1: "ensamble en un instante",
                    2: "derivado del ensamble en un instante", 5: "probabilidad en un instante",
                    6: "percentil en un instante", 7: "error del análisis",
                    8: "estadístico en un intervalo", 9: "probabilidad en un intervalo",
                    10: "percentil en un intervalo", 11: "ensamble en un intervalo",
                    12: "derivado del ensamble en un intervalo", 15: "promedio espacial",
                    20: "radar", 30: "satélite", 31: "satélite", 32: "satélite simulado",
                    48: "aerosol óptico", 65535: "faltante"}
PARAMETER = {  # (disciplina, categoría, número): (abreviatura, nombre, unidad)
    (0, 0, 0): ("TMP", "Temperatura", "K"), (0, 0, 1): ("VTMP", "Temperatura virtual", "K"),
    (0, 0, 2): ("POT", "Temperatura potencial", "K"), (0, 0, 6): ("DPT", "Punto de rocío", "K"),
    (0, 1, 0): ("SPFH", "Humedad específica", "kg/kg"), (0, 1, 1): ("RH", "Humedad relativa", "%"),
    (0, 1, 7): ("PRATE", "Tasa de precipitación", "kg/m²/s"),
    (0, 1, 8): ("APCP", "Precipitación total", "kg/m²"),
    (0, 2, 0): ("WDIR", "Dirección del viento", "° (de donde sopla)"),
    (0, 2, 1): ("WIND", "Velocidad del viento", "m/s"),
    (0, 2, 2): ("UGRD", "Componente U del viento", "m/s"),
    (0, 2, 3): ("VGRD", "Componente V del viento", "m/s"),
    (0, 2, 8): ("VVEL", "Velocidad vertical (presión)", "Pa/s"),
    (0, 2, 9): ("DZDT", "Velocidad vertical (geométrica)", "m/s"),
    (0, 2, 10): ("ABSV", "Vorticidad absoluta", "1/s"),
    (0, 2, 22): ("GUST", "Ráfaga", "m/s"),
    (0, 3, 0): ("PRES", "Presión", "Pa"), (0, 3, 1): ("PRMSL", "Presión al nivel del mar", "Pa"),
    (0, 3, 5): ("HGT", "Altura geopotencial", "gpm"),
    (0, 6, 1): ("TCDC", "Nubosidad total", "%"),
    (0, 7, 6): ("CAPE", "Energía convectiva disponible", "J/kg"),
    (0, 19, 0): ("VIS", "Visibilidad", "m"), (0, 19, 11): ("TKE", "Energía cinética turbulenta", "J/kg"),
    (0, 19, 20): ("ICIP", "Potencial de engelamiento", "%"),
    (0, 19, 22): ("CAT", "Turbulencia en aire claro", "%"),
    (0, 19, 29): ("EDPARM", "Tasa de disipación turbulenta", "m²/³/s"),
}
GENERATING_PROCESS = {0: "análisis", 1: "inicialización", 2: "pronóstico",
                      3: "pronóstico con corrección de sesgo", 4: "pronóstico de ensamble",
                      5: "pronóstico probabilístico", 6: "error del pronóstico",
                      7: "error del análisis", 8: "observación", 9: "climatológico",
                      10: "pronóstico probabilístico ponderado", 11: "ensamble con corrección",
                      12: "pos-procesado", 13: "nowcast", 14: "hindcast", 255: "faltante"}
TIME_UNIT = {0: "minuto", 1: "hora", 2: "día", 3: "mes", 4: "año", 5: "década",
             6: "30 años", 7: "siglo", 10: "3 horas", 11: "6 horas", 12: "12 horas",
             13: "segundo", 255: "faltante"}
FIXED_SURFACE = {1: "superficie del suelo o del agua", 2: "base de las nubes", 3: "tope de las nubes",
                 4: "isoterma de 0 °C", 5: "nivel de condensación adiabática", 6: "máximo viento",
                 7: "tropopausa", 8: "tope de la atmósfera", 100: "capa isobárica", 101: "nivel medio del mar",
                 102: "altitud sobre el nivel del mar", 103: "altura sobre el suelo",
                 104: "nivel sigma", 105: "nivel híbrido", 106: "profundidad bajo el suelo",
                 108: "nivel de presión sobre el suelo", 109: "superficie de vorticidad potencial",
                 200: "columna atmosférica total", 220: "capa límite planetaria", 255: "faltante"}
STATISTICAL_PROCESS = {0: "promedio", 1: "acumulación", 2: "máximo", 3: "mínimo",
                       4: "diferencia (fin − inicio)", 5: "raíz cuadrática media",
                       6: "desviación estándar", 7: "covarianza", 8: "diferencia (inicio − fin)",
                       9: "cociente", 255: "faltante"}
PACKING_TEMPLATE = {0: "simple", 1: "matriz de valores", 2: "compleja",
                    3: "compleja con diferencias espaciales", 4: "IEEE (coma flotante)",
                    40: "JPEG 2000", 41: "PNG", 42: "CCSDS", 50: "espectral simple",
                    51: "espectral compleja", 61: "logarítmica", 65535: "faltante"}
ORIGINAL_FIELD = {0: "coma flotante", 1: "enteros", 255: "faltante"}
BITMAP = {0: "mapa de bits incluido", 254: "mapa de bits del mensaje anterior",
          255: "sin mapa de bits (todos los puntos con dato)"}
IEEE_PRECISION = {1: "IEEE 32 bits", 2: "IEEE 64 bits", 3: "IEEE 128 bits"}

SECTION_NAMES = {0: "Indicador", 1: "Identificación", 2: "Uso local", 3: "Definición de la grilla",
                 4: "Definición del producto", 5: "Representación de los datos",
                 6: "Mapa de bits", 7: "Datos", 8: "Fin"}

_MISSING = {1: 0xFF, 2: 0xFFFF, 4: 0xFFFFFFFF}


class Node:
    """Un tramo del archivo con nombre: mensaje, sección, campo o subcampo.
    `value` es el valor crudo (entero, float, bytes o None) y `text` su
    interpretación para mostrar."""
    __slots__ = ("name", "offset", "size", "value", "text", "kind", "children", "parent", "meta")

    def __init__(self, name, offset, size, value=None, text="", kind="field", children=None, meta=None):
        self.name = name
        self.offset = int(offset)
        self.size = int(size)
        self.value = value
        self.text = text
        self.kind = kind            # message · section · field · data · row · cell
        self.children = children or []
        self.parent = None
        self.meta = meta            # 'data': cómo decodificar las celdas; 'row'/'cell': su índice
        for c in self.children:
            c.parent = self

    @property
    def end(self):
        return self.offset + self.size

    def add(self, node):
        node.parent = self
        self.children.append(node)
        return node

    def contains(self, pos):
        return self.offset <= pos < self.end

    def __repr__(self):
        return f"Node({self.name!r}, {self.offset}, {self.size}, {self.text!r})"


# ── Lectura de enteros GRIB2 ───────────────────────────────────────────────

def _uint(b):
    return int.from_bytes(b, "big")


def _sint(b):
    """Entero con signo GRIB2: el bit más alto es el signo (no complemento a 2)."""
    v = int.from_bytes(b, "big")
    top = 1 << (8 * len(b) - 1)
    return -(v & (top - 1)) if v & top else v


def _missing(b):
    return all(x == 0xFF for x in b)


def _scaled(factor, value):
    """valor × 10^−factor (ambos campos GRIB2 escalados)."""
    return value * (10.0 ** -factor)


def _fmt_deg(micro):
    return f"{micro / 1e6:.6f}°"


# ── Mensajes ──────────────────────────────────────────────────────────────

def scan_messages(data, limit=None):
    """[(offset, tamaño)] de cada mensaje GRIB2 del archivo. Se detiene en el
    primer tramo que no empieza por «GRIB» (o en `limit` mensajes)."""
    out = []
    pos = 0
    n = len(data)
    while pos + 16 <= n:
        if bytes(data[pos:pos + 4]) != b"GRIB":
            break
        if data[pos + 7] != 2:
            # Edición 1: longitud en 3 bytes
            size = _uint(data[pos + 4:pos + 7])
        else:
            size = _uint(data[pos + 8:pos + 16])
        if size <= 0 or pos + size > n:
            size = n - pos
        out.append((pos, size))
        pos += size
        if limit is not None and len(out) >= limit:
            break
    return out


def parse_message(data, offset, index=None, total=None):
    """Árbol de un mensaje que empieza en `offset`: nodo «mensaje» con un hijo
    por sección y, en cada sección, sus campos."""
    data = memoryview(data)
    off = offset
    n = len(data)
    if bytes(data[off:off + 4]) != b"GRIB":
        raise ValueError(f"no hay un mensaje GRIB en la posición {offset}")
    edition = data[off + 7]
    if edition != 2:
        size = _uint(data[off + 4:off + 7])
        msg = Node(_msg_name(index, total), off, size, kind="message",
                   text=f"GRIB edición {edition}: el visor sólo desarrolla la edición 2")
        msg.add(Node("GRIB", off, 4, bytes(data[off:off + 4]), "indicador"))
        msg.add(Node("Longitud total", off + 4, 3, size, f"{size} bytes"))
        msg.add(Node("Edición", off + 7, 1, edition, str(edition)))
        return msg
    size = _uint(data[off + 8:off + 16])
    if size <= 0 or off + size > n:
        size = n - off
    msg = Node(_msg_name(index, total), off, size, kind="message")
    sec0 = _section0(data, off)
    msg.add(sec0)
    pos = off + 16
    end = off + size
    ctx = {"discipline": data[off + 6], "sec5": None, "sec3": None}
    while pos + 4 <= end:
        if bytes(data[pos:pos + 4]) == b"7777":
            msg.add(Node("Sección 8 · Fin", pos, 4, b"7777", "«7777»", kind="section",
                         children=[Node("Marca de fin", pos, 4, b"7777", "«7777»")]))
            pos += 4
            break
        if pos + 5 > end:
            break
        length = _uint(data[pos:pos + 4])
        number = data[pos + 4]
        if length < 5 or pos + length > end:
            msg.add(Node(f"Sección {number} (truncada)", pos, end - pos, None,
                         f"longitud declarada {length} bytes", kind="section"))
            pos = end
            break
        sec = _parse_section(data, pos, length, number, ctx)
        msg.add(sec)
        pos += length
    if pos < end:
        msg.add(Node("Bytes sobrantes", pos, end - pos, None, f"{end - pos} bytes", kind="section"))
    msg.text = _summary(msg)
    return msg


def _msg_name(index, total):
    if index is None:
        return "Mensaje"
    if total:
        return f"Mensaje {index + 1} de {total}"
    return f"Mensaje {index + 1}"


def _summary(msg):
    """«TMP · 850 hPa · +6 h» a partir de lo ya decodificado."""
    parts = []
    for sec in msg.children:
        if sec.name.startswith("Sección 4"):
            for f in sec.children:
                if f.name == "Parámetro" and f.text:
                    parts.append(f.text.split(" ·")[0])
                elif f.name == "Primera superficie" and f.text:
                    parts.append(f.text)
                elif f.name == "Plazo" and f.text:
                    parts.append(f.text)
    return " · ".join(parts)


def _section0(data, off):
    disc = data[off + 6]
    ed = data[off + 7]
    size = _uint(data[off + 8:off + 16])
    sec = Node("Sección 0 · Indicador", off, 16, kind="section", text=f"{size} bytes")
    sec.add(Node("«GRIB»", off, 4, bytes(data[off:off + 4]), "identificador del mensaje"))
    sec.add(Node("Reservado", off + 4, 2, _uint(data[off + 4:off + 6]), ""))
    sec.add(Node("Disciplina", off + 6, 1, disc, f"{disc} = {DISCIPLINE.get(disc, '?')}"))
    sec.add(Node("Edición", off + 7, 1, ed, str(ed)))
    sec.add(Node("Longitud total del mensaje", off + 8, 8, size, f"{size} bytes"))
    return sec


def _parse_section(data, pos, length, number, ctx):
    name = f"Sección {number} · {SECTION_NAMES.get(number, 'desconocida')}"
    sec = Node(name, pos, length, kind="section", text=f"{length} bytes")
    sec.add(Node("Longitud de la sección", pos, 4, length, f"{length} bytes"))
    sec.add(Node("Número de sección", pos + 4, 1, number, str(number)))
    fn = {1: _section1, 2: _section2, 3: _section3, 4: _section4, 5: _section5,
          6: _section6, 7: _section7}.get(number)
    if fn is None:
        sec.add(Node("Contenido", pos + 5, length - 5, None, f"{length - 5} bytes"))
    else:
        fn(data, pos, length, sec, ctx)
    return sec


def _section1(data, pos, length, sec, ctx):
    p = pos
    centre = _uint(data[p + 5:p + 7])
    sub = _uint(data[p + 7:p + 9])
    sec.add(Node("Centro generador", p + 5, 2, centre, f"{centre} = {CENTRE.get(centre, 'sin nombre en la tabla C-11')}"))
    sec.add(Node("Subcentro", p + 7, 2, sub, f"{sub}" + (" (ninguno)" if sub == 0 else "")))
    tv = data[p + 9]
    sec.add(Node("Versión de las tablas maestras", p + 9, 1, tv, str(tv)))
    lv = data[p + 10]
    sec.add(Node("Versión de las tablas locales", p + 10, 1, lv, str(lv) + (" (no se usan)" if lv == 0 else "")))
    sig = data[p + 11]
    sec.add(Node("Significado de la hora de referencia", p + 11, 1, sig, f"{sig} = {SIGNIFICANCE_OF_RT.get(sig, '?')}"))
    y = _uint(data[p + 12:p + 14])
    mo, d, h, mi, s = data[p + 14], data[p + 15], data[p + 16], data[p + 17], data[p + 18]
    ref = Node("Hora de referencia", p + 12, 7, None, f"{y:04d}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}:{s:02d} UTC")
    ref.add(Node("Año", p + 12, 2, y, str(y)))
    ref.add(Node("Mes", p + 14, 1, mo, str(mo)))
    ref.add(Node("Día", p + 15, 1, d, str(d)))
    ref.add(Node("Hora", p + 16, 1, h, str(h)))
    ref.add(Node("Minuto", p + 17, 1, mi, str(mi)))
    ref.add(Node("Segundo", p + 18, 1, s, str(s)))
    sec.add(ref)
    ps = data[p + 19]
    sec.add(Node("Estado de producción", p + 19, 1, ps, f"{ps} = {PRODUCTION_STATUS.get(ps, '?')}"))
    td = data[p + 20]
    sec.add(Node("Tipo de datos procesados", p + 20, 1, td, f"{td} = {TYPE_OF_DATA.get(td, '?')}"))
    if length > 21:
        sec.add(Node("Reservado", p + 21, length - 21, None, f"{length - 21} bytes"))


def _section2(data, pos, length, sec, ctx):
    sec.add(Node("Datos de uso local", pos + 5, length - 5, None,
                 f"{length - 5} bytes definidos por el centro generador"))


def _section3(data, pos, length, sec, ctx):
    p = pos
    src = data[p + 5]
    sec.add(Node("Origen de la definición", p + 5, 1, src, f"{src} = {SOURCE_OF_GRID.get(src, '?')}"))
    npts = _uint(data[p + 6:p + 10])
    sec.add(Node("Número de puntos", p + 6, 4, npts, f"{npts} puntos"))
    nopt = data[p + 10]
    sec.add(Node("Octetos por entrada de la lista opcional", p + 10, 1, nopt, str(nopt) + (" (sin lista)" if nopt == 0 else "")))
    interp = data[p + 11]
    sec.add(Node("Interpretación de la lista", p + 11, 1, interp, str(interp) + (" (sin lista)" if interp == 0 else "")))
    tmpl = _uint(data[p + 12:p + 14])
    sec.add(Node("Plantilla de grilla", p + 12, 2, tmpl, f"3.{tmpl} = {GRID_TEMPLATE.get(tmpl, 'no desarrollada')}"))
    ctx["sec3"] = {"template": tmpl, "npts": npts}
    if tmpl == 0 and length >= 72:
        _grid_latlon(data, p, sec, ctx)
        rest = p + 72
    else:
        rest = p + 14
    if length > rest - p:
        sec.add(Node("Resto de la plantilla / lista opcional", rest, p + length - rest, None,
                     f"{p + length - rest} bytes"))


def _grid_latlon(data, p, sec, ctx):
    shape = data[p + 14]
    sec.add(Node("Forma de la Tierra", p + 14, 1, shape, f"{shape} = {SHAPE_OF_EARTH.get(shape, '?')}"))
    sec.add(_scaled_pair("Radio de la esfera", data, p + 15, "m"))
    sec.add(_scaled_pair("Eje mayor", data, p + 20, "m"))
    sec.add(_scaled_pair("Eje menor", data, p + 25, "m"))
    ni = _uint(data[p + 30:p + 34])
    nj = _uint(data[p + 34:p + 38])
    sec.add(Node("Ni (puntos a lo largo de un paralelo)", p + 30, 4, ni, str(ni)))
    sec.add(Node("Nj (puntos a lo largo de un meridiano)", p + 34, 4, nj, str(nj)))
    ba = _uint(data[p + 38:p + 42])
    sd = _uint(data[p + 42:p + 46])
    sec.add(Node("Ángulo básico", p + 38, 4, ba, str(ba) + (" (coordenadas en millonésimas de grado)" if ba == 0 else "")))
    sec.add(Node("Subdivisiones del ángulo básico", p + 42, 4, sd, str(sd) + (" (faltante)" if sd == 0xFFFFFFFF else "")))
    la1 = _sint(data[p + 46:p + 50])
    lo1 = _sint(data[p + 50:p + 54])
    sec.add(Node("La1 (latitud del primer punto)", p + 46, 4, la1, f"{la1} = {_fmt_deg(la1)}"))
    sec.add(Node("Lo1 (longitud del primer punto)", p + 50, 4, lo1, f"{lo1} = {_fmt_deg(lo1)}"))
    flags = data[p + 54]
    fl = Node("Resolución y componentes", p + 54, 1, flags, f"0b{flags:08b}")
    fl.add(Node("bit 3: incrementos i dados", p + 54, 1, (flags >> 5) & 1, "sí" if flags & 0x20 else "no"))
    fl.add(Node("bit 4: incrementos j dados", p + 54, 1, (flags >> 4) & 1, "sí" if flags & 0x10 else "no"))
    fl.add(Node("bit 5: viento relativo a la grilla", p + 54, 1, (flags >> 3) & 1,
                "U y V relativos a los ejes de la grilla" if flags & 0x08 else "U hacia el este, V hacia el norte"))
    sec.add(fl)
    la2 = _sint(data[p + 55:p + 59])
    lo2 = _sint(data[p + 59:p + 63])
    sec.add(Node("La2 (latitud del último punto)", p + 55, 4, la2, f"{la2} = {_fmt_deg(la2)}"))
    sec.add(Node("Lo2 (longitud del último punto)", p + 59, 4, lo2, f"{lo2} = {_fmt_deg(lo2)}"))
    di = _uint(data[p + 63:p + 67])
    dj = _uint(data[p + 67:p + 71])
    sec.add(Node("Di (incremento en longitud)", p + 63, 4, di, f"{di} = {_fmt_deg(di)}"))
    sec.add(Node("Dj (incremento en latitud)", p + 67, 4, dj, f"{dj} = {_fmt_deg(dj)}"))
    sm = data[p + 71]
    scan = Node("Modo de barrido", p + 71, 1, sm, f"0b{sm:08b}")
    scan.add(Node("bit 1: dirección i", p + 71, 1, (sm >> 7) & 1, "−i (oeste)" if sm & 0x80 else "+i (este)"))
    scan.add(Node("bit 2: dirección j", p + 71, 1, (sm >> 6) & 1, "+j (sur a norte)" if sm & 0x40 else "−j (norte a sur)"))
    scan.add(Node("bit 3: orden", p + 71, 1, (sm >> 5) & 1, "consecutivos en j" if sm & 0x20 else "consecutivos en i"))
    scan.add(Node("bit 4: filas alternadas", p + 71, 1, (sm >> 4) & 1, "sí (bustrofedón)" if sm & 0x10 else "no"))
    sec.add(scan)
    ctx["sec3"].update({"ni": ni, "nj": nj, "la1": la1, "lo1": lo1, "di": di, "dj": dj, "scan": sm})


def _scaled_pair(name, data, p, unit):
    f = data[p]
    v = _uint(data[p + 1:p + 5])
    if f == 0xFF or v == 0xFFFFFFFF:
        txt = "faltante"
    else:
        txt = f"{_scaled(_sint(data[p:p + 1]), v):g} {unit}"
    n = Node(name, p, 5, None, txt)
    n.add(Node("Factor de escala", p, 1, f, "faltante" if f == 0xFF else str(_sint(data[p:p + 1]))))
    n.add(Node("Valor escalado", p + 1, 4, v, "faltante" if v == 0xFFFFFFFF else str(v)))
    return n


def _section4(data, pos, length, sec, ctx):
    p = pos
    nv = _uint(data[p + 5:p + 7])
    sec.add(Node("Número de coordenadas verticales (NV)", p + 5, 2, nv, str(nv)))
    tmpl = _uint(data[p + 7:p + 9])
    sec.add(Node("Plantilla de producto", p + 7, 2, tmpl, f"4.{tmpl} = {PRODUCT_TEMPLATE.get(tmpl, 'no desarrollada')}"))
    rest = p + 9
    if tmpl in (0, 1, 2, 5, 6, 7, 8, 9, 10, 11, 12, 15, 48) and length >= 34:
        _product_common(data, p, sec, ctx)
        rest = p + 34
        if tmpl == 8 and length >= 58:
            _product_statistical(data, p + 34, sec)
            rest = p + 58
        elif tmpl == 1 and length >= 37:
            sec.add(Node("Tipo de pronóstico de ensamble", p + 34, 1, data[p + 34], str(data[p + 34])))
            sec.add(Node("Número de perturbación", p + 35, 1, data[p + 35], str(data[p + 35])))
            sec.add(Node("Miembros del ensamble", p + 36, 1, data[p + 36], str(data[p + 36])))
            rest = p + 37
    if length > rest - p:
        sec.add(Node("Resto de la plantilla", rest, p + length - rest, None, f"{p + length - rest} bytes"))


def _product_common(data, p, sec, ctx):
    disc = ctx.get("discipline", 0)
    cat = data[p + 9]
    num = data[p + 10]
    par = PARAMETER.get((disc, cat, num))
    txt = f"{par[0]} · {par[1]} ({par[2]})" if par else f"categoría {cat}, número {num}"
    par_node = Node("Parámetro", p + 9, 2, (cat, num), txt)
    par_node.add(Node("Categoría", p + 9, 1, cat, str(cat)))
    par_node.add(Node("Número", p + 10, 1, num, str(num)))
    sec.add(par_node)
    gp = data[p + 11]
    sec.add(Node("Tipo de proceso generador", p + 11, 1, gp, f"{gp} = {GENERATING_PROCESS.get(gp, '?')}"))
    sec.add(Node("Proceso de fondo", p + 12, 1, data[p + 12], str(data[p + 12]) + (" (faltante)" if data[p + 12] == 0xFF else "")))
    sec.add(Node("Identificador del proceso (modelo)", p + 13, 1, data[p + 13], str(data[p + 13]) + (" (faltante)" if data[p + 13] == 0xFF else "")))
    hc = _uint(data[p + 14:p + 16])
    sec.add(Node("Horas tras el corte de datos", p + 14, 2, hc, "faltante" if hc == 0xFFFF else str(hc)))
    sec.add(Node("Minutos tras el corte de datos", p + 16, 1, data[p + 16], "faltante" if data[p + 16] == 0xFF else str(data[p + 16])))
    tu = data[p + 17]
    ft = _sint(data[p + 18:p + 22])
    unit = TIME_UNIT.get(tu, "?")
    sec.add(Node("Unidad del plazo", p + 17, 1, tu, f"{tu} = {unit}"))
    sec.add(Node("Plazo", p + 18, 4, ft, f"+{ft} {unit}{'s' if ft != 1 and unit in ('hora', 'minuto', 'día') else ''}"))
    sec.add(_surface("Primera superficie", data, p + 22))
    sec.add(_surface("Segunda superficie", data, p + 28))


def _surface(name, data, p):
    t = data[p]
    f_raw = data[p + 1]
    v_raw = _uint(data[p + 2:p + 6])
    kind = FIXED_SURFACE.get(t, "?")
    if t == 0xFF or (f_raw == 0xFF and v_raw == 0xFFFFFFFF):
        txt = "ninguna" if t == 0xFF else f"{t} = {kind}"
        val_txt = "faltante"
    else:
        f = _sint(data[p + 1:p + 2])
        v = _sint(data[p + 2:p + 6])
        val = _scaled(f, v)
        if t == 100:
            txt = f"{val:g} Pa = {val / 100.0:g} hPa"
        elif t in (102, 103, 106):
            txt = f"{val:g} m"
        else:
            txt = f"{val:g}" if (f or v) else ""
        if txt:
            txt = f"{kind}: {txt}" if t != 100 else f"capa {txt}"
        else:
            txt = kind
        val_txt = f"{v} × 10^−{f} = {val:g}" if f else str(v)
    n = Node(name, p, 6, t, txt)
    n.add(Node("Tipo", p, 1, t, f"{t} = {kind}" if t != 0xFF else "255 = ninguna"))
    n.add(Node("Factor de escala", p + 1, 1, f_raw, "faltante" if f_raw == 0xFF else str(_sint(data[p + 1:p + 2]))))
    n.add(Node("Valor escalado", p + 2, 4, v_raw, val_txt))
    return n


def _product_statistical(data, p, sec):
    y = _uint(data[p:p + 2])
    txt = f"{y:04d}-{data[p + 2]:02d}-{data[p + 3]:02d} {data[p + 4]:02d}:{data[p + 5]:02d}:{data[p + 6]:02d} UTC"
    sec.add(Node("Fin del intervalo", p, 7, None, txt))
    sec.add(Node("Número de intervalos", p + 7, 1, data[p + 7], str(data[p + 7])))
    sec.add(Node("Puntos faltantes en el estadístico", p + 8, 4, _uint(data[p + 8:p + 12]), str(_uint(data[p + 8:p + 12]))))
    sp = data[p + 12]
    sec.add(Node("Proceso estadístico", p + 12, 1, sp, f"{sp} = {STATISTICAL_PROCESS.get(sp, '?')}"))
    sec.add(Node("Tipo de incremento", p + 13, 1, data[p + 13], str(data[p + 13])))
    tu = data[p + 14]
    sec.add(Node("Unidad del intervalo", p + 14, 1, tu, f"{tu} = {TIME_UNIT.get(tu, '?')}"))
    ln = _uint(data[p + 15:p + 19])
    sec.add(Node("Longitud del intervalo", p + 15, 4, ln, f"{ln} {TIME_UNIT.get(tu, '')}(s)"))
    tu2 = data[p + 19]
    sec.add(Node("Unidad del incremento", p + 19, 1, tu2, f"{tu2} = {TIME_UNIT.get(tu2, '?')}"))
    inc = _uint(data[p + 20:p + 24])
    sec.add(Node("Incremento", p + 20, 4, inc, str(inc)))


def _section5(data, pos, length, sec, ctx):
    p = pos
    nvals = _uint(data[p + 5:p + 9])
    sec.add(Node("Número de valores empaquetados", p + 5, 4, nvals, str(nvals)))
    tmpl = _uint(data[p + 9:p + 11])
    sec.add(Node("Plantilla de empaquetado", p + 9, 2, tmpl, f"5.{tmpl} = {PACKING_TEMPLATE.get(tmpl, 'no desarrollada')}"))
    info = {"template": tmpl, "nvals": nvals}
    rest = p + 11
    if tmpl in (0, 2, 3, 40, 41, 42) and length >= 21:
        R = struct.unpack(">f", bytes(data[p + 11:p + 15]))[0]
        E = _sint(data[p + 15:p + 17])
        D = _sint(data[p + 17:p + 19])
        bits = data[p + 19]
        orig = data[p + 20]
        sec.add(Node("Valor de referencia R", p + 11, 4, R, f"{R!r} (IEEE 32 bits)"))
        sec.add(Node("Factor de escala binaria E", p + 15, 2, E, f"{E} → ×2^{E}"))
        sec.add(Node("Factor de escala decimal D", p + 17, 2, D, f"{D} → ÷10^{D}"))
        sec.add(Node("Bits por valor", p + 19, 1, bits, f"{bits}" + (" (campo constante: todos los puntos valen R)" if bits == 0 else "")))
        sec.add(Node("Tipo de los valores originales", p + 20, 1, orig, f"{orig} = {ORIGINAL_FIELD.get(orig, '?')}"))
        info.update({"R": R, "E": E, "D": D, "bits": bits})
        rest = p + 21
        if tmpl in (2, 3) and length >= 47:
            sec.add(Node("Método de división en grupos", p + 21, 1, data[p + 21], str(data[p + 21])))
            sec.add(Node("Gestión de valores faltantes", p + 22, 1, data[p + 22], str(data[p + 22])))
            sec.add(Node("Valor faltante primario", p + 23, 4, _uint(data[p + 23:p + 27]), str(_uint(data[p + 23:p + 27]))))
            sec.add(Node("Valor faltante secundario", p + 27, 4, _uint(data[p + 27:p + 31]), str(_uint(data[p + 27:p + 31]))))
            ng = _uint(data[p + 31:p + 35])
            sec.add(Node("Número de grupos", p + 31, 4, ng, str(ng)))
            sec.add(Node("Referencia de los anchos de grupo", p + 35, 1, data[p + 35], str(data[p + 35])))
            sec.add(Node("Bits de los anchos de grupo", p + 36, 1, data[p + 36], str(data[p + 36])))
            sec.add(Node("Referencia de las longitudes de grupo", p + 37, 4, _uint(data[p + 37:p + 41]), str(_uint(data[p + 37:p + 41]))))
            sec.add(Node("Incremento de longitud", p + 41, 1, data[p + 41], str(data[p + 41])))
            sec.add(Node("Longitud real del último grupo", p + 42, 4, _uint(data[p + 42:p + 46]), str(_uint(data[p + 42:p + 46]))))
            sec.add(Node("Bits de las longitudes de grupo", p + 46, 1, data[p + 46], str(data[p + 46])))
            rest = p + 47
            if tmpl == 3 and length >= 49:
                sec.add(Node("Orden de las diferencias espaciales", p + 47, 1, data[p + 47], str(data[p + 47])))
                sec.add(Node("Octetos de los descriptores extra", p + 48, 1, data[p + 48], str(data[p + 48])))
                rest = p + 49
        elif tmpl == 40 and length >= 23:
            sec.add(Node("Tipo de compresión", p + 21, 1, data[p + 21], "sin pérdida" if data[p + 21] == 0 else f"{data[p + 21]} = con pérdida"))
            sec.add(Node("Relación de compresión objetivo", p + 22, 1, data[p + 22], "faltante" if data[p + 22] == 0xFF else f"{data[p + 22]}:1"))
            rest = p + 23
    elif tmpl == 4 and length >= 12:
        prec = data[p + 11]
        sec.add(Node("Precisión", p + 11, 1, prec, f"{prec} = {IEEE_PRECISION.get(prec, '?')}"))
        info["precision"] = prec
        rest = p + 12
    ctx["sec5"] = info
    if length > rest - p:
        sec.add(Node("Resto de la plantilla", rest, p + length - rest, None, f"{p + length - rest} bytes"))


def _section6(data, pos, length, sec, ctx):
    ind = data[pos + 5]
    sec.add(Node("Indicador del mapa de bits", pos + 5, 1, ind, f"{ind} = {BITMAP.get(ind, 'predefinido por el centro')}"))
    ctx["sec6"] = {"bitmap": ind != 255}
    if length > 6:
        sec.add(Node("Mapa de bits", pos + 6, length - 6, None, f"{length - 6} bytes, un bit por punto"))


def _section7(data, pos, length, sec, ctx):
    n = length - 5
    s5 = ctx.get("sec5") or {}
    tmpl = s5.get("template")
    txt = f"{n} bytes"
    s3 = ctx.get("sec3") or {}
    meta = {"template": tmpl, "start": pos + 5, "size": n, "nvals": s5.get("nvals", 0),
            "bitmap": bool((ctx.get("sec6") or {}).get("bitmap"))}
    for k in ("R", "E", "D", "bits", "precision"):
        if k in s5:
            meta[k] = s5[k]
    for k in ("ni", "nj", "la1", "lo1", "di", "dj", "scan"):
        if k in s3:
            meta[k] = s3[k]
    node = Node("Datos empaquetados", pos + 5, n, None, txt, kind="data", meta=meta)
    if tmpl == 0 and "bits" in s5:
        vals = decode_simple(data[pos + 5:pos + length], s5["R"], s5["E"], s5["D"], s5["bits"],
                             min(s5.get("nvals", 0), 8))
        if s5["bits"] == 0:
            node.text = f"{n} bytes: campo constante, todos los puntos = R ÷ 10^D = {_fmt_val(vals[0]) if vals else '?'}"
        elif vals:
            more = "…" if s5.get("nvals", 0) > len(vals) else ""
            node.text = f"{n} bytes · primeros valores (R + X·2^E) ÷ 10^D: " + ", ".join(_fmt_val(v) for v in vals) + more
    elif tmpl == 4:
        vals = decode_ieee(data[pos + 5:pos + length], s5.get("precision", 1), 8)
        if vals:
            more = "…" if s5.get("nvals", 0) > len(vals) else ""
            node.text = f"{n} bytes · un valor IEEE por punto: " + ", ".join(_fmt_val(v) for v in vals) + more
    elif tmpl is not None:
        node.text = f"{n} bytes · plantilla 5.{tmpl} ({PACKING_TEMPLATE.get(tmpl, '?')}): se decodifica con ecCodes"
    sec.add(node)


def _fmt_val(v):
    return f"{v:.6g}"


def decode_simple(buf, R, E, D, bits, count):
    """Primeros `count` valores de un empaquetado simple: (R + X·2^E) ÷ 10^D."""
    buf = bytes(buf)
    if bits == 0:
        return [R / (10.0 ** D)]
    out = []
    total_bits = len(buf) * 8
    for i in range(count):
        start = i * bits
        if start + bits > total_bits:
            break
        x = 0
        for b in range(bits):
            bit = start + b
            x = (x << 1) | ((buf[bit >> 3] >> (7 - (bit & 7))) & 1)
        out.append((R + x * (2.0 ** E)) / (10.0 ** D))
    return out


def decode_ieee(buf, precision, count):
    buf = bytes(buf)
    fmt, size = {1: (">f", 4), 2: (">d", 8)}.get(precision, (None, 0))
    if fmt is None:
        return []
    n = min(count, len(buf) // size)
    return [struct.unpack(fmt, buf[i * size:(i + 1) * size])[0] for i in range(n)]


# ── Celdas de la sección 7 ────────────────────────────────────────────────
# Los valores no forman un árbol pero se listan por demanda: filas de la
# grilla (o tandas de 1024 valores si no hay grilla regular o hay mapa de
# bits) y, dentro de cada fila, una celda por valor con su tramo de bytes y
# su valor decodificado. Con empaquetado simple (5.0) e IEEE (5.4) cada
# celda tiene un tramo propio; con los demás (complejo, JPEG, PNG) los
# valores vienen en bloque: la celda abarca toda la sección y su valor sólo
# se conoce si el que llama lo aporta (decodificado con ecCodes).

CHUNK = 1024


def _grid_ok(meta):
    ni, nj = meta.get("ni"), meta.get("nj")
    return bool(ni and nj and ni * nj == meta.get("nvals") and not meta.get("bitmap"))


def cell_count(meta):
    return int(meta.get("nvals") or 0)


def cell_range(meta, k):
    """(offset, size) de los bytes del valor `k`; con empaquetado en bloque,
    toda la sección; con campo constante (0 bits), un tramo vacío."""
    start, size, tmpl = meta["start"], meta["size"], meta.get("template")
    if tmpl == 0 and "bits" in meta:
        bits = meta["bits"]
        if bits == 0:
            return start, 0
        b0 = k * bits
        b1 = b0 + bits - 1
        lo, hi = b0 >> 3, b1 >> 3
        if lo >= size:
            return start + size, 0
        return start + lo, min(hi, size - 1) - lo + 1
    if tmpl == 4:
        sz = 8 if meta.get("precision") == 2 else 4
        return start + k * sz, sz
    return start, size


def cell_at(meta, pos):
    """Índice del valor cuyos bytes contienen `pos`, o None si el
    empaquetado no asigna bytes a cada valor."""
    start, size, tmpl = meta["start"], meta["size"], meta.get("template")
    if pos < start or pos >= start + size:
        return None
    if tmpl == 0 and meta.get("bits"):
        return min(((pos - start) * 8) // meta["bits"], max(0, cell_count(meta) - 1))
    if tmpl == 4:
        sz = 8 if meta.get("precision") == 2 else 4
        return min((pos - start) // sz, max(0, cell_count(meta) - 1))
    return None


def cell_value(data, meta, k):
    """Valor decodificado del valor `k` (simple o IEEE), o None."""
    tmpl = meta.get("template")
    if tmpl == 0 and "bits" in meta:
        R, E, D, bits = meta["R"], meta["E"], meta["D"], meta["bits"]
        if bits == 0:
            return R / (10.0 ** D)
        off, size = cell_range(meta, k)
        if size == 0:
            return None
        chunk = int.from_bytes(bytes(data[off:off + size]), "big")
        shift = size * 8 - ((k * bits) & 7) - bits
        x = (chunk >> shift) & ((1 << bits) - 1)
        return (R + x * (2.0 ** E)) / (10.0 ** D)
    if tmpl == 4:
        off, size = cell_range(meta, k)
        if off + size > meta["start"] + meta["size"]:
            return None
        return struct.unpack(">d" if size == 8 else ">f", bytes(data[off:off + size]))[0]
    return None


def cell_grid(meta, k):
    """(j, i) del valor `k` en la grilla, o None si no hay grilla regular."""
    if not _grid_ok(meta):
        return None
    return divmod(int(k), int(meta["ni"]))


def cell_latlon(meta, j, i):
    """(lat, lon) en grados de la celda (j, i), según La1/Lo1, Di/Dj y el
    modo de barrido; lon en −180…180."""
    scan = meta.get("scan", 0)
    la1, lo1 = meta["la1"] / 1e6, meta["lo1"] / 1e6
    dj, di = meta["dj"] / 1e6, meta["di"] / 1e6
    lat = la1 + (j * dj if scan & 0x40 else -j * dj)
    lon = lo1 + (-i * di if scan & 0x80 else i * di)
    lon = ((lon + 180.0) % 360.0) - 180.0
    return lat, lon


def _fmt_latlon(lat, lon):
    return (f"{abs(lat):.3f}°{'S' if lat < 0 else 'N'} "
            f"{abs(lon):.3f}°{'W' if lon < 0 else 'E'}")


def _span(meta, k0, k1):
    """Tramo de bytes que cubre los valores k0…k1."""
    o0, s0 = cell_range(meta, k0)
    o1, s1 = cell_range(meta, k1)
    return o0, max(o1 + s1, o0 + s0) - o0


def data_rows(node):
    """Filas del nodo de datos: una por fila de la grilla (j), o tandas de
    CHUNK valores. No las cuelga del nodo: lo hace quien las muestra."""
    meta = node.meta or {}
    n = cell_count(meta)
    rows = []
    if _grid_ok(meta):
        ni, nj = meta["ni"], meta["nj"]
        for j in range(nj):
            k0, k1 = j * ni, j * ni + ni - 1
            off, size = _span(meta, k0, k1)
            lat, _lon = cell_latlon(meta, j, 0)
            rows.append(Node(f"Fila j={j} · lat {abs(lat):.3f}°{'S' if lat < 0 else 'N'}", off, size,
                             None, f"{ni} valores, i=0…{ni - 1}", kind="row",
                             meta={"row": j, "k0": k0, "count": ni}))
    else:
        for r, k0 in enumerate(range(0, n, CHUNK)):
            k1 = min(n, k0 + CHUNK) - 1
            off, size = _span(meta, k0, k1)
            rows.append(Node(f"Valores {k0}…{k1}", off, size, None, f"{k1 - k0 + 1} valores", kind="row",
                             meta={"row": r, "k0": k0, "count": k1 - k0 + 1}))
    return rows


def row_of(node, k):
    """Índice de la fila (en data_rows) que contiene el valor `k`."""
    meta = node.meta or {}
    if _grid_ok(meta):
        return int(k) // int(meta["ni"])
    return int(k) // CHUNK


def row_cells(data, node, row, values=None):
    """Celdas de una fila: nombre con la celda ([j, i] y lat/lon, o el índice
    del valor), tramo de bytes y valor decodificado. `values` (vector de
    valores en el orden del archivo, p. ej. de ecCodes) suple el valor
    cuando el empaquetado no se decodifica acá."""
    meta = node.meta or {}
    rm = row.meta or {}
    k0, count = rm["k0"], rm["count"]
    grid = _grid_ok(meta)
    block = meta.get("template") not in (0, 4)
    out = []
    for k in range(k0, k0 + count):
        off, size = cell_range(meta, k)
        v = cell_value(data, meta, k)
        if v is None and values is not None and k < len(values):
            v = float(values[k])
        if grid:
            j, i = divmod(k, meta["ni"])
            name = f"[{j}, {i}] {_fmt_latlon(*cell_latlon(meta, j, i))}"
        else:
            name = f"Valor {k}"
        if v is None:
            txt = "se decodifica con ecCodes"
        else:
            txt = _fmt_val(v)
            if block:
                txt += " (en bloque: sin tramo propio)"
            elif size == 0:
                txt += " (campo constante: = R)"
        out.append(Node(name, off, size, v, txt, kind="cell", meta={"k": k}))
    return out


# ── Búsqueda ──────────────────────────────────────────────────────────────

def find_at(node, pos):
    """El nodo más profundo (dentro de `node`) que contiene la posición."""
    if not node.contains(pos):
        return None
    cur = node
    while True:
        nxt = None
        for c in cur.children:
            if c.contains(pos):
                nxt = c
                break
        if nxt is None:
            return cur
        cur = nxt


def path_of(node):
    """[mensaje, sección, campo, …] desde la raíz hasta `node`."""
    out = []
    while node is not None:
        out.append(node)
        node = node.parent
    out.reverse()
    return out


def hex_bytes(data, offset, size, limit=32):
    """«64 00 00 01 4c 08» del tramo (hasta `limit` bytes, con «…»)."""
    chunk = bytes(data[offset:offset + min(size, limit)])
    s = " ".join(f"{b:02x}" for b in chunk)
    return s + (" …" if size > limit else "")
