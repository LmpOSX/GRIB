from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QColorDialog, QSlider
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QBrush
from .glass_dialog import GlassDialog, add_shadow as _add_shadow


class ColorPreview(QFrame):
    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._color = color
        self.setFixedSize(220, 80)

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

    def __init__(self, parent=None, current_color: str = "#4A90D9",
                 current_opacity: int = 180):
        super().__init__(parent)
        self._color = current_color
        self._opacity = current_opacity
        self.setWindowTitle("Configuración")
        self.setMinimumWidth(420)
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)

        panel = QFrame()
        panel.setObjectName("GlassPanel")
        _add_shadow(panel)
        outer.addWidget(panel)

        lay = QVBoxLayout(panel)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(16)

        title = QLabel("Configuración de Apariencia")
        title.setObjectName("Heading")
        lay.addWidget(title)

        sub = QLabel("Color principal de la interfaz")
        sub.setObjectName("SubHeading")
        lay.addWidget(sub)

        prev_row = QHBoxLayout()
        self._preview = ColorPreview(self._color)
        prev_row.addWidget(self._preview)
        self._hex_label = QLabel(self._color)
        self._hex_label.setObjectName("SubHeading")
        prev_row.addWidget(self._hex_label)
        prev_row.addStretch()
        lay.addLayout(prev_row)

        presets_label = QLabel("Presets")
        presets_label.setObjectName("SubHeading")
        lay.addWidget(presets_label)

        for row_start in range(0, len(self.PRESETS), 4):
            row = QHBoxLayout()
            for hex_c, name in self.PRESETS[row_start:row_start + 4]:
                btn = self._make_color_btn(hex_c, name)
                row.addWidget(btn)
            lay.addLayout(row)

        custom_btn = QPushButton("Elegir color personalizado...")
        custom_btn.clicked.connect(self._pick_custom)
        lay.addWidget(custom_btn)

        # ── Transparency slider ────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        lay.addWidget(sep)

        opacity_label = QLabel("Transparencia")
        opacity_label.setObjectName("SubHeading")
        lay.addWidget(opacity_label)

        slider_row = QHBoxLayout()
        slider_row.setSpacing(12)

        more_transp = QLabel("Transparente")
        more_transp.setObjectName("SubHeading")
        slider_row.addWidget(more_transp)

        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(2, 255)
        self._opacity_slider.setValue(self._opacity)
        self._opacity_slider.setTickInterval(10)
        self._opacity_slider.valueChanged.connect(self._on_opacity_changed)
        slider_row.addWidget(self._opacity_slider, 1)

        less_transp = QLabel("Opaco")
        less_transp.setObjectName("SubHeading")
        slider_row.addWidget(less_transp)

        lay.addLayout(slider_row)

        self._opacity_value_label = QLabel(f"{self._opacity}")
        self._opacity_value_label.setObjectName("SubHeading")
        self._opacity_value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._opacity_value_label)

        # ── Buttons ────────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton("Aplicar")
        ok_btn.setObjectName("AccentBtn")
        ok_btn.clicked.connect(self._apply)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        lay.addLayout(btn_row)

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

    def _apply(self):
        self.accept()

    def selected_color(self) -> str:
        return self._color

    def selected_opacity(self) -> int:
        return self._opacity
