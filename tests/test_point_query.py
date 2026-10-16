# -*- coding: utf-8 -*-
"""Consulta de un punto (clic derecho): formatos, paso por hora, celda,
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

    def test_clic_derecho_abre_la_consulta(self):
        from app.dialogs.glass_dialog import GlassDialog
        w = self.w
        r = _reader_sintetico([850, 700, 500, 300, 200], shape=(5, 6))
        r.path = os.path.join(self._tmp.name, "sintetico.grib2")
        w.load_reader(r, r.path)
        self.app.processEvents()
        self.assertIsNone(w._point_dialog)
        # Clic derecho sobre el mapa (matplotlib: botón 3) con el lat/lon del evento
        x, y = w.plot.ax.transData.transform((-42.0, 0.0))
        from matplotlib.backend_bases import MouseEvent
        ev = MouseEvent("button_press_event", w.plot.canvas, x, y, button=3)
        w.plot._on_press(ev)
        self.app.processEvents()
        dlg = w._point_dialog
        self.assertIsNotNone(dlg)
        self.assertIsInstance(dlg, GlassDialog)
        self.assertTrue(dlg.isVisible())
        self.assertFalse(dlg.isModal())
        self.assertFalse(w.plot._panning)                       # el botón derecho no arrastra
        self.assertEqual(dlg.ed_geo.text(), "0000N04200W")
        self.assertIn("0000N04200W", dlg.lbl_cell.text())        # sobre el nodo: la celda es él
        self.assertEqual(dlg.ed_time.text(), "2610131800")       # validez del paso del panel
        self.assertEqual(dlg.fl(), 300)                          # FL del panel
        rows = dlg.rows()
        self.assertEqual(rows[1][0], "Nivel F300")
        self.assertEqual(rows[0][1], "300 hPa")       # F300 = 300.9 hPa: entre 500 y 300
        self.assertEqual(rows[2][1], "500 hPa")
        self.assertIn("interpolado en ln(p)", dlg.lbl_mode.text())
        # Cualquier FL y cualquier hora
        dlg.sp_fl.setValue(310)
        dlg.ed_time.setText("2610132200")
        self.app.processEvents()
        self.assertIn("paso [0] +6 h", dlg.lbl_step.text())
        self.assertIn("fuera de las ventanas", dlg.lbl_step.text())
        rows = dlg.rows()
        self.assertEqual(rows[1][1], "287.4 hPa ISA")
        self.assertEqual(rows[0][1], "200 hPa")
        self.assertEqual(rows[2][1], "300 hPa")
        self.assertNotEqual(rows[1][2], "—")
        self.assertRegex(rows[1][3], r"^-?\d+\.\d °C$")
        dlg.ed_time.setText("261013")
        self.app.processEvents()
        self.assertIn("hora inválida", dlg.lbl_step.text())
        self.assertEqual(dlg.rows()[1][2], "—")
        dlg.ed_time.setText("2610131900")
        self.app.processEvents()
        # Origen de celda (convención del FDP): esquina suroeste de la celda
        # que contiene el punto, no el nodo más cercano
        dlg.set_point(2.0, -43.0)
        self.assertEqual(dlg.ed_geo.text(), "0200N04300W")
        self.assertIn("0000N04800W", dlg.lbl_cell.text())             # esquina SO (lons cada 6°)
        self.assertEqual(dlg.cell(), "origin")
        # Otro clic derecho cambia el punto pero respeta FL y hora cargados
        w.open_point_dialog(-5.0, -36.0)
        self.assertEqual(dlg.ed_geo.text(), "0500S03600W")
        self.assertEqual((dlg.fl(), dlg.ed_time.text()), (310, "2610131900"))
        # Se puede escribir el punto a mano
        dlg.ed_geo.setText("0500N05200W")
        self.assertIn("0500N05400W", dlg.lbl_cell.text())             # origen: -54 ≤ -52 < -48
        # Copiar
        dlg.copy_text()
        from PyQt6.QtGui import QGuiApplication
        txt = QGuiApplication.clipboard().text()
        self.assertTrue(txt.startswith("Geodésico (grados y minutos): 0500N05200W\n"
                                       "Hora de sobrevuelo (YYMMDDHHMM): 2610131900\n"
                                       "Nivel de sobrevuelo (banda, sin F): 310\n"))
        # Cerrar el archivo deja la consulta sin datos; Vista ▸ Consultar punto la reabre
        w._file_close()
        self.assertEqual(dlg.lbl_step.text(), "Sin archivo abierto")
        self.assertEqual(dlg.rows()[1][2], "—")
        dlg.close()
        w._act_point.trigger()
        self.assertTrue(dlg.isVisible())
        self.assertEqual(w._act_point.shortcut().toString(), "Ctrl+I")


if __name__ == "__main__":
    unittest.main()
