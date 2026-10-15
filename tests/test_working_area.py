# -*- coding: utf-8 -*-
"""Working Area de las FIR: proyección estereográfica tangente, contorno,
configuración, selección de FIR de a una desde el menú y dibujo en el mapa."""
import math
import os
import shutil
import tempfile
import unittest

import numpy as np

from app import working_area as W

_app = None


def _qt():
    global _app
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication([])
    from app.dialogs import glass_dialog
    glass_dialog._apply_dialog_blur = lambda w: None
    return _app


SAEF = dict(code="SAEF", tangent_lat=-34.8, tangent_lon=-58.5, vertex_lat=-42.0, vertex_lon=-66.0,
            width_nm=700.0, height_nm=700.0, radius_km=6371.0, enabled=True)
SACF = dict(code="SACF", tangent_lat=-31.3, tangent_lon=-64.2, vertex_lat=-35.0, vertex_lon=-70.0,
            width_nm=500.0, height_nm=500.0, radius_km=6371.0, enabled=True)


class TestProyeccion(unittest.TestCase):
    def test_tangencia_es_el_origen(self):
        x, y = W.stereo_forward(-34.8, -58.5, -34.8, -58.5, 6371.0)
        self.assertAlmostEqual(float(x), 0.0)
        self.assertAlmostEqual(float(y), 0.0)

    def test_ida_y_vuelta(self):
        for lat, lon in ((-30.123, -55.456), (-45.0, -70.0), (-10.0, -40.0), (-34.8, -58.5)):
            x, y = W.stereo_forward(lat, lon, -34.8, -58.5, 6371.0)
            la, lo = W.stereo_inverse(x, y, -34.8, -58.5, 6371.0)
            self.assertAlmostEqual(float(la), lat, places=9)
            self.assertAlmostEqual(float(lo), lon, places=9)

    def test_ejes_norte_y_este(self):
        """Un punto al norte de la tangencia cae en +y, uno al este en +x."""
        x, y = W.stereo_forward(-33.8, -58.5, -34.8, -58.5, 6371.0)
        self.assertAlmostEqual(float(x), 0.0, places=9)
        self.assertGreater(float(y), 59.0)      # ≈ 60 NM por grado de latitud
        self.assertLess(float(y), 61.0)
        x, y = W.stereo_forward(-34.8, -57.5, -34.8, -58.5, 6371.0)
        self.assertGreater(float(x), 49.0)      # ≈ 60·cos(34,8°) NM por grado de longitud
        self.assertLess(abs(float(y)), 1.0)     # el paralelo se curva apenas (plano conforme)

    def test_radio_conforme(self):
        a = W.WGS84_A_KM
        b = a * (1.0 - W.WGS84_F)
        self.assertAlmostEqual(W.conformal_radius_km(0.0), b, places=3)     # √(M·N) en el ecuador = b
        self.assertAlmostEqual(W.conformal_radius_km(90.0), a / math.sqrt(1.0 - W.WGS84_E2), places=3)
        r = W.conformal_radius_km(-34.8)
        self.assertTrue(6360.0 < r < 6380.0)


