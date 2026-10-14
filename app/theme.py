"""
Generates a full QSS glassmorphism theme from a single accent hex color.
Background is intentionally translucent — blur is applied at the OS level.
"""
import os

from PyQt6.QtGui import QColor

# Imágenes de los indicadores (tilde y punto) en resources/, referenciadas
# por ruta absoluta en el stylesheet
_RESOURCES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "resources").replace("\\", "/")


def _hex(color: QColor) -> str:
    return color.name()


def _rgba(color: QColor, alpha: int) -> str:
    return f"rgba({color.red()},{color.green()},{color.blue()},{alpha})"


def generate_palette(accent_hex: str) -> dict:
    base = QColor(accent_hex)

    def darken(c: QColor, factor: float) -> QColor:
        h, s, l, a = c.getHsl()
        return QColor.fromHsl(h, s, max(0, int(l * factor)), a)

    def lighten(c: QColor, factor: float) -> QColor:
        h, s, l, a = c.getHsl()
        return QColor.fromHsl(h, s, min(255, int(l + (255 - l) * factor)), a)

    return dict(
        bg0=darken(base, 0.25),        # main window bg — lighter
        bg1=darken(base, 0.32),        # sidebar / toolbar
        bg2=darken(base, 0.42),        # input fields
        bg_data=darken(base, 0.28),    # data area (tree background)
        mid=darken(base, 0.55),        # header sections
        text_bright=lighten(base, 0.95),
        text_dim=lighten(base, 0.65),
        accent=base,
        accent_light=lighten(base, 0.40),
        hover=lighten(base, 0.20),
        border=lighten(base, 0.28),
        row_alt=darken(base, 0.34),    # alternating row tint
    )


def _font_stack() -> str:
    """Lista de familias para el stylesheet: la del sistema y, como reserva,
    solo familias que existan en esta máquina.  Qt intenta resolver cada
    nombre de la lista y avisa en consola por los que faltan (p. ej. "Segoe
    UI" en macOS), así que no se incluyen a ciegas."""
    try:
        from PyQt6.QtGui import QFontDatabase
        installed = set(QFontDatabase.families())
        fams = [QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont).family()]
        for cand in ("Segoe UI", "Helvetica Neue", "Arial"):
            if cand in installed and cand not in fams:
                fams.append(cand)
        return ", ".join(f'"{f}"' for f in fams if f)
    except Exception:
        return "sans-serif"


def opaque_base_css(accent_hex: str) -> str:
    """Fondo sólido para las ventanas cuando no hay desenfoque nativo
    (Windows/Linux, o macOS si falla): los rgba del tema se apilan encima."""
    p = generate_palette(accent_hex)
    return f"QDialog {{ background-color: {_hex(p['bg0'])}; }}\n"


def opaque_window_css(accent_hex: str) -> str:
    p = generate_palette(accent_hex)
    return f"QMainWindow {{ background-color: {_hex(p['bg0'])}; }}"


