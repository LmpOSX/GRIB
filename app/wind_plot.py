# -*- coding: utf-8 -*-
"""
Dibujo del mapa de viento y temperatura con matplotlib (backend QtAgg) y
cartopy opcional. No conoce la ventana ni los controles: recibe arrays y un
diccionario de opciones y dibuja sobre su propia figura.
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


# ---------------------------------------------------------------------------
# Dibujo del mapa
# ---------------------------------------------------------------------------
class WindPlot:
    """Encapsula la figura matplotlib (con cartopy si está disponible) y
    dibuja barbas, contornos, leyenda y grilla sobre un fondo oscuro."""

    def __init__(self, master=None):
        self.pal = dict(DEFAULT_PALETTE)
        self.fig = Figure(figsize=(9, 7), dpi=100, facecolor=self.pal["bg"])
        self.canvas = FigureCanvasQTAgg(self.fig)
        if master is not None:
            self.canvas.setParent(master)
        self.use_cartopy = HAVE_CARTOPY
        self.proj = ccrs.PlateCarree() if self.use_cartopy else None
        self.ax = None
        self.has_data = False
        self._features = None           # (costas, fronteras) ya cargadas
        self._features_error = None     # texto del error si no se pudieron cargar
        self._make_axes()
        self._style_axes()
        self.draw_empty()

    # ----------------------------------------------------------- helpers
    def _make_axes(self):
        self.fig.clear()
        if self.use_cartopy:
            self.ax = self.fig.add_subplot(1, 1, 1, projection=self.proj)
        else:
            self.ax = self.fig.add_subplot(1, 1, 1)
        self.fig.subplots_adjust(left=0.06, right=0.99, top=0.95, bottom=0.07)

    def _style_axes(self):
        ax = self.ax
        self.fig.set_facecolor(self.pal["bg"])
        ax.set_facecolor(self.pal["ax_bg"])
        for sp in ax.spines.values():
            sp.set_edgecolor(self.pal["text_dim"])
        ax.tick_params(colors=self.pal["text"], labelsize=8)
        ax.xaxis.label.set_color(self.pal["text"])
        ax.yaxis.label.set_color(self.pal["text"])

    def set_palette(self, **colors):
        """Reemplaza colores de la paleta (claves de DEFAULT_PALETTE). El
        cambio se ve en el próximo draw()/draw_empty()."""
        for k, v in colors.items():
            if k in self.pal and v:
                self.pal[k] = v

    def _tr(self):
        """kwargs de transformación para cartopy (vacío sin cartopy)."""
        return {"transform": self.proj} if self.use_cartopy else {}

    def get_extent(self):
        """Extensión actual [lonmin, lonmax, latmin, latmax]."""
        try:
            if self.use_cartopy:
                return list(self.ax.get_extent(crs=self.proj))
            x0, x1 = self.ax.get_xlim()
            y0, y1 = self.ax.get_ylim()
            return [x0, x1, y0, y1]
        except Exception:
            return None

    def set_extent(self, extent):
        """Fija la extensión [lonmin, lonmax, latmin, latmax]."""
        lon0, lon1, lat0, lat1 = extent
        if lon1 <= lon0 or lat1 <= lat0:
            return
        if self.use_cartopy:
            self.ax.set_extent([lon0, lon1, lat0, lat1], crs=self.proj)
        else:
            self.ax.set_xlim(lon0, lon1)
            self.ax.set_ylim(lat0, lat1)
        self.canvas.draw_idle()

    def draw_empty(self, message="Abra un archivo GRIB2 para comenzar"):
        self.ax.clear()
        self._style_axes()
        self.has_data = False
        self._base_map()
        self.ax.text(0.5, 0.5, message, transform=self.ax.transAxes, ha="center",
                     va="center", color=self.pal["text_dim"], fontsize=12)
        if self.use_cartopy:
            self.ax.set_global()
        self.canvas.draw_idle()

    def _load_features(self):
        """Carga (y descarga si hace falta) las costas y fronteras de Natural
        Earth a 50 m. Se fuerza la lectura de las geometrías aquí para que un
        fallo de descarga (sin red, SSL) se capture y no rompa el dibujo."""
        if self._features is not None or self._features_error is not None:
            return
        try:
            coast = cfeature.NaturalEarthFeature("physical", "coastline", "50m",
                                                 edgecolor=self.pal["coast"], facecolor="none")
            borders = cfeature.NaturalEarthFeature("cultural", "admin_0_boundary_lines_land",
                                                   "50m", edgecolor=self.pal["border"],
                                                   facecolor="none")
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
                self.ax.add_feature(coast, linewidth=0.8, zorder=3)
                self.ax.add_feature(borders, linewidth=0.6, linestyle="-", zorder=3)
            else:
                self.ax.text(0.99, 0.99,
                             "No se pudieron cargar las costas de Natural Earth "
                             f"(¿sin conexión?): {self._features_error}",
                             transform=self.ax.transAxes, color=self.pal["warn"], fontsize=7,
                             ha="right", va="top", zorder=10, wrap=True)
        else:
            self.ax.set_aspect("equal", adjustable="box")
            self.ax.text(0.99, 0.99, "cartopy no instalado: mapa sin costas ni fronteras",
                         transform=self.ax.transAxes, color=self.pal["warn"], fontsize=7,
                         ha="right", va="top", zorder=10)

    def _gridlines(self, lons, lats, fine):
        """Meridianos/paralelos cada 10° con etiquetas y, opcionalmente, la
        grilla fina del archivo."""
        dlon = float(abs(lons[1] - lons[0])) if len(lons) > 1 else 1.0
        dlat = float(abs(lats[1] - lats[0])) if len(lats) > 1 else 1.0
        if self.use_cartopy:
            gl = self.ax.gridlines(crs=self.proj, draw_labels=True,
                                   xlocs=mticker.MultipleLocator(10),
                                   ylocs=mticker.MultipleLocator(10),
                                   color=self.pal["grid"], linewidth=0.6, linestyle="--", zorder=2)
            gl.top_labels = False
            gl.right_labels = False
            gl.xlabel_style = {"color": self.pal["text"], "size": 8}
            gl.ylabel_style = {"color": self.pal["text"], "size": 8}
            if fine:
                self.ax.gridlines(crs=self.proj, draw_labels=False,
                                  xlocs=mticker.MultipleLocator(dlon),
                                  ylocs=mticker.MultipleLocator(dlat),
                                  color=self.pal["grid_fine"], linewidth=0.4, zorder=1)
        else:
            self.ax.xaxis.set_major_locator(mticker.MultipleLocator(10))
            self.ax.yaxis.set_major_locator(mticker.MultipleLocator(10))
            self.ax.xaxis.set_minor_locator(mticker.MultipleLocator(dlon))
            self.ax.yaxis.set_minor_locator(mticker.MultipleLocator(dlat))
            self.ax.grid(True, which="major", color=self.pal["grid"], linewidth=0.6, linestyle="--")
            if fine:
                self.ax.grid(True, which="minor", color=self.pal["grid_fine"], linewidth=0.4)
            self.ax.set_xlabel("Longitud")
            self.ax.set_ylabel("Latitud")

    def _legend(self):
        handles = [Line2D([0], [0], color=c, lw=3) for c in SPEED_COLORS]
        leg = self.ax.legend(handles, SPEED_LABELS, loc="lower left", fontsize=7,
                             title="Viento (kt)", title_fontsize=8, facecolor=self.pal["legend_bg"],
                             edgecolor=self.pal["text_dim"], labelcolor=self.pal["text"],
                             framealpha=0.85)
        leg.get_title().set_color(self.pal["text"])
        leg.set_zorder(20)

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
            stride      int   (submuestreo de barbas)
            extent      [lonmin, lonmax, latmin, latmax] o None
            title       str
        """
        ax = self.ax
        ax.clear()
        self._style_axes()
        self._base_map()
        tr = self._tr()

        X, Y = np.meshgrid(lons, lats)
        stride = max(1, int(opts.get("stride", 1)))
        sl = (slice(None, None, stride), slice(None, None, stride))
        mode = opts.get("mode", "viento")
        show_wind = opts.get("show_wind", True)
        wind_ok = (u is not None and v is not None)
        temp_ok = t is not None
        draw_wind = show_wind and wind_ok and mode in ("viento", "ambos")
        draw_temp = show_wind and temp_ok and mode in ("temperatura", "ambos")
        extra = opts.get("extra_info", False)

        spd = direc = None
        if wind_ok:
            uk = np.ma.masked_invalid(u * MS_TO_KT)
            vk = np.ma.masked_invalid(v * MS_TO_KT)
            spd, direc = speed_dir_from_uv(u, v)
            spd = np.ma.masked_invalid(spd)

        # Fondo de velocidad
        if draw_wind and opts.get("fill", False):
            top = max(float(np.nanmax(spd)) + 1.0, SPEED_BINS[-1] + 10.0)
            ax.contourf(X, Y, spd, levels=SPEED_BINS + [top], colors=SPEED_COLORS,
                        alpha=0.30, zorder=1, **tr)

        # Contornos de temperatura cada 2 °C
        if draw_temp:
            tc = np.ma.masked_invalid(t - KELVIN)
            if tc.count() > 0:
                tmin = math.floor(float(tc.min()) / 2.0) * 2.0
                tmax = math.ceil(float(tc.max()) / 2.0) * 2.0
                levels = np.arange(tmin, tmax + 0.1, 2.0)
                if len(levels) >= 2:
                    cs = ax.contour(X, Y, tc, levels=levels, colors=TEMP_CONTOUR,
                                    linewidths=0.7, linestyles="solid", zorder=4, **tr)
                    try:
                        ax.clabel(cs, fmt="%d", fontsize=7, colors=TEMP_LABEL, inline=True)
                    except Exception:
                        pass

        # Barbas de viento coloreadas por velocidad
        if draw_wind:
            ax.barbs(X[sl], Y[sl], uk[sl], vk[sl], spd[sl], cmap=SPEED_CMAP, norm=SPEED_NORM,
                     length=5.5, linewidth=0.7, pivot="middle", flip_barb=(Y[sl] < 0),
                     zorder=5, clip_on=True, **tr)

        # Extra Info: valores numéricos al lado de cada barba
        if extra and show_wind and (draw_wind or draw_temp):
            dlon = float(abs(lons[1] - lons[0])) if len(lons) > 1 else 1.0
            dlat = float(abs(lats[1] - lats[0])) if len(lats) > 1 else 1.0
            xs, ys = X[sl], Y[sl]
            spd_s = spd[sl] if (draw_wind and spd is not None) else None
            t_s = (t[sl] - KELVIN) if draw_temp else None
            nj, ni = xs.shape
            for j in range(nj):
                for i in range(ni):
                    parts = []
                    col = self.pal["text"]
                    if spd_s is not None and not np.ma.is_masked(spd_s[j, i]):
                        s_val = float(spd_s[j, i])
                        parts.append(f"{s_val:.0f}")
                        col = speed_color(s_val)
                    if t_s is not None and not np.isnan(t_s[j, i]):
                        parts.append(f"{t_s[j, i]:.0f}°")
                    if parts:
                        txt = ax.text(xs[j, i] + 0.12 * dlon * stride,
                                      ys[j, i] + 0.12 * dlat * stride,
                                      " ".join(parts), fontsize=6, color=col, ha="left",
                                      va="bottom", zorder=6, **tr)
                        # Recorta el texto al área del mapa (no se dibuja fuera).
                        # Con cartopy sólo funciona el recorte por bbox.
                        txt.set_clip_box(ax.bbox)
                        txt.set_clip_on(True)

        # Grilla, leyenda, título
        self._gridlines(lons, lats, opts.get("grid", False))
        if draw_wind:
            self._legend()
        ax.set_title(opts.get("title", ""), color=self.pal["text"], fontsize=10, loc="left")
        if not show_wind:
            ax.text(0.99, 0.01, "Capa de datos deshabilitada", transform=ax.transAxes,
                    ha="right", va="bottom", color=self.pal["warn"], fontsize=8, zorder=10)

        # Extensión
        extent = opts.get("extent")
        if extent is None:
            extent = [float(lons.min()), float(lons.max()), float(lats.min()), float(lats.max())]
        self.set_extent(extent)
        self.has_data = True
        self.canvas.draw_idle()

    def save_png(self, path, dpi=150):
        self.fig.savefig(path, dpi=dpi, facecolor=self.fig.get_facecolor())