class TestVariacionMagnetica(unittest.TestCase):
    def test_parse(self):
        self.assertAlmostEqual(W.parse_variation("7W"), -7.0)
        self.assertAlmostEqual(W.parse_variation("7 w"), -7.0)
        self.assertAlmostEqual(W.parse_variation("7°W"), -7.0)
        self.assertAlmostEqual(W.parse_variation("O7"), -7.0)
        self.assertAlmostEqual(W.parse_variation("6°55'E"), 6.0 + 55.0 / 60.0)
        self.assertAlmostEqual(W.parse_variation("6°55'30\"E"), 6.0 + 55.0 / 60.0 + 30.0 / 3600.0)
        self.assertAlmostEqual(W.parse_variation("10,5w"), -10.5)
        self.assertAlmostEqual(W.parse_variation("-7"), -7.0)                       # este positivo
        self.assertAlmostEqual(W.parse_variation("+6.9"), 6.9)
        self.assertAlmostEqual(W.parse_variation("7", "west_positive"), -7.0)        # oeste positivo
        self.assertAlmostEqual(W.parse_variation("-7", "west_positive"), 7.0)
        self.assertAlmostEqual(W.parse_variation("7W", "west_positive"), -7.0)       # la letra manda
        self.assertAlmostEqual(W.parse_variation("0"), 0.0)
        for bad in ("", "abc", "7°75'W", "-7W", "200", "7 8 9 10"):
            with self.assertRaises(W.WorkingAreaError, msg=bad):
                W.parse_variation(bad)

    def test_format(self):
        self.assertEqual(W.format_variation(-10.01), "10.0°W")
        self.assertEqual(W.format_variation(6.92), "6.9°E")
        self.assertEqual(W.format_variation(0.0), "0.0°")
        self.assertEqual(W.format_variation(-10.0, "east_positive", "signed"), "-10.0")
        self.assertEqual(W.format_variation(-10.0, "west_positive", "signed"), "+10.0")
        self.assertEqual(W.format_variation(0.0, "west_positive", "signed"), "0.0")
        for v in (-10.0, 6.9, 0.0, 180.0):
            for conv in ("east_positive", "west_positive"):
                self.assertAlmostEqual(W.parse_variation(W.format_variation(v, conv, "signed"), conv), v)
                self.assertAlmostEqual(W.parse_variation(W.format_variation(v)), v, places=1)

    def test_plano_girado(self):
        """Con variación oeste, el norte verdadero cae a la derecha del eje
        y de la WA; con variación este, a la izquierda."""
        base = dict(SAEF, variation_deg=0.0)
        for var, sign in ((-10.0, 1), (10.0, -1)):
            wa = W.WorkingArea(**dict(base, variation_deg=var))
            x, y = wa.forward(SAEF["tangent_lat"] + 1.0, SAEF["tangent_lon"])   # 1° al norte de la tangencia
            self.assertAlmostEqual(math.degrees(math.atan2(float(x), float(y))), -var, places=6)
            self.assertEqual(1 if float(x) > 0 else -1, sign)
            lat, lon = wa.inverse(*wa.forward(-30.0, -55.0))
            self.assertAlmostEqual(float(lat), -30.0, places=9)
            self.assertAlmostEqual(float(lon), -55.0, places=9)
            # el cuadrado sigue teniendo lados de 700 NM en su plano
            (x0, y0), (x1, y1), (x2, y2), _ = wa.corners_xy()
            self.assertAlmostEqual(math.hypot(x1 - x0, y1 - y0), 700.0)
            self.assertAlmostEqual(math.hypot(x2 - x1, y2 - y1), 700.0)
        wa0 = W.WorkingArea(**base)
        wa1 = W.WorkingArea(**dict(base, variation_deg=-10.0))
        # distintas esquinas NE: el cuadrado giró alrededor del vértice SO
        self.assertAlmostEqual(wa0.corners()[0][0], wa1.corners()[0][0], places=9)
        self.assertNotAlmostEqual(wa0.corners()[2][1], wa1.corners()[2][1], places=2)

    def test_tangencia_y_validacion(self):
        a = W.WorkingArea(**dict(SAEF, tangency=True))
        b = W.WorkingArea(**dict(SACF, tangency=True))
        errs = W.validate_working_areas([a, b])
        self.assertTrue(any("sólo una" in e for e in errs))
        self.assertEqual(W.validate_working_areas([a, W.WorkingArea(**SACF)]), [])
        self.assertIs(W.find_tangency([W.WorkingArea(**SACF), a]), a)
        self.assertIsNone(W.find_tangency([W.WorkingArea(**SACF)]))
        self.assertIsNone(W.find_tangency([W.WorkingArea(**dict(SAEF, tangency=True, width_nm=0.0))]))
        bad = W.WorkingArea(**dict(SAEF, variation_deg=200.0))
        self.assertTrue(any("variación" in e for e in W.validate_working_area(bad)))
        d = a.to_dict()
        self.assertEqual((d["variation_deg"], d["tangency"]), (0.0, True))
        self.assertTrue(W.WorkingArea.from_dict(d).tangency)
        self.assertIn("tangencia de la proyección", W.describe(a))
        self.assertIn("var. 10.0°W", W.describe(W.WorkingArea(**dict(SAEF, variation_deg=-10.0))))

    def test_parametros_de_proyeccion(self):
        import pyproj
        lat, lon, r = -34.8222, -58.5358, 6370.643
        for up in (0.0, -10.0, 25.0):
            params = W.tangent_projection_params(lat, lon, r, up)
            crs = pyproj.CRS.from_proj4(" ".join(f"+{k}={v}" for k, v in params) + f" +R={r * 1000} +units=m")
            ll = pyproj.CRS.from_proj4(f"+proj=longlat +R={r * 1000}")
            tr = pyproj.Transformer.from_crs(ll, crs, always_xy=True)
            x0, y0 = tr.transform(lon, lat)
            self.assertLess(math.hypot(x0, y0), 1.0)                          # la tangencia es el origen
            xn, yn = tr.transform(lon, lat + 1.0)
            self.assertAlmostEqual(math.degrees(math.atan2(xn - x0, yn - y0)), -up, places=6)
            self.assertAlmostEqual(math.hypot(xn - x0, yn - y0) / 1852.0, 60.04, places=1)