def build_stylesheet(accent_hex: str, font_size: int = 13,
                     opacity: int = 180) -> str:
    p = generate_palette(accent_hex)
    font_stack = _font_stack()

    # Clamp opacity — minimum 2 because Qt QSS treats rgba(…,1) as 1.0 (opaque)
    opacity = max(2, min(255, opacity))

    # Derive per-element alphas from the master opacity (min 2 to avoid the 1→255 bug)
    a0    = opacity                           # main window bg
    a1    = max(2, opacity - 10)              # sidebar / toolbar
    a2    = max(2, opacity - 5)               # input fields
    a_d   = max(2, opacity - 20)              # data area — most transparent
    a_mid = max(2, opacity - 10)              # header sections
    a_row = max(2, int(opacity * 0.28))       # alternating row — subtle
    a_dlg = max(2, opacity - 40)              # dialogs — lighter than data area

    bg0   = _rgba(p["bg0"], a0)
    bg1   = _rgba(p["bg1"], a1)
    bg2   = _rgba(p["bg2"], a2)
    bg_d  = _rgba(p["bg_data"], a_d)
    bg_dlg = _rgba(p["bg_data"], a_dlg)
    mid   = _rgba(p["mid"], a_mid)
    row_a = _rgba(p["row_alt"], a_row)
    acc   = _hex(p["accent"])
    accl  = _hex(p["accent_light"])
    hov   = _rgba(p["hover"], 100)
    brd   = _rgba(p["border"], 80)
    txt   = _hex(p["text_bright"])
    txd   = _hex(p["text_dim"])
    acc_solid = _rgba(p["accent"], 230)
    sel   = _rgba(p["accent"], 90)

    h1 = font_size + 4   # Heading
    h2 = font_size - 1   # SubHeading
    h3 = font_size - 2   # SidebarSection / small labels
    total_sz = font_size + 1

    css = f"""
/* ── Global ── */
* {{
    font-family: {font_stack};
    font-size: {font_size}px;
    color: {txt};
    selection-background-color: {sel};
    selection-color: {txt};
}}

QMainWindow, QDialog {{
    background: transparent;
}}

/* ── Main container (content extends under native titlebar) ── */
#MainContainer {{
    background: {bg0};
    border: none;
    padding-top: 28px;
}}

/* ── Sidebar ── */
#ContentPanel {{
    background: transparent;
}}

/* ── Project list ── */
QListWidget {{
    background: transparent;
    border: none;
    outline: none;
}}
QListWidget::item {{
    padding: 8px 16px;
    border-radius: 6px;
    color: {txd};
}}
QListWidget::item:selected {{
    background: {sel};
    color: {txt};
}}
QListWidget::item:hover:!selected {{
    background: {hov};
    color: {txt};
}}

/* ── Budget tree ── */
QTreeWidget {{
    background: {bg_d};
    border: none;
    outline: none;
    alternate-background-color: {row_a};
    show-decoration-selected: 0;
}}
QTreeWidget::item {{
    padding: 5px 4px;
    border-radius: 3px;
}}
QTreeWidget::item:selected {{
    background: {sel};
}}
QTreeWidget::item:hover:!selected {{
    background: {hov};
}}
QTreeWidget::branch {{
    background: transparent;
}}
QTreeWidget::branch:has-children:closed {{
    image: none;
    border: none;
}}
QTreeWidget::branch:open:has-children {{
    image: none;
    border: none;
}}

QHeaderView {{
    background: transparent;
    border: none;
}}
QHeaderView::section {{
    background: {mid};
    color: {txd};
    padding: 6px 8px;
    border: none;
    border-right: 1px solid {brd};
    font-size: {h2}px;
    font-weight: 600;
    letter-spacing: 0.4px;
}}
QHeaderView::section:hover {{
    background: {hov};
    color: {txt};
}}
QHeaderView::section:first {{
    border-top-left-radius: 6px;
}}
QHeaderView::section:last {{
    border-right: none;
    border-top-right-radius: 6px;
}}

/* ── Scrollbars ── */
QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {brd};
    border-radius: 3px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: transparent;
    height: 12px;
}}
QScrollBar::handle:horizontal {{
    background: {brd};
    border-radius: 3px;
    min-width: 24px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* ── Buttons ── */
QPushButton, QToolButton {{
    background: {bg2};
    border: none;
    border-radius: 7px;
    padding: 5px 12px;
    color: {txt};
    font-weight: 500;
}}
QPushButton:hover, QToolButton:hover {{
    background: {hov};
}}
QPushButton:pressed, QToolButton:pressed {{
    background: {acc_solid};
}}
QToolButton::menu-indicator {{
    image: none;
    width: 0;
}}
#DropdownBtn {{
    padding-right: 18px;
}}
#DropdownBtn::menu-indicator {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    right: 4px;
}}
QPushButton#AccentBtn {{
    background: {acc_solid};
    font-weight: 600;
}}
QPushButton#AccentBtn:hover {{
    background: {accl};
}}
QPushButton#DangerBtn {{
    background: rgba(160,35,35,180);
}}
QPushButton#DangerBtn:hover {{
    background: rgba(200,45,45,200);
}}

/* ── Inputs ── */
QLineEdit, QTextEdit, QDoubleSpinBox, QSpinBox, QComboBox, QDateEdit {{
    background: {bg2};
    border: none;
    border-radius: 6px;
    padding: 5px 10px;
    color: {txt};
}}
QLineEdit:focus, QTextEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QDateEdit:focus {{
    background: {mid};
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox::down-arrow {{ image: none; }}
QComboBox QAbstractItemView {{
    background: {bg0};
    border: none;
    border-radius: 6px;
    selection-background-color: {sel};
    outline: none;
    padding: 4px;
}}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
QSpinBox::up-button, QSpinBox::down-button,
QDateEdit::up-button, QDateEdit::down-button, QDateEdit::drop-down {{
    background: transparent;
    border: none;
    width: 14px;
}}

/* ── Labels ── */
QLabel {{
    color: {txt};
    background: transparent;
}}
QLabel#Heading {{
    font-size: {h1}px;
    font-weight: 700;
}}
QLabel#SubHeading {{
    font-size: {h2}px;
    color: {txd};
    letter-spacing: 0.3px;
}}
QLabel#TotalLabel {{
    font-size: {total_sz}px;
    font-weight: 700;
    color: {accl};
}}

/* ── Glass panel for dialogs — lighter than main window ── */
#GlassPanel {{
    background: {bg_dlg};
    border-radius: 14px;
    border: none;
}}

/* ── Group box ── */
QGroupBox {{
    background: {bg1};
    border: none;
    border-radius: 8px;
    margin-top: 18px;
    padding-top: 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    color: {txd};
    font-size: {h2}px;
    font-weight: 600;
}}

/* ── Action bar (top, replaces sidebar) ── */
#ActionBar {{
    background: {bg1};
    border-bottom: 1px solid {brd};
}}
#ActionSep {{
    color: {brd};
    margin: 0 2px;
}}
#SearchField {{
    background: {bg2};
    border: 1px solid {brd};
    border-radius: 4px;
    padding: 3px 8px;
    color: {txt};
}}
#SearchField:focus {{
    border-color: {acc_solid};
}}

/* ── Toolbar / footer ── */
#Toolbar {{
    background: {bg1};
    border-bottom: 1px solid {brd};
}}
#Footer {{
    background: {bg1};
    border-top: 1px solid {brd};
}}

/* ── Tooltip ── */
QToolTip {{
    background: rgba(255, 248, 190, 215);
    border: none;
    color: #6b4800;
    border-radius: 8px;
    padding: 1px 10px;
    margin: 0px;
    font-size: {h2}px;
}}

/* ── Separator ── */
QFrame[frameShape="4"],
QFrame[frameShape="5"] {{
    color: {brd};
    background: {brd};
    max-height: 1px;
    border: none;
}}

/* ── Menu bar ── */
#AppMenuBar {{
    background: {bg1};
    border-bottom: 1px solid {brd};
    padding: 0 4px;
    spacing: 2px;
}}
#AppMenuBar::item {{
    padding: 4px 10px;
    border-radius: 4px;
    color: {txd};
    font-size: {h2}px;
}}
#AppMenuBar::item:selected {{
    background: {hov};
    color: {txt};
}}
#AppMenuBar::item:pressed {{
    background: {sel};
}}

/* ── Menu ── */
QMenu {{
    background: {_rgba(p["bg0"], 240)};
    border: 1px solid {brd};
    border-radius: 8px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 28px 6px 12px;
    border-radius: 5px;
    color: {txt};
}}
QMenu::item:selected {{
    background: {sel};
}}
QMenu::separator {{
    height: 1px;
    background: {brd};
    margin: 4px 8px;
}}

/* ── Message box ── */
QMessageBox {{
    background: {_rgba(p["bg0"], 240)};
}}

/* ── Table widget (currencies, versions, etc.) ── */
QTableWidget {{
    background: {bg_d};
    border: none;
    outline: none;
    alternate-background-color: {row_a};
    gridline-color: {brd};
    color: {txt};
}}
QTableWidget::item {{
    padding: 4px 6px;
    color: {txt};
}}
QTableWidget::item:selected {{
    background: {sel};
    color: {txt};
}}
QTableWidget QHeaderView::section {{
    background: {mid};
    color: {txd};
    padding: 5px 8px;
    border: none;
    border-right: 1px solid {brd};
    font-weight: 600;
}}
QTableCornerButton::section {{
    background: {mid};
    border: none;
}}

/* ── Sheet tab bar ── */
#SheetTabBar {{
    background: {bg1};
    border-bottom: 1px solid {brd};
}}

#SheetTabInner::tab {{
    background: {bg2};
    color: {txd};
    border: 1px solid {brd};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 5px 14px;
    margin-right: 2px;
    font-size: {font_size}px;
}}

#SheetTabInner::tab:selected {{
    background: {acc};
    color: {txt};
    font-weight: bold;
}}

#SheetTabInner::tab:hover:!selected {{
    background: {mid};
}}

/* ── Welcome / empty state ── */
#WelcomeWidget {{
    background: transparent;
}}
QLabel#WelcomeTitle {{
    font-size: {font_size + 22}px;
    font-weight: 700;
    color: {txt};
    letter-spacing: 0.5px;
}}
QLabel#WelcomeSubtitle {{
    font-size: {font_size + 2}px;
    color: {txd};
}}
QLabel#WelcomeSectionHeader {{
    font-size: {h2}px;
    color: {txd};
    letter-spacing: 0.4px;
    font-weight: 600;
}}
QLabel#WelcomeEmpty {{
    font-size: {font_size}px;
    color: {txd};
    font-style: italic;
}}
QPushButton#WelcomeBtn {{
    background: {bg2};
    border: 1px solid {brd};
    border-radius: 10px;
    padding: 8px 20px;
    color: {txt};
    font-size: {font_size + 1}px;
    font-weight: 600;
}}
QPushButton#WelcomeBtn:hover {{
    background: {hov};
    border-color: {accl};
}}
QPushButton#WelcomeBtn:pressed {{
    background: {acc_solid};
}}
#RecentFilesList {{
    background: {bg2};
    border: 1px solid {brd};
    border-radius: 10px;
    padding: 6px;
    outline: none;
}}
#RecentFilesList::item {{
    padding: 8px 12px;
    border-radius: 6px;
    color: {txt};
}}
#RecentFilesList::item:hover {{
    background: {hov};
}}
#RecentFilesList::item:selected {{
    background: {sel};
}}

/* ── Slider (for settings) ── */
QSlider::groove:horizontal {{
    border: none;
    height: 4px;
    background: {brd};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {accl};
    border: none;
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 8px;
}}
QSlider::handle:horizontal:hover {{
    background: {txt};
}}

/* ── Visor GRIB: panel de controles ── */
QLabel#PanelTitle {{
    font-size: {h2}px;
    font-weight: 700;
    color: {accl};
    letter-spacing: 0.6px;
}}
QLabel#StatusMono {{
    font-family: "Menlo", "Consolas", "DejaVu Sans Mono", monospace;
    font-size: {h2}px;
    color: {accl};
}}
QLabel#StatusWarn {{
    font-family: "Menlo", "Consolas", "DejaVu Sans Mono", monospace;
    font-size: {h2}px;
    color: {txt};
    font-weight: 600;
}}
QPushButton#FLBtn {{
    padding: 4px 6px;
    font-family: "Menlo", "Consolas", "DejaVu Sans Mono", monospace;
}}
QPushButton#FLBtn:checked {{
    background: {acc_solid};
    color: {txt};
    font-weight: 700;
}}
QCheckBox, QRadioButton {{
    color: {txt};
    background: transparent;
    spacing: 6px;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {brd};
    background: {bg2};
}}
QCheckBox::indicator {{
    border-radius: 3px;
}}
QRadioButton::indicator {{
    border-radius: 7px;
}}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {acc_solid};
    border-color: {accl};
}}
QCheckBox::indicator:checked {{
    image: url("{_RESOURCES}/check.svg");
}}
QRadioButton::indicator:checked {{
    image: url("{_RESOURCES}/radio_dot.svg");
}}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border-color: {accl};
}}
QPlainTextEdit {{
    background: {bg_d};
    border: none;
    border-radius: 6px;
    padding: 4px;
    color: {txt};
    font-family: "Menlo", "Consolas", "DejaVu Sans Mono", monospace;
    font-size: {h3}px;
}}
QProgressBar {{
    background: {bg2};
    border: none;
    border-radius: 4px;
    height: 8px;
}}
QProgressBar::chunk {{
    background: {acc_solid};
    border-radius: 4px;
}}
QCalendarWidget QWidget {{
    background: {_rgba(p["bg0"], 240)};
}}
QStatusBar {{
    background: {bg1};
    border-top: 1px solid {brd};
    color: {txt};
    font-family: "Menlo", "Consolas", "DejaVu Sans Mono", monospace;
    font-size: {h2}px;
}}
QStatusBar::item {{ border: none; }}
QScrollArea {{
    background: transparent;
    border: none;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}
"""
    import sys as _sys
    if _sys.platform != 'darwin':
        css += '\n' + opaque_base_css(accent_hex)
    return css
