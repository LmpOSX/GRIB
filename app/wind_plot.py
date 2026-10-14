# -*- coding: utf-8 -*-
"""
Dibujo del mapa de viento y temperatura con matplotlib (backend QtAgg) y
cartopy opcional. No conoce la ventana ni los controles: recibe arrays y un
diccionario de opciones y dibuja sobre su propia figura.

Organización en capas, pensada para que zoom y pan sean fluidos:

* base: costas, fronteras y grillas (cartopy). Se construye una vez por
  proyección / opción de grilla / tamaño de fuente y se conserva entre
  redibujos, igual que los ejes (así no se pierde la vista actual al cambiar
  nivel, paso o variable).
* estática: fondo de velocidad, contornos de temperatura, leyenda y título.
  Se reconstruye en cada draw().
* por vista: barbas y rótulos de "Extra Info" sólo para los puntos visibles,
  con un tope automático de cantidad (al alejar la vista se ralean, al
  acercarla se ven todos). Se reconstruye cuando la vista se estabiliza.

Mientras se arrastra (pan) o se usa la rueda, las capas caras de dibujar
(rótulos y etiquetas de la grilla) se ocultan y se vuelven a mostrar
150 ms después del último cambio de vista.
"""

import math
import os

import numpy as np

import matplotlib
matplotlib.use("QtAgg")
import matplotlib.ticker as mticker  # noqa: E402
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg  # noqa: E402
from matplotlib.colors import BoundaryNorm, ListedColormap  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.transforms import Bbox, Affine2D  # noqa: E402
from matplotlib.collections import PathCollection, LineCollection  # noqa: E402
from matplotlib.textpath import TextPath  # noqa: E402
from matplotlib.font_manager import FontProperties  # noqa: E402

from PyQt6 import sip  # noqa: E402
from PyQt6.QtCore import QPoint, Qt, QTimer  # noqa: E402
from PyQt6.QtGui import QImage, QPainter  # noqa: E402

from .grib_reader import (  # noqa: E402
    KELVIN, MS_TO_KT, SPEED_BINS, SPEED_COLORS, SPEED_LABELS,
    speed_color, speed_dir_from_uv)

# ---------------------------------------------------------------------------
# Dependencia opcional: cartopy
# ---------------------------------------------------------------------------
# Certificados SSL: cartopy descarga las costas de Natural Earth la primera
# vez que se usan; algunos Python (p. ej. instaladores de python.org en macOS)
# no encuentran los certificados del sistema. Si 'certifi' está instalado se
# usa su paquete de certificados.
if "SSL_CERT_FILE" not in os.environ:
    try:
        import certifi
        os.environ["SSL_CERT_FILE"] = certifi.where()
    except Exception:
        pass

try:
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    HAVE_CARTOPY = True
except Exception:  # pragma: no cover - depende del entorno
    ccrs = None
    cfeature = None
    HAVE_CARTOPY = False

# Escala de colores de las barbas como mapa de colores de matplotlib
SPEED_CMAP = ListedColormap(SPEED_COLORS)
SPEED_NORM = BoundaryNorm(SPEED_BINS + [10000], ncolors=len(SPEED_COLORS))

# Paleta por defecto del mapa (fondo oscuro estilo pantalla ATC). La ventana
# la reemplaza con los colores del tema vía WindPlot.set_palette(). Los
# colores de los datos (escala de barbas, contornos de temperatura) no son
# de la interfaz y no cambian con el tema.
DEFAULT_PALETTE = {
    "bg": "#000000",         # fondo de la figura
    "ax_bg": "#060606",      # fondo de los ejes
    "text": "#e8e8e8",       # títulos, etiquetas, leyenda
    "text_dim": "#aaaaaa",   # textos secundarios y spines
    "coast": "#c8c8c8",      # costas
    "border": "#8c8c8c",     # fronteras
    "grid": "#5a5a5a",       # meridianos/paralelos cada 10°
    "grid_fine": "#333333",  # grilla fina del archivo
    "legend_bg": "#111111",  # fondo de la leyenda
    "warn": "#ff9966",       # avisos sobre el mapa
}
TEMP_CONTOUR = "#ff5cf0"       # contornos de temperatura (dato, no tema)
TEMP_LABEL = "#ffb3f7"

# Proyecciones del mapa: (clave, nombre para el combo). Todas menos la
# primera necesitan cartopy. Las "centradas en el dominio" se construyen con
# el centro de la grilla del archivo.
PROJECTIONS = [
    ("platecarree", "Lat/Lon (PlateCarree)"),
    ("stereo", "Estereográfica conforme (centro del dominio)"),
    ("spstereo", "Estereográfica polar sur"),
    ("npstereo", "Estereográfica polar norte"),
    ("mercator", "Mercator"),
    ("lambert", "Lambert conforme (centro del dominio)"),
]


def make_projection(key, lons=None, lats=None):
    """Construye la proyección cartopy para la clave dada. Sin cartopy
    devuelve None (ejes matplotlib comunes en lat/lon)."""
    if not HAVE_CARTOPY:
        return None
    lon_c = float(np.mean(lons)) if lons is not None and len(lons) else 0.0
    lat_c = float(np.mean(lats)) if lats is not None and len(lats) else 0.0
    if key == "stereo":
        return ccrs.Stereographic(central_latitude=lat_c, central_longitude=lon_c)
    if key == "spstereo":
        return ccrs.SouthPolarStereo(central_longitude=lon_c)
    if key == "npstereo":
        return ccrs.NorthPolarStereo(central_longitude=lon_c)
    if key == "mercator":
        return ccrs.Mercator(central_longitude=lon_c)
    if key == "lambert":
        # Paralelos estándar simétricos alrededor del centro del dominio
        half = max(5.0, (float(np.max(lats)) - float(np.min(lats))) / 4.0) if lats is not None and len(lats) else 10.0
        p1 = max(-85.0, min(85.0, lat_c - half))
        p2 = max(-85.0, min(85.0, lat_c + half))
        if abs(p1 + p2) < 1.0:
            # Dominio centrado en el ecuador: PROJ rechaza paralelos simétricos;
            # se corre el cono hacia el hemisferio del centro (o el sur)
            p1, p2 = ((5.0, 15.0) if lat_c > 0 else (-15.0, -5.0))
        return ccrs.LambertConformal(central_longitude=lon_c, central_latitude=lat_c,
                                     standard_parallels=(p1, p2),
                                     cutoff=(30 if (p1 + p2) < 0 else -30))
    return ccrs.PlateCarree()


# ---------------------------------------------------------------------------
# Canvas Qt translúcido
# ---------------------------------------------------------------------------
class TranslucentCanvas(FigureCanvasQTAgg):
    """FigureCanvasQTAgg que respeta el alfa de la figura: el backend
    original borra en blanco (eraseRect) antes de copiar la imagen, lo que
    tapa el fondo de vidrio de la ventana. Acá se copia la imagen RGBA tal
    cual sobre lo que ya pintó el padre."""

    def __init__(self, figure=None):
        super().__init__(figure)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)

    def paintEvent(self, event):
        self._draw_idle()
        if not hasattr(self, "renderer"):
            return
        painter = QPainter(self)
        try:
            rect = event.rect()
            width = rect.width() * self.device_pixel_ratio
            height = rect.height() * self.device_pixel_ratio
            left, top = self.mouseEventCoords(rect.topLeft())
            bbox = Bbox([[left, top - height], [left + width, top]])
            buf = memoryview(self.copy_from_bbox(bbox))
            ptr = int(sip.voidptr(buf))
            qimage = QImage(ptr, buf.shape[1], buf.shape[0], QImage.Format.Format_RGBA8888)
            qimage.setDevicePixelRatio(self.device_pixel_ratio)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.drawImage(QPoint(rect.left(), rect.top()), qimage)
            self._draw_rect_callback(painter)
        finally:
            painter.end()


