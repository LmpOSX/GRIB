# -*- coding: utf-8 -*-
"""Working Area (WA) de una FIR: un cuadrado medido en millas náuticas sobre
un plano en proyección estereográfica tangente a un punto de tangencia, con
origen en el vértice suroeste y lados hacia el norte y el este.

Parámetros: código de la FIR, punto de tangencia (lat/lon), vértice SO
(lat/lon), ancho hacia el este y alto hacia el norte (NM) y el radio de la
esfera conforme (km). La proyección es la estereográfica esférica estándar
(Snyder, «Map Projections», fórmulas 21-2 a 21-4 y 20-14 a 20-15); el eje
y del plano apunta al norte en el punto de tangencia y el eje x al este.

El módulo no usa Qt: lo comparten el mapa (`wind_plot.set_working_areas`),
el diálogo de FIR (pestaña «Working Area») y los tests.
"""
import math
import re

import numpy as np

NM_KM = 1.852                       # una milla náutica en km
DEFAULT_RADIUS_KM = 6371.0          # radio medio terrestre; se puede reemplazar
                                    # por el radio conforme en la tangencia
WGS84_A_KM = 6378.137
WGS84_F = 1.0 / 298.257223563
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)

RADIUS_MIN_KM, RADIUS_MAX_KM = 6000.0, 6500.0
SIZE_MAX_NM = 6000.0
DEFAULT_STEP_NM = 5.0               # densificación de los lados al dibujar

WA_STYLE_DEFAULT = {"color": "#ffd54f", "line_width": 1.3, "label_size": 8}

# Convención de signo de la variación magnética en la interfaz y los
# archivos de configuración exportados. Internamente siempre se guarda
# «este positivo» (−10 = 10° W), la convención de la navegación.
MAGVAR_CONVENTIONS = [
    ("east_positive", "Este positivo, Oeste negativo (−10 = 10° W)"),
    ("west_positive", "Oeste positivo, Este negativo (10 = 10° W)"),
]


class WorkingAreaError(ValueError):
    pass


def conformal_radius_km(lat_deg):
    """Radio de la esfera conforme en una latitud sobre WGS84: √(M·N), la
    media geométrica de los radios de curvatura meridiano y transversal.
    Es el valor que suelen usar los sistemas de vigilancia para el plano
    estereográfico local."""
    s2 = math.sin(math.radians(lat_deg)) ** 2
    n = WGS84_A_KM / math.sqrt(1.0 - WGS84_E2 * s2)
    m = WGS84_A_KM * (1.0 - WGS84_E2) / (1.0 - WGS84_E2 * s2) ** 1.5
    return math.sqrt(m * n)


def stereo_forward(lat, lon, lat0, lon0, radius_km):
    """(lat, lon) → (x, y) en NM sobre el plano tangente en (lat0, lon0).
    Acepta escalares o arrays."""
    lat = np.radians(np.asarray(lat, dtype=float))
    lon = np.radians(np.asarray(lon, dtype=float))
    p0, l0 = math.radians(lat0), math.radians(lon0)
    r_nm = radius_km / NM_KM
    dl = lon - l0
    den = 1.0 + math.sin(p0) * np.sin(lat) + math.cos(p0) * np.cos(lat) * np.cos(dl)
    k = 2.0 * r_nm / den
    x = k * np.cos(lat) * np.sin(dl)
    y = k * (math.cos(p0) * np.sin(lat) - math.sin(p0) * np.cos(lat) * np.cos(dl))
    return x, y


