# -*- coding: utf-8 -*-
"""«Generar GRIB…»: un formulario para fabricar un GRIB2 a mano.

Arriba, lo general del archivo: corrida y plazo, zona (manual o por FIR con
sus casillas y margen), resolución (0,25 / 0,50 / 1,00°), carpeta y nombre.
Abajo, la tabla de niveles: un botón por modo (INDRA 14, OACI 17, OACI 56,
WAFS 56) la llena con los FL de ese modo y fija cómo se etiquetan; en cada
fila se escribe la temperatura, la velocidad y la dirección del viento. Los
valores son uniformes en toda la grilla. El viento se puede grabar como
U/V o como dirección y velocidad.
"""
import datetime as dt
import os

from PyQt6.QtCore import Qt, QDate, QTimer
from PyQt6.QtGui import QColor, QPen
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QFrame, QCheckBox,
    QComboBox, QLineEdit, QMessageBox, QRadioButton, QDoubleSpinBox, QSpinBox, QDateEdit,
    QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView, QWidget, QAbstractItemView,
    QButtonGroup, QSizePolicy, QStyledItemDelegate, QStyle,
)

from .glass_dialog import GlassDialog, add_shadow as _add_shadow
from ..widgets.areas_editor import CoordEdit
from .. import areas as A
from .. import fl_table as flt
from .. import grib_generate as gg
from .. import wind_format as wfm
from .download_dialog import MODE_BUTTONS

COLS = ("FL", "Presión", "T (°C)", "Viento (kt)", "Dir (°)")
COL_FL, COL_P, COL_T, COL_SPD, COL_DIR = range(5)
EDITABLE_COLS = (COL_FL, COL_T, COL_SPD, COL_DIR)


class _CellDelegate(QStyledItemDelegate):
    """Edición visible: el editor tapa la celda con el mismo valor, centrado,
    con el texto preseleccionado (una tecla lo reemplaza; las flechas sueltan
    la selección para corregirlo); la celda actual lleva un marco del color
    de acento para que se vea cuál se edita."""

    def __init__(self, accent, parent=None):
        super().__init__(parent)
        self._accent = QColor(accent)

    def createEditor(self, parent, option, index):
        ed = QLineEdit(parent)
        ed.setObjectName("TableCellEditor")
        ed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ed.setFrame(True)
        return ed

    def setEditorData(self, editor, index):
        editor.setText(str(index.data() or ""))
        editor.selectAll()
        QTimer.singleShot(0, editor.selectAll)     # por si el foco vuelve a mover el cursor

    def setModelData(self, editor, model, index):
        model.setData(index, editor.text().strip(), Qt.ItemDataRole.EditRole)

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)            # tapa la celda entera

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        view = self.parent()
        if view is not None and index == view.currentIndex() and index.column() in EDITABLE_COLS:
            painter.save()
            painter.setPen(QPen(self._accent, 2))
            painter.drawRect(option.rect.adjusted(1, 1, -2, -2))
            painter.restore()