# ---------------------------------------------------------------------------
# Dibujo del mapa
# ---------------------------------------------------------------------------
MAX_BARBS = 2500        # barbas / flechas visibles como máximo (se ralea automáticamente)
WIND_STYLES = [("barbas", "Barbas"), ("flechas", "Flechas (vectores)"), ("curvas", "Curvas (líneas de corriente)")]
ARROW_LEN_IN = 0.24         # largo fijo de las flechas (pulgadas, a escala de fuente 1)
BARB_LENGTH_PT = 5.5        # largo nominal de las barbas (puntos de matplotlib)
BARB_PX_PER_PT = 3.1        # px que ocupa el asta por punto de `length` (a 72 dpi)
GLYPH_MIN_FACTOR = 0.5      # al alejar, barbas y flechas se achican hasta la mitad y recién ahí se ralean
GLYPH_FILL = 0.88           # fracción del espacio entre puntos que puede ocupar un glifo
STREAM_NOMINAL_CELL_PX = 18.0   # curvas: por debajo de esta separación entre puntos se afinan
CALM_KT = 0.5               # por debajo no hay dirección: sin flecha
STREAM_ARROW_PX = 55.0      # separación entre flechas embebidas en las curvas (px)
LABEL_SIZE_DEFAULT = 7      # tamaño base (pt) de los rótulos de Extra Info
GRID_LABEL_MARGIN_PX = (66.0, 18.0, 14.0, 38.0)   # margen de inscripciones: izq, der, arriba, abajo
GRID_STEPS = [(10, "10°"), (5, "5°"), (1, "1°")]   # grilla de grados seleccionable
MAX_LABELS = 900        # rótulos de Extra Info visibles como máximo
SETTLE_MS = 150         # espera tras el último cambio de vista para reconstruir


def integrate_streamlines(xs, ys, u, v, density=2.0, step=0.5, max_steps=None,
                          min_cells=3):
    """Líneas de corriente del campo (u, v) sobre la grilla regular xs (nx),
    ys (ny), integradas EN BLOQUE con numpy.

    * Se trabaja en coordenadas de índice de grilla con el campo de
      direcciones unitario (sólo importa hacia dónde apunta el viento), con
      paso fijo `step` celdas y Runge-Kutta de orden 2 (punto medio) sobre
      matrices (N semillas × 2) hacia adelante y hacia atrás.
    * Las semillas son los centros de una grilla de ocupación de
      30·densidad celdas por eje (como matplotlib). Se integran por rondas
      (cuatro clases de paridad) todas las semillas de la ronda a la vez;
      después, del centro hacia afuera, cada trayectoria se acepta hasta
      donde entra en una celda ya ocupada o en una que ella misma ya
      visitó (los remolinos cierran una sola vuelta) y se descarta si no
      cubre `min_cells` celdas. Las rondas siguientes sólo integran las
      semillas cuya celda sigue libre, que son pocas.
    Devuelve una lista de arrays (n, 2) en coordenadas (x, y)."""
    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)
    nx, ny = len(xs), len(ys)
    if nx < 2 or ny < 2:
        return []
    u = np.asarray(u, dtype=float)
    v = np.asarray(v, dtype=float)
    dx = (xs[-1] - xs[0]) / (nx - 1)
    dy = (ys[-1] - ys[0]) / (ny - 1)
    with np.errstate(all="ignore"):
        ui = u / dx
        vi = v / dy
        mag = np.hypot(ui, vi)
        di = np.where(mag > 0, ui / mag, np.nan)
        dj = np.where(mag > 0, vi / mag, np.nan)
    mx = my = max(4, int(30 * density))          # como matplotlib: 30·densidad por eje
    sx, sy = mx / (nx - 1), my / (ny - 1)

    def cells_of(pts):
        ci = np.clip((pts[:, 0] * sx).astype(int), 0, mx - 1)
        cj = np.clip((pts[:, 1] * sy).astype(int), 0, my - 1)
        return cj * mx + ci

    def direction(p):
        """Dirección unitaria interpolada (bilineal) en puntos de índice
        (N, 2); la grilla es uniforme, así que el índice es floor()."""
        px = np.nan_to_num(p[:, 0], nan=-1.0)     # NaN → fuera del dominio
        py = np.nan_to_num(p[:, 1], nan=-1.0)
        i0 = np.clip(np.floor(px).astype(int), 0, nx - 2)
        j0 = np.clip(np.floor(py).astype(int), 0, ny - 2)
        tx = (px - i0)[:, None]
        ty = (py - j0)[:, None]
        f00 = dir_field[j0, i0]
        f01 = dir_field[j0, i0 + 1]
        f10 = dir_field[j0 + 1, i0]
        f11 = dir_field[j0 + 1, i0 + 1]
        d = (f00 * (1 - tx) * (1 - ty) + f01 * tx * (1 - ty)
             + f10 * (1 - tx) * ty + f11 * tx * ty)
        m = np.hypot(d[:, 0], d[:, 1])
        inside = (px >= 0) & (px <= nx - 1) & (py >= 0) & (py <= ny - 1)
        with np.errstate(all="ignore"):
            d = np.where(((m > 1e-9) & inside)[:, None], d / m[:, None], np.nan)
        return d

    dir_field = np.stack([di, dj], axis=-1)          # (ny, nx, 2)
    if max_steps is None:
        max_steps = int(0.8 * (nx + ny) / step)

    def integrate(seeds, sign, stop_cells=None):
        """Trayectorias (K+1, N, 2) desde `seeds` (N, 2); NaN tras terminar.
        Con `stop_cells` (ocupación ya conocida) la trayectoria muere al
        entrar en una celda ocupada: las rondas tardías son casi gratis."""
        p = seeds.astype(float).copy()
        out = np.full((max_steps + 1, len(p), 2), np.nan)
        out[0] = p
        alive = np.ones(len(p), dtype=bool)
        for k in range(1, max_steps + 1):
            idx = np.flatnonzero(alive)
            if not len(idx):
                break
            pa = p[idx]
            d1 = direction(pa) * sign
            d2 = direction(pa + 0.5 * step * d1) * sign
            q = pa + step * d2
            okq = (np.isfinite(q).all(axis=1) & (q[:, 0] >= 0) & (q[:, 0] <= nx - 1)
                   & (q[:, 1] >= 0) & (q[:, 1] <= ny - 1))
            if stop_cells is not None:
                qq = np.where(okq[:, None], q, 0.0)
                okq &= ~stop_cells[cells_of(qq)]
            alive[idx[~okq]] = False
            q[~okq] = np.nan
            p[idx] = q
            out[k, idx] = q
        return out

    cx = (np.arange(mx) + 0.5) * (nx - 1) / mx
    cy = (np.arange(my) + 0.5) * (ny - 1) / my
    SX, SY = np.meshgrid(cx, cy)
    seeds_all = np.column_stack([SX.ravel(), SY.ravel()])
    dist = np.hypot(SX.ravel() - (nx - 1) / 2.0, SY.ravel() - (ny - 1) / 2.0)
    order = np.argsort(dist, kind="stable")
    ii = (np.arange(mx)[None, :] % 2 + 2 * (np.arange(my)[:, None] % 2)).ravel()
    rounds = [order[ii[order] == r] for r in (0, 3, 1, 2)]

    occupied = np.zeros(mx * my, dtype=bool)

    def accept(pts, own):
        """Recorta `pts` donde entra en una celda ocupada (por otras o por
        el otro tramo de esta misma trayectoria) o vuelve a una celda que
        ya recorrió. Devuelve (pts, celdas)."""
        pts = pts[np.isfinite(pts).all(axis=1)]
        if len(pts) < 2:
            return pts, np.array([], dtype=int)
        c = cells_of(pts)
        change = np.ones(len(c), dtype=bool)
        change[1:] = c[1:] != c[:-1]
        seen_before = np.zeros(len(c), dtype=bool)
        if len(c) > 1:
            # celda ya recorrida antes por este tramo (reentrada)
            order_c = np.argsort(c, kind="stable")
            cs = c[order_c]
            first = np.ones(len(c), dtype=bool)
            first[1:] = cs[1:] != cs[:-1]
            seen_before[order_c] = ~first
        stop = np.flatnonzero(change & (occupied[c] | np.isin(c, own) | seen_before))
        stop = stop[stop > 0]
        if len(stop):
            pts, c = pts[:stop[0]], c[:stop[0]]
        return pts, c

    trajs = []
    empty = np.array([], dtype=int)
    for rnd in rounds:
        seed_cells = cells_of(seeds_all[rnd])
        rnd = rnd[~occupied[seed_cells]]
        if not len(rnd):
            continue
        seeds = seeds_all[rnd]
        stop = occupied if trajs else None          # tras la 1.ª ronda, mueren en celdas ocupadas
        fwd = integrate(seeds, +1.0, stop)          # (K+1, N, 2): todas a la vez
        bwd = integrate(seeds, -1.0, stop)
        for n in range(len(rnd)):
            if occupied[cells_of(seeds[n:n + 1])[0]]:
                continue
            f_pts, f_cells = accept(fwd[:, n, :], empty)
            b_pts, b_cells = accept(bwd[:, n, :], f_cells)
            cells = np.unique(np.concatenate([f_cells, b_cells]))
            if len(cells) < min_cells:
                continue
            pts = np.concatenate([b_pts[::-1], f_pts[1:]]) if len(b_pts) else f_pts
            if len(pts) < 2:
                continue
            occupied[cells] = True
            trajs.append(np.column_stack([xs[0] + pts[:, 0] * dx, ys[0] + pts[:, 1] * dy]))
    return trajs


