# -*- coding: utf-8 -*-
"""Preferencias del visor, en pestañas:

* Apariencia: color de acento (con vista previa en vivo) y transparencia.
* Mapa: proyección y valores iniciales de CONFIG (Extra Info, grilla, fondo,
  densidad).
* Descarga: resolución, niveles intermedios, horas y destino por defecto del
  diálogo «Descargar GFS…».
* Motor: biblioteca ecCodes o programa wgrib2 (con su ruta y un botón para
  probarlo).

Recibe la configuración actual y devuelve en ``values()`` sólo las claves
que administra; la ventana decide qué aplicar.
"""
import os

from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QFrame,
    QColorDialog, QSlider, QTabWidget, QWidget, QComboBox, QCheckBox, QSpinBox,
    QRadioButton, QButtonGroup, QLineEdit, QFileDialog,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QBrush

from .glass_dialog import GlassDialog, add_shadow as _add_shadow
from ..config import OPACITY_MAX
from .. import gfs_download as gfs
from ..grib_engines import ENGINES, ec, find_wgrib2, wgrib2_version
from ..wind_plot import PROJECTIONS, HAVE_CARTOPY


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

    TABS = ("Apariencia", "Mapa", "Descarga", "Motor")

    def __init__(self, parent=None, cfg: dict = None):
        super().__init__(parent)
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
        self.tabs.addTab(self._tab_descarga(), self.TABS[2])
        self.tabs.addTab(self._tab_motor(), self.TABS[3])
        lay.addWidget(self.tabs, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton("Aplicar")
        ok_btn.setObjectName("AccentBtn")
        ok_btn.clicked.connect(self.accept)
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
        for key, name in PROJECTIONS:
            self.cb_proj.addItem(name, key)
        idx = self.cb_proj.findData(self._cfg.get("projection", "platecarree"))
        self.cb_proj.setCurrentIndex(max(0, idx))
        if not HAVE_CARTOPY:
            self.cb_proj.setEnabled(False)
            self.cb_proj.setToolTip("Las proyecciones requieren cartopy")
        lay.addWidget(self.cb_proj)

        self._sub(lay, "Valores iniciales de CONFIG (también se guardan al cambiarlos en el panel)")
        self.chk_extra = QCheckBox("Extra Info (kt / °C junto a cada barba)")
        self.chk_extra.setChecked(bool(self._cfg.get("map_extra_info", False)))
        self.chk_grid = QCheckBox("Grilla lat/lon del archivo")
        self.chk_grid.setChecked(bool(self._cfg.get("map_grid", False)))
        self.chk_fill = QCheckBox("Fondo de velocidad (contornos rellenos)")
        self.chk_fill.setChecked(bool(self._cfg.get("map_fill", False)))
        for c in (self.chk_extra, self.chk_grid, self.chk_fill):
            lay.addWidget(c)
        row = QHBoxLayout()
        row.addWidget(QLabel("Densidad: cada N puntos"))
        self.spin_stride = QSpinBox()
        self.spin_stride.setRange(1, 10)
        self.spin_stride.setValue(int(self._cfg.get("map_stride", 1)))
        row.addWidget(self.spin_stride)
        row.addStretch()
        lay.addLayout(row)
        lay.addStretch()
        return w

    # ── Descarga ──
    def _tab_descarga(self):
        w, lay = self._page()
        self._sub(lay, "Valores iniciales del diálogo «Descargar GFS…»")
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.addWidget(QLabel("Resolución"), 0, 0)
        self.cb_res = QComboBox()
        for r in gfs.RESOLUTIONS:
            self.cb_res.addItem(r[1], r[0])
        idx = self.cb_res.findData(self._cfg.get("download_resolution", "0p25"))
        self.cb_res.setCurrentIndex(max(0, idx))
        self.cb_res.currentIndexChanged.connect(self._on_res_changed)
        g.addWidget(self.cb_res, 0, 1)
        g.addWidget(QLabel("Horas: desde"), 1, 0)
        self.h_from = QSpinBox(); self.h_from.setRange(0, gfs.MAX_HOUR)
        self.h_from.setValue(int(self._cfg.get("download_h_from", 6)))
        g.addWidget(self.h_from, 1, 1)
        g.addWidget(QLabel("hasta"), 1, 2)
        self.h_to = QSpinBox(); self.h_to.setRange(0, gfs.MAX_HOUR)
        self.h_to.setValue(int(self._cfg.get("download_h_to", 12)))
        g.addWidget(self.h_to, 1, 3)
        g.addWidget(QLabel("cada"), 1, 4)
        self.h_step = QSpinBox(); self.h_step.setRange(1, 24); self.h_step.setSuffix(" h")
        self.h_step.setValue(int(self._cfg.get("download_h_step", 3)))
        g.addWidget(self.h_step, 1, 5)
        lay.addLayout(g)

        self.chk_extra_levels = QCheckBox("Incluir niveles intermedios cada 25 hPa (875 … 125; "
                                          "pgrb2b a 0,25°, pgrb2full a 0,50°)")
        self.chk_extra_levels.setChecked(bool(self._cfg.get("download_extra_levels", False)))
        lay.addWidget(self.chk_extra_levels)
        self._hint(lay, "Con los intermedios, cada FL del visor queda a menos de 8 hPa de "
                        "un nivel del archivo (F320 ≈ 275, F360 ≈ 225, F410 ≈ 175) y la "
                        "interpolación en ln(p) es mínima. A 1,00° no existen.")
        self.chk_merge = QCheckBox("Unir los pasos en un solo archivo")
        self.chk_merge.setChecked(bool(self._cfg.get("download_merge", True)))
        lay.addWidget(self.chk_merge)
        self.chk_open = QCheckBox("Abrir en el visor al terminar")
        self.chk_open.setChecked(bool(self._cfg.get("download_open", True)))
        lay.addWidget(self.chk_open)
        self._on_res_changed()
        lay.addStretch()
        return w

    def _on_res_changed(self, *_):
        ok = gfs.extra_levels_available(self.cb_res.currentData())
        self.chk_extra_levels.setEnabled(ok)
        if not ok:
            self.chk_extra_levels.setChecked(False)

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
            "map_extra_info": self.chk_extra.isChecked(),
            "map_grid": self.chk_grid.isChecked(),
            "map_fill": self.chk_fill.isChecked(),
            "map_stride": int(self.spin_stride.value()),
            "download_resolution": self.cb_res.currentData(),
            "download_extra_levels": self.chk_extra_levels.isChecked(),
            "download_merge": self.chk_merge.isChecked(),
            "download_open": self.chk_open.isChecked(),
            "download_h_from": int(self.h_from.value()),
            "download_h_to": int(self.h_to.value()),
            "download_h_step": int(self.h_step.value()),
            "engine": self.selected_engine(),
            "wgrib2_path": self.ed_wgrib2.text().strip(),
        }
