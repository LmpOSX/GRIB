# -*- coding: utf-8 -*-
"""Consulta de un punto (ficha del clic): formatos, paso por hora, celda,
capas de abajo/arriba e interpolación en el lector, y el diálogo."""
import datetime as dt
import math
import os
import tempfile
import unittest

import numpy as np

from app import point_query as pq
from app import fl_table as flt
from app.grib_reader import GribStep, fl_to_hpa
from tests.test_grib_reader import _reader_sintetico

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OACI = os.path.join(ROOT, "tests", "data", "WAFS_oaci_test.grib2")
UTC = dt.timezone.utc


class TestFormatos(unittest.TestCase):
    def test_geodesico_grados_y_minutos(self):
        self.assertEqual(pq.geodesic_ddmm(-31.42, -64.18), "3125S06411W")
        self.assertEqual(pq.geodesic_ddmm(0.0, 0.0), "0000N00000E")
        self.assertEqual(pq.geodesic_ddmm(-0.0, -1e-12), "0000N00000E")
        self.assertEqual(pq.geodesic_ddmm(-0.009, -0.5), "0001S00030W")
        self.assertEqual(pq.geodesic_ddmm(45.999, 179.999), "4600N18000E")   # 59.9' redondea y acarrea
        self.assertEqual(pq.parse_geodesic("3125S06411W"), (-(31 + 25 / 60), -(64 + 11 / 60)))
        self.assertEqual(pq.parse_geodesic(" 0530n 17030e "), (5.5, 170.5))
        for bad in ("", "3125S6411W", "3165S06411W", "9100N00000E", "31.4S64.2W"):
            self.assertIsNone(pq.parse_geodesic(bad), bad)

    def test_hora_de_sobrevuelo(self):
        self.assertEqual(pq.parse_overflown_time("2510221300"),
                         dt.datetime(2025, 10, 22, 13, 0, tzinfo=UTC))
        self.assertEqual(pq.parse_overflown_time("202510221300"),
                         dt.datetime(2025, 10, 22, 13, 0, tzinfo=UTC))
        self.assertIsNone(pq.parse_overflown_time("25102213"))
        self.assertIsNone(pq.parse_overflown_time("2513221300"))      # mes 13
        self.assertIsNone(pq.parse_overflown_time(""))
        self.assertEqual(pq.format_overflown_time(dt.datetime(2025, 10, 22, 13, 0, tzinfo=UTC)),
                         "2510221300")
        self.assertEqual(pq.format_overflown_time(None), "")

    def test_textos_de_capa(self):
        capa = {"p": 300.9, "label": 300.0, "fl": 300, "spd": 68.4, "dir": 281.6, "t": 228.55}
        self.assertEqual(pq.layer_name(capa), "300 hPa (F300, 300.9 hPa ISA)")
        self.assertEqual(pq.layer_name({"p": 287.4, "label": None, "fl": 310}), "287.4 hPa ISA")
        self.assertEqual(pq.layer_name({"p": 300.0, "label": 300.0, "fl": None}), "300 hPa")
        self.assertEqual(pq.wind_text(capa), "68 kt / 282°")
        self.assertEqual(pq.wind_text(capa, variation=-10.0), "68 kt / 282° (292°M)")
        self.assertEqual(pq.temp_text(capa), "-44.6 °C")
        self.assertEqual(pq.wind_text(None), "—")
        self.assertEqual(pq.temp_text({"t": None}), "—")


