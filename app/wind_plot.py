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
from matplotlib.transforms import Bbox  # noqa: E402

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
MAX_BARBS = 2500        # barbas visibles como máximo (se ralea automáticamente)
MAX_LABELS = 900        # rótulos de Extra Info visibles como máximo
SETTLE_MS = 150         # espera tras el último cambio de vista para reconstruir


class WindPlot:
    """Encapsula la figura matplotlib (con cartopy si está disponible) y
    dibuja barbas, contornos, leyenda y grilla sobre un fondo oscuro."""

    def __init__(self, master=None):
        self.pal = dict(DEFAULT_PALETTE)
        self.font_scale = 1.0           # multiplicador de todas las fuentes del mapa
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
        self._label_artists = []        # rótulos de Extra Info
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
        self.fig.subplots_adjust(left=0.045, right=0.995, top=0.955, bottom=0.055)
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

    def _on_resize(self, _event):
        """Al cambiar el tamaño del canvas se vuelve a llenar el área."""
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

    def _gridlines(self, dlon, dlat, fine):
        """Meridianos/paralelos cada 10° con etiquetas y, opcionalmente, la
        grilla fina del archivo."""
        if self.use_cartopy:
            # Meridianos y paralelos cada 10°, etiquetados en los bordes del
            # mapa (también en proyecciones no rectangulares)
            gl = self.ax.gridlines(crs=self.data_crs, draw_labels=True,
                                   xlocs=mticker.MultipleLocator(10),
                                   ylocs=mticker.MultipleLocator(10),
                                   x_inline=False, y_inline=False, rotate_labels=False,
                                   color=self.pal["grid"], linewidth=0.8, linestyle="-",
                                   alpha=0.9, zorder=2)
            gl.top_labels = False
            gl.right_labels = False
            gl.xlabel_style = {"color": self.pal["text"], "size": self._fs(9)}
            gl.ylabel_style = {"color": self.pal["text"], "size": self._fs(9)}
            gl.n_steps = 30          # puntos por línea (100 por defecto): mucho más rápido
            self._gridliners.append(gl)
            if fine:
                # Grilla del archivo (p. ej. 1°): más tenue, punteada
                gf = self.ax.gridlines(
                    crs=self.data_crs, draw_labels=False,
                    xlocs=mticker.MultipleLocator(dlon),
                    ylocs=mticker.MultipleLocator(dlat),
                    color=self.pal["grid_fine"], linewidth=0.6,
                    linestyle=":", alpha=0.9, zorder=1)
                gf.n_steps = 30
                self._gridliners.append(gf)
        else:
            self.ax.xaxis.set_major_locator(mticker.MultipleLocator(10))
            self.ax.yaxis.set_major_locator(mticker.MultipleLocator(10))
            self.ax.xaxis.set_minor_locator(mticker.MultipleLocator(dlon))
            self.ax.yaxis.set_minor_locator(mticker.MultipleLocator(dlat))
            self.ax.grid(True, which="major", color=self.pal["grid"], linewidth=0.8, linestyle="-")
            self.ax.grid(fine, which="minor", color=self.pal["grid_fine"], linewidth=0.6,
                         linestyle=":")
            self.ax.set_xlabel("Longitud", fontsize=self._fs(9))
            self.ax.set_ylabel("Latitud", fontsize=self._fs(9))

    def _ensure_base(self, dlon, dlat, fine):
        """Reconstruye costas y grillas sólo si cambió algo que las afecta."""
        key = (self.proj_key, bool(fine), round(self.font_scale, 3), round(dlon, 6),
               round(dlat, 6))
        if key == self._base_key:
            return
        self._remove_all(self._base_artists)
        self._remove_all(self._gridliners)
        self._style_axes()
        self._base_map()
        self._gridlines(dlon, dlat, fine)
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
            grid        bool  (grilla fina del archivo)
            fill        bool  (fondo de velocidad en contornos rellenos)
            stride      int   (submuestreo mínimo de barbas)
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
            }

            # Capa base (se conserva entre redibujos)
            self._ensure_base(dlon, dlat, opts.get("grid", False))

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
            ax.set_title(opts.get("title", ""), color=self.pal["text"],
                         fontsize=self._fs(10), loc="left", wrap=True)
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

    def _refresh_view_layers(self):
        """Reconstruye barbas y rótulos para los puntos visibles, con raleo
        automático para no superar MAX_BARBS / MAX_LABELS."""
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
        si = self._aligned_slice(i0, i1, stride)
        sj = self._aligned_slice(j0, j1, stride)
        lons, lats = d["lons"], d["lats"]
        X, Y = np.meshgrid(lons[si], lats[sj])
        if X.size == 0:
            return

        if d["draw_wind"]:
            uk, vk, spd = d["uk"][sj, si], d["vk"][sj, si], d["spd"][sj, si]
            self._view_artists.append(ax.barbs(
                X, Y, uk, vk, spd, cmap=SPEED_CMAP, norm=SPEED_NORM,
                length=5.5 * max(0.8, self.font_scale), linewidth=0.7, pivot="middle",
                flip_barb=(Y < 0), zorder=5, clip_on=True, **tr))

        if d["extra"]:
            n_barbs = X.size
            k = int(math.ceil(math.sqrt(n_barbs / MAX_LABELS)))
            stride_l = stride * max(1, k)
            si_l = self._aligned_slice(i0, i1, stride_l)
            sj_l = self._aligned_slice(j0, j1, stride_l)
            Xl, Yl = np.meshgrid(lons[si_l], lats[sj_l])
            spd_s = d["spd"][sj_l, si_l] if d["draw_wind"] else None
            t_s = (d["t"][sj_l, si_l] - KELVIN) if d["draw_temp"] else None
            off_x = 0.12 * d["dlon"] * stride_l
            off_y = 0.12 * d["dlat"] * stride_l
            fs = self._fs(6)
            nj, ni = Xl.shape
            for jj in range(nj):
                for ii in range(ni):
                    parts = []
                    col = self.pal["text"]
                    if spd_s is not None and not np.ma.is_masked(spd_s[jj, ii]):
                        s_val = float(spd_s[jj, ii])
                        parts.append(f"{s_val:.0f}")
                        col = speed_color(s_val)
                    if t_s is not None and not np.isnan(t_s[jj, ii]):
                        parts.append(f"{t_s[jj, ii]:.0f}°")
                    if parts:
                        txt = ax.text(Xl[jj, ii] + off_x, Yl[jj, ii] + off_y, " ".join(parts),
                                      fontsize=fs, color=col, ha="left", va="bottom",
                                      zorder=6, **tr)
                        # Recorte al área del mapa (con cartopy sólo funciona por bbox)
                        txt.set_clip_box(ax.bbox)
                        txt.set_clip_on(True)
                        self._label_artists.append(txt)

    def save_png(self, path, dpi=150):
        """Guarda la vista actual con fondo opaco (el alfa es sólo para la
        ventana)."""
        fa, aa = self.fig.patch.get_alpha(), self.ax.patch.get_alpha()
        self.fig.patch.set_alpha(1.0)
        self.ax.patch.set_alpha(1.0)
        try:
            self.fig.savefig(path, dpi=dpi, facecolor=self.pal["bg"])
        finally:
            self.fig.patch.set_alpha(fa)
            self.ax.patch.set_alpha(aa)
