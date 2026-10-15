# -*- coding: utf-8 -*-
"""Diálogo «Límites de FIR», en pestañas:

* Regiones: qué FIR se dibujan (Argentina y vecinas, una por una) y el
  estilo (colores, grosor, relleno, tamaño de etiqueta).
* Extremos: latitud norte/sur y longitud este/oeste máximas de cada FIR
  calculadas del polígono cargado, y si la grilla meteorológica abierta la
  cubre completa, en parte o nada.
* Datos: de dónde salen los límites. Descarga de VATSpy (no oficial),
  descarga de openAIP (con clave en el llavero), archivo propio
  (GeoJSON / KML / KMZ / Shapefile, p. ej. el generado desde el AIP) y el
  conversor de texto del AIP.

`values()` devuelve las claves fir_* de la configuración. Las descargas
corren en un hilo con progreso y cancelación.
"""
import os
import shutil

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QFrame, QTabWidget, QWidget,
    QCheckBox, QListWidget, QListWidgetItem, QDoubleSpinBox, QSpinBox, QColorDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QComboBox, QProgressBar,
    QFileDialog, QMessageBox,
)

from .glass_dialog import GlassDialog, add_shadow as _add_shadow
from .. import fir as firmod
from ..config import DEFAULTS
from ..sources import credentials as creds
from ..sources.base import DownloadError, DownloadCancelled

FILE_FILTER = ("Límites de FIR (*.geojson *.json *.kml *.kmz *.shp);;GeoJSON (*.geojson *.json);;"
               "KML (*.kml *.kmz);;Shapefile (*.shp);;Todos los archivos (*)")
COVERAGE_TEXT = {"completa": "✔ completa", "parcial": "◐ parcial", "ninguna": "✖ ninguna",
                 "sin grilla": "— (sin archivo abierto)", "sin datos": "—"}


class _FirWorker(QThread):
    progress = pyqtSignal(str, float)
    done = pyqtSignal(object, str)      # resultado, mensaje de error ('' si ok)

    def __init__(self, kind, cfg, parent=None):
        super().__init__(parent)
        self._kind, self._cfg = kind, cfg
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            if self._kind == "vatspy":
                res = firmod.download_vatspy(progress_cb=self.progress.emit,
                                             cancel=lambda: self._cancel)
            else:
                from ..sources.openaip_fir import OpenAipFirSource
                from ..sources import source_config
                src = OpenAipFirSource()
                params = source_config(self._cfg, src.key)["params"]
                res = src.download_firs(params=params, progress_cb=self.progress.emit,
                                        cancel=lambda: self._cancel)
            self.done.emit(res, "")
        except DownloadCancelled:
            self.done.emit(None, "cancelada")
        except DownloadError as exc:
            self.done.emit(None, str(exc))
        except Exception as exc:          # pragma: no cover - imprevistos
            self.done.emit(None, f"{type(exc).__name__}: {exc}")