class TestLector(unittest.TestCase):
    def test_paso_por_hora(self):
        r = _reader_sintetico([850, 700])
        run = dt.datetime(2026, 10, 13, 12, tzinfo=UTC)
        r.steps = [GribStep("6", run, run + dt.timedelta(hours=6)),
                   GribStep("9", run, run + dt.timedelta(hours=9)),
                   GribStep("12", run, run + dt.timedelta(hours=12))]
        r._compute_windows()
        self.assertEqual(r.step_for_time(run + dt.timedelta(hours=6)), (0, True))
        self.assertEqual(r.step_for_time(run + dt.timedelta(hours=8, minutes=59)), (0, True))
        self.assertEqual(r.step_for_time(run + dt.timedelta(hours=9)), (1, True))
        self.assertEqual(r.step_for_time(run + dt.timedelta(hours=14, minutes=59)), (2, True))
        # Fuera de las ventanas: el de validez más cercana
        self.assertEqual(r.step_for_time(run + dt.timedelta(hours=2)), (0, False))
        self.assertEqual(r.step_for_time(run + dt.timedelta(hours=16)), (2, False))
        self.assertEqual(r.step_for_time(run.replace(tzinfo=None) + dt.timedelta(hours=10)), (1, True))
        self.assertEqual(r.step_for_time(None), (None, False))

    def test_celda_mas_cercana_y_origen(self):
        r = _reader_sintetico([850, 700], shape=(3, 4))      # lats -10,0,10; lons -60,-50,-40,-30
        self.assertEqual(r.grid_index(-2.0, -47.0), (1, 1))               # nodo (0, -50)
        self.assertEqual(r.grid_index(-2.0, -47.0, "origin"), (0, 1))     # esquina SO: lat -10, lon -50
        self.assertEqual(r.grid_index(0.0, -50.0, "origin"), (1, 1))      # sobre el nodo
        self.assertEqual(r.grid_index(9.9, -30.5, "origin"), (1, 2))
        self.assertIsNone(r.grid_index(-20.0, -47.0))                      # fuera (más de media celda)
        self.assertIsNone(r.grid_index(-2.0, -75.0))
        self.assertIsNone(r.grid_index(-11.0, -47.0, "origin"))

    def test_consulta_interpola_entre_capas(self):
        r = _reader_sintetico([850, 700, 500, 300, 200], shape=(5, 6))
        res = r.point_query(0, 310, 0.0, -42.0)
        p = fl_to_hpa(310)
        self.assertEqual(res["mode"], "interp")
        self.assertEqual((res["lower"]["label"], res["upper"]["label"]), (300.0, 200.0))
        w = (math.log(p) - math.log(300)) / (math.log(200) - math.log(300))
        self.assertAlmostEqual(res["w"], w)
        esperado = (1 - w) * 300 + w * 200
        self.assertAlmostEqual(res["value"]["u"], esperado)
        self.assertAlmostEqual(res["value"]["v"], -esperado)
        self.assertAlmostEqual(res["value"]["t"], 200 + esperado / 10)
        self.assertAlmostEqual(res["value"]["spd"], math.hypot(esperado, esperado) * 1.943844, places=3)
        self.assertAlmostEqual(res["value"]["dir"], 315.0)                 # u>0, v<0: del noroeste
        self.assertEqual(res["lower"]["u"], 300.0)
        self.assertEqual(res["upper"]["u"], 200.0)
        self.assertEqual((res["lat"], res["lon"]), (0.0, -42.0))
        self.assertIsNone(res["lower"]["fl"])                              # archivo crudo: sin FL
        # Nivel exacto: F300 cae (±0.05 hPa) en ninguno de los niveles crudos; 500 hPa = F180 no
        res = r.point_query(0, 180, 0.0, -42.0)
        self.assertEqual(res["mode"], "interp")
        # Fuera de rango: no se extrapola, se toma la capa más cercana
        res = r.point_query(0, 20, 0.0, -42.0)
        self.assertTrue(res["extrapolated"])
        self.assertIsNone(res["lower"])
        self.assertEqual(res["upper"]["label"], 850.0)
        self.assertEqual(res["value"]["u"], 850.0)
        res = r.point_query(0, 600, 0.0, -42.0)
        self.assertTrue(res["extrapolated"])
        self.assertIsNone(res["upper"])
        self.assertEqual(res["lower"]["label"], 200.0)
        self.assertIsNone(r.point_query(0, 300, 80.0, -42.0))             # fuera de la grilla

    def test_consulta_en_archivo_oaci(self):
        """Archivo etiquetado: la presión real de cada capa es la ISA del
        FL (no la etiqueta); F300 es nivel exacto; F310 interpola entre
        F300 y F320 con las ISA 300.9 y 274.5."""
        from app.grib_reader import GribReader
        r = GribReader(OACI)
        self.assertEqual(r.true_pressure(300.0), flt.isa_pa(300) / 100.0)
        self.assertEqual(r.fl_of_level(450.0), 210)
        self.assertEqual(r.profile(0, "u")[0], (flt.isa_pa(50) / 100.0, 850.0))
        res = r.point_query(0, 300, -31.42, -64.18)
        self.assertEqual(res["mode"], "exact")
        self.assertEqual(res["value"]["label"], 300.0)
        self.assertEqual((res["lower"]["fl"], res["upper"]["fl"]), (270, 320))
        self.assertEqual((res["lat"], res["lon"]), (-31.0, -64.0))
        res = r.point_query(0, 310, -31.42, -64.18, cell="origin")
        self.assertEqual((res["lat"], res["lon"]), (-32.0, -65.0))
        self.assertEqual((res["lower"]["p"], res["upper"]["p"]),
                         (flt.isa_pa(300) / 100.0, flt.isa_pa(320) / 100.0))
        lo, hi, p = res["lower"], res["upper"], fl_to_hpa(310)
        w = (math.log(p) - math.log(lo["p"])) / (math.log(hi["p"]) - math.log(lo["p"]))
        self.assertAlmostEqual(res["value"]["t"], (1 - w) * lo["t"] + w * hi["t"])
        self.assertTrue(lo["spd"] > 0 and hi["spd"] > 0)
        # El mapa interpola igual (misma presión real) que la consulta
        u, v, t, info = r.interp_to_pressure(0, p)
        self.assertEqual(info["bracket"], (lo["p"], hi["p"]))
        self.assertEqual(info["bracket_labels"], (300.0, 275.0))
        self.assertAlmostEqual(float(t[res["j"], res["i"]]), res["value"]["t"])
        # Hora: tres plazos 6/9/12 h, ventanas de 3 h
        run = r.run_time()
        self.assertEqual(r.step_for_time(run + dt.timedelta(hours=10)), (1, True))
        self.assertEqual(r.step_for_time(run + dt.timedelta(hours=20)), (2, False))

    def test_columna_de_la_celda(self):
        r = _reader_sintetico([850, 700, 500, 300, 200], shape=(3, 4))
        col = r.column_query(0, 0.0, -40.0, "nearest")
        self.assertEqual([l["label"] for l in col], [850, 700, 500, 300, 200])
        self.assertEqual(col[0]["p"], 850.0)
        self.assertAlmostEqual(col[-1]["spd"], math.hypot(200, 200) * 1.943844, places=1)
        self.assertIsNone(r.column_query(0, 50.0, -40.0, "nearest"))

    def test_informe(self):
        r = _reader_sintetico([850, 700, 500, 300, 200], shape=(5, 6))
        res = r.point_query(0, 310, 0.0, -42.0)
        txt = pq.report_text(0.0, -42.0, "2610131800", 310, r.steps[0], 0, True, res,
                             variation=-10.0, cell="nearest")
        lines = txt.splitlines()
        self.assertEqual(lines[0], "Geodésico (grados y minutos): 0000N04200W")
        self.assertEqual(lines[1], "Hora de sobrevuelo (YYMMDDHHMM): 2610131800")
        self.assertEqual(lines[2], "Nivel de sobrevuelo (banda, sin F): 310")
        self.assertTrue(lines[3].startswith("Step: [0] +6 h  validez 18:00 13/10 UTC  (ventana 18:00–21:00)"))
        self.assertIn("Origen de celda: 0000N04200W", lines[4])
        self.assertIn("Capa superior 200 hPa", txt)
        self.assertIn("Nivel F310 287.4 hPa ISA · interpolado en ln(p) entre 300 hPa y 200 hPa", txt)
        self.assertIn("Capa inferior 300 hPa", txt)
        self.assertIn("°M)", txt)
        self.assertEqual(txt.count("Temperatura (°C):"), 3)
        self.assertIn("fuera de la grilla", pq.report_text(80.0, 0.0, "x", 300, None, None, False, None))