def _sample_bilinear(x, y, field, qx, qy):
    """Muestreo bilineal de `field` (ny, nx) con ejes ascendentes `x`, `y`
    en los puntos `qx`, `qy` (arrays de igual forma). NaN fuera del dominio
    o donde falta algún vecino."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    qx = np.asarray(qx, dtype=float)
    qy = np.asarray(qy, dtype=float)
    ix = np.searchsorted(x, qx, side="right") - 1
    iy = np.searchsorted(y, qy, side="right") - 1
    valid = ((ix >= 0) & (ix < len(x) - 1) & (iy >= 0) & (iy < len(y) - 1)
             & np.isfinite(qx) & np.isfinite(qy))
    ix = np.clip(ix, 0, max(0, len(x) - 2))
    iy = np.clip(iy, 0, max(0, len(y) - 2))
    with np.errstate(all="ignore"):
        tx = (qx - x[ix]) / (x[ix + 1] - x[ix])
        ty = (qy - y[iy]) / (y[iy + 1] - y[iy])
        out = (field[iy, ix] * (1 - tx) * (1 - ty) + field[iy, ix + 1] * tx * (1 - ty)
               + field[iy + 1, ix] * (1 - tx) * ty + field[iy + 1, ix + 1] * tx * ty)
    out = np.asarray(out, dtype=float)
    out[~valid] = np.nan
    return out


class WindPlot:
    """Encapsula la figura matplotlib (con cartopy si está disponible) y
    dibuja barbas, contornos, leyenda y grilla sobre un fondo oscuro."""

    def __init__(self, master=None):
        self.pal = dict(DEFAULT_PALETTE)
        self.font_scale = 1.0           # multiplicador de todas las fuentes del mapa
        self._title = ""                # título del mapa (sólo en el PNG exportado)
        self.alpha = 1.0                # opacidad del fondo de la figura (0–1)
        self.fig = Figure(figsize=(9, 7), dpi=100, facecolor=self.pal["bg"])
        self.canvas = TranslucentCanvas(self.fig)
        if master is not None:
            self.canvas.setParent(master)
        self.use_cartopy = HAVE_CARTOPY
        self.data_crs = ccrs.PlateCarree() if self.use_cartopy else None   # los datos vienen en lat/lon
        self.proj_key = "platecarree"
        self.proj = ccrs.PlateCarree() if self.use_cartopy else None       # proyección del mapa
        self.ax = None
        self.has_data = False
        self._features = None           # (costas, fronteras) ya cargadas
        self._features_error = None     # texto del error si no se pudieron cargar
        self._data = None               # campos y opciones del último draw()
        self._base_artists = []         # costas, fronteras, avisos de base
        self._gridliners = []           # Gridliner de cartopy (10° y fina)
        self._base_key = None
        self._static_artists = []       # contornos, leyenda, textos fijos
        self._view_artists = []         # barbas
        self._label_artists = []        # rótulos de Extra Info (una PathCollection)
        self.label_texts = []           # textos de los rótulos visibles (inspección / tests)
        self.label_fontsize = LABEL_SIZE_DEFAULT
        self._in_draw = False
        self._interacting = False
        self._settle_timer = QTimer()
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(SETTLE_MS)
        self._settle_timer.timeout.connect(self._on_view_settled)
        # Pan por arrastre con el botón izquierdo (sin modo ni botón aparte)
        self._panning = False
        self.on_view_push = None        # callable: guarda la vista antes de moverla (Inicio)
        self.canvas.mpl_connect("button_press_event", self._on_press)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("button_release_event", self._on_release)
        self.canvas.mpl_connect("resize_event", self._on_resize)
        self._make_axes()
        self._style_axes()
        self.draw_empty()

    # ----------------------------------------------------------- ejes
    def _make_axes(self):
        self.fig.clear()
        if self.use_cartopy:
            self.ax = self.fig.add_subplot(1, 1, 1, projection=self.proj)
        else:
            self.ax = self.fig.add_subplot(1, 1, 1)
        self._apply_margins()
        self._base_artists, self._gridliners = [], []
        self._static_artists, self._view_artists, self._label_artists = [], [], []
        self._base_key = None
        self.ax.callbacks.connect("xlim_changed", self._on_lim_changed)
        self.ax.callbacks.connect("ylim_changed", self._on_lim_changed)

    def set_projection(self, key, lons=None, lats=None):
        """Cambia la proyección del mapa y recrea los ejes. Devuelve True si
        la proyección cambió (sin cartopy sólo existe lat/lon)."""
        if not self.use_cartopy:
            self.proj_key = "platecarree"
            return False
        self.proj_key = key if key in dict(PROJECTIONS) else "platecarree"
        self.proj = make_projection(self.proj_key, lons, lats)
        self._make_axes()
        self._style_axes()
        self.has_data = False
        return True

    def to_lonlat(self, x, y):
        """Convierte coordenadas de los ejes (proyectadas) a lon/lat."""
        if self.use_cartopy and self.proj_key != "platecarree":
            try:
                lon, lat = self.data_crs.transform_point(x, y, self.proj)
                if np.isfinite(lon) and np.isfinite(lat):
                    return float(lon), float(lat)
                return None, None
            except Exception:
                return None, None
        return float(x), float(y)

    def _style_axes(self):
        ax = self.ax
        self.fig.set_facecolor(self.pal["bg"])
        self.fig.patch.set_alpha(self.alpha)
        ax.set_facecolor(self.pal["ax_bg"])
        ax.patch.set_alpha(self.alpha)
        for sp in ax.spines.values():
            sp.set_edgecolor(self.pal["text_dim"])
        ax.tick_params(colors=self.pal["text"], labelsize=self._fs(8))
        ax.xaxis.label.set_color(self.pal["text"])
        ax.yaxis.label.set_color(self.pal["text"])

    def _fs(self, base):
        """Tamaño de fuente escalado por el zoom de fuente de la interfaz."""
        return max(4.0, base * self.font_scale)

    def set_palette(self, **colors):
        """Reemplaza colores de la paleta (claves de DEFAULT_PALETTE). El
        cambio se ve en el próximo draw()/draw_empty()."""
        changed = False
        for k, v in colors.items():
            if k in self.pal and v and self.pal[k] != v:
                self.pal[k] = v
                changed = True
        if changed:
            self._base_key = None       # costas y grillas con los colores nuevos

    def set_font_scale(self, scale):
        scale = max(0.5, min(3.0, float(scale)))
        if abs(scale - self.font_scale) > 1e-6:
            self.font_scale = scale
            self._base_key = None       # etiquetas de la grilla con el tamaño nuevo
            self._apply_margins()

    def set_opacity(self, alpha):
        """Opacidad del fondo de la figura y de los ejes (0 = transparente)."""
        self.alpha = max(0.0, min(1.0, float(alpha)))
        self.fig.patch.set_alpha(self.alpha)
        if self.ax is not None:
            self.ax.patch.set_alpha(self.alpha)

    def _tr(self):
        """kwargs de transformación para cartopy (vacío sin cartopy)."""
        return {"transform": self.data_crs} if self.use_cartopy else {}

    # ----------------------------------------------------------- vista
    def get_extent(self):
        """Extensión actual [lonmin, lonmax, latmin, latmax]."""
        try:
            if self.use_cartopy:
                return list(self.ax.get_extent(crs=self.data_crs))
            x0, x1 = self.ax.get_xlim()
            y0, y1 = self.ax.get_ylim()
            return [x0, x1, y0, y1]
        except Exception:
            return None

    def set_extent(self, extent):
        """Fija la extensión [lonmin, lonmax, latmin, latmax] y la amplía en
        el sentido que haga falta para llenar el área del mapa."""
        lon0, lon1, lat0, lat1 = extent
        if lon1 <= lon0 or lat1 <= lat0:
            return
        if self.use_cartopy:
            self.ax.set_extent([lon0, lon1, lat0, lat1], crs=self.data_crs)
        else:
            self.ax.set_xlim(lon0, lon1)
            self.ax.set_ylim(lat0, lat1)
        self._fit_view_to_box()
        self.canvas.draw_idle()

    def _fit_view_to_box(self):
        """Amplía (nunca recorta) los límites actuales para que su proporción
        coincida con la del área de los ejes: así el mapa, que mantiene la
        escala igual en x e y, ocupa todo el canvas en vez de dejar franjas
        vacías a los costados o arriba y abajo."""
        ax = self.ax
        try:
            bw, bh = float(ax.bbox.width), float(ax.bbox.height)
        except Exception:
            return
        if bw <= 1 or bh <= 1:
            return
        x0, x1 = ax.get_xlim()
        y0, y1 = ax.get_ylim()
        w, h = x1 - x0, y1 - y0
        if w <= 0 or h <= 0:
            return
        box_aspect = bw / bh
        if w / h < box_aspect:
            # El área es más ancha que la vista: se ensancha en x
            new_w = h * box_aspect
            cx = (x0 + x1) / 2.0
            ax.set_xlim(cx - new_w / 2.0, cx + new_w / 2.0)
        else:
            new_h = w / box_aspect
            cy = (y0 + y1) / 2.0
            ax.set_ylim(cy - new_h / 2.0, cy + new_h / 2.0)

    def _apply_margins(self, with_title=False):
        """Márgenes de la figura en píxeles (no en fracción): lo justo para
        las etiquetas de lat/lon a la izquierda y abajo, y para el título
        sólo cuando se exporta (en pantalla lo reemplaza la franja STATUS)."""
        try:
            w_in, h_in = self.fig.get_size_inches()
            dpi = float(self.fig.dpi)
            w, h = w_in * dpi, h_in * dpi
        except Exception:
            return
        if w < 80 or h < 80:
            return
        # Margen de inscripciones: las etiquetas de lat/lon se escriben
        # fuera de los ejes (izquierda y abajo) y necesitan este espacio;
        # arriba y a la derecha queda un margen chico para que nada se corte.
        s = max(0.8, self.font_scale)
        left = GRID_LABEL_MARGIN_PX[0] * s
        right = GRID_LABEL_MARGIN_PX[1] * s
        top = (36.0 * s) if with_title else GRID_LABEL_MARGIN_PX[2] * s
        bottom = GRID_LABEL_MARGIN_PX[3] * s
        self.fig.subplots_adjust(left=left / w, right=1.0 - right / w,
                                 top=1.0 - top / h, bottom=bottom / h)

    def _on_resize(self, _event):
        """Al cambiar el tamaño del canvas se recalculan los márgenes y se
        vuelve a llenar el área."""
        self._apply_margins()
        if self.has_data and not self._in_draw:
            self._fit_view_to_box()

    def zoom_at(self, x, y, factor):
        """Acerca (factor < 1) o aleja (factor > 1) la vista alrededor del
        punto (x, y) en coordenadas de los ejes (rueda del mouse)."""
        if not self.has_data or x is None or y is None:
            return
        x0, x1 = self.ax.get_xlim()
        y0, y1 = self.ax.get_ylim()
        self.ax.set_xlim(x - (x - x0) * factor, x + (x1 - x) * factor)
        self.ax.set_ylim(y - (y - y0) * factor, y + (y1 - y) * factor)
        self.canvas.draw_idle()

    # ----------------------------------------------------------- pan
    def _on_press(self, event):
        if (event.button != 1 or event.inaxes is not self.ax or not self.has_data
                or event.dblclick):
            return
        if self.on_view_push is not None:
            try:
                self.on_view_push()
            except Exception:
                pass
        self.ax.start_pan(event.x, event.y, 1)
        self._panning = True
        self.canvas.setCursor(Qt.CursorShape.ClosedHandCursor)

    def _on_motion(self, event):
        if not self._panning:
            if self.has_data and event.inaxes is self.ax:
                self.canvas.setCursor(Qt.CursorShape.OpenHandCursor)
            elif self.canvas.cursor().shape() != Qt.CursorShape.ArrowCursor:
                self.canvas.setCursor(Qt.CursorShape.ArrowCursor)
            return
        self.ax.drag_pan(1, None, event.x, event.y)
        self.canvas.draw_idle()

    def _on_release(self, event):
        if not self._panning:
            return
        self._panning = False
        try:
            self.ax.end_pan()
        except Exception:
            pass
        self.canvas.setCursor(Qt.CursorShape.OpenHandCursor
                              if event.inaxes is self.ax else Qt.CursorShape.ArrowCursor)
        self._settle_timer.start()

    def _on_lim_changed(self, _ax):
        """Cualquier cambio de vista (pan, zoom, rueda, Inicio): mientras
        dura la interacción se ocultan las capas caras y se reprograma la
        reconstrucción de las capas por vista."""
        if self._in_draw or not self.has_data:
            return
        if not self._interacting:
            self._interacting = True
            self._set_heavy_visible(False)
        self._settle_timer.start()

    def _on_view_settled(self):
        self._interacting = False
        if not self.has_data or self._data is None:
            return
        self._set_heavy_visible(True)
        self._refresh_view_layers()
        self.canvas.draw_idle()

    def _set_heavy_visible(self, visible):
        """Oculta/muestra lo caro de dibujar en cada cuadro: los rótulos de
        Extra Info y las grillas de cartopy. Gridliner.draw no respeta
        set_visible, así que se apaga su actualización automática y se
        ocultan sus hijos (líneas reproyectadas en cada cuadro y etiquetas)."""
        for gl in self._gridliners:
            try:
                gl._auto_update = bool(visible)
                children = list(gl.xline_artists) + list(gl.yline_artists)
                try:
                    children += list(gl.label_artists)
                except Exception:
                    pass
                for c in children:
                    c.set_visible(visible)
            except Exception:
                pass
        for t in self._label_artists:
            t.set_visible(visible)

    # ----------------------------------------------------------- capas
    @staticmethod
    def _remove_all(artists):
        for a in artists:
            try:
                a.remove()
            except Exception:
                pass
        artists.clear()

    def draw_empty(self, message="Abra un archivo GRIB2 para comenzar"):
        self._settle_timer.stop()
        self._interacting = False
        self._in_draw = True
        try:
            self.ax.clear()
            self._base_artists, self._gridliners = [], []
            self._static_artists, self._view_artists, self._label_artists = [], [], []
            self._base_key = None
            self._data = None
            self._style_axes()
            self.has_data = False
            self._base_map()
            self.ax.text(0.5, 0.5, message, transform=self.ax.transAxes, ha="center",
                         va="center", color=self.pal["text_dim"], fontsize=self._fs(12))
            if self.use_cartopy:
                self.ax.set_global()
        finally:
            self._in_draw = False
        self.canvas.draw_idle()

    def _load_features(self):
        """Carga (y descarga si hace falta) las costas y fronteras de Natural
        Earth a 50 m. Se fuerza la lectura de las geometrías aquí para que un
        fallo de descarga (sin red, SSL) se capture y no rompa el dibujo."""
        if self._features is not None or self._features_error is not None:
            return
        try:
            coast = cfeature.NaturalEarthFeature("physical", "coastline", "50m",
                                                 facecolor="none")
            borders = cfeature.NaturalEarthFeature("cultural", "admin_0_boundary_lines_land",
                                                   "50m", facecolor="none")
            # Fuerza la descarga/lectura de los shapefiles ahora
            list(coast.geometries())
            list(borders.geometries())
            self._features = (coast, borders)
        except Exception as exc:
            self._features_error = f"{type(exc).__name__}: {exc}"

    def _base_map(self):
        """Costas y fronteras (cartopy) o aviso si no está disponible."""
        if self.use_cartopy:
            self._load_features()
            if self._features is not None:
                coast, borders = self._features
                self._base_artists.append(self.ax.add_feature(
                    coast, edgecolor=self.pal["coast"], facecolor="none",
                    linewidth=0.8, zorder=3))
                self._base_artists.append(self.ax.add_feature(
                    borders, edgecolor=self.pal["border"], facecolor="none",
                    linewidth=0.6, linestyle="-", zorder=3))
            else:
                self._base_artists.append(self.ax.text(
                    0.99, 0.99,
                    "No se pudieron cargar las costas de Natural Earth "
                    f"(¿sin conexión?): {self._features_error}",
                    transform=self.ax.transAxes, color=self.pal["warn"], fontsize=self._fs(7),
                    ha="right", va="top", zorder=10, wrap=True))
        else:
            self.ax.set_aspect("equal", adjustable="box")
            self._base_artists.append(self.ax.text(
                0.99, 0.99, "cartopy no instalado: mapa sin costas ni fronteras",
                transform=self.ax.transAxes, color=self.pal["warn"], fontsize=self._fs(7),
                ha="right", va="top", zorder=10))

    @staticmethod
    def grid_spacing(step):
        """(principal, secundaria) en grados para la grilla elegida: con 10°
        sólo principales cada 10; con 5°, principales cada 10 y secundarias
        (a rayas) cada 5; con 1°, principales cada 5 (10 y 5 iguales) y
        secundarias (punteadas) cada 1."""
        step = int(step) if step in (10, 5, 1) else 10
        if step == 10:
            return 10, None
        if step == 5:
            return 10, 5
        return 5, 1

    def _gridlines(self, dlon, dlat, fine, step=10):
        """Meridianos/paralelos de la grilla de grados elegida (principales
        etiquetadas en los bordes, secundarias con otro trazo) y,
        opcionalmente, la grilla fina del archivo."""
        major, minor = self.grid_spacing(step)
        if self.use_cartopy:
            gl = self.ax.gridlines(crs=self.data_crs, draw_labels=True,
                                   xlocs=mticker.MultipleLocator(major),
                                   ylocs=mticker.MultipleLocator(major),
                                   x_inline=False, y_inline=False, rotate_labels=False,
                                   color=self.pal["grid"], linewidth=0.9, linestyle="-",
                                   alpha=1.0, zorder=2)
            gl.top_labels = False
            gl.right_labels = False
            gl.xlabel_style = {"color": self.pal["text"], "size": self._fs(9)}
            gl.ylabel_style = {"color": self.pal["text"], "size": self._fs(9)}
            gl.xpadding = 6
            gl.ypadding = 6
            gl.n_steps = 30          # puntos por línea (100 por defecto): mucho más rápido
            self._gridliners.append(gl)
            if minor:
                gm = self.ax.gridlines(
                    crs=self.data_crs, draw_labels=False,
                    xlocs=mticker.MultipleLocator(minor),
                    ylocs=mticker.MultipleLocator(minor),
                    color=self.pal["grid"], linewidth=0.7,
                    linestyle="--" if minor == 5 else ":", alpha=0.85, zorder=2)
                gm.n_steps = 30
                self._gridliners.append(gm)
            if fine:
                # Grilla del archivo (p. ej. 0,25°): más tenue, punteada
                gf = self.ax.gridlines(
                    crs=self.data_crs, draw_labels=False,
                    xlocs=mticker.MultipleLocator(dlon),
                    ylocs=mticker.MultipleLocator(dlat),
                    color=self.pal["grid_fine"], linewidth=0.5,
                    linestyle=":", alpha=0.9, zorder=1)
                gf.n_steps = 30
                self._gridliners.append(gf)
        else:
            self.ax.xaxis.set_major_locator(mticker.MultipleLocator(major))
            self.ax.yaxis.set_major_locator(mticker.MultipleLocator(major))
            sub = minor or dlon
            self.ax.xaxis.set_minor_locator(mticker.MultipleLocator(sub))
            self.ax.yaxis.set_minor_locator(mticker.MultipleLocator(minor or dlat))
            self.ax.grid(True, which="major", color=self.pal["grid"], linewidth=0.9, linestyle="-")
            self.ax.grid(bool(minor) or fine, which="minor", color=self.pal["grid"],
                         linewidth=0.7, linestyle="--" if minor == 5 else ":")
            self.ax.set_xlabel("Longitud", fontsize=self._fs(9))
            self.ax.set_ylabel("Latitud", fontsize=self._fs(9))

    def _ensure_base(self, dlon, dlat, fine, step=10):
        """Reconstruye costas y grillas sólo si cambió algo que las afecta."""
        key = (self.proj_key, bool(fine), int(step), round(self.font_scale, 3), round(dlon, 6),
               round(dlat, 6))
        if key == self._base_key:
            return
        self._remove_all(self._base_artists)
        self._remove_all(self._gridliners)
        self._style_axes()
        self._base_map()
        self._gridlines(dlon, dlat, fine, step)
        self._base_key = key

    def _legend(self):
        handles = [Line2D([0], [0], color=c, lw=3) for c in SPEED_COLORS]
        leg = self.ax.legend(handles, SPEED_LABELS, loc="lower left", fontsize=self._fs(7),
                             title="Viento (kt)", title_fontsize=self._fs(8),
                             facecolor=self.pal["legend_bg"], edgecolor=self.pal["text_dim"],
                             labelcolor=self.pal["text"], framealpha=0.85)
        leg.get_title().set_color(self.pal["text"])
        leg.set_zorder(20)
        return leg

    # -------------------------------------------------------------- draw
    def draw(self, lats, lons, u, v, t, opts):
        """Dibuja el mapa.

        lats, lons : arrays 1D ascendentes.
        u, v       : componentes en m/s (arrays 2D o None).
        t          : temperatura en K (array 2D o None).
        opts       : dict con claves
            mode        'viento' | 'temperatura' | 'ambos'
            show_wind   bool  (False = capa de viento deshabilitada)
            extra_info  bool  (velocidad/temperatura al lado de cada barba)
            label_size  int   (pt base de los rótulos de Extra Info)
            label_units bool  (rótulos con unidad: "12 kt −45 °C")
            wind_style  'barbas' | 'flechas' | 'curvas' (representación del viento)
            grid        bool  (grilla fina del archivo)
            grid_step   10 | 5 | 1 (grilla de grados: principales y secundarias)
            fill        bool  (fondo de velocidad en contornos rellenos)
            stride      int   (submuestreo mínimo de barbas / flechas; en curvas
                               baja la densidad de líneas)
            keep_view   bool  (True = conservar la vista actual de zoom/pan)
            extent      [lonmin, lonmax, latmin, latmax] o None (= todo el dominio)
            title       str
        """
        self._settle_timer.stop()
        self._interacting = False
        self._in_draw = True
        try:
            ax = self.ax
            tr = self._tr()
            lats = np.asarray(lats, dtype=float)
            lons = np.asarray(lons, dtype=float)
            dlon = float(abs(lons[1] - lons[0])) if len(lons) > 1 else 1.0
            dlat = float(abs(lats[1] - lats[0])) if len(lats) > 1 else 1.0
            mode = opts.get("mode", "viento")
            show_wind = opts.get("show_wind", True)
            wind_ok = (u is not None and v is not None)
            temp_ok = t is not None
            draw_wind = show_wind and wind_ok and mode in ("viento", "ambos")
            draw_temp = show_wind and temp_ok and mode in ("temperatura", "ambos")

            spd = uk = vk = None
            if wind_ok:
                uk = np.ma.masked_invalid(u * MS_TO_KT)
                vk = np.ma.masked_invalid(v * MS_TO_KT)
                spd, _ = speed_dir_from_uv(u, v)
                spd = np.ma.masked_invalid(spd)
            self._data = {
                "lats": lats, "lons": lons, "dlon": dlon, "dlat": dlat,
                "u": u, "v": v, "t": t, "uk": uk, "vk": vk, "spd": spd,
                "draw_wind": draw_wind, "draw_temp": draw_temp,
                "extra": bool(opts.get("extra_info", False)) and show_wind,
                "stride": max(1, int(opts.get("stride", 1))),
                "style": opts.get("wind_style", "barbas"),
                "label_size": max(4, int(opts.get("label_size", LABEL_SIZE_DEFAULT))),
                "label_units": bool(opts.get("label_units", True)),
            }

            # Capa base (se conserva entre redibujos)
            self._ensure_base(dlon, dlat, opts.get("grid", False), opts.get("grid_step", 10))

            # Capa estática: se reconstruye entera
            self._remove_all(self._static_artists)
            self._remove_all(self._view_artists)
            self._remove_all(self._label_artists)
            X, Y = np.meshgrid(lons, lats)

            if draw_wind and opts.get("fill", False):
                top = max(float(np.nanmax(spd)) + 1.0, SPEED_BINS[-1] + 10.0)
                self._static_artists.append(ax.contourf(
                    X, Y, spd, levels=SPEED_BINS + [top], colors=SPEED_COLORS,
                    alpha=0.30, zorder=1, **tr))

            if draw_temp:
                tc = np.ma.masked_invalid(t - KELVIN)
                if tc.count() > 0:
                    tmin = math.floor(float(tc.min()) / 2.0) * 2.0
                    tmax = math.ceil(float(tc.max()) / 2.0) * 2.0
                    levels = np.arange(tmin, tmax + 0.1, 2.0)
                    if len(levels) >= 2:
                        cs = ax.contour(X, Y, tc, levels=levels, colors=TEMP_CONTOUR,
                                        linewidths=0.7, linestyles="solid", zorder=4, **tr)
                        self._static_artists.append(cs)
                        try:
                            labels = ax.clabel(cs, fmt="%d", fontsize=self._fs(7),
                                               colors=TEMP_LABEL, inline=True)
                            self._static_artists.extend(labels or [])
                        except Exception:
                            pass

            if draw_wind:
                self._static_artists.append(self._legend())
            # El título va sólo en el PNG exportado: en pantalla lo da STATUS
            self._title = opts.get("title", "")
            ax.set_title("")
            if not show_wind:
                self._static_artists.append(ax.text(
                    0.99, 0.01, "Capa de datos deshabilitada", transform=ax.transAxes,
                    ha="right", va="bottom", color=self.pal["warn"], fontsize=self._fs(8),
                    zorder=10))

            # Vista: se conserva, o se fija a la extensión pedida / al dominio
            if not (opts.get("keep_view") and self.has_data):
                extent = opts.get("extent") or [float(lons.min()), float(lons.max()),
                                                float(lats.min()), float(lats.max())]
                lon0, lon1, lat0, lat1 = extent
                if lon1 > lon0 and lat1 > lat0:
                    if self.use_cartopy:
                        ax.set_extent([lon0, lon1, lat0, lat1], crs=self.data_crs)
                    else:
                        ax.set_xlim(lon0, lon1)
                        ax.set_ylim(lat0, lat1)
                    self._fit_view_to_box()
            self.has_data = True

            # Capa por vista: barbas y rótulos de lo visible
            self._refresh_view_layers()
        finally:
            self._in_draw = False
        self.canvas.draw_idle()

    # ------------------------------------------------------ capas por vista
    def _visible_index_ranges(self):
        """Rangos de índices (i0, i1, j0, j1) de la grilla dentro de la vista
        actual, con un margen de una celda. Sin vista conocida, todo."""
        d = self._data
        lons, lats = d["lons"], d["lats"]
        ext = self.get_extent()
        if ext is None or not all(np.isfinite(ext)):
            return 0, len(lons), 0, len(lats)
        lon0, lon1, lat0, lat1 = ext
        i0 = int(np.searchsorted(lons, lon0 - d["dlon"], side="left"))
        i1 = int(np.searchsorted(lons, lon1 + d["dlon"], side="right"))
        j0 = int(np.searchsorted(lats, lat0 - d["dlat"], side="left"))
        j1 = int(np.searchsorted(lats, lat1 + d["dlat"], side="right"))
        return max(0, i0), min(len(lons), i1), max(0, j0), min(len(lats), j1)

    @staticmethod
    def _aligned_slice(start, stop, step):
        """slice(start', stop, step) con start' múltiplo de step, para que
        las barbas no 'salten' entre vistas."""
        first = ((start + step - 1) // step) * step
        return slice(first, stop, step)

    def _cell_px(self):
        """Píxeles entre dos puntos de grilla adyacentes en la vista actual
        (el menor de los dos ejes), medido en el centro de la vista."""
        d = self._data
        lons, lats = d["lons"], d["lats"]
        ext = self.get_extent()
        try:
            lon_c = float(np.clip((ext[0] + ext[1]) / 2.0, lons.min(), lons.max()))
            lat_c = float(np.clip((ext[2] + ext[3]) / 2.0, lats.min(), lats.max()))
        except Exception:
            lon_c, lat_c = float(lons[len(lons) // 2]), float(lats[len(lats) // 2])
        pl = np.array([lon_c, lon_c + d["dlon"], lon_c])
        pa = np.array([lat_c, lat_c, lat_c + d["dlat"]])
        if self.use_cartopy:
            xy = self.proj.transform_points(self.data_crs, pl, pa)[:, :2]
        else:
            xy = np.column_stack([pl, pa])
        if not np.isfinite(xy).all():
            return 0.0
        disp = self.ax.transData.transform(xy)
        dx = float(np.hypot(*(disp[1] - disp[0])))
        dy = float(np.hypot(*(disp[2] - disp[0])))
        return max(0.0, min(dx, dy))

    def _fit_glyph(self, nominal_px, cell_px, stride):
        """Elige el factor de tamaño del glifo (1 = nominal) y el raleo para
        que el glifo no ocupe más de GLYPH_FILL del espacio entre puntos: al
        alejar primero se achica (hasta GLYPH_MIN_FACTOR) y sólo después se
        ralea. Devuelve (factor, stride)."""
        if cell_px <= 0 or nominal_px <= 0:
            return 1.0, stride
        room = GLYPH_FILL * cell_px * stride
        if nominal_px <= room:
            return 1.0, stride
        f = max(GLYPH_MIN_FACTOR, room / nominal_px)
        glyph = nominal_px * f
        if glyph > room:
            stride = max(stride, int(math.ceil(glyph / (GLYPH_FILL * cell_px))))
        return f, stride

    def _refresh_view_layers(self):
        """Reconstruye la capa de viento y los rótulos para los puntos
        visibles. Al alejar la vista los glifos se achican hasta un mínimo
        y recién después se ralean (nunca más de MAX_BARBS / MAX_LABELS)."""
        d = self._data
        if d is None:
            return
        ax = self.ax
        tr = self._tr()
        self._remove_all(self._view_artists)
        self._remove_all(self._label_artists)
        if not (d["draw_wind"] or d["draw_temp"]):
            return
        i0, i1, j0, j1 = self._visible_index_ranges()
        n_vis = max(1, (i1 - i0) * (j1 - j0))
        stride = max(d["stride"], int(math.ceil(math.sqrt(n_vis / MAX_BARBS))))
        cell = self._cell_px()
        scale = max(0.8, self.font_scale)
        dpi = float(self.fig.dpi)
        style = d.get("style", "barbas")
        if style == "flechas":
            nominal = ARROW_LEN_IN * scale * dpi
        elif style == "barbas":
            nominal = BARB_LENGTH_PT * scale * BARB_PX_PER_PT * dpi / 72.0
        else:
            nominal = 0.0
        factor, stride = self._fit_glyph(nominal, cell, stride)
        if style == "curvas" and cell > 0:
            factor = float(np.clip(cell / STREAM_NOMINAL_CELL_PX, 0.45, 1.0))
        si = self._aligned_slice(i0, i1, stride)
        sj = self._aligned_slice(j0, j1, stride)
        lons, lats = d["lons"], d["lats"]
        X, Y = np.meshgrid(lons[si], lats[sj])
        if X.size == 0:
            return

        if d["draw_wind"]:
            self._draw_wind(X, Y, sj, si, stride, i0, i1, j0, j1, factor)

        if d["extra"]:
            self._draw_labels(X, stride, i0, i1, j0, j1, cell)

    _textpath_cache = {}

    @classmethod
    def _text_path(cls, text, size):
        """Trazado vectorial de un rótulo (en puntos), con caché: los textos
        se repiten mucho («12 kt», «−45 °C»)."""
        key = (text, round(size, 2))
        path = cls._textpath_cache.get(key)
        if path is None:
            if len(cls._textpath_cache) > 4000:
                cls._textpath_cache.clear()
            path = TextPath((0, 0), text, size=size, prop=FontProperties())
            cls._textpath_cache[key] = path
        return path

    def _draw_labels(self, X, stride, i0, i1, j0, j1, cell):
        """Rótulos de Extra Info como UNA colección de trazados (no un
        artista de texto por punto): matplotlib dibuja cientos de textos
        uno por uno, con layout y rasterizado de glifos cada vez; una
        PathCollection se transforma y pinta de una sola pasada."""
        d = self._data
        ax = self.ax
        dpi = float(self.fig.dpi)
        fs = self._fs(d["label_size"])
        fs_px = fs * dpi / 72.0
        n_chars = 0
        if d["draw_wind"]:
            n_chars += 5 if d["label_units"] else 2
        if d["draw_temp"]:
            n_chars += 6 if d["label_units"] else 4
        label_w = 0.62 * fs_px * (n_chars + 1)
        label_h = 1.3 * fs_px
        k = int(math.ceil(math.sqrt(X.size / MAX_LABELS)))
        stride_l = stride * max(1, k)
        if cell > 0:
            stride_l = max(stride_l, int(math.ceil(label_w / cell)), int(math.ceil(label_h / cell)))
        lons, lats = d["lons"], d["lats"]
        si_l = self._aligned_slice(i0, i1, stride_l)
        sj_l = self._aligned_slice(j0, j1, stride_l)
        Xl, Yl = np.meshgrid(lons[si_l], lats[sj_l])
        if Xl.size == 0:
            self.label_texts, self.label_fontsize = [], fs
            return
        off_x = 0.15 * d["dlon"] * stride
        off_y = 0.30 * d["dlat"] * stride       # por encima del glifo, que está centrado en el punto
        u_kt = " kt" if d["label_units"] else ""
        u_c = " °C" if d["label_units"] else "°"
        # Valores y colores en bloque (matrices), textos en una pasada corta
        spd_s = None
        if d["draw_wind"]:
            spd_s = np.ma.filled(d["spd"][sj_l, si_l].astype(float), np.nan).ravel()
        t_s = None
        if d["draw_temp"]:
            t_s = (np.asarray(d["t"][sj_l, si_l], dtype=float) - KELVIN).ravel()
        xs = (Xl + off_x).ravel()
        ys = (Yl + off_y).ravel()
        n = xs.size
        colors = np.tile(np.array(matplotlib.colors.to_rgba(self.pal["text"])), (n, 1))
        if spd_s is not None:
            ok = np.isfinite(spd_s)
            colors[ok] = SPEED_CMAP(SPEED_NORM(spd_s[ok]))
        paths, offsets, facecolors, texts = [], [], [], []
        for i in range(n):
            parts = []
            if spd_s is not None and np.isfinite(spd_s[i]):
                parts.append(f"{spd_s[i]:.0f}{u_kt}")
            if t_s is not None and np.isfinite(t_s[i]):
                parts.append(f"{t_s[i]:.0f}{u_c}")
            if not parts:
                continue
            text = "  ".join(parts)
            paths.append(self._text_path(text, fs))
            offsets.append((xs[i], ys[i]))
            facecolors.append(colors[i])
            texts.append(text)
        self.label_texts, self.label_fontsize = texts, fs
        if not paths:
            return
        if self.use_cartopy:
            offset_tr = self.data_crs._as_mpl_transform(ax)
        else:
            offset_tr = ax.transData
        coll = PathCollection(paths, offsets=np.asarray(offsets), offset_transform=offset_tr,
                              facecolors=facecolors, edgecolors="none", linewidths=0,
                              zorder=6)
        coll.set_transform(Affine2D().scale(dpi / 72.0))   # trazados en puntos → píxeles
        coll.set_clip_box(ax.bbox)
        coll.set_clip_on(True)
        ax.add_collection(coll, autolim=False)
        self._label_artists.append(coll)

    def _draw_wind(self, X, Y, sj, si, stride, i0, i1, j0, j1, factor=1.0):
        """Capa de viento según el estilo: barbas, flechas (vectores) o
        curvas (líneas de corriente). Las tres usan la escala fija de colores
        por velocidad. `factor` (≤ 1) achica los glifos al alejar la vista."""
        d = self._data
        ax = self.ax
        tr = self._tr()
        style = d.get("style", "barbas")
        if style == "curvas":
            self._draw_streamlines(stride, i0, i1, j0, j1, factor)
            return
        if style == "flechas":
            # Flechas de largo fijo que apuntan hacia donde sopla el viento;
            # la velocidad va sólo en el color. Sin flecha donde hay calma.
            scale = max(0.8, self.font_scale) * factor
            uk, vk, spd = d["uk"][sj, si], d["vk"][sj, si], d["spd"][sj, si]
            with np.errstate(all="ignore"):
                mag = np.ma.masked_less(spd, CALM_KT)
                ue = uk / mag
                ve = vk / mag
            if ue.count() == 0:
                return
            self._view_artists.append(ax.quiver(
                X, Y, ue, ve, spd, cmap=SPEED_CMAP, norm=SPEED_NORM,
                pivot="middle", scale_units="inches", scale=1.0 / (ARROW_LEN_IN * scale),
                width=0.003 * max(0.55, factor), headwidth=3.5, headlength=4.5,
                headaxislength=4.0, minlength=0.0, zorder=5, clip_on=True, **tr))
            return
        uk, vk, spd = d["uk"][sj, si], d["vk"][sj, si], d["spd"][sj, si]
        self._view_artists.append(ax.barbs(
            X, Y, uk, vk, spd, cmap=SPEED_CMAP, norm=SPEED_NORM,
            length=BARB_LENGTH_PT * max(0.8, self.font_scale) * factor,
            linewidth=0.7 * max(0.55, factor), pivot="middle",
            flip_barb=(Y < 0), zorder=5, clip_on=True, **tr))

    def _draw_streamlines(self, stride, i0, i1, j0, j1, factor=1.0):
        """Líneas de corriente coloreadas por velocidad. `Densidad` N baja la
        densidad de líneas (2 / N).

        El campo se muestrea (bilineal) sobre una grilla regular de la
        proyección que cubre la vista, se rotan los vectores con cartopy y
        las trayectorias se integran todas a la vez con numpy
        (`integrate_streamlines`), en lugar del integrador punto por punto
        de matplotlib."""
        d = self._data
        ax = self.ax
        lons, lats = d["lons"], d["lats"]
        uk = np.ma.filled(d["uk"].astype(float), np.nan)
        vk = np.ma.filled(d["vk"].astype(float), np.nan)
        spd = np.ma.filled(d["spd"].astype(float), np.nan)
        if not np.isfinite(uk).any():
            return
        density = max(0.25, 2.0 / max(1, stride))
        scale = max(0.8, self.font_scale) * factor
        try:
            if self.use_cartopy:
                proj = ax.projection
                x0, x1, y0, y1 = ax.get_extent(proj)
                if not (x1 > x0 and y1 > y0):
                    return
                nx = 120
                ny = int(np.clip(nx * (y1 - y0) / (x1 - x0), 30, 240))
                xs = np.linspace(x0, x1, nx)
                ys = np.linspace(y0, y1, ny)
                XP, YP = np.meshgrid(xs, ys)
                ll = self.data_crs.transform_points(proj, XP, YP)
                qlon, qlat = ll[..., 0], ll[..., 1]
                ok = np.isfinite(qlon) & np.isfinite(qlat)
                qlon = np.where(ok, qlon, lons[0])
                qlat = np.where(ok, qlat, lats[0])
                if lons.max() > 180.0:
                    qlon = np.where(qlon < 0.0, qlon + 360.0, qlon)
                elif lons.min() < 0.0:
                    qlon = np.where(qlon > 180.0, qlon - 360.0, qlon)
                us = _sample_bilinear(lons, lats, uk, qlon, qlat)
                vs = _sample_bilinear(lons, lats, vk, qlon, qlat)
                ss = _sample_bilinear(lons, lats, spd, qlon, qlat)
                us[~ok] = np.nan
                vs[~ok] = np.nan
                ss[~ok] = np.nan
                good = np.isfinite(us) & np.isfinite(vs)
                if good.sum() < 4:
                    return
                with np.errstate(all="ignore"):
                    up, vp = proj.transform_vectors(self.data_crs, qlon, qlat,
                                                    np.where(good, us, 0.0), np.where(good, vs, 0.0))
                up = np.where(good, up, np.nan)
                vp = np.where(good, vp, np.nan)
            else:
                # Grilla lat/lon ya regular: recorte visible
                xs, ys = lons[i0:i1], lats[j0:j1]
                if len(xs) < 2 or len(ys) < 2:
                    return
                up, vp, ss = uk[j0:j1, i0:i1], vk[j0:j1, i0:i1], spd[j0:j1, i0:i1]
            trajs = integrate_streamlines(xs, ys, up, vp, density=density)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Líneas de corriente: %s", exc)
            return
        if not trajs:
            return
        # Velocidad a lo largo de cada trayectoria (color por segmento)
        segs, vals, trajs_v = [], [], []
        for pts in trajs:
            v = _sample_bilinear(xs, ys, ss, pts[:, 0], pts[:, 1])
            seg = np.stack([pts[:-1], pts[1:]], axis=1)
            segs.append(seg)
            vals.append(0.5 * (v[:-1] + v[1:]))
            trajs_v.append((pts, v))
        segs = np.concatenate(segs)
        vals = np.concatenate(vals)
        lc = LineCollection(segs, cmap=SPEED_CMAP, norm=SPEED_NORM, linewidths=1.1 * scale,
                            zorder=5, transform=ax.transData)
        lc.set_array(np.ma.masked_invalid(vals))
        lc.set_clip_box(ax.bbox)
        lc.set_clip_on(True)
        ax.add_collection(lc, autolim=False)
        self._view_artists.append(lc)
        self._view_artists.extend(self._stream_arrows(trajs_v, scale))

    def _stream_arrows(self, trajs, scale):
        """Flechas de sentido embebidas en las líneas de corriente, una cada
        STREAM_ARROW_PX píxeles de cada trayectoria, del color de la
        velocidad local. `trajs`: lista de (puntos (n, 2), velocidad (n,)).

        Todas las puntas van en UNA LineCollection de «chevrones» (dos
        segmentos por flecha) calculados con numpy en coordenadas de datos a
        partir del tamaño en píxeles, en vez de un FancyArrowPatch por flecha
        (cada parche se transformaba y dibujaba por separado)."""
        ax = self.ax
        spacing = STREAM_ARROW_PX * scale
        head = 7.0 * scale                       # largo de las alas (px)
        tips, dirs, vals = [], [], []
        for pts, v in trajs:
            if len(pts) < 3:
                continue
            v = np.asarray(v, dtype=float)
            disp = ax.transData.transform(pts)
            d = np.hypot(np.diff(disp[:, 0]), np.diff(disp[:, 1]))
            cum = np.concatenate([[0.0], np.cumsum(d)])
            total = cum[-1]
            if total < spacing * 0.6:
                targets = np.array([total / 2.0])
            else:
                n = int(total // spacing)
                off = (total - n * spacing) / 2.0
                targets = off + spacing * (np.arange(max(1, n)) + 0.5)
            i = np.clip(np.searchsorted(cum, targets) - 1, 0, len(pts) - 2)
            seg = disp[i + 1] - disp[i]
            norm = np.hypot(seg[:, 0], seg[:, 1])
            ok = norm > 1e-6
            if not ok.any():
                continue
            tips.append(disp[i + 1][ok])
            dirs.append(seg[ok] / norm[ok][:, None])
            vals.append(v[np.minimum(i + 1, len(v) - 1)][ok])
        if not tips:
            return []
        tips = np.concatenate(tips)          # (M, 2) en píxeles
        dirs = np.concatenate(dirs)
        vals = np.concatenate(vals)
        # Alas a ±28° de la dirección, hacia atrás desde la punta
        ang = np.deg2rad(28.0)
        c, s_ = np.cos(ang), np.sin(ang)
        left = np.column_stack([-dirs[:, 0] * c + dirs[:, 1] * s_, -dirs[:, 0] * s_ - dirs[:, 1] * c])
        right = np.column_stack([-dirs[:, 0] * c - dirs[:, 1] * s_, dirs[:, 0] * s_ - dirs[:, 1] * c])
        a = tips + head * left
        b = tips + head * right
        inv = ax.transData.inverted()
        segs = np.stack([np.stack([inv.transform(a), inv.transform(tips)], axis=1),
                         np.stack([inv.transform(b), inv.transform(tips)], axis=1)], axis=1)
        segs = segs.reshape(-1, 2, 2)            # (2M, 2, 2) en datos
        colors = SPEED_CMAP(SPEED_NORM(np.repeat(np.nan_to_num(vals, nan=0.0), 2)))
        colors[np.repeat(~np.isfinite(vals), 2)] = matplotlib.colors.to_rgba(self.pal["text"])
        lc = LineCollection(segs, colors=colors, linewidths=1.5 * scale, zorder=6,
                            transform=ax.transData, capstyle="round")
        lc.set_clip_box(ax.bbox)
        lc.set_clip_on(True)
        ax.add_collection(lc, autolim=False)
        return [lc]

    def save_png(self, path, dpi=150):
        """Guarda la vista actual con fondo opaco (el alfa es sólo para la
        ventana)."""
        fa, aa = self.fig.patch.get_alpha(), self.ax.patch.get_alpha()
        self.fig.patch.set_alpha(1.0)
        self.ax.patch.set_alpha(1.0)
        title = getattr(self, "_title", "")
        try:
            if title:
                self.ax.set_title(title, color=self.pal["text"], fontsize=self._fs(10),
                                  loc="left", wrap=True)
                self._apply_margins(with_title=True)
            self.fig.savefig(path, dpi=dpi, facecolor=self.pal["bg"])
        finally:
            if title:
                self.ax.set_title("")
                self._apply_margins()
            self.fig.patch.set_alpha(fa)
            self.ax.patch.set_alpha(aa)