class GenerateGribDialog(GlassDialog):
    """`generated_path` queda con la ruta escrita al terminar (o None);
    `open_after` dice si hay que abrirlo en el visor."""

    def __init__(self, parent=None, cfg=None, dest_dir=".", region=None):
        super().__init__(parent)
        self.setWindowTitle("Generar GRIB")
        self.setMinimumWidth(760)
        self._cfg = cfg if cfg is not None else {}
        self._dest_dir = dest_dir
        self._areas = list(A.areas_from_config(self._cfg))
        self._area_checks = {}
        self._area_updating = False
        self._mode = flt.normalize_mode(self._cfg.get("wafs_mode", flt.DEFAULT_MODE))
        self.generated_path = None
        self.open_after = True
        self._build_ui()
        if region is not None:
            self.set_region(*region)
        self._apply_mode(self._mode)
        self._refresh_area()

    # ── Construcción ─────────────────────────────────────────────────────────

    @staticmethod
    def _group(parent_lay, title):
        box = QFrame()
        box.setObjectName("DownloadGroup")
        parent_lay.addWidget(box)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(10, 4, 10, 6)
        lay.setSpacing(4)
        lbl = QLabel(title)
        lbl.setObjectName("GroupTitle")
        lay.addWidget(lbl)
        return lay

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        panel = QFrame()
        panel.setObjectName("GlassPanel")
        _add_shadow(panel)
        outer.addWidget(panel)
        plan = QVBoxLayout(panel)
        plan.setContentsMargins(24, 16, 24, 16)
        plan.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel("Generar GRIB")
        title.setObjectName("Heading")
        head.addWidget(title)
        hint = QLabel("un perfil uniforme (temperatura y viento por FL) sobre una grilla regular")
        hint.setObjectName("Hint")
        head.addSpacing(12)
        head.addWidget(hint, 1)
        plan.addLayout(head)

        # ── Corrida y plazo ──
        lay = self._group(plan, "Corrida y plazo")
        row = QHBoxLayout()
        row.addWidget(QLabel("Corrida"))
        now = dt.datetime.now(dt.timezone.utc)
        self.ed_date = QDateEdit(QDate(now.year, now.month, now.day))
        self.ed_date.setDisplayFormat("yyyy-MM-dd")
        self.ed_date.setCalendarPopup(True)
        row.addWidget(self.ed_date)
        self.cb_cycle = QComboBox()
        for c in (0, 6, 12, 18):
            self.cb_cycle.addItem(f"{c:02d}Z", c)
        self.cb_cycle.setCurrentIndex(max(0, self.cb_cycle.findData((now.hour // 6) * 6)))
        row.addWidget(self.cb_cycle)
        row.addSpacing(16)
        row.addWidget(QLabel("Plazo"))
        self.sp_step = QSpinBox()
        self.sp_step.setRange(0, 384)
        self.sp_step.setSuffix(" h")
        self.sp_step.setValue(int(self._cfg.get("download_h_from", 6)))
        self.sp_step.setMaximumWidth(90)
        row.addWidget(self.sp_step)
        row.addSpacing(16)
        self.lbl_valid = QLabel("")
        self.lbl_valid.setObjectName("Hint")
        row.addWidget(self.lbl_valid, 1)
        lay.addLayout(row)
        for w in (self.ed_date, self.cb_cycle, self.sp_step):
            sig = getattr(w, "dateChanged", None) or getattr(w, "currentIndexChanged", None) \
                or getattr(w, "valueChanged", None)
            sig.connect(lambda *_a: self._refresh_valid())
        self._refresh_valid()

        # ── Área y grilla ──
        lay = self._group(plan, "Área y grilla")
        zg = QGridLayout()
        zg.setHorizontalSpacing(8)
        zg.setVerticalSpacing(4)
        zg.addWidget(QLabel("Área"), 0, 0, alignment=Qt.AlignmentFlag.AlignRight)
        self.rb_manual = QRadioButton("Manual")
        self.rb_fir = QRadioButton("Por FIR")
        grp = QButtonGroup(self)
        grp.addButton(self.rb_manual)
        grp.addButton(self.rb_fir)
        mode_cfg = self._cfg.get("download_area_mode", "fir")
        (self.rb_fir if mode_cfg == "fir" else self.rb_manual).setChecked(True)
        self.rb_manual.toggled.connect(lambda _c: self._refresh_area())
        zg.addWidget(self.rb_manual, 0, 1)
        self.manual_box = QWidget()
        g = QGridLayout(self.manual_box)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(6)
        fmt = self._cfg.get("areas_coord_format", "decimal")
        mr = self._cfg.get("download_manual_region") or [4.0, -64.0, -90.0, -22.0]
        self.lat_n = self._coord(g, "Lat N", 0, 0, "lat", float(mr[0]), fmt)
        self.lat_s = self._coord(g, "Lat S", 0, 2, "lat", float(mr[1]), fmt)
        self.lon_w = self._coord(g, "Lon W", 0, 4, "lon", float(mr[2]), fmt)
        self.lon_e = self._coord(g, "Lon E", 0, 6, "lon", float(mr[3]), fmt)
        zg.addWidget(self.manual_box, 0, 2)
        zg.addWidget(self.rb_fir, 1, 1)
        self.fir_box = QWidget()
        fl = QHBoxLayout(self.fir_box)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(6)
        self.area_grid_w = QWidget()
        self.area_grid = QGridLayout(self.area_grid_w)
        self.area_grid.setContentsMargins(0, 0, 0, 0)
        self.area_grid.setHorizontalSpacing(10)
        self.area_grid.setVerticalSpacing(2)
        fl.addWidget(self.area_grid_w)
        fl.addSpacing(10)
        b = QPushButton("Todas")
        b.clicked.connect(lambda: self._set_all_areas(True))
        fl.addWidget(b)
        b = QPushButton("Ninguna")
        b.clicked.connect(lambda: self._set_all_areas(False))
        fl.addWidget(b)
        fl.addStretch()
        zg.addWidget(self.fir_box, 1, 2)
        self._build_area_checks()
        zg.addWidget(QLabel("Resolución"), 2, 0, alignment=Qt.AlignmentFlag.AlignRight)
        res_row = QHBoxLayout()
        self.cb_res = QComboBox()
        for val, text in gg.RESOLUTIONS:
            self.cb_res.addItem(text, val)
        self.cb_res.setCurrentIndex(max(0, self.cb_res.findData(float(self._cfg.get("generate_res_deg", 0.25)))))
        self.cb_res.currentIndexChanged.connect(lambda _i: self._refresh_area())
        res_row.addWidget(self.cb_res)
        res_row.addSpacing(16)
        self.lbl_margin = QLabel("Margen por FIR")
        res_row.addWidget(self.lbl_margin)
        self.spin_margin = QDoubleSpinBox()
        self.spin_margin.setRange(0.0, 10.0)
        self.spin_margin.setDecimals(2)
        self.spin_margin.setSingleStep(0.25)
        self.spin_margin.setSuffix("°")
        self.spin_margin.setValue(float(self._cfg.get("areas_margin_deg", A.DEFAULT_MARGIN_DEG)))
        self.spin_margin.setToolTip("Se suma por fuera a cada límite de la envolvente de las FIR marcadas")
        self.spin_margin.valueChanged.connect(lambda _v: self._refresh_area())
        res_row.addWidget(self.spin_margin)
        res_row.addStretch()
        zg.addLayout(res_row, 2, 1, 1, 2)
        self.lbl_size = QLabel("")
        self.lbl_size.setObjectName("Hint")
        self.lbl_size.setWordWrap(True)
        # Que el texto largo de la zona no ensanche el diálogo: se ajusta al ancho que haya
        self.lbl_size.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.lbl_size.setMinimumHeight(2 * self.lbl_size.fontMetrics().lineSpacing() + 4)
        zg.addWidget(self.lbl_size, 3, 1, 1, 2)
        zg.setColumnStretch(2, 1)
        lay.addLayout(zg)

        # ── Niveles y valores ──
        lay = self._group(plan, "Niveles y valores (uniformes en toda la grilla)")
        row = QHBoxLayout()
        row.addWidget(QLabel("Niveles"))
        self.mode_buttons = {}
        for m in flt.MODES:
            b = QPushButton(MODE_BUTTONS[m])
            b.setCheckable(True)
            b.setToolTip(flt.MODE_LABELS[m] + ". Llena la tabla con los FL de ese modo y fija "
                         "cómo se etiquetan los niveles en el archivo.")
            b.clicked.connect(lambda _on, m=m: self._on_mode_clicked(m))
            self.mode_buttons[m] = b
            row.addWidget(b)
        row.addSpacing(16)
        row.addWidget(QLabel("Viento en el archivo"))
        self.cb_wind = QComboBox()
        for key, text in wfm.FORMATS:
            self.cb_wind.addItem(text, key)
        self.cb_wind.setCurrentIndex(max(0, self.cb_wind.findData(
            wfm.normalize(self._cfg.get("download_wind_format", "uv")))))
        self.cb_wind.setToolTip("La tabla se carga siempre en velocidad y dirección; el archivo se "
                                "graba como U/V (UGRD/VGRD, como los modelos) o como dirección y "
                                "velocidad (WDIR/WIND) según esta opción. El visor lee los dos; el "
                                "WAFS operativo lleva U/V.")
        row.addWidget(self.cb_wind)
        row.addStretch()
        lay.addLayout(row)

        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setMinimumHeight(260)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # Edición: un clic (o Tab, o las flechas) pone la celda en edición con
        # el valor preseleccionado; Enter aplica, Esc sale sin cambiar y deja
        # la fila elegida; Tab recorre celdas y filas
        self.table.setItemDelegate(_CellDelegate(self._cfg.get("accent_color", "#4A90D9"), self.table))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.CurrentChanged
                                   | QAbstractItemView.EditTrigger.SelectedClicked
                                   | QAbstractItemView.EditTrigger.DoubleClicked
                                   | QAbstractItemView.EditTrigger.EditKeyPressed
                                   | QAbstractItemView.EditTrigger.AnyKeyPressed)
        self.table.setTabKeyNavigation(True)
        self.table.currentCellChanged.connect(self._on_current_cell_changed)
        self.table.setToolTip("FL (de a 10, FL050–FL600), temperatura en °C, velocidad en kt y "
                              "dirección verdadera en grados (de dónde sopla). La presión es la "
                              "etiqueta con la que se graba el nivel en el modo elegido. Siempre "
                              "hay una fila elegida: Agregar inserta FL+10 encima de ella y "
                              "Quitar la saca y pasa a la de abajo.")
        self.table.itemChanged.connect(self._on_item_changed)
        lay.addWidget(self.table)
        row = QHBoxLayout()
        for text, fn, tip in (
                ("Temperatura ISA", self._fill_isa, "Pone en cada fila la temperatura ISA de su FL"),
                ("Copiar hacia abajo", self._copy_down, "Copia T, viento y dirección de la fila "
                                                        "elegida a todas las de abajo"),
                ("Agregar FL", self._add_row, "Agrega una fila (FL siguiente libre)"),
                ("Quitar FL", self._remove_row, "Quita la fila elegida")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        self.lbl_levels = QLabel("")
        self.lbl_levels.setObjectName("Hint")
        row.addWidget(self.lbl_levels)
        lay.addLayout(row)

        # ── Archivo ──
        lay = self._group(plan, "Archivo")
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.addWidget(QLabel("Carpeta"), 0, 0)
        self.dest = QLineEdit(self._dest_dir)
        g.addWidget(self.dest, 0, 1)
        b = QPushButton("Elegir…")
        b.clicked.connect(self._pick_dir)
        g.addWidget(b, 0, 2)
        g.addWidget(QLabel("Nombre"), 1, 0)
        self.name = QLineEdit()
        self.name.setPlaceholderText("(automático: generado_<corrida>_<plazo>_<res>_<área>_<modo>)")
        g.addWidget(self.name, 1, 1)
        self.chk_open = QCheckBox("Abrir en el visor al terminar")
        self.chk_open.setChecked(bool(self._cfg.get("download_open", True)))
        g.addWidget(self.chk_open, 1, 2)
        lay.addLayout(g)

        row = QHBoxLayout()
        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("SubHeading")
        row.addWidget(self.lbl_status, 1)
        self.btn_cancel = QPushButton("Cerrar")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_generate = QPushButton("Generar")
        self.btn_generate.setObjectName("AccentBtn")
        self.btn_generate.clicked.connect(self._generate)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_generate)
        plan.addLayout(row)

    def _coord(self, grid, text, r, c, kind, val, fmt="decimal"):
        grid.addWidget(QLabel(text), r, c, alignment=Qt.AlignmentFlag.AlignRight)
        ed = CoordEdit(kind, val, fmt)
        ed.value_changed.connect(lambda _v: self._refresh_area())
        ed.invalid.connect(lambda msg: self.lbl_size.setText("Coordenada inválida: " + msg))
        grid.addWidget(ed, r, c + 1)
        return ed

    # ── Corrida ──────────────────────────────────────────────────────────────

    def run(self):
        d = self.ed_date.date()
        return dt.datetime(d.year(), d.month(), d.day(), int(self.cb_cycle.currentData() or 0),
                           tzinfo=dt.timezone.utc)

    def step_h(self):
        return int(self.sp_step.value())

    def _refresh_valid(self):
        valid = self.run() + dt.timedelta(hours=self.step_h())
        self.lbl_valid.setText(f"validez {valid:%d/%m %H:%M} UTC")

    # ── Área ─────────────────────────────────────────────────────────────────

    def _build_area_checks(self):
        wanted = set(self._cfg.get("download_area_codes") or A.ARGENTINA_CODES)
        enabled = [a for a in self._areas if a.enabled]
        for k, a in enumerate(enabled):
            c = QCheckBox(a.code)
            c.setToolTip(a.name or a.code)
            c.setChecked(a.code in wanted)
            c.setMinimumWidth(c.sizeHint().width())      # que no se recorte el código
            c.toggled.connect(lambda _on: self._refresh_area())
            self._area_checks[a.code] = c
            self.area_grid.addWidget(c, k // 6, k % 6)

    def _set_all_areas(self, on):
        self._area_updating = True
        try:
            for c in self._area_checks.values():
                c.setChecked(on)
        finally:
            self._area_updating = False
        self._refresh_area()

    def area_mode(self):
        return "fir" if self.rb_fir.isChecked() else "manual"

    def selected_codes(self):
        return [a.code for a in self._areas if a.code in self._area_checks
                and self._area_checks[a.code].isChecked()]

    def margin(self):
        return float(self.spin_margin.value())

    def fir_envelope(self):
        codes = set(self.selected_codes())
        return A.envelope([a for a in self._areas if a.code in codes], self.margin())

    def region(self):
        """Zona (top, bottom, left, right) elegida, o None si falta."""
        if self.area_mode() == "fir":
            return self.fir_envelope()
        return (self.lat_n.value(), self.lat_s.value(), self.lon_w.value(), self.lon_e.value())

    def set_region(self, top, bottom, left, right):
        self.rb_manual.setChecked(True)
        for ed, v in ((self.lat_n, top), (self.lat_s, bottom), (self.lon_w, left), (self.lon_e, right)):
            ed.set_value(v)
        self._refresh_area()

    def resolution(self):
        return float(self.cb_res.currentData() or 0.25)

    def _refresh_area(self):
        if self._area_updating or not hasattr(self, "lbl_size"):
            return
        fir = self.area_mode() == "fir"
        self.fir_box.setEnabled(fir)
        self.manual_box.setEnabled(not fir)
        self.spin_margin.setEnabled(fir)
        self.lbl_margin.setEnabled(fir)
        region = self.region()
        if fir and not self.selected_codes():
            self.lbl_size.setText("Marcá al menos una FIR (o pasá a modo manual).")
            return
        if region is None:
            self.lbl_size.setText("")
            return
        if region[0] <= region[1] or region[3] <= region[2]:
            self.lbl_size.setText("La zona está invertida: Lat N > Lat S y Lon E > Lon W.")
            return
        lats, lons, zone = gg.grid_axes(region, self.resolution())

        def lat(v):
            return f"{abs(v):g}{'N' if v >= 0 else 'S'}"

        def lon(v):
            return f"{abs(v):g}{'E' if v >= 0 else 'W'}"
        txt = (f"grilla {len(lons)} × {len(lats)} puntos  ·  zona {lat(zone[0])}–{lat(zone[1])}, "
               f"{lon(zone[2])}–{lon(zone[3])} (redondeada hacia afuera a {self.resolution():g}°)")
        if fir:
            txt += f"  ·  margen {self.margin():g}° incluido"
        self.lbl_size.setText(txt)

    # ── Tabla de niveles ─────────────────────────────────────────────────────

    def _on_mode_clicked(self, mode):
        self._apply_mode(mode)

    def _apply_mode(self, mode):
        """Botón de modo: la tabla pasa a tener exactamente los FL del modo,
        conservando los valores de los FL que ya estaban."""
        self._mode = flt.normalize_mode(mode)
        for m, b in self.mode_buttons.items():
            b.setChecked(m == self._mode)
        old = {r["fl"]: r for r in self._rows(strict=False)}
        rows = []
        for fl in sorted(flt.mode_fls(self._mode), reverse=True):
            r = old.get(fl) or {"fl": fl, "t_c": round(gg.isa_temp_c(fl), 1), "spd_kt": 0.0, "dir_deg": 0.0}
            rows.append(r)
        self._set_rows(rows)

    def _set_rows(self, rows, select=None):
        """Rellena la tabla y deja elegida la fila `select` (por defecto la
        última, abajo): siempre hay una fila elegida si hay filas."""
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(0)
            for r in rows:
                self._append_row(r)
        finally:
            self.table.blockSignals(False)
        self._refresh_pressures()
        self._select_row(self.table.rowCount() - 1 if select is None else select)

    def _select_row(self, i):
        n = self.table.rowCount()
        if n == 0:
            self.table.clearSelection()
            return
        i = max(0, min(int(i), n - 1))
        self.table.setCurrentCell(i, COL_FL)
        self.table.selectRow(i)
        self.table.scrollToItem(self.table.item(i, COL_FL))
        self.table.setFocus()

    def _append_row(self, r):
        i = self.table.rowCount()
        self.table.insertRow(i)
        vals = (f"{int(r['fl'])}", "", f"{float(r['t_c']):g}", f"{float(r['spd_kt']):g}",
                f"{float(r['dir_deg']):g}")
        for c, v in enumerate(vals):
            it = QTableWidgetItem(v)
            it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if c == COL_P:
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(i, c, it)

    def _refresh_pressures(self):
        """Columna «Presión»: la etiqueta del nivel en el modo vigente (y
        «repetido» si el FL ya está en otra fila)."""
        self.table.blockSignals(True)
        try:
            fls = []
            for i in range(self.table.rowCount()):
                try:
                    fls.append(int(round(float(self.table.item(i, COL_FL).text()))))
                except (AttributeError, ValueError):
                    fls.append(None)
            for i in range(self.table.rowCount()):
                it_p = self.table.item(i, COL_P)
                if it_p is None:
                    continue
                fl = fls[i]
                if fl is None:
                    it_p.setText("FL inválido")
                elif fl not in flt.FL_TABLE:
                    it_p.setText("FL fuera de la tabla")
                elif fls.count(fl) > 1:
                    it_p.setText("repetido")
                else:
                    pa = flt.label_pa(fl, self._mode)
                    it_p.setText(f"{pa / 100.0:g} hPa" + ("" if self._mode == "WAFS" else " (nominal)"))
        finally:
            self.table.blockSignals(False)
        n = self.table.rowCount()
        self.lbl_levels.setText(f"{n} nivel(es) · modo {self._mode}")

    def _on_current_cell_changed(self, row, col, prev_row, prev_col):
        """La columna Presión no se edita: al caer en ella (Tab, flechas) se
        sigue de largo en el sentido del movimiento, y se abre el editor."""
        if row < 0:
            return
        if col == COL_P:
            nxt = COL_T if prev_col < COL_P or prev_row != row else COL_FL
            QTimer.singleShot(0, lambda: self.table.setCurrentCell(row, nxt))
            return
        idx = self.table.model().index(row, col)
        if idx.isValid() and self.table.state() != QAbstractItemView.State.EditingState:
            QTimer.singleShot(0, lambda: self.table.edit(idx))

    def _on_item_changed(self, item):
        if item.column() == COL_FL:
            # Un FL escrito a mano saca a la tabla del modo: se mantiene la etiqueta del modo
            self._refresh_pressures()

    def _rows(self, strict=True):
        """[{fl, t_c, spd_kt, dir_deg}] de la tabla; con `strict` las filas
        inválidas se saltean, sin él se devuelven las que se puedan leer."""
        out = []
        for i in range(self.table.rowCount()):
            try:
                out.append({"fl": int(round(float(self.table.item(i, COL_FL).text()))),
                            "t_c": float(self.table.item(i, COL_T).text().replace(",", ".")),
                            "spd_kt": float(self.table.item(i, COL_SPD).text().replace(",", ".")),
                            "dir_deg": float(self.table.item(i, COL_DIR).text().replace(",", "."))})
            except (AttributeError, ValueError):
                if strict:
                    raise ValueError(f"fila {i + 1}: valores incompletos o no numéricos")
        return out

    def _selected_row(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if rows:
            return rows[0].row()
        return self.table.currentRow() if self.table.currentRow() >= 0 else None

    def _fill_isa(self):
        self.table.blockSignals(True)
        try:
            for i in range(self.table.rowCount()):
                try:
                    fl = int(round(float(self.table.item(i, COL_FL).text())))
                except (AttributeError, ValueError):
                    continue
                self.table.item(i, COL_T).setText(f"{gg.isa_temp_c(fl):.1f}")
        finally:
            self.table.blockSignals(False)

    def _copy_down(self):
        i = self._selected_row()
        if i is None:
            self.lbl_status.setText("Elegí la fila desde la que copiar.")
            return
        vals = [self.table.item(i, c).text() for c in (COL_T, COL_SPD, COL_DIR)]
        self.table.blockSignals(True)
        try:
            for j in range(i + 1, self.table.rowCount()):
                for c, v in zip((COL_T, COL_SPD, COL_DIR), vals):
                    self.table.item(j, c).setText(v)
        finally:
            self.table.blockSignals(False)
        self.lbl_status.setText("")

    def _row_dict(self, i):
        """La fila `i` como dict, o None si no se puede leer."""
        try:
            return {"fl": int(round(float(self.table.item(i, COL_FL).text()))),
                    "t_c": float(self.table.item(i, COL_T).text().replace(",", ".")),
                    "spd_kt": float(self.table.item(i, COL_SPD).text().replace(",", ".")),
                    "dir_deg": float(self.table.item(i, COL_DIR).text().replace(",", "."))}
        except (AttributeError, ValueError):
            return None

    def _add_row(self):
        """Inserta una fila encima de la elegida con FL + 10 (aunque ese FL ya
        esté: la columna Presión lo marca «repetido» para corregirlo), con la
        T ISA y el viento de la fila elegida; la elegida sigue siéndolo. Sin
        filas, agrega FL050 y la elige."""
        i = self._selected_row()
        if i is None or self.table.rowCount() == 0:
            fl = flt.FL_LOWEST
            self.table.blockSignals(True)
            try:
                self._append_row({"fl": fl, "t_c": round(gg.isa_temp_c(fl), 1), "spd_kt": 0.0, "dir_deg": 0.0})
            finally:
                self.table.blockSignals(False)
            self._refresh_pressures()
            self._select_row(self.table.rowCount() - 1)
            self._uncheck_modes()
            return
        base = self._row_dict(i) or {"fl": flt.FL_LOWEST, "t_c": 0.0, "spd_kt": 0.0, "dir_deg": 0.0}
        fl = min(flt.FL_HIGHEST, base["fl"] + flt.FL_STEP)
        new = {"fl": fl, "t_c": round(gg.isa_temp_c(fl), 1), "spd_kt": base["spd_kt"], "dir_deg": base["dir_deg"]}
        self.table.blockSignals(True)
        try:
            self.table.insertRow(i)
            vals = (f"{new['fl']}", "", f"{new['t_c']:g}", f"{new['spd_kt']:g}", f"{new['dir_deg']:g}")
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == COL_P:
                    it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(i, c, it)
        finally:
            self.table.blockSignals(False)
        self._refresh_pressures()
        self._select_row(i + 1)              # la que estaba elegida, ahora una más abajo
        self._uncheck_modes()

    def _remove_row(self):
        """Quita la fila elegida y elige la de abajo; si era la última de
        abajo, la nueva última; sin filas no queda nada elegido."""
        i = self._selected_row()
        if i is None or self.table.rowCount() == 0:
            self.lbl_status.setText("No hay fila elegida.")
            return
        self.table.removeRow(i)
        self._refresh_pressures()
        self._select_row(i if i < self.table.rowCount() else self.table.rowCount() - 1)
        self._uncheck_modes()

    def _uncheck_modes(self):
        """La tabla ya no coincide con un modo: los botones se destildan, pero
        el etiquetado sigue siendo el del último modo elegido."""
        fls = sorted(r["fl"] for r in self._rows(strict=False))
        for m, b in self.mode_buttons.items():
            b.setChecked(m == self._mode and fls == sorted(flt.mode_fls(m)))

    # ── Archivo ──────────────────────────────────────────────────────────────

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Carpeta de destino", self.dest.text() or ".")
        if d:
            self.dest.setText(d)

    def wind_format(self):
        return wfm.normalize(self.cb_wind.currentData())

    def output_path(self):
        run, step = self.run(), self.step_h()
        tag = A.area_tag(self.selected_codes() if self.area_mode() == "fir" else [], self.area_mode())
        base = self.name.text().strip() or gg.default_basename(run, step, self.resolution(), tag,
                                                                 self.wind_format(), self._mode)
        if not base.lower().endswith(".grib2"):
            base += ".grib2"
        return os.path.join(self.dest.text().strip() or ".", base)

    def _generate(self):
        region = self.region()
        if self.area_mode() == "fir" and not self.selected_codes():
            QMessageBox.warning(self, "Generar GRIB", "Marcá al menos una FIR, o pasá a modo manual.")
            return
        if region is None or region[0] <= region[1] or region[3] <= region[2]:
            QMessageBox.warning(self, "Generar GRIB", "La zona no es válida (Lat N > Lat S, Lon E > Lon W).")
            return
        try:
            rows = self._rows()
        except ValueError as exc:
            QMessageBox.warning(self, "Generar GRIB", str(exc))
            return
        rows, err = gg.validate_rows(rows)
        if err:
            QMessageBox.warning(self, "Generar GRIB", err)
            return
        path = self.output_path()
        if os.path.exists(path):
            r = QMessageBox.question(self, "Generar GRIB",
                                     f"Ya existe {os.path.basename(path)}. ¿Reemplazar?")
            if r != QMessageBox.StandardButton.Yes:
                return
        try:
            data, info = gg.generate_grib(rows, region, self.resolution(), mode=self._mode,
                                          run=self.run(), step_h=self.step_h(),
                                          wind_format=self.wind_format())
            prov = gg.provenance(rows, info, self.area_mode(),
                                 self.selected_codes() if self.area_mode() == "fir" else [],
                                 self.margin() if self.area_mode() == "fir" else 0.0, region)
            gg.write_generated(path, data, prov)
        except Exception as exc:
            QMessageBox.critical(self, "Generar GRIB", f"No se pudo generar el archivo:\n{exc}")
            return
        self.generated_path = path
        self.open_after = self.chk_open.isChecked()
        self._cfg["generate_res_deg"] = self.resolution()
        self._cfg["download_wind_format"] = self.wind_format()
        self._cfg["download_area_mode"] = self.area_mode()
        if self.area_mode() == "fir":
            self._cfg["download_area_codes"] = self.selected_codes()
        else:
            self._cfg["download_manual_region"] = list(region)
        self.lbl_status.setText(f"Generado: {os.path.basename(path)} ({info['mensajes']} mensajes)")
        self.accept()