class TestPerfil(unittest.TestCase):
    """WindProfileWidget: filas, FL intercalado o coincidente, perfil denso."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _layers(levels, spd=20.0):
        return [dict(p=float(p), label=float(p), fl=None, spd=spd, dir=270.0, t=250.0) for p in levels]

    def test_barbas_y_nombres(self):
        from app.widgets.wind_profile_widget import barb_counts, level_name
        self.assertEqual(barb_counts(0), (0, 0, 0))
        self.assertEqual(barb_counts(3), (0, 0, 1))
        self.assertEqual(barb_counts(15), (0, 1, 1))
        self.assertEqual(barb_counts(52), (1, 0, 0))
        self.assertEqual(barb_counts(78), (1, 3, 0))
        self.assertEqual(barb_counts(120), (2, 2, 0))
        self.assertEqual(level_name(dict(p=300.9, label=300.0, fl=300)), "F300")
        self.assertEqual(level_name(dict(p=300.0, label=300.0, fl=None)), "300 hPa")
        self.assertEqual(level_name(dict(p=287.4, label=None, fl=310)), "F310")

    def test_filas_fl_intercalado_o_coincidente(self):
        from app.widgets.wind_profile_widget import WindProfileWidget
        w = WindProfileWidget()
        self.assertEqual(w.sizeHint().height(), 0)                    # sin filas no ocupa lugar
        w.set_layers(self._layers([850, 500, 300]), value=dict(p=287.4, label=None, fl=310, spd=33.3,
                                                                dir=359.6, t=230.0), variation=-8.0)
        rows = w.rows()
        self.assertEqual([r[0] for r in rows], ["F310", "300 hPa", "500 hPa", "850 hPa"])
        self.assertEqual(rows[0], ("F310", 33, 0, -43.1, True))
        self.assertEqual(rows[1], ("300 hPa", 20, 270, -23.1, False))
        self.assertIn("°M", w._row_text(dict(rows=None, spd=33.3, dir=359.6, t=230.0)))
        # FL que coincide con un nivel: se resalta ese y toma el nombre del FL
        w.set_layers(self._layers([850, 500, 300]), value=dict(p=300.0, label=None, fl=300, spd=20.0,
                                                                dir=270.0, t=250.0))
        self.assertEqual([(r[0], r[4]) for r in w.rows()],
                         [("F300", True), ("500 hPa", False), ("850 hPa", False)])
        # Sin dato de viento no falla
        w.set_layers([dict(p=500.0, label=500.0, fl=None, spd=None, dir=None, t=None)])
        self.assertEqual(w.rows(), [("500 hPa", None, None, None, False)])
        w.resize(w.sizeHint())
        w.grab()                                                       # se dibuja sin error

    def test_perfil_denso_entra_en_la_altura(self):
        from app.widgets.wind_profile_widget import WindProfileWidget, ROW_MIN, ROW_MAX
        w = WindProfileWidget()
        w.set_layers(self._layers(range(1000, 95, -25)))              # 37 niveles
        w.set_max_height(2000)
        h_full = w.sizeHint().height()
        self.assertGreaterEqual(w._row_h(), ROW_MAX)
        w.set_max_height(300)
        self.assertLessEqual(w.sizeHint().height(), 37 * ROW_MIN + w._header_h() + 2)
        self.assertLess(w.sizeHint().height(), h_full)
        w.resize(w.sizeHint())
        w.grab()
        w.set_max_height(2000)                                        # vuelve a las filas altas
        self.assertGreaterEqual(w._row_h(), ROW_MAX)


class TestDialogo(unittest.TestCase):
    def setUp(self):
        from PyQt6.QtWidgets import QApplication
        from app import config
        from app.dialogs import glass_dialog
        glass_dialog._apply_dialog_blur = lambda w: None
        self.app = QApplication.instance() or QApplication([])
        self._tmp = tempfile.TemporaryDirectory()
        self._old_cfg_path = config.CONFIG_PATH
        config.CONFIG_PATH = os.path.join(self._tmp.name, "config.json")
        from app.main_window import MainWindow
        self.w = MainWindow()
        self.w.show()
        self.app.processEvents()

    def tearDown(self):
        from app import config
        self.w.close()
        self.w.deleteLater()
        self.app.processEvents()
        config.CONFIG_PATH = self._old_cfg_path
        self._tmp.cleanup()

    def _click(self, lon, lat):
        """Clic (sin arrastrar) sobre el mapa en lon/lat: press + release."""
        from matplotlib.backend_bases import MouseEvent
        x, y = self.w.plot.ax.transData.transform((lon, lat))
        self.w.plot._on_press(MouseEvent("button_press_event", self.w.plot.canvas, x, y, button=1))
        self.w.plot._on_release(MouseEvent("button_release_event", self.w.plot.canvas, x, y, button=1))
        self.app.processEvents()

    def test_ficha_tras_punto_sin_datos_entra_en_el_mapa(self):
        """Después de una ficha sin datos (perfil oculto), la de un punto con
        datos debe quedar igual que si fuera la primera: el perfil con filas
        de la misma altura y la ficha entera dentro del mapa."""
        from app.widgets import wind_profile_widget as wpw
        w = self.w
        # Muchos niveles y una ventana baja: el perfil tiene que comprimir sus
        # filas para entrar (si no, el defecto no se nota)
        r = _reader_sintetico(list(range(1000, 95, -25)), shape=(5, 6))
        r.path = os.path.join(self._tmp.name, "sintetico.grib2")
        w.resize(1000, 560)
        w.load_reader(r, r.path)
        self.app.processEvents()
        canvas = w.plot.canvas
        # Referencia: ficha limpia de un punto con datos
        pop = w._show_point_popup(0.0, -42.0)
        self.app.processEvents()
        ref_h, ref_row = pop.height(), pop.query.profile._row_h()
        self.assertLessEqual(ref_h, canvas.height())
        self.assertLess(ref_row, wpw.ROW_MAX)                     # filas comprimidas
        self.assertTrue(pop.query.profile.isVisible())
        # Punto fuera de la grilla: sin perfil, ficha chica
        w._show_point_popup(60.0, 100.0)
        self.app.processEvents()
        self.assertFalse(pop.query.profile.isVisible())
        self.assertIn("fuera de la grilla", pop.query.lbl_cell.text())
        self.assertLess(pop.height(), ref_h)
        # El clic en el mapa la cierra (y no abre otra); con la ficha oculta
        # Qt no refresca el tamaño de lo que cambia adentro, que es lo que
        # dejaba el perfil estirado en el clic siguiente
        pop.hide()
        self.app.processEvents()
        # Y de nuevo un punto con datos: igual que la referencia
        w._show_point_popup(0.0, -42.0)
        self.app.processEvents()
        self.assertTrue(pop.query.profile.isVisible())
        self.assertLessEqual(pop.height(), canvas.height())
        # Un píxel de tolerancia: con otras fuentes (Linux) el resto de la ficha
        # cambia de alto y la fila redondea distinto; el defecto real daba
        # 1160 px de ficha en un mapa de 684
        self.assertLessEqual(abs(pop.query.profile._row_h() - ref_row), 1)
        self.assertLessEqual(abs(pop.height() - ref_h), ref_row + 2 + len(pop.query.profile.rows()))

    def test_ficha_se_reajusta_si_el_mapa_cambia_de_alto(self):
        """El mapa puede terminar de acomodarse después del clic (con fuente
        15 baja 18 px justo después de mostrar la ficha; en Linux, 1 px), o
        la ventana achicarse con la ficha abierta: la ficha se vuelve a
        ajustar al alto nuevo y sigue entera dentro del mapa."""
        import json
        from app import config
        from app.main_window import MainWindow
        self.w.close()
        self.w.deleteLater()
        self.app.processEvents()
        with open(config.CONFIG_PATH, "w") as fh:
            json.dump({"font_size": 15}, fh)
        self.w = MainWindow()
        self.w.show()
        self.app.processEvents()
        w = self.w
        r = _reader_sintetico(list(range(1000, 95, -25)), shape=(5, 6))
        r.path = os.path.join(self._tmp.name, "sintetico.grib2")
        w.resize(1000, 560)
        w.load_reader(r, r.path)
        self.app.processEvents()
        pop = w._show_point_popup(0.0, -42.0)
        self.app.processEvents()
        canvas = w.plot.canvas
        self.assertTrue(pop.isVisible())
        self.assertTrue(pop.query.profile.isVisible())
        self.assertLessEqual(pop.height(), canvas.height())
        self.assertLessEqual(pop.y() + pop.height(), canvas.height())

    def test_clic_abre_la_ficha_editable(self):
        w = self.w
        r = _reader_sintetico([850, 700, 500, 300, 200], shape=(5, 6))
        r.path = os.path.join(self._tmp.name, "sintetico.grib2")
        w.load_reader(r, r.path)
        self.app.processEvents()
        self.assertIsNone(w._info_popup)
        self._click(-42.0, 0.0)
        pop = w._info_popup
        self.assertIsNotNone(pop)
        self.assertTrue(pop.isVisible())
        self.assertIs(pop.parentWidget(), w.plot.canvas)        # hija del mapa, no una ventana
        q = pop.query
        self.assertTrue(q.isVisible())
        self.assertEqual(q.ed_geo.text(), "0000N04200W")
        self.assertIn("0000N04200W", q.lbl_cell.text())          # sobre el nodo: la celda es él
        self.assertEqual(q.ed_time.text(), "2610131800")         # validez del paso del panel
        self.assertEqual(q.fl(), 300)                            # FL del panel
        rows = q.rows()
        self.assertEqual(rows[1][0], "Nivel F300")
        self.assertEqual(rows[0][1], "300 hPa")       # F300 = 300.9 hPa: entre 500 y 300
        self.assertEqual(rows[2][1], "500 hPa")
        self.assertIn("interpolado en ln(p)", q.lbl_mode.text())
        # El perfil de la celda: los cinco niveles con F300 intercalado y resaltado
        self.assertTrue(q.profile.isVisible())
        prof = q.profile.rows()
        self.assertEqual([r[0] for r in prof], ["200 hPa", "300 hPa", "F300", "500 hPa", "700 hPa", "850 hPa"])
        self.assertTrue(prof[2][4])
        self.assertEqual(prof[1][1], round(math.hypot(300, 300) * 1.943844))
        self.assertNotIn("ARCHIVO", pop.text())
        # Los campos son editables ahí mismo: cualquier FL y cualquier hora
        self.assertFalse(q.ed_time.isReadOnly())
        q.sp_fl.setValue(310)
        q.ed_time.setText("2610132200")
        self.app.processEvents()
        self.assertIn("paso [0] +6 h", q.lbl_step.text())
        self.assertIn("fuera de las ventanas", q.lbl_step.text())
        rows = q.rows()
        self.assertEqual(rows[1][1], "287.4 hPa ISA")
        self.assertEqual(rows[0][1], "200 hPa")
        self.assertEqual(rows[2][1], "300 hPa")
        self.assertNotEqual(rows[1][2], "—")
        self.assertRegex(rows[1][3], r"^-?\d+\.\d °C$")
        q.ed_time.setText("261013")
        self.app.processEvents()
        self.assertIn("hora inválida", q.lbl_step.text())
        self.assertEqual(q.rows()[1][2], "—")
        self.assertFalse(q.profile.isVisible())                  # sin dato no hay perfil
        q.ed_time.setText("2610131900")
        self.app.processEvents()
        # Origen de celda (convención del FDP): esquina suroeste de la celda
        # que contiene el punto, no el nodo más cercano
        q.set_point(2.0, -43.0)
        self.assertEqual(q.ed_geo.text(), "0200N04300W")
        self.assertIn("0000N04800W", q.lbl_cell.text())              # esquina SO (lons cada 6°)
        self.assertEqual(q.cell(), "origin")
        # Se puede escribir el punto a mano
        q.ed_geo.setText("0500N05200W")
        self.assertIn("0500N05400W", q.lbl_cell.text())              # origen: -54 ≤ -52 < -48
        # Copiar
        pop.btn_copy.click()
        from PyQt6.QtGui import QGuiApplication
        txt = QGuiApplication.clipboard().text()
        self.assertTrue(txt.startswith("Geodésico (grados y minutos): 0500N05200W\n"
                                       "Hora de sobrevuelo (YYMMDDHHMM): 2610131900\n"
                                       "Nivel de sobrevuelo (banda, sin F): 310\n"))
        self.assertIn("Perfil de la celda (de arriba hacia abajo):\n  200 hPa  ", txt)
        self.assertTrue(txt.rstrip().endswith("°C"))
        # Escape la cierra (el único Escape de la ventana)
        w._on_escape()
        self.assertFalse(pop.isVisible())
        # Otro clic la abre en el punto nuevo, con el paso y el FL del panel
        self._click(-36.0, -5.0)
        self.assertTrue(pop.isVisible())
        self.assertEqual(q.ed_geo.text(), "0500S03600W")
        self.assertEqual((q.fl(), q.ed_time.text()), (300, "2610131800"))
        # En modo presión la consulta es la misma, con el FL de ese nivel
        w.panel.level_mode, w.panel.sel_p = "p", 500.0
        w._on_escape()
        self._click(-36.0, -5.0)
        self.assertTrue(q.isVisible())
        self.assertEqual(q.fl(), 180)                            # F180 = 500 hPa ISA
        self.assertIn("F180", [r[0] for r in q.profile.rows()])

    def test_clic_afuera_solo_cierra_y_cmd_i_reabre(self):
        from PyQt6.QtCore import QEvent, QPointF, Qt
        from PyQt6.QtGui import QMouseEvent
        w = self.w
        r = _reader_sintetico([850, 700, 500, 300, 200], shape=(5, 6))
        r.path = os.path.join(self._tmp.name, "sintetico.grib2")
        w.load_reader(r, r.path)
        self.app.processEvents()
        self._click(-42.0, 0.0)
        pop = w._info_popup
        self.assertTrue(pop.isVisible())
        # Un clic sobre la ficha no llega al mapa (no abre otra ni arrastra)
        self.assertIsNone(pop.mousePressEvent(QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(5, 5), Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)))
        self.assertTrue(pop.isVisible())
        # El mismo clic llega antes dirigido a la ventana nativa (QWindow): no
        # cuenta como «afuera» (si no, un clic en un campo cerraba la ficha)
        from PyQt6.QtCore import QObject
        self.assertFalse(pop.eventFilter(QObject(), QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(5, 5), Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)))
        self.assertTrue(pop.isVisible())
        # Un clic dirigido a un campo de la ficha tampoco la cierra
        pop.eventFilter(pop.query.ed_geo, QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(5, 5), Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
        self.assertTrue(pop.isVisible())
        # Con la ficha abierta, el mapa no reconoce el botón izquierdo: ni
        # arrastra ni abre otra ficha
        from matplotlib.backend_bases import MouseEvent
        x, y = w.plot.ax.transData.transform((-36.0, -5.0))
        w.plot._on_press(MouseEvent("button_press_event", w.plot.canvas, x, y, button=1))
        self.assertFalse(w.plot._panning)
        w.plot._on_release(MouseEvent("button_release_event", w.plot.canvas, x, y, button=1))
        self.assertTrue(pop.isVisible())
        self.assertEqual(pop.query.ed_geo.text(), "0000N04200W")
        # Un clic sobre el mapa, fuera de la ficha: el filtro la cierra en el
        # press y el clic que se informa después no abre otra
        canvas = w.plot.canvas
        press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(2, 2), Qt.MouseButton.LeftButton,
                            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        pop.eventFilter(canvas, press)
        self.assertFalse(pop.isVisible())
        self._click(-36.0, -5.0)
        self.assertFalse(pop.isVisible())
        self.assertEqual(pop.query.ed_geo.text(), "0000N04200W")   # no cambió el punto
        # El clic siguiente sí abre
        self._click(-36.0, -5.0)
        self.assertTrue(pop.isVisible())
        self.assertEqual(pop.query.ed_geo.text(), "0500S03600W")
        # Cerrar el archivo la oculta y la deja sin datos; ⌘I la reabre en el
        # último punto, y abrir otro archivo la rellena
        w._file_close()
        self.assertFalse(pop.isVisible())
        self.assertEqual(pop.query.lbl_step.text(), "Sin archivo abierto")
        self.assertEqual(w._act_point.shortcut().toString(), "Ctrl+I")
        w.load_reader(r, r.path)
        w._act_point.trigger()
        self.assertTrue(pop.isVisible())
        self.assertEqual(pop.query.ed_geo.text(), "0500S03600W")
        self.assertNotEqual(pop.query.rows()[1][2], "—")


if __name__ == "__main__":
    unittest.main()
