# -*- coding: utf-8 -*-
"""Preferencias del visor, en pestañas:

* Apariencia: color de acento (con vista previa en vivo) y transparencia.
* Mapa: proyección y valores iniciales de VIENTO y MAPA (viento, Extra Info, grilla, fondo,
  densidad).
* Fuentes: habilitar cada fuente, sus parámetros, credenciales y prueba.
* Descarga: plazos y destino por defecto de «Obtener datos…», caché.
* Áreas / FIR: tabla de áreas de descarga (recuadros por FIR), margen y
  formato de coordenadas; exportar / importar la tabla; y la tabla de
  grillas con nombre (FDP Arg y las propias).
* Guardar: valores por defecto del bloque «Archivo a guardar».
* Perfiles: los perfiles de ese bloque (de fábrica y propios), con la
  grilla y el modo de FL que arrastran.
* Motor: biblioteca ecCodes o programa wgrib2 (con su ruta y un botón para
  probarlo).

Recibe la configuración actual y devuelve en ``values()`` sólo las claves
que administra; la ventana decide qué aplicar.
"""
import os

from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QFrame,
    QColorDialog, QSlider, QTabWidget, QWidget, QComboBox, QCheckBox, QSpinBox,
    QRadioButton, QButtonGroup, QLineEdit, QFileDialog, QScrollArea,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QBrush

from .glass_dialog import GlassDialog, add_shadow as _add_shadow
from ..config import OPACITY_MAX, default_working_dir
from ..utils import MOD_KEY
from .. import gfs_download as gfs
from ..grib_engines import ENGINES, ec, find_wgrib2, wgrib2_version
from ..wind_plot import PROJECTIONS, WA_PROJECTIONS, HAVE_CARTOPY, WIND_STYLES, GRID_STEPS
from ..working_area import MAGVAR_CONVENTIONS
from ..fl_table import MODES, MODE_LABELS, DEFAULT_MODE
from ..sources import all_sources, source_config, set_source_config, source_label
from ..sources.cache import DownloadCache
from ..widgets.areas_editor import AreasEditor
from ..widgets.grids_editor import GridsEditor
from ..widgets.profiles_editor import ProfilesEditor
from ..widgets.save_options import SaveOptionsBox


class ColorPreview(QFrame):
    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._color = color
        self.setFixedSize(220, 60)

    def set_color(self, hex_color: str):
        self._color = hex_color
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(QColor(self._color)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self.rect(), 10, 10)