class FirDialog(GlassDialog):
    TABS = ("Regiones", "Extremos", "Datos")

    def __init__(self, parent=None, cfg=None, regions=None, notes=None, grid_bbox=None):
        super().__init__(parent)
        self._cfg = dict(cfg or {})
        self._regions = dict(regions or {})
        self._notes = list(notes or [])
        self._grid_bbox = grid_bbox
        self._worker = None
        self._color = self._cfg.get("fir_color", DEFAULTS["fir_color"])
        self._nb_color = self._cfg.get("fir_neighbor_color", DEFAULTS["fir_neighbor_color"])
        self._user_file = self._cfg.get("fir_user_file", "") or ""
        self.setWindowTitle("Límites de FIR")
        self.setMinimumWidth(840)
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
        lay.setSpacing(10)

        title = QLabel("Límites de FIR (Regiones de Información de Vuelo)")
        title.setObjectName("Heading")
        lay.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_regiones(), self.TABS[0])
        self.tabs.addTab(self._tab_extremos(), self.TABS[1])
        self.tabs.addTab(self._tab_datos(), self.TABS[2])
        lay.addWidget(self.tabs, 1)

        row = QHBoxLayout()
        row.addStretch()
        b = QPushButton("Cancelar")
        b.clicked.connect(self.reject)
        row.addWidget(b)
        b = QPushButton("Aplicar")
        b.setObjectName("AccentBtn")
        b.clicked.connect(self.accept)
        row.addWidget(b)
        lay.addLayout(row)

    @staticmethod
    def _page():
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 10, 4, 4)
        lay.setSpacing(8)
        return w, lay

    @staticmethod
    def _sub(lay, text):
        lbl = QLabel(text)
        lbl.setObjectName("SubHeading")
        lay.addWidget(lbl)
        return lbl

    @staticmethod
    def _hint(lay, text):
        lbl = QLabel(text)
        lbl.setObjectName("Hint")
        lbl.setWordWrap(True)
        lay.addWidget(lbl)
        return lbl

    # ── Regiones ──
    def _region_text(self, code, name):
        r = self._regions.get(code)
        if r is None:
            return f"{code}  {name}   —  sin datos"
        return f"{code}  {name}   ·  {r.n_vertices} vértices  ·  {r.source}" + \
            ("  (oficial)" if r.official else "")

    def _tab_regiones(self):
        w, lay = self._page()
        self.chk_enabled = QCheckBox("Mostrar los límites de las FIR de Argentina")
        self.chk_enabled.setChecked(bool(self._cfg.get("fir_enabled", False)))
        self.chk_neighbors = QCheckBox("Incluir las FIR vecinas (más tenues, a rayas)")
        self.chk_neighbors.setChecked(bool(self._cfg.get("fir_neighbors", False)))
        lay.addWidget(self.chk_enabled)
        lay.addWidget(self.chk_neighbors)
        self._sub(lay, "FIR a dibujar")
        active = set(self._cfg.get("fir_active") or DEFAULTS["fir_active"])
        self.lst = QListWidget()
        self.lst.setMaximumHeight(300)
        for header, pairs in (("Argentina", firmod.ARGENTINA_FIRS), ("Vecinas", firmod.NEIGHBOR_FIRS)):
            h = QListWidgetItem(header)
            h.setFlags(Qt.ItemFlag.NoItemFlags)
            self.lst.addItem(h)
            for code, name in pairs:
                it = QListWidgetItem(self._region_text(code, name))
                it.setData(Qt.ItemDataRole.UserRole, code)
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(Qt.CheckState.Checked if code in active else Qt.CheckState.Unchecked)
                if code not in self._regions:
                    it.setToolTip("No hay polígono para esta FIR en ninguna fuente cargada")
                self.lst.addItem(it)
        lay.addWidget(self.lst)

        self._sub(lay, "Estilo")
        g = QGridLayout()
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(6)
        g.addWidget(QLabel("Color (Argentina)"), 0, 0)
        self.btn_color = QPushButton()
        self.btn_color.setFixedWidth(90)
        self.btn_color.clicked.connect(lambda: self._pick_color("ar"))
        g.addWidget(self.btn_color, 0, 1)
        g.addWidget(QLabel("Color (vecinas)"), 0, 2)
        self.btn_nb_color = QPushButton()
        self.btn_nb_color.setFixedWidth(90)
        self.btn_nb_color.clicked.connect(lambda: self._pick_color("nb"))
        g.addWidget(self.btn_nb_color, 0, 3)
        g.addWidget(QLabel("Grosor (pt)"), 1, 0)
        self.spin_lw = QDoubleSpinBox()
        self.spin_lw.setRange(0.3, 5.0)
        self.spin_lw.setSingleStep(0.1)
        self.spin_lw.setDecimals(1)
        self.spin_lw.setValue(float(self._cfg.get("fir_line_width", DEFAULTS["fir_line_width"])))
        g.addWidget(self.spin_lw, 1, 1)
        g.addWidget(QLabel("Relleno (%)"), 1, 2)
        self.spin_fill = QSpinBox()
        self.spin_fill.setRange(0, 60)
        self.spin_fill.setValue(int(round(100 * float(self._cfg.get("fir_fill_alpha", DEFAULTS["fir_fill_alpha"])))))
        self.spin_fill.setToolTip("0 = sólo el contorno; el relleno es semitransparente")
        g.addWidget(self.spin_fill, 1, 3)
        g.addWidget(QLabel("Etiqueta (pt)"), 2, 0)
        self.spin_label = QSpinBox()
        self.spin_label.setRange(5, 18)
        self.spin_label.setValue(int(self._cfg.get("fir_label_size", DEFAULTS["fir_label_size"])))
        g.addWidget(self.spin_label, 2, 1)
        b = QPushButton("Estilo por defecto")
        b.clicked.connect(self._reset_style)
        g.addWidget(b, 2, 3)
        g.setColumnStretch(4, 1)
        lay.addLayout(g)
        self._refresh_color_buttons()
        self._hint(lay, "La etiqueta (nombre y código OACI) va en el punto de etiqueta del dataset o, "
                        "si falta, en un punto interior calculado (no el centroide, que en polígonos "
                        "cóncavos cae afuera). El contorno se dibuja con el color elegido y se "
                        "recorta a la vista; los sectores hasta el polo se densifican antes de "
                        "proyectar.")
        lay.addStretch()
        return w

    def _refresh_color_buttons(self):
        for btn, col in ((self.btn_color, self._color), (self.btn_nb_color, self._nb_color)):
            btn.setText(col)
            btn.setStyleSheet(f"QPushButton {{ background: {col}; color: #000; border: 1px solid #888; }}")

    def _pick_color(self, which):
        cur = self._color if which == "ar" else self._nb_color
        c = QColorDialog.getColor(QColor(cur), self, "Color de los límites de FIR")
        if c.isValid():
            if which == "ar":
                self._color = c.name()
            else:
                self._nb_color = c.name()
            self._refresh_color_buttons()

    def _reset_style(self):
        self._color = DEFAULTS["fir_color"]
        self._nb_color = DEFAULTS["fir_neighbor_color"]
        self.spin_lw.setValue(DEFAULTS["fir_line_width"])
        self.spin_fill.setValue(int(round(100 * DEFAULTS["fir_fill_alpha"])))
        self.spin_label.setValue(DEFAULTS["fir_label_size"])
        self._refresh_color_buttons()

    # ── Extremos ──
    def _tab_extremos(self):
        w, lay = self._page()
        if self._grid_bbox is not None:
            g = firmod.normalize_grid_bbox(*self._grid_bbox)
            self._sub(lay, f"Grilla abierta: lon {g[0]:.2f}° a {g[1]:.2f}°, lat {g[2]:.2f}° a {g[3]:.2f}°")
        else:
            self._sub(lay, "Sin archivo abierto: la cobertura se calcula al abrir una grilla")
        cols = ["FIR", "Código", "Norte", "Sur", "Este", "Oeste", "Vértices", "Cobertura", "Fuente"]
        rows = [(c, n) for c, n in firmod.ARGENTINA_FIRS + firmod.NEIGHBOR_FIRS]
        self.table = QTableWidget(len(rows), len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        hh = self.table.horizontalHeader()
        for i in range(len(cols)):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(len(cols) - 1, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setMinimumHeight(360)
        self.coverage = {}
        for r_i, (code, name) in enumerate(rows):
            reg = self._regions.get(code)
            vals = [name, code]
            if reg is not None:
                e = reg.extremes()
                cov = firmod.coverage(reg, self._grid_bbox)
                self.coverage[code] = cov
                vals += [f"{e['norte']:.2f}°", f"{e['sur']:.2f}°", f"{e['este']:.2f}°", f"{e['oeste']:.2f}°",
                         str(reg.n_vertices), COVERAGE_TEXT.get(cov, cov), reg.source]
            else:
                vals += ["—", "—", "—", "—", "0", "—", "sin datos"]
            for c_i, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if 2 <= c_i <= 6:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(r_i, c_i, it)
        lay.addWidget(self.table, 1)
        self._hint(lay, "Extremos calculados del polígono cargado (recuadro de la FIR). «Completa» "
                        "significa que el recuadro de la grilla contiene al de la FIR; «parcial», "
                        "que se solapan. Las FIR Comodoro Rivadavia, Punta Arenas y Johannesburgo "
                        "Oceánico llegan a 90° S, así que una grilla regional siempre las cubre "
                        "parcialmente.")
        return w

    # ── Datos ──
    def _tab_datos(self):
        w, lay = self._page()
        row = QHBoxLayout()
        row.addWidget(QLabel("Fuente descargada preferida"))
        self.cb_pref = QComboBox()
        self.cb_pref.addItem("VATSpy Data Project (abierta, no oficial)", "vatspy")
        self.cb_pref.addItem("openAIP (API con clave, no oficial)", "openaip")
        self.cb_pref.setCurrentIndex(max(0, self.cb_pref.findData(self._cfg.get("fir_preferred", "vatspy"))))
        row.addWidget(self.cb_pref, 1)
        lay.addLayout(row)
        self._hint(lay, "Orden de prioridad: el archivo propio reemplaza, para las FIR que contiene, a "
                        "la fuente preferida; esta reemplaza a la copia incluida con el visor."
                        + ("\nCargado ahora: " + " · ".join(self._notes) if self._notes else ""))

        # VATSpy
        self._sub(lay, "VATSpy Data Project — fuente abierta de respaldo (CC BY-SA 4.0)")
        self.lbl_vatspy = QLabel("")
        self.lbl_vatspy.setObjectName("Hint")
        self.lbl_vatspy.setWordWrap(True)
        lay.addWidget(self.lbl_vatspy)
        row = QHBoxLayout()
        self.btn_vatspy = QPushButton("Descargar límites de FIR (VATSpy)")
        self.btn_vatspy.setToolTip(firmod.VATSPY_URL)
        self.btn_vatspy.clicked.connect(lambda: self._start("vatspy"))
        row.addWidget(self.btn_vatspy)
        row.addStretch()
        lay.addLayout(row)
        warn = self._hint(lay, "⚠ " + firmod.VATSPY_NOTICE)
        warn.setObjectName("StatusWarn")

        # openAIP
        self._sub(lay, "openAIP — tercera fuente, con clave de API (CC BY-NC 4.0)")
        self.lbl_openaip = QLabel("")
        self.lbl_openaip.setObjectName("Hint")
        self.lbl_openaip.setWordWrap(True)
        lay.addWidget(self.lbl_openaip)
        row = QHBoxLayout()
        b = QPushButton("Configurar clave…")
        b.setToolTip("Clave de API de openAIP, guardada en el llavero del sistema (también en "
                     "Preferencias ▸ Fuentes)")
        b.clicked.connect(self._configure_openaip)
        row.addWidget(b)
        self.btn_openaip = QPushButton("Descargar de openAIP")
        self.btn_openaip.clicked.connect(lambda: self._start("openaip"))
        row.addWidget(self.btn_openaip)
        row.addStretch()
        lay.addLayout(row)

        # Archivo propio
        self._sub(lay, "Archivo propio (GeoJSON, KML/KMZ o Shapefile; p. ej. el generado desde el AIP)")
        self.lbl_user = QLabel("")
        self.lbl_user.setObjectName("Hint")
        self.lbl_user.setWordWrap(True)
        lay.addWidget(self.lbl_user)
        row = QHBoxLayout()
        b = QPushButton("Cargar archivo propio…")
        b.clicked.connect(self._pick_user_file)
        row.addWidget(b)
        self.btn_user_clear = QPushButton("Quitar")
        self.btn_user_clear.clicked.connect(self._clear_user_file)
        row.addWidget(self.btn_user_clear)
        b = QPushButton("Convertir texto del AIP…")
        b.setToolTip("Pegar la lista de vértices del AIP ENR 2.1 y generar un GeoJSON")
        b.clicked.connect(self._convert_aip)
        row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)

        # Progreso
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        lay.addWidget(self.progress)
        row = QHBoxLayout()
        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("SubHeading")
        self.lbl_status.setWordWrap(True)
        row.addWidget(self.lbl_status, 1)
        self.btn_cancel_dl = QPushButton("Cancelar descarga")
        self.btn_cancel_dl.setEnabled(False)
        self.btn_cancel_dl.clicked.connect(self._cancel_download)
        row.addWidget(self.btn_cancel_dl)
        lay.addLayout(row)
        lay.addStretch()
        self._refresh_data_labels()
        return w

    def _refresh_data_labels(self):
        info = firmod.file_info(firmod.data_file(firmod.VATSPY_FILE))
        if info:
            self.lbl_vatspy.setText(f"Descargado: {info['n']} FIR, {info['descargado'] or info['modificado']} "
                                    f"→ {info['ruta']}")
        else:
            b = firmod.file_info(firmod.BUNDLED_FILE)
            self.lbl_vatspy.setText("Todavía no se descargó; se usa la copia incluida con el visor"
                                    + (f" ({b['n']} FIR, {b['descargado'][:10]})" if b else " (no encontrada)")
                                    + ".")
        tok = creds.get("openaip_fir", "token") if creds.available() else None
        info = firmod.file_info(firmod.data_file(firmod.OPENAIP_FILE))
        txt = "Clave de API: " + ("guardada " + creds.masked(tok) if tok else "sin definir")
        if info:
            txt += f"   ·   descargado: {info['n']} FIR, {info['descargado'] or info['modificado']}"
        self.lbl_openaip.setText(txt)
        self.btn_openaip.setEnabled(bool(tok) and self._worker is None)
        if self._user_file:
            n = ""
            try:
                regs = firmod.load_any(self._user_file)
                n = f"  ·  {len(regs)} FIR: " + ", ".join(sorted(r.code for r in regs))
            except Exception as exc:
                n = f"  ·  no se pudo leer: {exc}"
            self.lbl_user.setText(self._user_file + n)
        else:
            self.lbl_user.setText("Sin archivo propio.")
        self.btn_user_clear.setEnabled(bool(self._user_file))

    # ── Descargas ──
    def _set_busy(self, busy):
        self.btn_vatspy.setEnabled(not busy)
        self.btn_cancel_dl.setEnabled(busy)
        if not busy:
            self._refresh_data_labels()
        else:
            self.btn_openaip.setEnabled(False)

    def _start(self, kind):
        if self._worker is not None and self._worker.isRunning():
            return
        self.progress.setValue(0)
        self.lbl_status.setText("Conectando…")
        self._worker = _FirWorker(kind, self._cfg, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(lambda res, err, k=kind: self._on_done(k, res, err))
        self._set_busy(True)
        self._worker.start()

    def _on_progress(self, msg, frac):
        self.lbl_status.setText(msg)
        self.progress.setValue(int(max(0.0, min(1.0, frac)) * 1000))

    def _on_done(self, kind, res, err):
        self._worker = None
        self._set_busy(False)
        if err == "cancelada":
            self.lbl_status.setText("Descarga cancelada.")
            self.progress.setValue(0)
            return
        if err:
            self.lbl_status.setText("Error: " + err.splitlines()[0])
            QMessageBox.critical(self, "Descargar límites de FIR", err)
            return
        if kind == "vatspy":
            path, found, missing = res
            msg = f"VATSpy: {len(found)} FIR guardadas en {os.path.basename(path)}."
            if missing:
                msg += " Faltan: " + ", ".join(missing) + "."
        else:
            path, regions, unknown = res
            msg = f"openAIP: {len(regions)} FIR guardadas en {os.path.basename(path)}."
            if unknown:
                msg += f" Sin código reconocido: {len(unknown)} (" + ", ".join(unknown[:4]) + ")."
            self.cb_pref.setCurrentIndex(max(0, self.cb_pref.findData("openaip")))
        self.lbl_status.setText(msg + " Se aplica al cerrar el diálogo.")
        self.progress.setValue(1000)

    def _cancel_download(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self.lbl_status.setText("Cancelando…")

    def _configure_openaip(self):
        from .source_config_dialog import SourceConfigDialog
        from ..sources.openaip_fir import OpenAipFirSource
        from ..sources import set_source_config
        src = OpenAipFirSource()
        dlg = SourceConfigDialog(self, src, self._cfg)
        if dlg.exec():
            set_source_config(self._cfg, src.key, enabled=dlg.enabled(), params=dlg.params())
        self._refresh_data_labels()

    # ── Archivo propio ──
    def _pick_user_file(self):
        start = os.path.dirname(self._user_file) if self._user_file else (self._cfg.get("last_directory") or "")
        path, _ = QFileDialog.getOpenFileName(self, "Archivo de límites de FIR", start, FILE_FILTER)
        if not path:
            return
        self.set_user_file(path)

    def set_user_file(self, path):
        """Valida el archivo, lo copia a la carpeta de datos (así sigue
        disponible si el original se mueve) y lo deja como archivo propio."""
        try:
            regs = firmod.load_any(path)
        except Exception as exc:
            QMessageBox.critical(self, "Archivo propio", f"No se pudo leer el archivo:\n{exc}")
            return False
        if not regs:
            QMessageBox.warning(self, "Archivo propio",
                                "El archivo no contiene ninguna FIR con código OACI reconocible "
                                "(propiedad id / icao / code, o el código en el nombre).")
            return False
        ext = os.path.splitext(path)[1].lower()
        if ext == ".shp":
            # Un Shapefile son varios archivos: se guarda convertido a GeoJSON
            dest = firmod.data_file(firmod.USER_FILE)
            firmod.save_geojson(regs, dest, {"fuente": "archivo propio", "origen": path})
        else:
            dest = firmod.data_file("fir_usuario" + (ext if ext in (".kml", ".kmz") else ".geojson"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if os.path.abspath(path) != os.path.abspath(dest):
                shutil.copyfile(path, dest)
        self._user_file = dest
        self._refresh_data_labels()
        self.lbl_status.setText(f"Archivo propio: {len(regs)} FIR ({', '.join(sorted(r.code for r in regs))}). "
                                "Reemplaza a las demás fuentes para esas FIR al aplicar.")
        return True

    def _clear_user_file(self):
        self._user_file = ""
        self._refresh_data_labels()

    def _convert_aip(self):
        from .aip_convert_dialog import AipConvertDialog
        dlg = AipConvertDialog(self, start_dir=self._cfg.get("last_directory") or "")
        if dlg.exec() and dlg.saved_path and dlg.use_as_user_file:
            self.set_user_file(dlg.saved_path)

    # ── Resultado ──
    def active_codes(self):
        out = []
        for i in range(self.lst.count()):
            it = self.lst.item(i)
            code = it.data(Qt.ItemDataRole.UserRole)
            if code and it.checkState() == Qt.CheckState.Checked:
                out.append(code)
        return out

    def values(self) -> dict:
        return {
            "fir_enabled": self.chk_enabled.isChecked(),
            "fir_neighbors": self.chk_neighbors.isChecked(),
            "fir_active": self.active_codes(),
            "fir_color": self._color,
            "fir_neighbor_color": self._nb_color,
            "fir_line_width": round(float(self.spin_lw.value()), 2),
            "fir_fill_alpha": round(self.spin_fill.value() / 100.0, 3),
            "fir_label_size": int(self.spin_label.value()),
            "fir_preferred": self.cb_pref.currentData() or "vatspy",
            "fir_user_file": self._user_file,
            "sources": dict(self._cfg.get("sources") or {}),
        }

    def closeEvent(self, event):
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)
        super().closeEvent(event)