class TestWorkingArea(unittest.TestCase):
    def test_esquinas_y_contorno(self):
        wa = W.WorkingArea(**SAEF)
        so, se, ne, no = wa.corners()
        self.assertAlmostEqual(so[0], -42.0, places=9)
        self.assertAlmostEqual(so[1], -66.0, places=9)
        # lados medidos en el plano
        (x0, y0), (x1, y1), (x2, y2), (x3, y3) = wa.corners_xy()
        self.assertAlmostEqual(math.hypot(x1 - x0, y1 - y0), 700.0)
        self.assertAlmostEqual(math.hypot(x2 - x1, y2 - y1), 700.0)
        self.assertAlmostEqual(math.hypot(x3 - x0, y3 - y0), 700.0)
        self.assertGreater(ne[0], so[0])        # la esquina NE está más al norte
        self.assertGreater(ne[1], so[1])        # y más al este
        ring = wa.ring(step_nm=5.0)
        self.assertEqual(ring.shape[1], 2)
        self.assertEqual(len(ring), 4 * 140)
        self.assertAlmostEqual(ring[0, 0], -66.0, places=9)
        self.assertAlmostEqual(ring[0, 1], -42.0, places=9)
        self.assertTrue((np.abs(ring[:, 0]) <= 180).all() and (np.abs(ring[:, 1]) <= 90).all())

    def test_contiene(self):
        wa = W.WorkingArea(**SAEF)
        self.assertTrue(wa.contains(-37.0, -60.0))
        self.assertFalse(wa.contains(-20.0, -40.0))
        self.assertTrue(wa.contains(-42.0, -66.0))      # el vértice pertenece
        lon, lat = wa.label_point()
        self.assertTrue(wa.contains(lat, lon))
        bb = wa.bbox()
        self.assertLess(bb[0], -66.0 + 1e-6)
        self.assertLessEqual(bb[2], -42.0 + 1e-6)

    def test_validacion(self):
        self.assertEqual(W.validate_working_area(W.WorkingArea(**SAEF)), [])
        bad = W.WorkingArea(**dict(SAEF, width_nm=0.0))
        self.assertTrue(any("ancho" in e for e in W.validate_working_area(bad)))
        bad = W.WorkingArea(**dict(SAEF, radius_km=5000.0))
        self.assertTrue(any("radio" in e for e in W.validate_working_area(bad)))
        bad = W.WorkingArea(**dict(SAEF, code="SA1F"))
        self.assertTrue(any("código" in e for e in W.validate_working_area(bad)))
        bad = W.WorkingArea(**dict(SAEF, vertex_lat=95.0))
        self.assertTrue(any("latitud" in e for e in W.validate_working_area(bad)))
        far = W.WorkingArea(**dict(SAEF, vertex_lat=60.0, vertex_lon=120.0))
        self.assertTrue(any("90°" in e for e in W.validate_working_area(far)))
        dup = W.validate_working_areas([W.WorkingArea(**SAEF), W.WorkingArea(**SAEF)])
        self.assertTrue(any("repetido" in e for e in dup))

    def test_config_ida_y_vuelta(self):
        was = [W.WorkingArea(**SAEF), W.WorkingArea(**dict(SACF, enabled=False))]
        cfg = {"working_areas": W.working_areas_to_config(was)}
        back = W.working_areas_from_config(cfg)
        self.assertEqual([w.to_dict() for w in back], [w.to_dict() for w in was])
        self.assertEqual(W.find_working_area(back, "sacf").code, "SACF")
        self.assertIsNone(W.find_working_area(back, "SARR"))
        self.assertEqual(W.working_areas_from_config({}), [])
        self.assertEqual(W.working_areas_from_config({"working_areas": [None, 3]}), [])
        self.assertIn("NE", W.describe(was[0]))


