# -*- coding: utf-8 -*-
"""Perfil vertical del viento en la celda de la consulta, para la ficha del
clic: una fila por nivel del archivo, de arriba hacia abajo, con

* la etiqueta del nivel (F300 en un archivo etiquetado por FL, 300 hPa en
  uno crudo),
* una barra pintada con el color de la escala de velocidad del mapa
  (grib_reader.speed_color, continua; la excepción conocida al tema) cuyo
  largo es la velocidad,
* la barba sobre una brújula con el norte arriba (barbas del lado del
  hemisferio, como en el mapa) y
* los números: kt, dirección (° y °M si hay variación) y temperatura, y
* si se da, lo que mostraría el FDP de INDRA para ese FL (columna «FDP»).

El FL pedido se intercala (interpolado) y se resalta con el acento; si
coincide con un nivel del archivo se resalta ese. Con muchos niveles las
filas se achican (hasta 8 px) y los textos se escriben cada tantas filas,
siempre el del FL pedido; la barra de colores queda continua, como un
perfil. La altura máxima la fija la ficha (set_max_height).

Colores y letra salen del tema vía QSS (QWidget#WindProfile): el texto
(color), el acento (selection-background-color) y la pista de las barras
(alternate-background-color).
"""
import math

from PyQt6.QtCore import Qt, QSize, QRectF, QPointF
from PyQt6.QtGui import QPainter, QPen, QColor, QPolygonF, QPalette, QFont
from PyQt6.QtWidgets import QWidget

from ..grib_reader import speed_color, KELVIN, SPEED_STOPS

ROW_MAX = 28        # alto máximo de una fila (px)
ROW_MIN = 8         # alto mínimo (perfil denso)
ROW_FLOOR = 5       # si ni con ROW_MIN entra en el mapa, hasta acá antes que salirse
BAR_W = 64          # largo de la barra al tope de la escala
BAR_MAX_KT = float(SPEED_STOPS[-1])   # velocidad que llena la barra (tope de la escala)
GAP = 10


def level_name(layer):
    """`F300` (etiquetado por FL o FL pedido) o `300 hPa` (archivo crudo)."""
    fl = layer.get("fl")
    if fl is not None:
        return f"F{int(fl):03d}"
    if layer.get("label") is not None:
        return f"{layer['label']:g} hPa"
    return f"{layer['p']:.0f} hPa"


def barb_counts(spd_kt):
    """(banderas de 50, barbas de 10, medias de 5) de una velocidad, con
    el redondeo a 5 kt de las barbas; (0, 0, 0) en calma (< 2.5 kt)."""
    s = int(round(float(spd_kt) / 5.0)) * 5
    return s // 50, (s % 50) // 10, (s % 10) // 5


class WindProfileWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WindProfile")
        self._rows = []            # [{"name", "spd", "dir", "t", "hl"}]
        self._variation = 0.0
        self._southern = False
        self._max_h = 440
        self._fdp = None           # {FL: texto} de la columna «FDP», o None

    # ── Datos ────────────────────────────────────────────────────────────────

    def set_layers(self, layers, value=None, variation=0.0, southern=False, fdp=None):
        """`layers`: la columna del archivo de abajo hacia arriba (lo que da
        GribReader.column_query); `value`: la capa del FL pedido (point_query
        ['value']) que se intercala por presión, o None; `fdp`: {FL: texto}
        de lo que mostraría el FDP, por el FL de cada capa que el FDP lee y
        el FL pedido, o None (sin columna)."""
        from ..point_query import fdp_layer_fl
        rows = [dict(name=level_name(l), spd=l.get("spd"), dir=l.get("dir"), t=l.get("t"),
                     p=float(l["p"]), hl=False, fdp_fl=fdp_layer_fl(l)) for l in (layers or [])]
        if value is not None and value.get("p") is not None:
            p = float(value["p"])
            same = [r for r in rows if abs(r["p"] - p) < 0.05]
            if same:
                same[0]["hl"] = True
                same[0]["name"] = level_name(value) if value.get("fl") is not None else same[0]["name"]
            else:
                rows.append(dict(name=level_name(value), spd=value.get("spd"), dir=value.get("dir"),
                                 t=value.get("t"), p=p, hl=True, fdp_fl=value.get("fl")))
        rows.sort(key=lambda r: r["p"])          # menos presión primero: arriba
        self._fdp = dict(fdp) if fdp else None
        self._rows = rows
        self._variation = float(variation or 0.0)
        self._southern = bool(southern)
        self.updateGeometry()
        self.update()

    def set_max_height(self, h):
        self._max_h = max(int(h), ROW_MIN * 4)
        self.updateGeometry()
        self.update()

    def rows(self):
        """[(nombre, kt, dirección, temperatura °C, resaltada)] de arriba
        hacia abajo (tests)."""
        out = []
        for r in self._rows:
            t = None if r["t"] is None else round(r["t"] - KELVIN, 1)
            out.append((r["name"], None if r["spd"] is None else round(r["spd"]),
                        None if r["dir"] is None else round(r["dir"]) % 360, t, r["hl"]))
        return out

    # ── Geometría ────────────────────────────────────────────────────────────

    def _fm(self):
        return self.fontMetrics()

    def _row_h(self):
        n = max(1, len(self._rows))
        row_max = max(ROW_MAX, self._fm().height() + 6)     # con letra grande, filas más altas
        avail = self._max_h - self._header_h()
        h = avail / n
        if h >= ROW_MIN:
            return int(min(row_max, h))
        # Perfil muy denso en un mapa muy bajo (un GFS crudo con 37 capas en
        # una ventana chica, fuentes altas de Linux): la ficha tiene que
        # entrar entera, así que las filas bajan de ROW_MIN hasta ROW_FLOOR
        return int(max(ROW_FLOOR, h))

    def _header_h(self):
        return self._fm().height() + 4

    def _cols(self):
        """x de cada columna: etiqueta, barra, brújula, texto; y el ancho total."""
        fm = self._fm()
        name_w = max([fm.horizontalAdvance(r["name"]) for r in self._rows] + [fm.horizontalAdvance("8888 hPa")])
        comp = max(ROW_MIN, min(ROW_MAX, self._row_h())) + 4
        x_name = 2
        x_bar = x_name + name_w + GAP
        x_comp = x_bar + BAR_W + GAP
        x_txt = x_comp + comp + GAP
        txt_w = fm.horizontalAdvance(self._text_sample())
        return x_name, x_bar, x_comp, x_txt, x_txt + txt_w + 2

    def _text_sample(self):
        s = "8888 kt  888°"
        if abs(self._variation) >= 0.05:
            s += "  888°M"
        s += "  -88.8 °C"
        if self._fdp:
            s += "   888 kt 888° -88 °C"
        return s

    def sizeHint(self):
        if not self._rows:
            return QSize(0, 0)
        w = self._cols()[4]
        h = self._header_h() + self._row_h() * len(self._rows) + 2
        return QSize(w, h)

    def minimumSizeHint(self):
        return self.sizeHint()

    # ── Textos ───────────────────────────────────────────────────────────────

    def _row_text(self, r):
        if r["spd"] is None:
            txt = "  —"
        else:
            txt = f"{r['spd']:3.0f} kt  {r['dir'] % 360.0:03.0f}°"
            if abs(self._variation) >= 0.05:
                txt += f"  {(r['dir'] - self._variation) % 360.0:03.0f}°M"
        if r["t"] is not None:
            txt += f"  {r['t'] - KELVIN:5.1f} °C"
        return txt

    def _fdp_text(self, r):
        if not self._fdp or r.get("fdp_fl") is None:
            return ""
        return self._fdp.get(int(r["fdp_fl"]), "")

    # ── Dibujo ───────────────────────────────────────────────────────────────

    def paintEvent(self, _event):
        if not self._rows:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pal = self.palette()
        c_txt = pal.color(QPalette.ColorRole.WindowText)
        c_acc = pal.color(QPalette.ColorRole.Highlight)
        c_track = pal.color(QPalette.ColorRole.AlternateBase)
        c_dim = QColor(c_txt)
        c_dim.setAlpha(140)
        fm = self._fm()
        fh = fm.height()
        row_h = self._row_h()
        x_name, x_bar, x_comp, x_txt, total_w = self._cols()
        total_w = max(total_w, self.width())
        comp = x_txt - GAP - x_comp
        # Cabecera
        y = 0
        p.setPen(c_dim)
        hdr = ["nivel", "kt", "", "kt / °" + ("/ °M" if abs(self._variation) >= 0.05 else "") + "  °C"]
        for x, t in zip((x_name, x_bar, x_comp, x_txt), hdr):
            p.drawText(QRectF(x, y, total_w - x, self._header_h()),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, t)
        x_fdp = x_txt + fm.horizontalAdvance(self._text_sample().split("   888 kt")[0]) + GAP
        if self._fdp:
            p.drawText(QRectF(x_fdp, y, total_w - x_fdp, self._header_h()),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "FDP")
        y = self._header_h()
        dense = row_h < fh
        k = max(1, int(math.ceil(fh / float(row_h)))) if dense else 1
        hl_idx = next((i for i, r in enumerate(self._rows) if r["hl"]), None)
        bold = QFont(self.font())
        bold.setBold(True)
        for i, r in enumerate(self._rows):
            top = y + i * row_h
            cy = top + row_h / 2.0
            if r["hl"]:
                fill = QColor(c_acc)
                fill.setAlpha(70)
                p.setPen(QPen(c_acc, 1))
                p.setBrush(fill)
                p.drawRoundedRect(QRectF(0.5, top + 0.5, total_w - 1, row_h - 1), 3, 3)
            # Barra: pista y largo según la velocidad, con el color de la escala
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c_track)
            bh = max(2.0, row_h - (4 if row_h >= 12 else 1))
            p.drawRect(QRectF(x_bar, cy - bh / 2.0, BAR_W, bh))
            if r["spd"] is not None:
                p.setBrush(QColor(speed_color(r["spd"])))
                w = max(2.0, BAR_W * min(r["spd"], BAR_MAX_KT) / BAR_MAX_KT)
                p.drawRect(QRectF(x_bar, cy - bh / 2.0, w, bh))
            # Brújula y barba
            size = max(ROW_MIN, min(comp, row_h))
            self._draw_barb(p, QPointF(x_comp + comp / 2.0, cy), size, r["spd"], r["dir"],
                            c_txt, c_dim)
            # Textos: todos si entran; en perfil denso cada k filas, y siempre
            # la del FL pedido (sin pisarse con las vecinas)
            show = (not dense) or r["hl"] or (i % k == 0 and (hl_idx is None or abs(i - hl_idx) >= k))
            if not show:
                continue
            p.setFont(bold if r["hl"] else self.font())
            p.setPen(c_txt if (r["hl"] or not dense) else c_dim)
            ty = cy - fh / 2.0
            if dense:
                ty = min(max(0.0, ty), y + len(self._rows) * row_h - fh)
            p.drawText(QRectF(x_name, ty, x_bar - x_name, fh),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, r["name"])
            p.drawText(QRectF(x_txt, ty, total_w - x_txt, fh),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._row_text(r))
            fdp = self._fdp_text(r)
            if fdp:
                p.drawText(QRectF(x_fdp, ty, total_w - x_fdp, fh),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, fdp)
        p.end()

    def _draw_barb(self, p, c, size, spd, direc, c_txt, c_dim):
        """Brújula (norte arriba) con la barba del viento: el asta sale del
        centro hacia donde viene el viento; banderas de 50, barbas de 10 y
        medias de 5 del lado del hemisferio (como en el mapa)."""
        rad = size / 2.0
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(c_dim, 1))
        p.drawEllipse(c, rad, rad)
        if size >= 14:
            for a in (0, 90, 180, 270):          # marcas N E S O
                ux, uy = math.sin(math.radians(a)), -math.cos(math.radians(a))
                p.drawLine(QPointF(c.x() + ux * rad, c.y() + uy * rad),
                           QPointF(c.x() + ux * (rad - 2.5), c.y() + uy * (rad - 2.5)))
        if spd is None or direc is None:
            return
        pen = QPen(c_txt, 1.4 if size >= 14 else 1.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        if spd < 2.5:
            p.drawEllipse(c, rad * 0.3, rad * 0.3)
            return
        d = math.radians(direc)
        ux, uy = math.sin(d), -math.cos(d)                   # hacia donde viene
        px, py = math.cos(d), math.sin(d)                    # lado de las barbas (hemisferio norte)
        if self._southern:
            px, py = -px, -py
        L = rad * 0.95
        tip = QPointF(c.x() + ux * L, c.y() + uy * L)
        p.drawLine(c, tip)
        n50, n10, n5 = barb_counts(spd)
        step = L / max(4.0, n50 + n10 + n5 + 1.0)            # repartidas a lo largo del asta
        blen = rad * 0.7
        pos = L                                               # desde la punta hacia el centro
        p.setBrush(c_txt)
        for _ in range(n50):
            a = QPointF(c.x() + ux * pos, c.y() + uy * pos)
            b = QPointF(c.x() + ux * (pos - step), c.y() + uy * (pos - step))
            m = QPointF(c.x() + ux * (pos - step / 2.0) + px * blen, c.y() + uy * (pos - step / 2.0) + py * blen)
            p.drawPolygon(QPolygonF([a, m, b]))
            pos -= step
        for _ in range(n10):
            a = QPointF(c.x() + ux * pos, c.y() + uy * pos)
            p.drawLine(a, QPointF(a.x() + px * blen, a.y() + py * blen))
            pos -= step
        if n5:
            if n50 == 0 and n10 == 0:
                pos -= step                                   # la media sola va un paso más adentro
            a = QPointF(c.x() + ux * pos, c.y() + uy * pos)
            p.drawLine(a, QPointF(a.x() + px * blen / 2.0, a.y() + py * blen / 2.0))