def stereo_inverse(x, y, lat0, lon0, radius_km):
    """(x, y) en NM sobre el plano tangente en (lat0, lon0) → (lat, lon)
    en grados, con la longitud normalizada a −180…180."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    p0, l0 = math.radians(lat0), math.radians(lon0)
    r_nm = radius_km / NM_KM
    rho = np.hypot(x, y)
    c = 2.0 * np.arctan2(rho, 2.0 * r_nm)
    with np.errstate(invalid="ignore", divide="ignore"):
        sinc, cosc = np.sin(c), np.cos(c)
        lat = np.arcsin(np.clip(cosc * math.sin(p0) + np.where(rho > 0, y * sinc * math.cos(p0) / rho, 0.0),
                                -1.0, 1.0))
        lon = l0 + np.arctan2(x * sinc, rho * math.cos(p0) * cosc - y * math.sin(p0) * sinc)
    lat = np.where(rho > 0, lat, p0)
    lon = np.where(rho > 0, lon, l0)
    lon = (np.degrees(lon) + 180.0) % 360.0 - 180.0
    return np.degrees(lat), lon


def parse_variation(text, convention="east_positive"):
    """Variación magnética en grados, este positivo. Acepta `7W`, `7 W`,
    `7°W`, `6°55'E`, `6°55'30"E`, `W7`, `10.5w` y números sueltos (`-7`,
    `+6.9`, `7`), que se interpretan según la convención elegida."""
    t = str(text or "").strip().upper().replace(",", ".").replace("º", "°")
    if not t:
        raise WorkingAreaError("variación magnética vacía")
    hemi = None
    for h in ("E", "W", "O"):
        if t.startswith(h):
            hemi, t = h, t[1:].strip()
        elif t.endswith(h):
            hemi, t = h, t[:-1].strip()
    if hemi == "O":
        hemi = "W"
    sign = 1.0
    if t.startswith(("+", "-", "−")):
        sign = -1.0 if t[0] in "-−" else 1.0
        t = t[1:].strip()
    parts = [x for x in re.split(r"[°'\"\s]+", t) if x]
    if not parts or len(parts) > 3:
        raise WorkingAreaError(f"variación magnética «{text}» inválida")
    try:
        nums = [float(x) for x in parts]
    except ValueError:
        raise WorkingAreaError(f"variación magnética «{text}» inválida") from None
    if any(v < 0 for v in nums) or any(v >= 60 for v in nums[1:]):
        raise WorkingAreaError(f"variación magnética «{text}» inválida")
    value = nums[0] + (nums[1] / 60.0 if len(nums) > 1 else 0.0) + (nums[2] / 3600.0 if len(nums) > 2 else 0.0)
    value *= sign
    if hemi is not None:
        if sign < 0:
            raise WorkingAreaError(f"variación magnética «{text}»: signo y hemisferio a la vez")
        value = -value if hemi == "W" else value
    elif convention == "west_positive":
        value = -value
    if abs(value) > 180.0:
        raise WorkingAreaError(f"variación magnética «{text}» fuera de ±180°")
    return value


def format_variation(value, convention="east_positive", style="letter"):
    """`letter`: `10.0°W` / `6.9°E` / `0.0°`; `signed`: número con el signo
    de la convención elegida."""
    v = float(value)
    if style == "signed":
        if convention == "west_positive":
            v = -v
        return f"{v:+.1f}" if abs(v) >= 0.05 else "0.0"
    if abs(v) < 0.05:
        return "0.0°"
    return f"{abs(v):.1f}°{'E' if v > 0 else 'W'}"


def _destination(lat, lon, bearing, dist_deg):
    """Punto a `dist_deg` grados de arco de (lat, lon) en el acimut `bearing`."""
    p, l, b, d = map(math.radians, (lat, lon, bearing, dist_deg))
    lat2 = math.asin(math.sin(p) * math.cos(d) + math.cos(p) * math.sin(d) * math.cos(b))
    lon2 = l + math.atan2(math.sin(b) * math.sin(d) * math.cos(p), math.cos(d) - math.sin(p) * math.sin(lat2))
    return math.degrees(lat2), (math.degrees(lon2) + 180.0) % 360.0 - 180.0


def tangent_projection_params(lat, lon, radius_km, up_bearing=0.0):
    """Parámetros PROJ de una estereográfica esférica tangente en (lat, lon)
    cuyo eje «arriba» apunta al acimut verdadero `up_bearing` (la variación
    magnética, este positivo, para tener el norte magnético arriba).

    PROJ no gira el plano de `stere`, así que se usa `ob_tran`: se elige un
    polo rotado a 90° del punto de tangencia en ese acimut; el punto queda
    en el ecuador rotado (lon 0) y la estereográfica ecuatorial resulta
    tangente ahí con «arriba» hacia el polo rotado. El desfasaje de
    longitud rotada (o_lon_p) se calibra con pyproj. Devuelve una lista de
    pares (clave, valor) sin el radio: lo aporta el globo de cartopy."""
    import pyproj
    r_m = float(radius_km) * 1000.0
    lat_p, lon_p = _destination(lat, lon, up_bearing, 90.0)
    base = [("proj", "ob_tran"), ("o_lat_p", lat_p), ("lon_0", lon_p + 180.0)]
    ll = pyproj.CRS.from_proj4(f"+proj=longlat +R={r_m} +no_defs")

    def proj4(extra):
        return " ".join(f"+{k}={v}" for k, v in base + extra) + f" +R={r_m} +no_defs"
    tr = pyproj.Transformer.from_crs(ll, pyproj.CRS.from_proj4(proj4([("o_proj", "longlat"), ("o_lon_p", 0.0)])),
                                     always_xy=True)
    lt, _ = tr.transform(lon, lat)
    if abs(lt) <= 2.0 * math.pi + 1e-9 and abs(lt) < 7.0:
        lt = math.degrees(lt)                      # ob_tran + longlat devuelve radianes
    for cand in (-lt, lt, 180.0 - lt, 180.0 + lt):
        params = base + [("o_proj", "stere"), ("o_lon_p", cand)]
        t2 = pyproj.Transformer.from_crs(ll, pyproj.CRS.from_proj4(proj4([("o_proj", "stere"), ("o_lon_p", cand)]) +
                                                                     " +units=m"), always_xy=True)
        x0, y0 = t2.transform(lon, lat)
        if math.hypot(x0, y0) < 1.0:
            return params
    raise WorkingAreaError("no se pudo calibrar la proyección tangente")


class WorkingArea:
    FIELDS = ("code", "tangent_lat", "tangent_lon", "vertex_lat", "vertex_lon",
              "width_nm", "height_nm", "radius_km", "enabled", "variation_deg", "tangency")

    def __init__(self, code, tangent_lat=0.0, tangent_lon=0.0, vertex_lat=0.0, vertex_lon=0.0,
                 width_nm=0.0, height_nm=0.0, radius_km=DEFAULT_RADIUS_KM, enabled=True,
                 variation_deg=0.0, tangency=False):
        self.code = str(code or "").strip().upper()
        self.tangent_lat = float(tangent_lat)
        self.tangent_lon = float(tangent_lon)
        self.vertex_lat = float(vertex_lat)
        self.vertex_lon = float(vertex_lon)
        self.width_nm = float(width_nm)
        self.height_nm = float(height_nm)
        self.radius_km = float(radius_km)
        self.enabled = bool(enabled)
        self.variation_deg = float(variation_deg)      # este positivo; gira el plano
        self.tangency = bool(tangency)                 # la proyección del mapa es tangente acá

    # ── geometría ──
    def forward(self, lat, lon):
        """(lat, lon) → (x, y) en NM en el plano de la WA: estereográfico
        tangente y girado por la variación magnética, así el eje y apunta
        al norte magnético (un punto al norte verdadero cae a la derecha
        del eje con variación oeste)."""
        x, y = stereo_forward(lat, lon, self.tangent_lat, self.tangent_lon, self.radius_km)
        if self.variation_deg:
            d = math.radians(self.variation_deg)
            x, y = x * math.cos(d) - y * math.sin(d), x * math.sin(d) + y * math.cos(d)
        return x, y

    def inverse(self, x, y):
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        if self.variation_deg:
            d = math.radians(-self.variation_deg)
            x, y = x * math.cos(d) - y * math.sin(d), x * math.sin(d) + y * math.cos(d)
        return stereo_inverse(x, y, self.tangent_lat, self.tangent_lon, self.radius_km)

    def origin_xy(self):
        """Vértice SO en el plano (NM)."""
        x, y = self.forward(self.vertex_lat, self.vertex_lon)
        return float(x), float(y)

    def corners_xy(self):
        """SO, SE, NE, NO en el plano (NM)."""
        x0, y0 = self.origin_xy()
        w, h = self.width_nm, self.height_nm
        return [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)]

    def corners(self):
        """SO, SE, NE, NO en (lat, lon)."""
        xy = np.array(self.corners_xy())
        lat, lon = self.inverse(xy[:, 0], xy[:, 1])
        return [(float(a), float(b)) for a, b in zip(lat, lon)]

    def ring(self, step_nm=DEFAULT_STEP_NM):
        """Contorno (lon, lat) de N×2, abierto, empezando en el vértice SO
        y recorriendo SE, NE, NO; los lados se densifican cada `step_nm`
        porque rectos en el plano son curvas en lat/lon."""
        pts = []
        cs = self.corners_xy()
        for (xa, ya), (xb, yb) in zip(cs, cs[1:] + cs[:1]):
            n = max(1, int(math.ceil(math.hypot(xb - xa, yb - ya) / max(step_nm, 0.1))))
            t = np.arange(n) / n
            pts.append(np.column_stack([xa + (xb - xa) * t, ya + (yb - ya) * t]))
        xy = np.vstack(pts)
        lat, lon = self.inverse(xy[:, 0], xy[:, 1])
        return np.column_stack([lon, lat])

    def label_point(self, frac=0.04):
        """(lon, lat) un poco por dentro del vértice SO, para la etiqueta."""
        x0, y0 = self.origin_xy()
        lat, lon = self.inverse(x0 + frac * self.width_nm, y0 + frac * self.height_nm)
        return float(lon), float(lat)

    def bbox(self):
        """(lonmin, lonmax, latmin, latmax) del contorno."""
        r = self.ring(step_nm=20.0)
        return (float(r[:, 0].min()), float(r[:, 0].max()), float(r[:, 1].min()), float(r[:, 1].max()))

    def contains(self, lat, lon):
        """True si el punto cae dentro del cuadrado (en el plano)."""
        x, y = self.forward(lat, lon)
        x0, y0 = self.origin_xy()
        return bool(x0 <= x <= x0 + self.width_nm and y0 <= y <= y0 + self.height_nm)

    # ── serialización ──
    def to_dict(self):
        return {k: getattr(self, k) for k in self.FIELDS}

    @classmethod
    def from_dict(cls, d):
        d = dict(d or {})
        return cls(d.get("code", ""), d.get("tangent_lat", 0.0), d.get("tangent_lon", 0.0),
                   d.get("vertex_lat", 0.0), d.get("vertex_lon", 0.0), d.get("width_nm", 0.0),
                   d.get("height_nm", 0.0), d.get("radius_km", DEFAULT_RADIUS_KM), d.get("enabled", True),
                   d.get("variation_deg", 0.0), d.get("tangency", False))

    def copy(self):
        return WorkingArea.from_dict(self.to_dict())

    def __repr__(self):
        return (f"WorkingArea({self.code}, tang=({self.tangent_lat:.4f},{self.tangent_lon:.4f}), "
                f"SO=({self.vertex_lat:.4f},{self.vertex_lon:.4f}), {self.width_nm:g}×{self.height_nm:g} NM, "
                f"R={self.radius_km:g} km, var={format_variation(self.variation_deg)}"
                f"{', tangencia' if self.tangency else ''})")


def validate_working_area(wa):
    """Lista de errores (vacía si la WA es válida)."""
    errs = []
    if not (1 <= len(wa.code) <= 4) or not wa.code.isalpha():
        errs.append(f"código «{wa.code}» inválido (1 a 4 letras)")
    for name, v in (("latitud de tangencia", wa.tangent_lat), ("latitud del vértice", wa.vertex_lat)):
        if not -90.0 <= v <= 90.0:
            errs.append(f"{name} fuera de −90…90")
    for name, v in (("longitud de tangencia", wa.tangent_lon), ("longitud del vértice", wa.vertex_lon)):
        if not -180.0 <= v <= 180.0:
            errs.append(f"{name} fuera de −180…180")
    for name, v in (("ancho", wa.width_nm), ("alto", wa.height_nm)):
        if not (0.0 < v <= SIZE_MAX_NM):
            errs.append(f"{name} debe estar entre 0 y {SIZE_MAX_NM:.0f} NM")
    if not (RADIUS_MIN_KM <= wa.radius_km <= RADIUS_MAX_KM):
        errs.append(f"radio fuera de {RADIUS_MIN_KM:.0f}…{RADIUS_MAX_KM:.0f} km")
    if not (-180.0 <= wa.variation_deg <= 180.0):
        errs.append("variación magnética fuera de ±180°")
    if not errs:
        # El vértice tiene que estar en el hemisferio visible del plano
        d = math.radians(90.0)
        x, y = wa.origin_xy()
        if math.hypot(x, y) > 2.0 * wa.radius_km / NM_KM * math.tan(d / 2.0):
            errs.append("el vértice queda a más de 90° del punto de tangencia")
    return [f"{wa.code or '(sin código)'}: {e}" for e in errs]


def validate_working_areas(was):
    errs = []
    seen = set()
    for wa in was:
        errs += validate_working_area(wa)
        if wa.code in seen:
            errs.append(f"{wa.code}: código repetido")
        seen.add(wa.code)
    tang = [wa.code for wa in was if wa.tangency]
    if len(tang) > 1:
        errs.append("sólo una Working Area puede ser el punto de tangencia: " + ", ".join(tang))
    return errs


def find_tangency(was):
    """La WA marcada como punto de tangencia de la proyección (válida), o None."""
    for wa in was:
        if wa.tangency and not validate_working_area(wa):
            return wa
    return None


def working_areas_from_config(cfg):
    out = []
    for d in (cfg or {}).get("working_areas") or []:
        if not isinstance(d, dict):
            continue
        try:
            out.append(WorkingArea.from_dict(d))
        except (TypeError, ValueError):
            continue
    return out


def working_areas_to_config(was):
    return [wa.to_dict() for wa in was]


def find_working_area(was, code):
    code = str(code or "").upper()
    for wa in was:
        if wa.code == code:
            return wa
    return None


def describe(wa):
    """Resumen de una línea: esquinas y tamaño, para el diálogo y STATUS."""
    (slat, slon), _se, (nlat, nlon), _no = wa.corners()
    return (f"{wa.code}: {wa.width_nm:g} × {wa.height_nm:g} NM, SO {slat:.4f}° {slon:.4f}°, "
            f"NE {nlat:.4f}° {nlon:.4f}°, tangencia {wa.tangent_lat:.4f}° {wa.tangent_lon:.4f}°, "
            f"R {wa.radius_km:.3f} km, var. {format_variation(wa.variation_deg)}"
            + (" · tangencia de la proyección" if wa.tangency else ""))