class TestVentana(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _qt()
        cls.tmp = tempfile.mkdtemp()
        from app import config
        cls._old_path = config.CONFIG_PATH
        config.CONFIG_PATH = os.path.join(cls.tmp, "config.json")

    @classmethod
    def tearDownClass(cls):
        from app import config
        config.CONFIG_PATH = cls._old_path
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        from app import config
        try:
            os.remove(config.CONFIG_PATH)       # cada test arranca con la configuración por defecto
        except OSError:
            pass
        from app.main_window import MainWindow
        self.w = MainWindow()
        self.w.show()
        _app.processEvents()

    def tearDown(self):
        self.w.close()
        self.w.deleteLater()
        _app.processEvents()

    def test_menu_una_por_una(self):
        w = self.w
        self.assertEqual(len(w._fir_code_actions), 14)
        self.assertFalse(w._cfg["fir_enabled"])
        w.toggle_fir_code("SAEF", True)
        self.assertTrue(w._cfg["fir_enabled"])
        self.assertEqual(w._cfg["fir_active"], ["SAEF"])
        self.assertEqual([r.code for r in w.plot.fir_visible()], ["SAEF"])
        self.assertTrue(w._fir_code_actions["SAEF"].isChecked())
        self.assertFalse(w._fir_code_actions["SACF"].isChecked())
        w.toggle_fir_code("SACF", True)
        self.assertEqual(w._cfg["fir_active"], ["SACF", "SAEF"])
        # una vecina enciende las vecinas
        self.assertFalse(w._cfg["fir_neighbors"])
        w.toggle_fir_code("SUEO", True)
        self.assertTrue(w._cfg["fir_neighbors"])
        self.assertEqual(sorted(r.code for r in w.plot.fir_visible()), ["SACF", "SAEF", "SUEO"])
        w.toggle_fir_code("SAEF", False)
        self.assertEqual(sorted(r.code for r in w.plot.fir_visible()), ["SACF", "SUEO"])
        w.set_fir_codes([])
        self.assertEqual(w.plot.fir_visible(), [])
        w.set_fir_codes(list(w._fir_code_actions))
        self.assertEqual(len(w.plot.fir_visible()), 14)
        w.set_fir_codes(["SARR", "SACF", "SAMF", "SAEF", "SAVF"])
        self.assertEqual(len(w.plot.fir_visible()), 5)

    def test_wa_con_la_fir(self):
        w = self.w
        w._cfg["working_areas"] = [dict(SAEF), dict(SACF, enabled=False)]
        w.set_fir_codes(["SAEF", "SACF"])
        self.assertEqual(w.plot.wa_visible(), [])            # todavía no se pidió
        w.set_wa_show(True)
        self.assertEqual(w.plot.wa_visible(), ["SAEF"])      # SACF está deshabilitada
        self.assertTrue(w.panel.chk_wa.isChecked())
        self.assertTrue(w._act_wa.isChecked())
        w.plot.draw_empty()
        self.assertEqual(len(w.plot._wa_artists), 2)         # contorno + etiqueta
        w.toggle_fir_code("SAEF", False)
        self.assertEqual(w.plot.wa_visible(), [])            # sin la FIR no hay WA
        w.toggle_fir_code("SAEF", True)
        self.assertEqual(w.plot.wa_visible(), ["SAEF"])
        w.panel.chk_wa.setChecked(False)
        self.assertFalse(w._cfg["wa_show"])
        self.assertEqual(w.plot.wa_visible(), [])
        w.set_wa_show(True)
        for key in ("stereo", "spstereo", "mercator", "lambert", "platecarree"):
            w.plot.set_projection(key, np.linspace(-80, -40, 5), np.linspace(-55, -15, 5))
            w.plot.draw_empty()
            self.assertEqual(len(w.plot._wa_artists), 2, key)

    def test_proyeccion_tangente_a_la_wa(self):
        from app.wind_plot import HAVE_CARTOPY
        if not HAVE_CARTOPY:
            self.skipTest("sin cartopy")
        from tests.test_grib_reader import _reader_sintetico
        w = self.w
        r = _reader_sintetico([850, 700], shape=(69, 69))
        r.lats = np.arange(-64.0, 4.1, 1.0)
        r.lons = np.arange(-90.0, -21.9, 1.0)
        r.path = os.path.join(self.tmp, "s.grib2")
        w.load_reader(r, r.path)
        w._cfg["working_areas"] = [dict(SAEF, variation_deg=-10.0, tangency=True), dict(SACF)]
        w.set_projection("stereo")
        t = w.plot.tangent
        self.assertEqual(t["code"], "SAEF")
        self.assertAlmostEqual(t["up_bearing"], -10.0)
        self.assertEqual(type(w.plot.proj).__name__, "TangentStereographic")
        # la WA de tangencia es un cuadrado alineado a los ejes del mapa
        wa = W.WorkingArea(**dict(SAEF, variation_deg=-10.0, tangency=True))
        cs = wa.corners()
        xy = w.plot.proj.transform_points(w.plot.data_crs, np.array([c[1] for c in cs]),
                                          np.array([c[0] for c in cs]))[:, :2] / 1852.0
        self.assertAlmostEqual(xy[1, 1], xy[0, 1], places=3)
        self.assertAlmostEqual(xy[1, 0] - xy[0, 0], 700.0, places=3)
        self.assertAlmostEqual(xy[3, 1] - xy[0, 1], 700.0, places=3)
        # el norte verdadero aparece 10° a la derecha; el cursor agrega °M
        x0, y0 = w.plot.proj.transform_point(SAEF["tangent_lon"], SAEF["tangent_lat"], w.plot.data_crs)
        xn, yn = w.plot.proj.transform_point(SAEF["tangent_lon"], SAEF["tangent_lat"] + 1.0, w.plot.data_crs)
        self.assertAlmostEqual(math.degrees(math.atan2(xn - x0, yn - y0)), 10.0, places=5)
        self.assertIn("°M)", w.cursor_text(-60.0, -35.0))
        self.assertIn("tangente a la WA SAEF", w.projection_text())
        self.assertIn("10.0°W", w.projection_text())
        self.assertIn("tangente a WA SAEF", w.panel.cb_proj.itemText(w.panel.cb_proj.findData("stereo")))
        self.assertIn("tangente a WA SAEF", w._proj_actions["stereo"].text())
        w.set_wa_show(True)
        w.set_fir_codes(["SAEF", "SACF"])
        w.plot.canvas.draw()
        self.assertEqual(w.plot.wa_visible(), ["SACF", "SAEF"])
        # sin tangencia (o con una inválida): centro del dominio, como siempre
        w._cfg["working_areas"][0]["tangency"] = False
        w._refresh_tangent_projection()
        self.assertIsNone(w.plot.tangent)
        self.assertEqual(type(w.plot.proj).__name__, "Stereographic")
        self.assertNotIn("°M", w.cursor_text(-60.0, -35.0))
        self.assertEqual(w.panel.cb_proj.itemText(w.panel.cb_proj.findData("stereo")),
                         "Estereográfica conforme (centro del dominio)")
        w._cfg["working_areas"][0]["tangency"] = True
        w._cfg["working_areas"][0]["width_nm"] = 0.0
        w._refresh_tangent_projection()
        self.assertIsNone(w.plot.tangent)
        # Lambert: centrada en la tangencia con su radio, sin giro magnético
        w._cfg["working_areas"][0]["width_nm"] = 700.0
        w.set_projection("lambert")
        t = w.plot.tangent
        self.assertEqual((t["code"], t["up_bearing"], t["variation_deg"]), ("SAEF", 0.0, 0.0))
        self.assertEqual(type(w.plot.proj).__name__, "LambertConformal")
        x0, y0 = w.plot.proj.transform_point(SAEF["tangent_lon"], SAEF["tangent_lat"], w.plot.data_crs)
        self.assertLess(math.hypot(x0, y0), 1.0)
        xn, yn = w.plot.proj.transform_point(SAEF["tangent_lon"], SAEF["tangent_lat"] + 1.0, w.plot.data_crs)
        self.assertAlmostEqual(math.degrees(math.atan2(xn - x0, yn - y0)), 0.0, places=6)
        self.assertIn("Lambert conforme centrada en la WA SAEF", w.projection_text())
        self.assertIn("norte verdadero arriba", w.projection_text())
        self.assertNotIn("°M", w.cursor_text(-60.0, -35.0))
        self.assertIn("tangente a WA SAEF", w.panel.cb_proj.itemText(w.panel.cb_proj.findData("lambert")))
        # las demás proyecciones no usan la tangencia
        w.set_projection("mercator")
        self.assertIsNone(w.plot.tangent)
        w.set_projection("stereo")
        self.assertEqual(w.plot.tangent["code"], "SAEF")

    def test_dialogo_variacion_y_tangencia(self):
        from app.dialogs import fir_dialog
        from app.dialogs.fir_dialog import FirDialog
        warnings = []
        fir_dialog.QMessageBox.warning = lambda *a, **k: warnings.append(a[2])
        w = self.w
        w._cfg["working_areas"] = [dict(SAEF, variation_deg=-10.0, tangency=True), dict(SACF)]
        d = FirDialog(w, cfg=w._cfg, regions=w._fir_regions, notes=[], grid_bbox=None)
        self.assertEqual(d.wa_table.cellWidget(0, d.W_VAR).text(), "-10.0")
        self.assertTrue(d.wa_table.cellWidget(0, d.W_TG).isChecked())
        e = d.wa_table.cellWidget(1, d.W_VAR)
        e.setText("6°55'E")
        d._wa_commit_variation(e)
        self.assertEqual(e.text(), "+6.9")
        e.setText("8W")
        d._wa_commit_variation(e)
        self.assertEqual(e.text(), "-8.0")
        # la tangencia es excluyente
        d.wa_table.cellWidget(1, d.W_TG).setChecked(True)
        self.assertFalse(d.wa_table.cellWidget(0, d.W_TG).isChecked())
        v = d.values()
        self.assertEqual([(x["code"], x["variation_deg"], x["tangency"]) for x in v["working_areas"]],
                         [("SAEF", -10.0, False), ("SACF", -8.0, True)])
        # texto inválido: aviso propio y Aplicar bloqueado
        e.setText("abc")
        d._wa_commit_variation(e)
        self.assertIn("inválida", d.lbl_wa_error.text())
        self.assertTrue(any("inválida" in x for x in d.wa_errors()))
        d.accept()
        self.assertEqual(d.result(), 0)
        e.setText("8W")
        d._wa_commit_variation(e)
        d.accept()
        self.assertEqual(d.result(), 1)
        # convención oeste positivo: el número cambia de signo, el valor interno no
        w._cfg["magvar_convention"] = "west_positive"
        w._cfg.update(v)
        d2 = FirDialog(w, cfg=w._cfg, regions=w._fir_regions, notes=[], grid_bbox=None)
        self.assertEqual(d2.wa_table.cellWidget(0, d2.W_VAR).text(), "+10.0")
        self.assertAlmostEqual(d2._wa_row(0).variation_deg, -10.0)
        e2 = d2.wa_table.cellWidget(0, d2.W_VAR)
        e2.setText("7")
        d2._wa_commit_variation(e2)
        self.assertAlmostEqual(d2._wa_row(0).variation_deg, -7.0)
        from app.dialogs.settings_dialog import SettingsDialog
        sd = SettingsDialog(w, cfg=w._cfg)
        self.assertEqual(sd.cb_magvar.currentData(), "west_positive")
        sd.cb_magvar.setCurrentIndex(0)
        self.assertEqual(sd.values()["magvar_convention"], "east_positive")

    def test_dialogo_working_area(self):
        from app.dialogs import fir_dialog
        from app.dialogs.fir_dialog import FirDialog
        warnings = []
        fir_dialog.QMessageBox.warning = lambda *a, **k: warnings.append(a[2])   # sin modal
        w = self.w
        w._cfg["working_areas"] = [dict(SAEF)]
        d = FirDialog(w, cfg=w._cfg, regions=w._fir_regions, notes=[], grid_bbox=None)
        self.assertEqual(d.tabs.tabText(3), "Working Area")
        self.assertEqual(d.wa_table.rowCount(), 1)
        self.assertEqual(d.wa_errors(), [])
        self.assertIn("SAEF", d.lbl_wa_info.text())
        d._wa_add_default()
        self.assertEqual(d.wa_table.rowCount(), 2)
        self.assertEqual(d.wa_table.cellWidget(1, d.W_CODE).text(), "SARR")
        d.wa_table.cellWidget(1, d.W_TLAT).set_value(-27.0)
        d.wa_table.cellWidget(1, d.W_TLON).set_value(-59.0)
        d.wa_table.cellWidget(1, d.W_VLAT).set_value(-31.0)
        d.wa_table.cellWidget(1, d.W_VLON).set_value(-63.0)
        d.wa_table.cellWidget(1, d.W_W).setValue(400.0)
        d.wa_table.cellWidget(1, d.W_H).setValue(450.0)
        d.wa_table.selectRow(1)
        d._wa_conformal()
        self.assertAlmostEqual(d.wa_table.cellWidget(1, d.W_R).value(), W.conformal_radius_km(-27.0), places=3)
        d.chk_wa_show.setChecked(True)
        v = d.values()
        self.assertEqual([x["code"] for x in v["working_areas"]], ["SAEF", "SARR"])
        self.assertEqual(v["working_areas"][1]["width_nm"], 400.0)
        self.assertTrue(v["wa_show"])
        # un ancho inválido bloquea Aplicar
        d.wa_table.cellWidget(1, d.W_W).setValue(0.0)
        self.assertTrue(d.wa_errors())
        d.accept()
        self.assertEqual(d.result(), 0)
        self.assertEqual(len(warnings), 1)
        d.wa_table.cellWidget(1, d.W_W).setValue(400.0)
        d.accept()
        self.assertEqual(d.result(), 1)
        w._cfg.update(d.values())
        w.set_fir_codes(["SARR"])
        self.assertEqual(w.plot.wa_visible(), ["SARR"])
        # borrar la fila elegida
        d2 = FirDialog(w, cfg=w._cfg, regions=w._fir_regions, notes=[], grid_bbox=None)
        d2.wa_table.selectRow(0)
        d2._wa_remove()
        self.assertEqual([x["code"] for x in d2.values()["working_areas"]], ["SARR"])


if __name__ == "__main__":
    unittest.main()