class SettingsDialog(GlassDialog):
    theme_changed = pyqtSignal(str)
    opacity_changed = pyqtSignal(int)

    PRESETS = [
        ("#4A90D9", "Azul"),
        ("#5B8C5A", "Verde"),
        ("#7B4FB0", "Violeta"),
        ("#C0674D", "Terracota"),
        ("#4A9D9C", "Teal"),
        ("#C4973E", "Dorado"),
        ("#3A5F8A", "Marino"),
        ("#8A3A5F", "Bordo"),
    ]

    TABS = ("Apariencia", "Mapa", "Fuentes", "Descarga", "Áreas / FIR", "WAFS", "Guardar", "Perfiles",
            "Motor")

    def __init__(self, parent=None, cfg: dict = None, owner=None):
        """`parent` es la ventana sobre la que se apila (puede ser otro
        diálogo, como el de descarga); `owner` la ventana principal, de la
        que salen las FIR cargadas y el diálogo «Límites de FIR»."""
        super().__init__(parent)
        self._owner = owner if owner is not None else parent
        self._cfg = dict(cfg or {})
        self._color = self._cfg.get("accent_color", "#4A90D9")
        self._opacity = int(self._cfg.get("opacity", 180))
        self.setWindowTitle("Preferencias")
        self.setMinimumWidth(560)
        self._build_ui()

    # ── Construcción ─────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)

        panel = QFrame()
        panel.setObjectName("GlassPanel")
        _add_shadow(panel)
        outer.addWidget(panel)

        lay = QVBoxLayout(panel)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)

        title = QLabel("Preferencias")
        title.setObjectName("Heading")
        lay.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_apariencia(), self.TABS[0])
        self.tabs.addTab(self._tab_mapa(), self.TABS[1])
        self.tabs.addTab(self._tab_fuentes(), self.TABS[2])
        self.tabs.addTab(self._tab_descarga(), self.TABS[3])
        self.tabs.addTab(self._tab_areas(), self.TABS[4])
        self.tabs.addTab(self._tab_wafs(), self.TABS[5])
        self.tabs.addTab(self._tab_guardar(), self.TABS[6])
        self.tabs.addTab(self._tab_perfiles(), self.TABS[7])
        self.tabs.addTab(self._tab_motor(), self.TABS[8])
        lay.addWidget(self.tabs, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton("Aplicar")
        ok_btn.setObjectName("AccentBtn")
        ok_btn.clicked.connect(self._accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        lay.addLayout(btn_row)

    @staticmethod
    def _page():
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)
        return w, lay

    @staticmethod
    def _sub(lay, text):
        lbl = QLabel(text)
        lbl.setObjectName("SubHeading")
        lay.addWidget(lbl)

    @staticmethod
    def _hint(lay, text):
        lbl = QLabel(text)
        lbl.setObjectName("Hint")
        lbl.setWordWrap(True)
        lay.addWidget(lbl)

    # ── Apariencia ──
    def _tab_apariencia(self):
        w, lay = self._page()
        self._sub(lay, "Color principal de la interfaz")
        prev_row = QHBoxLayout()
        self._preview = ColorPreview(self._color)
        prev_row.addWidget(self._preview)
        self._hex_label = QLabel(self._color)
        self._hex_label.setObjectName("SubHeading")
        prev_row.addWidget(self._hex_label)
        prev_row.addStretch()
        lay.addLayout(prev_row)

        for row_start in range(0, len(self.PRESETS), 4):
            row = QHBoxLayout()
            for hex_c, name in self.PRESETS[row_start:row_start + 4]:
                row.addWidget(self._make_color_btn(hex_c, name))
            lay.addLayout(row)

        custom_btn = QPushButton("Elegir color personalizado...")
        custom_btn.clicked.connect(self._pick_custom)
        lay.addWidget(custom_btn)

        self._sub(lay, "Transparencia")
        slider_row = QHBoxLayout()
        slider_row.setSpacing(12)
        lbl = QLabel("Transparente")
        lbl.setObjectName("SubHeading")
        slider_row.addWidget(lbl)
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(2, OPACITY_MAX)
        self._opacity_slider.setValue(self._opacity)
        self._opacity_slider.setTickInterval(10)
        self._opacity_slider.valueChanged.connect(self._on_opacity_changed)
        slider_row.addWidget(self._opacity_slider, 1)
        lbl = QLabel("Opaco")
        lbl.setObjectName("SubHeading")
        slider_row.addWidget(lbl)
        lay.addLayout(slider_row)
        self._opacity_value_label = QLabel(f"{self._opacity}")
        self._opacity_value_label.setObjectName("SubHeading")
        self._opacity_value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._opacity_value_label)
        self._hint(lay, "El tamaño de fuente se cambia con Ctrl + / Ctrl − / Ctrl 0 "
                        "(⌘ en macOS) y también escala los textos del mapa.")
        lay.addStretch()
        return w

    # ── Mapa ──
    def _tab_mapa(self):
        w, lay = self._page()
        self._sub(lay, "Proyección del mapa")
        self.cb_proj = QComboBox()
        from .. import working_area as wamod
        tang = wamod.find_tangency(wamod.working_areas_from_config(self._cfg))
        for key, name in PROJECTIONS:
            if key in WA_PROJECTIONS and tang is not None:
                name = name.replace("tangente a WA", f"tangente a WA {tang.code}")
            self.cb_proj.addItem(name, key)
            if key in WA_PROJECTIONS and tang is None:
                self.cb_proj.model().item(self.cb_proj.count() - 1).setEnabled(False)
        idx = self.cb_proj.findData(self._cfg.get("projection", "platecarree"))
        self.cb_proj.setCurrentIndex(max(0, idx))
        if not HAVE_CARTOPY:
            self.cb_proj.setEnabled(False)
            self.cb_proj.setToolTip("Las proyecciones requieren cartopy")
        lay.addWidget(self.cb_proj)

        self._sub(lay, "Valores iniciales de VIENTO y MAPA (también se guardan al cambiarlos en el panel)")
        row = QHBoxLayout()
        row.addWidget(QLabel("Viento"))
        self.cb_style = QComboBox()
        for key, name in WIND_STYLES:
            self.cb_style.addItem(name, key)
        self.cb_style.setCurrentIndex(max(0, self.cb_style.findData(
            self._cfg.get("map_wind_style", "barbas"))))
        row.addWidget(self.cb_style, 1)
        lay.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Grilla de grados"))
        self.cb_grid_step = QComboBox()
        for val, name in GRID_STEPS:
            self.cb_grid_step.addItem(name, val)
        self.cb_grid_step.setCurrentIndex(max(0, self.cb_grid_step.findData(
            int(self._cfg.get("map_grid_step", 10)))))
        row.addWidget(self.cb_grid_step, 1)
        lay.addLayout(row)
        self.chk_extra = QCheckBox("Extra Info (kt / °C junto a cada punto)")
        self.chk_extra.setChecked(bool(self._cfg.get("map_extra_info", False)))
        self.chk_grid = QCheckBox("Grilla lat/lon del archivo")
        self.chk_grid.setChecked(bool(self._cfg.get("map_grid", False)))
        self.chk_fill = QCheckBox("Fondo de velocidad (contornos rellenos)")
        self.chk_fill.setChecked(bool(self._cfg.get("map_fill", False)))
        self.chk_coast = QCheckBox("Costas y fronteras")
        self.chk_coast.setChecked(bool(self._cfg.get("map_coast", True)))
        self.chk_graticule = QCheckBox("Grilla de grados (meridianos y paralelos con rótulos)")
        self.chk_graticule.setChecked(bool(self._cfg.get("map_graticule", True)))
        for c in (self.chk_extra, self.chk_grid, self.chk_fill, self.chk_coast, self.chk_graticule):
            lay.addWidget(c)
        row = QHBoxLayout()
        row.addWidget(QLabel("Densidad: cada N puntos"))
        self.spin_stride = QSpinBox()
        self.spin_stride.setRange(1, 10)
        self.spin_stride.setValue(int(self._cfg.get("map_stride", 1)))
        row.addWidget(self.spin_stride)
        row.addStretch()
        lay.addLayout(row)
        self._sub(lay, "Rótulos de Extra Info")
        row = QHBoxLayout()
        row.addWidget(QLabel("Tamaño (pt)"))
        self.spin_label = QSpinBox()
        self.spin_label.setRange(5, 16)
        self.spin_label.setValue(int(self._cfg.get("map_label_size", 7)))
        self.spin_label.setToolTip("Tamaño base de los números junto a cada punto; " +
                                   MOD_KEY + " +/− lo escala junto con el resto del mapa")
        row.addWidget(self.spin_label)
        row.addStretch()
        lay.addLayout(row)
        self.chk_label_units = QCheckBox("Mostrar unidades (kt, °C)")
        self.chk_label_units.setChecked(bool(self._cfg.get("map_label_units", True)))
        lay.addWidget(self.chk_label_units)
        self._sub(lay, "Zoom y desplazamiento")
        row = QHBoxLayout()
        row.addWidget(QLabel("Rueda: % por paso"))
        self.spin_zoom = QSpinBox()
        self.spin_zoom.setRange(1, 80)
        self.spin_zoom.setValue(int(self._cfg.get("map_zoom_step", 20)))
        self.spin_zoom.setToolTip("Cuánto se acerca o aleja la vista por cada muesca de la rueda "
                                  "(en un trackpad, por cada 40 px de gesto)")
        row.addWidget(self.spin_zoom)
        row.addWidget(QLabel("   Modo fino (" + MOD_KEY + " o Shift apretados): ÷"))
        self.spin_fine = QSpinBox()
        self.spin_fine.setRange(2, 50)
        self.spin_fine.setValue(int(self._cfg.get("map_fine_divisor", 5)))
        self.spin_fine.setToolTip("Con " + MOD_KEY + " o Shift apretados la rueda y el arrastre se "
                                  "dividen por este número; los botones + y − usan el paso fino")
        row.addWidget(self.spin_fine)
        row.addStretch()
        lay.addLayout(row)
        self._sub(lay, "Variación magnética (Working Areas)")
        row = QHBoxLayout()
        row.addWidget(QLabel("Convención de signo al escribirla"))
        self.cb_magvar = QComboBox()
        for key, name in MAGVAR_CONVENTIONS:
            self.cb_magvar.addItem(name, key)
        self.cb_magvar.setCurrentIndex(max(0, self.cb_magvar.findData(
            self._cfg.get("magvar_convention", "east_positive"))))
        self.cb_magvar.setToolTip("Cómo se interpreta un número sin letra en la columna Var. mag. de las "
                                  "Working Areas; 10W o 6°55'E se entienden siempre. Internamente se guarda "
                                  "este positivo.")
        row.addWidget(self.cb_magvar, 1)
        lay.addLayout(row)
        lay.addStretch()
        return w

    # ── Fuentes ──
    def _tab_fuentes(self):
        from PyQt6.QtWidgets import QListWidget, QListWidgetItem
        w, lay = self._page()
        self._sub(lay, "Fuentes de datos (✓ FL = publica los niveles OACI por nivel de vuelo)")
        # Borrador local de la configuración de fuentes (se aplica con Aplicar)
        self._sources_wrapper = {"sources": dict(self._cfg.get("sources") or {})}
        self.lst_sources = QListWidget()
        for src in all_sources():
            st = source_config(self._sources_wrapper, src.key)
            kind = "altura" if src.kind == "altura" else "superficie"
            item = QListWidgetItem(f"{source_label(src)}   [{kind}]"
                                   + ("   🔑" if src.needs_credentials else ""))
            item.setToolTip(src.model)
            item.setData(Qt.ItemDataRole.UserRole, src.key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if st["enabled"] else Qt.CheckState.Unchecked)
            self.lst_sources.addItem(item)
        self.lst_sources.itemDoubleClicked.connect(lambda _i: self._configure_source())
        self.lst_sources.itemChanged.connect(self._on_source_checked)
        lay.addWidget(self.lst_sources, 1)
        row = QHBoxLayout()
        b = QPushButton("Configurar…")
        b.clicked.connect(self._configure_source)
        row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        self._hint(lay, "La casilla habilita la fuente en el selector de la ventana. «Configurar…» "
                        "abre sus parámetros por defecto, credenciales y «Probar conexión».")
        # Fuentes de límites de FIR (capa del mapa, no datos meteorológicos)
        self._sub(lay, "Límites de FIR (capa del mapa)")
        row = QHBoxLayout()
        lbl = QLabel("openAIP (límites de FIR)   🔑 clave de API en el llavero")
        row.addWidget(lbl, 1)
        self.btn_openaip = QPushButton("Configurar…")
        self.btn_openaip.clicked.connect(self._configure_openaip_fir)
        row.addWidget(self.btn_openaip)
        lay.addLayout(row)
        self._hint(lay, "VATSpy (sin clave) y el archivo propio se manejan en Vista ▸ FIR ▸ "
                        "Configurar FIR… Los límites de VATSpy y openAIP no son oficiales: para "
                        "uso operativo verificarlos contra el AIP Argentina ENR 2.1.")
        return w

    def _configure_openaip_fir(self):
        from .source_config_dialog import SourceConfigDialog
        from ..sources.openaip_fir import OpenAipFirSource
        src = OpenAipFirSource()
        dlg = SourceConfigDialog(self, src, self._wrap())
        if dlg.exec():
            set_source_config(self._wrap(), src.key, enabled=dlg.enabled(), params=dlg.params())

    def _on_source_checked(self, item):
        key = item.data(Qt.ItemDataRole.UserRole)
        set_source_config(self._wrap(), key, enabled=item.checkState() == Qt.CheckState.Checked)

    def _wrap(self):
        """Diccionario con la clave 'sources': el borrador local."""
        return self._sources_wrapper

    def _configure_source(self):
        from .source_config_dialog import SourceConfigDialog
        from ..sources import get_source
        item = self.lst_sources.currentItem()
        if item is None:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        src = get_source(key)
        dlg = SourceConfigDialog(self, src, self._wrap())
        if dlg.exec():
            set_source_config(self._wrap(), key, enabled=dlg.enabled(), params=dlg.params())
            item.setCheckState(Qt.CheckState.Checked if dlg.enabled() else Qt.CheckState.Unchecked)

    # ── Descarga ──
    def _tab_descarga(self):
        w, lay = self._page()
        self._sub(lay, "Valores iniciales del diálogo «Obtener datos…»")
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.addWidget(QLabel("Plazos: desde"), 0, 0)
        self.h_from = QSpinBox(); self.h_from.setRange(0, gfs.MAX_HOUR)
        self.h_from.setValue(int(self._cfg.get("download_h_from", 6)))
        g.addWidget(self.h_from, 0, 1)
        g.addWidget(QLabel("hasta"), 0, 2)
        self.h_to = QSpinBox(); self.h_to.setRange(0, gfs.MAX_HOUR)
        self.h_to.setValue(int(self._cfg.get("download_h_to", 12)))
        g.addWidget(self.h_to, 0, 3)
        g.addWidget(QLabel("cada"), 0, 4)
        self.h_step = QSpinBox(); self.h_step.setRange(1, 24); self.h_step.setSuffix(" h")
        self.h_step.setValue(int(self._cfg.get("download_h_step", 3)))
        g.addWidget(self.h_step, 0, 5)
        lay.addLayout(g)
        self.chk_merge = QCheckBox("Unir los plazos en un solo archivo")
        self.chk_merge.setChecked(bool(self._cfg.get("download_merge", True)))
        lay.addWidget(self.chk_merge)
        self.chk_open = QCheckBox("Abrir en el visor al terminar")
        self.chk_open.setChecked(bool(self._cfg.get("download_open", True)))
        lay.addWidget(self.chk_open)
        self._hint(lay, "La resolución, el suavizado y los niveles de cada fuente se configuran "
                        "en la pestaña Fuentes.")

        self._sub(lay, "Directorio de trabajo por defecto")
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.addWidget(QLabel("Carpeta"), 0, 0)
        self.ed_download_dir = QLineEdit(str(self._cfg.get("download_dir") or ""))
        self.ed_download_dir.setPlaceholderText(default_working_dir())
        self.ed_download_dir.textChanged.connect(self._refresh_download_dir_label)
        g.addWidget(self.ed_download_dir, 0, 1)
        b = QPushButton("Elegir…")
        b.clicked.connect(self._pick_download_dir)
        g.addWidget(b, 0, 2)
        g.setColumnStretch(1, 1)
        lay.addLayout(g)
        self.lbl_download_dir = QLabel("")
        self.lbl_download_dir.setObjectName("Hint")
        self.lbl_download_dir.setWordWrap(True)
        lay.addWidget(self.lbl_download_dir)
        self._refresh_download_dir_label()

        self._sub(lay, "Caché de descargas (no se vuelve a bajar lo ya bajado)")
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.addWidget(QLabel("Tamaño máximo"), 0, 0)
        self.cache_mb = QSpinBox(); self.cache_mb.setRange(0, 100000); self.cache_mb.setSuffix(" MB")
        self.cache_mb.setSpecialValueText("sin límite")
        self.cache_mb.setValue(int(self._cfg.get("cache_max_mb", 500)))
        g.addWidget(self.cache_mb, 0, 1)
        g.addWidget(QLabel("Conservar"), 0, 2)
        self.cache_days = QSpinBox(); self.cache_days.setRange(0, 365); self.cache_days.setSuffix(" días")
        self.cache_days.setSpecialValueText("siempre")
        self.cache_days.setValue(int(self._cfg.get("cache_max_days", 3)))
        g.addWidget(self.cache_days, 0, 3)
        b = QPushButton("Vaciar caché")
        b.clicked.connect(self._clear_cache)
        g.addWidget(b, 0, 4)
        lay.addLayout(g)
        self.lbl_cache = QLabel("")
        self.lbl_cache.setObjectName("Hint")
        lay.addWidget(self.lbl_cache)
        self._refresh_cache_label()
        lay.addStretch()
        return w

    def _pick_download_dir(self):
        start = self.ed_download_dir.text().strip() or default_working_dir()
        d = QFileDialog.getExistingDirectory(self, "Directorio de trabajo por defecto", start)
        if d:
            self.ed_download_dir.setText(d)

    def _refresh_download_dir_label(self):
        """Explica dónde se guarda y avisa si la carpeta indicada no existe."""
        d = self.ed_download_dir.text().strip()
        base = ("Carpeta inicial de «Obtener datos…» y de las exportaciones al arrancar. "
                "Al abrir un archivo (también desde el Finder o el gestor de archivos), el "
                "directorio de trabajo pasa a ser el de ese archivo hasta cerrar el programa.")
        if d and not os.path.isdir(d):
            base = f"La carpeta «{d}» no existe: se usará {default_working_dir()}. " + base
        elif not d:
            base = f"Vacío: se usa {default_working_dir()}. " + base
        self.lbl_download_dir.setText(base)

    def _cache(self):
        return DownloadCache(max_mb=self.cache_mb.value(), max_days=self.cache_days.value())

    def _refresh_cache_label(self):
        c = self._cache()
        n = len(c.entries())
        self.lbl_cache.setText(f"{n} archivo(s), {c.size_bytes() / 1e6:.1f} MB en {c.folder}")

    def _clear_cache(self):
        self._cache().clear()
        self._refresh_cache_label()

    # ── Áreas / FIR ──
    def _tab_areas(self):
        w, lay = self._page()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        lay.addWidget(scroll, 1)
        scroll.setWidget(inner)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(10)
        row = QHBoxLayout()
        lbl = QLabel("Áreas de descarga por FIR (envolvente de las marcadas + margen)")
        lbl.setObjectName("SubHeading")
        row.addWidget(lbl, 1)
        self.btn_fir = QPushButton("Límites de FIR y Working Areas…")
        self.btn_fir.setToolTip("La ventana «Límites de FIR» (Vista ▸ FIR): qué FIR se dibujan y "
                                "con qué estilo, sus extremos, los datos de los límites y las "
                                "Working Areas. Lo que se cambia ahí se aplica al cerrarla.")
        self.btn_fir.clicked.connect(self._open_fir_dialog)
        row.addWidget(self.btn_fir)
        lay.addLayout(row)
        regions_fn = None
        owner = self._owner
        if owner is not None and hasattr(owner, "_fir_regions"):
            regions_fn = lambda: getattr(owner, "_fir_regions", {})   # noqa: E731
        self.areas_editor = AreasEditor(self._cfg, regions_fn=regions_fn)
        lay.addWidget(self.areas_editor)
        lbl = QLabel("Grillas con nombre (recuadro exacto y resolución; sin margen)")
        lbl.setObjectName("SubHeading")
        lay.addWidget(lbl)
        self.grids_editor = GridsEditor(self._cfg)
        self.areas_editor.cb_format.currentIndexChanged.connect(
            lambda _i: self.grids_editor.set_coord_format(self.areas_editor.coord_format()))
        self.grids_editor.changed.connect(self._on_grids_changed)
        lay.addWidget(self.grids_editor)
        lay.addStretch()
        return w

    def _on_grids_changed(self):
        """Los perfiles y el bloque de Guardar ven la tabla de grillas nueva."""
        grids = self.grids_editor.grids()
        if hasattr(self, "profiles_editor"):
            self.profiles_editor.set_grids(grids)
        if hasattr(self, "save_box"):
            self.save_box.set_profiles(self.save_box.profiles(), grids)

    def _open_fir_dialog(self):
        """«Límites de FIR»: por la ventana principal si la hay (aplica y
        guarda al cerrar); si no, el diálogo solo sobre la copia local."""
        owner = self._owner
        if owner is not None and hasattr(owner, "open_fir_dialog"):
            owner.open_fir_dialog(parent=self)      # apilado sobre Preferencias
            return
        from .fir_dialog import FirDialog
        dlg = FirDialog(self, cfg=self._cfg)
        if dlg.exec():
            self._cfg.update(dlg.values())

    def select_tab(self, name):
        """Muestra la pestaña por su nombre («WAFS», «Áreas / FIR», …)."""
        if name in self.TABS:
            self.tabs.setCurrentIndex(self.TABS.index(name))

    def lock_tab(self, name):
        """Deja sólo esa pestaña accesible (las demás grisadas): abiertas
        desde otro diálogo, como «Preferencias WAFS…» de la descarga, las
        Preferencias se limitan a lo que ese diálogo necesita."""
        if name not in self.TABS:
            return
        self.select_tab(name)
        for i, t in enumerate(self.TABS):
            self.tabs.setTabEnabled(i, t == name)
        self.setWindowTitle(f"Preferencias · {name}")

    def _accept(self):
        from PyQt6.QtWidgets import QMessageBox
        errs = self.areas_editor.errors()
        if errs:
            self.tabs.setCurrentIndex(self.TABS.index("Áreas / FIR"))
            QMessageBox.warning(self, "Preferencias", "Corregí la tabla de áreas antes de aplicar:\n"
                                + "\n".join(errs[:6]))
            return
        errs = self.grids_editor.errors()
        if errs:
            self.tabs.setCurrentIndex(self.TABS.index("Áreas / FIR"))
            QMessageBox.warning(self, "Preferencias", "Corregí la tabla de grillas antes de aplicar:\n"
                                + "\n".join(errs[:6]))
            return
        errs = self.profiles_editor.errors()
        if errs:
            self.tabs.setCurrentIndex(self.TABS.index("Perfiles"))
            QMessageBox.warning(self, "Preferencias", "Corregí los perfiles antes de aplicar:\n"
                                + "\n".join(errs[:6]))
            return
        self.accept()

    # ── WAFS ──
    def _tab_wafs(self):
        w, lay = self._page()
        self._sub(lay, "Formato interno único: WAFS (viento y temperatura OACI por nivel de vuelo)")
        self._hint(lay, "Lo que se descarga de una fuente de altura (GFS, ECMWF, ICON, genérica) y "
                        "los archivos locales en niveles de presión se convierten al formato WAFS "
                        "antes de mostrarse: cada FL cada 1000 ft interpolado en ln(p) a su presión "
                        "ISA exacta y grabado con la etiqueta del modo elegido. Lo que ya viene "
                        "etiquetado por FL no se toca.")
        row = QHBoxLayout()
        row.addWidget(QLabel("Modo de etiquetado por defecto"))
        self.cb_wafs_mode = QComboBox()
        for m in MODES:
            self.cb_wafs_mode.addItem(MODE_LABELS[m], m)
        self.cb_wafs_mode.setCurrentIndex(max(0, self.cb_wafs_mode.findData(
            str(self._cfg.get("wafs_mode", DEFAULT_MODE)).upper())))
        self.cb_wafs_mode.setToolTip("Con qué etiqueta de nivel se graba cada FL al convertir o exportar: "
                                     "nominal en hPa (INDRA 14 FL / OACI 17 FL / OACI56) o la presión ISA en Pa (WAFS). "
                                     "El dato va siempre a la ISA exacta. Es el botón de modo con el que arranca "
                                     "el diálogo Obtener datos.")
        row.addWidget(self.cb_wafs_mode, 1)
        b = QPushButton("Ver tabla…")
        b.clicked.connect(self._show_fl_table)
        row.addWidget(b)
        lay.addLayout(row)
        self.chk_wafs = QCheckBox("Convertir a WAFS por defecto (así arranca la casilla del "
                                  "diálogo de descarga)")
        self.chk_wafs.setChecked(bool(self._cfg.get("wafs_convert", True)))
        lay.addWidget(self.chk_wafs)
        self.chk_wafs_local = QCheckBox("Convertir también los archivos locales al abrirlos "
                                        "(se escribe <nombre>_wafs.grib2 junto al original)")
        self.chk_wafs_local.setChecked(bool(self._cfg.get("wafs_convert_local", True)))
        lay.addWidget(self.chk_wafs_local)
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.addWidget(QLabel("Rango de niveles: FL"), 0, 0)
        self.wafs_fl_min = QSpinBox(); self.wafs_fl_min.setRange(0, 600); self.wafs_fl_min.setSingleStep(10)
        self.wafs_fl_min.setValue(int(self._cfg.get("wafs_fl_min", 50)))
        g.addWidget(self.wafs_fl_min, 0, 1)
        g.addWidget(QLabel("a FL"), 0, 2)
        self.wafs_fl_max = QSpinBox(); self.wafs_fl_max.setRange(0, 600); self.wafs_fl_max.setSingleStep(10)
        self.wafs_fl_max.setValue(int(self._cfg.get("wafs_fl_max", 530)))
        g.addWidget(self.wafs_fl_max, 0, 3)
        g.setColumnStretch(4, 1)
        lay.addLayout(g)
        self.chk_wafs_extend = QCheckBox("Ampliar el rango si la fuente trae niveles por debajo de "
                                         "850 hPa o por encima de 100 hPa (hasta FL600)")
        self.chk_wafs_extend.setChecked(bool(self._cfg.get("wafs_fl_extend", True)))
        lay.addWidget(self.chk_wafs_extend)
        self.chk_wafs_extrap = QCheckBox("FL fuera de los niveles de la fuente: usar el nivel más "
                                         "cercano (extrapolar) en vez de omitirlos")
        self.chk_wafs_extrap.setChecked(bool(self._cfg.get("wafs_extrapolate", False)))
        lay.addWidget(self.chk_wafs_extrap)
        self._hint(lay, "Por defecto FL050–FL530, lo que cubre el GFS entre 850 y 100 hPa. Los FL "
                        "extrapolados quedan anotados en la procedencia (archivo .json) del "
                        "convertido. La exportación (Archivo ▸ Exportar a WAFS…) usa estas mismas "
                        "opciones cuando lo cargado todavía no está en WAFS.")
        lay.addStretch()
        return w

    def _tab_guardar(self):
        w, lay = self._page()
        self._sub(lay, "Archivo a guardar: cómo se graba lo que escribe el visor")
        self._hint(lay, "Valores por defecto del bloque «Archivo a guardar» de Obtener datos…, "
                        "Exportar a WAFS…, Generar GRIB… y Guardar como…; también se aplican al "
                        "convertir un archivo al abrirlo. El perfil carga de una vez los valores de "
                        "uno de la pestaña Perfiles (NOAA GFS, WAFS WAFC Washington, WAFS WAFC London, "
                        "FDP o los propios). Regrillado bilineal a "
                        "0,25, 0,50, 1,00 o 1,25° (con wgrib2 si es el motor y tiene la "
                        "interpolación). Viento como U/V o como dirección y velocidad; decimales del "
                        "viento y de la temperatura (factor decimal con escala binaria 0: se "
                        "respetan exactos); etiqueta de capa de los archivos por Nivel (nominal "
                        "850, ISA 843,1 o ISA entera 843); empaquetado simple o un valor IEEE por "
                        "celda; centro generador del origen o «sin centro» (65535).")
        self.save_box = SaveOptionsBox(cfg=self._cfg)
        lay.addWidget(self.save_box)
        self._hint(lay, "Dentro del GRIB la temperatura va siempre en K, el viento en m/s y la "
                        "dirección en grados verdaderos, y las coordenadas en millonésimas de "
                        "grado: lo fija el formato. El visor muestra °C y kt.")
        lay.addStretch()
        return w

    # ── Perfiles ──
    def _tab_perfiles(self):
        w, lay = self._page()
        self._sub(lay, "Perfiles del bloque «Archivo a guardar»")
        self._hint(lay, "Cada perfil es un juego completo de valores del bloque con nombre, más la "
                        "grilla con nombre (Áreas / FIR) y el modo de etiquetado de los niveles que "
                        "arrastra al elegirlo. Los de fábrica se editan y renombran, no se borran: se "
                        "ocultan; «Restaurar de fábrica» los devuelve.")
        self.profiles_editor = ProfilesEditor(self._cfg, grids=self.grids_editor.grids())
        self.profiles_editor.changed.connect(
            lambda: self.save_box.set_profiles(self.profiles_editor.profiles(), self.grids_editor.grids()))
        lay.addWidget(self.profiles_editor, 1)
        return w

    def _show_fl_table(self):
        from .fl_table_dialog import FlTableDialog
        FlTableDialog(self, mode=self.cb_wafs_mode.currentData() or DEFAULT_MODE).exec()

    # ── Motor ──
    def _tab_motor(self):
        w, lay = self._page()
        self._sub(lay, "Motor de lectura de GRIB2")
        self._engine_group = QButtonGroup(self)
        self.rb_engine = {}
        current = self._cfg.get("engine", "eccodes")
        for key, name in ENGINES:
            rb = QRadioButton(name)
            rb.setChecked(key == current)
            self._engine_group.addButton(rb)
            self.rb_engine[key] = rb
            lay.addWidget(rb)
        ecc_txt = ("ecCodes disponible." if ec is not None
                   else "ecCodes NO disponible (pip install eccodes).")
        self._hint(lay, ecc_txt + " Ambos motores entregan los mismos campos; wgrib2 "
                        "corre como proceso externo por cada campo leído y sirve para "
                        "contrastar o cuando ecCodes no puede instalarse.")

        self._sub(lay, "Ruta de wgrib2 (vacío = buscar en el PATH)")
        row = QHBoxLayout()
        self.ed_wgrib2 = QLineEdit(self._cfg.get("wgrib2_path", ""))
        self.ed_wgrib2.setPlaceholderText("/usr/local/bin/wgrib2")
        row.addWidget(self.ed_wgrib2, 1)
        b = QPushButton("Buscar…")
        b.clicked.connect(self._pick_wgrib2)
        row.addWidget(b)
        b = QPushButton("Probar")
        b.clicked.connect(self._test_wgrib2)
        row.addWidget(b)
        lay.addLayout(row)
        self.lbl_wgrib2 = QLabel("")
        self.lbl_wgrib2.setObjectName("Hint")
        self.lbl_wgrib2.setWordWrap(True)
        lay.addWidget(self.lbl_wgrib2)
        self._test_wgrib2(quiet=True)
        lay.addStretch()
        return w

    def _pick_wgrib2(self):
        start = self.ed_wgrib2.text().strip() or os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(self, "Programa wgrib2", start)
        if path:
            self.ed_wgrib2.setText(path)
            self._test_wgrib2()

    def _test_wgrib2(self, quiet=False):
        """Busca wgrib2 (ruta indicada, variable WGRIB2 o PATH) y muestra su versión."""
        exe = find_wgrib2(self.ed_wgrib2.text())
        if not exe:
            self.lbl_wgrib2.setText("wgrib2 no encontrado." if quiet else
                                    "wgrib2 no encontrado: indicá la ruta o instalalo en el PATH.")
            return False
        ver = wgrib2_version(exe)
        if ver:
            self.lbl_wgrib2.setText(f"Encontrado: {exe}\n{ver[:90]}")
            return True
        self.lbl_wgrib2.setText(f"{exe} existe pero no responde a -version.")
        return False

    # ── Color ──
    def _make_color_btn(self, hex_color: str, name: str) -> QPushButton:
        btn = QPushButton(name)
        btn.setFixedHeight(32)
        color = QColor(hex_color)
        text_color = "#fff" if color.lightness() < 140 else "#111"
        btn.setStyleSheet(
            f"QPushButton {{ background: {hex_color}; color: {text_color}; "
            f"border-radius: 6px; border: none; font-weight: 600; }}"
        )
        btn.clicked.connect(lambda _, c=hex_color: self._select_color(c))
        return btn

    def _select_color(self, hex_color: str):
        self._color = hex_color
        self._preview.set_color(hex_color)
        self._hex_label.setText(hex_color)
        self.theme_changed.emit(hex_color)

    def _pick_custom(self):
        color = QColorDialog.getColor(QColor(self._color), self, "Elegir color")
        if color.isValid():
            self._select_color(color.name())

    def _on_opacity_changed(self, value: int):
        self._opacity = value
        self._opacity_value_label.setText(f"{value}")
        self.opacity_changed.emit(value)

    # ── Resultado ────────────────────────────────────────────────────────────

    def selected_color(self) -> str:
        return self._color

    def selected_opacity(self) -> int:
        return self._opacity

    def selected_engine(self) -> str:
        for key, rb in self.rb_engine.items():
            if rb.isChecked():
                return key
        return "eccodes"

    def values(self) -> dict:
        """Claves de configuración administradas por el diálogo."""
        return {
            "accent_color": self._color,
            "opacity": self._opacity,
            "projection": self.cb_proj.currentData() or "platecarree",
            "map_wind_style": self.cb_style.currentData() or "barbas",
            "map_extra_info": self.chk_extra.isChecked(),
            "map_grid": self.chk_grid.isChecked(),
            "map_grid_step": int(self.cb_grid_step.currentData() or 10),
            "map_fill": self.chk_fill.isChecked(),
            "map_stride": int(self.spin_stride.value()),
            "map_label_size": int(self.spin_label.value()),
            "map_label_units": self.chk_label_units.isChecked(),
            "map_coast": self.chk_coast.isChecked(),
            "map_graticule": self.chk_graticule.isChecked(),
            "map_zoom_step": int(self.spin_zoom.value()),
            "map_fine_divisor": int(self.spin_fine.value()),
            "magvar_convention": self.cb_magvar.currentData() or "east_positive",
            "sources": dict(self._wrap()["sources"]),
            "cache_max_mb": int(self.cache_mb.value()),
            "cache_max_days": int(self.cache_days.value()),
            "download_dir": self.ed_download_dir.text().strip(),
            "download_merge": self.chk_merge.isChecked(),
            "download_open": self.chk_open.isChecked(),
            "download_h_from": int(self.h_from.value()),
            "download_h_to": int(self.h_to.value()),
            "download_h_step": int(self.h_step.value()),
            **self.areas_editor.values(),
            **self.grids_editor.values(),
            **self.profiles_editor.values(),
            "wafs_convert": self.chk_wafs.isChecked(),
            "wafs_convert_local": self.chk_wafs_local.isChecked(),
            "wafs_mode": self.cb_wafs_mode.currentData() or DEFAULT_MODE,
            "wafs_fl_min": int(self.wafs_fl_min.value()),
            "wafs_fl_max": int(self.wafs_fl_max.value()),
            "wafs_fl_extend": self.chk_wafs_extend.isChecked(),
            "wafs_extrapolate": self.chk_wafs_extrap.isChecked(),
            **self.save_box.config_values(),
            "engine": self.selected_engine(),
            "wgrib2_path": self.ed_wgrib2.text().strip(),
        }
