# -*- coding: utf-8 -*-
"""Tests unitarios de app.grib_reader (sin interfaz gráfica)."""
import datetime as dt
import glob
import math
import os
import tempfile
import unittest

import numpy as np

from app import grib_reader as gr
from app.grib_reader import (GribReader, GribStep, fl_to_hpa, normalize_grid,
                             orient_values, speed_color, speed_dir_from_uv)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestISA(unittest.TestCase):
    def test_niveles_conocidos(self):
        # Valores de la atmósfera estándar (±0.5 hPa)
        self.assertAlmostEqual(fl_to_hpa(50), 843.1, delta=0.5)
        self.assertAlmostEqual(fl_to_hpa(100), 696.8, delta=0.5)
        self.assertAlmostEqual(fl_to_hpa(180), 506.0, delta=0.5)
        self.assertAlmostEqual(fl_to_hpa(300), 300.9, delta=0.5)
        self.assertAlmostEqual(fl_to_hpa(530), 100.4, delta=0.5)

    def test_tropopausa_continua(self):
        # La fórmula troposférica y la isotérmica coinciden en 36089 ft
        p_tropo = 1013.25 * (1.0 - 6.8756e-6 * 36089.0) ** 5.2559
        self.assertAlmostEqual(fl_to_hpa(360.89), p_tropo, places=6)
        self.assertAlmostEqual(fl_to_hpa(0), 1013.25, places=6)

    def test_monotona_decreciente(self):
        prev = fl_to_hpa(0)
        for fl in range(10, 600, 10):
            p = fl_to_hpa(fl)
            self.assertLess(p, prev)
            prev = p


class TestVientoYColores(unittest.TestCase):
    def test_direccion_meteorologica(self):
        u = np.array([10.0, 0.0, -10.0, 0.0, 10.0])
        v = np.array([0.0, 10.0, 0.0, -10.0, 10.0])
        spd, direc = speed_dir_from_uv(u, v)
        np.testing.assert_allclose(direc, [270.0, 180.0, 90.0, 0.0, 225.0])
        np.testing.assert_allclose(spd[:4], 10.0 * gr.MS_TO_KT)
        self.assertAlmostEqual(spd[4], math.hypot(10, 10) * gr.MS_TO_KT)

    def test_escalares(self):
        spd, direc = speed_dir_from_uv(3.0, 4.0)
        self.assertAlmostEqual(float(spd), 5.0 * 1.943844, places=5)
        self.assertAlmostEqual(float(direc), (270.0 - math.degrees(math.atan2(4, 3))) % 360)

    def test_escala_colores(self):
        esperado = {0: 0, 9.9: 0, 10: 1, 19.9: 1, 20: 2, 29.9: 2, 30: 3,
                    39.9: 3, 40: 4, 49.9: 4, 50: 5, 120: 5}
        for kt, idx in esperado.items():
            self.assertEqual(speed_color(kt), gr.SPEED_COLORS[idx], msg=f"{kt} kt")
        self.assertEqual(speed_color(float("nan")), "#888888")
        self.assertEqual(speed_color(None), "#888888")


class TestGrilla(unittest.TestCase):
    def test_lon_0_360_y_lat_decreciente(self):
        lat = np.linspace(4, -64, 69)          # de norte a sur
        lon = np.linspace(270, 338, 69)        # 0–360
        lats, lons, order, flip = normalize_grid(lat, lon)
        self.assertTrue(flip)
        self.assertEqual(lats[0], -64.0)
        self.assertEqual(lats[-1], 4.0)
        np.testing.assert_allclose(lons, np.linspace(-90, -22, 69))
        np.testing.assert_array_equal(order, np.arange(69))

    def test_lon_cruza_antimeridiano(self):
        lat = np.array([-10.0, 0.0, 10.0])      # ya ascendente
        lon = np.array([170.0, 180.0, 190.0, 200.0])
        lats, lons, order, flip = normalize_grid(lat, lon)
        self.assertFalse(flip)
        np.testing.assert_array_equal(lats, lat)
        np.testing.assert_allclose(lons, [-180.0, -170.0, -160.0, 170.0])
        np.testing.assert_array_equal(order, [1, 2, 3, 0])

    def test_orient_values(self):
        lat = np.array([10.0, 0.0, -10.0])      # decreciente
        lon = np.array([350.0, 0.0, 10.0])      # 350 → −10
        lats, lons, order, flip = normalize_grid(lat, lon)
        vals = np.arange(9, dtype=float)         # fila 0 = lat 10: [0,1,2]
        arr = orient_values(vals, 3, 3, flip, order)
        # Fila 0 ahora es lat −10 (valores 6,7,8); columna 0 es lon −10 (350)
        np.testing.assert_array_equal(arr[0], [6.0, 7.0, 8.0])
        np.testing.assert_array_equal(arr[2], [0.0, 1.0, 2.0])
        self.assertEqual(lons[0], -10.0)
        self.assertTrue(arr.flags["C_CONTIGUOUS"])


def _reader_sintetico(levels, shape=(3, 4)):
    """GribReader armado a mano (sin archivo): campos constantes por nivel,
    u = nivel, v = −nivel, t = 200 + nivel/10, en el paso 0."""
    r = object.__new__(GribReader)
    r.path = "<sintetico>"
    r.messages, r.other_messages, r.warnings = [], [], []
    r.index, r.cache = {}, {}
    r.lats = np.linspace(-10, 10, shape[0])
    r.lons = np.linspace(-60, -30, shape[1])
    r.grid = {"grid_type": "regular_ll", "ni": shape[1], "nj": shape[0],
              "lat_first": float(r.lats[-1]), "lon_first": float(r.lons[0]),
              "lat_last": float(r.lats[0]), "lon_last": float(r.lons[-1]),
              "di": float(r.lons[1] - r.lons[0]), "dj": float(r.lats[1] - r.lats[0]),
              "j_positive": 0}
    run = dt.datetime(2026, 10, 13, 12, tzinfo=dt.timezone.utc)
    r.steps = [GribStep("6", run, run + dt.timedelta(hours=6))]
    r._compute_windows()
    r.levels = sorted(levels, reverse=True)
    r.has_surface, r.kind = False, "altura"
    r.variables = ["u", "v", "t"]
    for lv in levels:
        r.index[(0, "u", float(lv))] = object()
        r.index[(0, "v", float(lv))] = object()
        r.index[(0, "t", float(lv))] = object()
        r.cache[(0, "u", float(lv))] = np.full(shape, float(lv))
        r.cache[(0, "v", float(lv))] = np.full(shape, -float(lv))
        r.cache[(0, "t", float(lv))] = np.full(shape, 200.0 + lv / 10.0)
    return r


class TestInterpolacion(unittest.TestCase):
    def test_lineal_en_ln_p(self):
        r = _reader_sintetico([850, 700, 500])
        p = 600.0
        u, v, t, info = r.interp_to_pressure(0, p)
        w = (math.log(p) - math.log(700)) / (math.log(500) - math.log(700))
        esperado = (1 - w) * 700 + w * 500
        self.assertAlmostEqual(float(u[0, 0]), esperado, places=9)
        self.assertAlmostEqual(float(v[0, 0]), -esperado, places=9)
        self.assertAlmostEqual(float(t[0, 0]), 200 + esperado / 10, places=9)
        self.assertFalse(info["extrapolated"])
        self.assertEqual(info["bracket"], (700.0, 500.0))
        self.assertEqual(info["nearest"], 700.0)   # 600 está más cerca de 700 en ln(p)

    def test_nivel_exacto_sin_interpolar(self):
        r = _reader_sintetico([850, 700, 500])
        u, v, t, info = r.interp_to_pressure(0, 700.0)
        self.assertAlmostEqual(float(u[1, 1]), 700.0)
        self.assertEqual(info["bracket"], (850.0, 700.0))
        u2, v2, t2, info2 = r.get_level_fields(0, 700.0)
        self.assertIs(u2, r.cache[(0, "u", 700.0)])
        self.assertEqual(info2["mode"], "nivel")

    def test_extrapolacion_usa_nivel_mas_cercano(self):
        r = _reader_sintetico([850, 700, 500])
        u, _, _, info = r.interp_to_pressure(0, 900.0)
        self.assertTrue(info["extrapolated"])
        self.assertEqual(info["nearest"], 850.0)
        self.assertEqual(float(u[0, 0]), 850.0)
        u, _, _, info = r.interp_to_pressure(0, 100.0)
        self.assertTrue(info["extrapolated"])
        self.assertEqual(info["nearest"], 500.0)
        self.assertEqual(float(u[0, 0]), 500.0)

    def test_variable_ausente(self):
        r = _reader_sintetico([850, 700])
        del r.index[(0, "t", 850.0)], r.index[(0, "t", 700.0)]
        u, v, t, info = r.interp_to_pressure(0, 750.0)
        self.assertIsNotNone(u)
        self.assertIsNone(t)

    def test_levels_for(self):
        r = _reader_sintetico([500, 850, 700])
        self.assertEqual(r.levels_for(0, "u"), [850.0, 700.0, 500.0])
        self.assertEqual(r.levels_for(1, "u"), [])


class TestVentanas(unittest.TestCase):
    def test_ventanas_por_paso_siguiente(self):
        r = _reader_sintetico([850])
        run = r.steps[0].run
        r.steps = [GribStep(str(h), run, run + dt.timedelta(hours=h)) for h in (6, 9, 12)]
        r._compute_windows()
        self.assertEqual(r.steps[0].window_end, r.steps[1].valid)
        self.assertEqual(r.steps[2].window_end, r.steps[2].valid + dt.timedelta(hours=3))

    def test_ventana_de_rango(self):
        r = _reader_sintetico([850])
        run = r.steps[0].run
        r.steps = [GribStep("6-9", run, run + dt.timedelta(hours=9))]
        r._compute_windows()
        self.assertEqual(r.steps[0].window_start, run + dt.timedelta(hours=6))
        self.assertEqual(r.steps[0].window_end, run + dt.timedelta(hours=9))
        self.assertEqual(r.steps[0].label(), "+9h  21:00 13/10 UTC")


def _escribir_grib_sintetico(path, steps=(6, 9), levels=(850, 700, 500), ni=8, nj=6):
    """GRIB2 chico con u, v, t en niveles de presión, latitudes decrecientes y
    longitudes 0–360, como los archivos GFS del caso de uso."""
    import eccodes as ec
    lats = np.linspace(4, -16, nj)
    lons = np.linspace(270, 298, ni)
    LON, LAT = np.meshgrid(lons, lats)
    params = {"u": (0, 2, 2), "v": (0, 2, 3), "t": (0, 0, 0)}
    with open(path, "wb") as out:
        for st in steps:
            for lv in levels:
                for var, (d, c, n) in params.items():
                    gid = ec.codes_grib_new_from_samples("regular_ll_pl_grib2")
                    ec.codes_set(gid, "discipline", d)
                    ec.codes_set(gid, "parameterCategory", c)
                    ec.codes_set(gid, "parameterNumber", n)
                    ec.codes_set(gid, "typeOfLevel", "isobaricInhPa")
                    ec.codes_set(gid, "level", lv)
                    ec.codes_set(gid, "dataDate", 20261013)
                    ec.codes_set(gid, "dataTime", 1200)
                    ec.codes_set(gid, "stepUnits", "h")
                    ec.codes_set(gid, "forecastTime", st)
                    ec.codes_set(gid, "Ni", ni)
                    ec.codes_set(gid, "Nj", nj)
                    ec.codes_set(gid, "latitudeOfFirstGridPointInDegrees", float(lats[0]))
                    ec.codes_set(gid, "longitudeOfFirstGridPointInDegrees", float(lons[0]))
                    ec.codes_set(gid, "latitudeOfLastGridPointInDegrees", float(lats[-1]))
                    ec.codes_set(gid, "longitudeOfLastGridPointInDegrees", float(lons[-1]))
                    ec.codes_set(gid, "iDirectionIncrementInDegrees", 4.0)
                    ec.codes_set(gid, "jDirectionIncrementInDegrees", 4.0)
                    ec.codes_set(gid, "jScansPositively", 0)
                    if var == "u":
                        vals = LAT + lv / 100.0          # distinto por fila
                    elif var == "v":
                        vals = LON - 300.0 + st           # distinto por columna
                    else:
                        vals = np.full(LAT.shape, 250.0 + lv / 10.0)
                    ec.codes_set_values(gid, vals.ravel())
                    ec.codes_write(gid, out)
                    ec.codes_release(gid)


@unittest.skipIf(gr.ec is None, "eccodes no disponible")
class TestLecturaGrib(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "sintetico.grib2")
        _escribir_grib_sintetico(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_inventario(self):
        r = GribReader(self.path)
        self.assertEqual(len(r.messages), 18)
        self.assertEqual([s.step_range for s in r.steps], ["6", "9"])
        self.assertEqual(r.levels, [850.0, 700.0, 500.0])
        self.assertEqual(r.variables, ["u", "v", "t"])
        self.assertEqual((r.grid["ni"], r.grid["nj"]), (8, 6))
        self.assertEqual(r.steps[0].valid, dt.datetime(2026, 10, 13, 18, tzinfo=dt.timezone.utc))
        txt = r.inventory_text()
        self.assertIn("NIVELES (hPa): 850, 700, 500", txt)
        self.assertIn("Ni=8  Nj=6", txt)

    def test_orientacion_y_cache(self):
        r = GribReader(self.path)
        self.assertEqual(r.lats[0], -16.0)
        self.assertEqual(r.lons[0], -90.0)
        u = r.get_field(0, "u", 850.0)
        # u = lat + 8.5: la fila 0 (lat −16) debe valer −7.5
        np.testing.assert_allclose(u[0], -16.0 + 8.5)
        np.testing.assert_allclose(u[-1], 4.0 + 8.5)
        v = r.get_field(1, "v", 700.0)
        # v = lon − 300 + 9: columna 0 (lon 270) = −21
        np.testing.assert_allclose(v[:, 0], -21.0)
        self.assertIs(r.get_field(0, "u", 850.0), u)      # cache
        self.assertIsNone(r.get_field(0, "u", 999.0))

    def test_archivo_invalido(self):
        bad = os.path.join(self.tmp.name, "malo.grib2")
        with open(bad, "wb") as fh:
            fh.write(b"esto no es un grib")
        with self.assertRaises(Exception):
            GribReader(bad)
        with self.assertRaises(FileNotFoundError):
            GribReader(os.path.join(self.tmp.name, "no_existe.grib2"))


class TestMotorWgrib2(unittest.TestCase):
    """Parseo de la salida de wgrib2 (sin el programa) y, si hay un wgrib2
    disponible (PATH o variable WGRIB2), lectura completa comparada con ecCodes."""

    INV = ("2:56731:d=2026101406:UGRD:100 mb:6 hour fcst::D=20261014060000:"
           "vt=20261014120000:(213 x 177)")
    GRID = ("1:0:grid_template=0:winds(N/S):\n"
            "\tlat-lon grid:(213 x 177) units 1e-06 input WE:SN output WE:SN res 48\n"
            "\tlat -64.000000 to -20.000000 by 0.250000\n"
            "\tlon 285.000000 to 338.000000 by 0.250000 #points=37701\n")

    def test_parse_inventario(self):
        from app import grib_engines as ge
        m = ge.parse_inventory_line(self.INV)
        self.assertEqual((m.record, m.index, m.offset), ("2", 2, 56731))
        self.assertEqual((m.var, m.short_name, m.units), ("u", "UGRD", "m s**-1"))
        self.assertEqual((m.type_of_level, m.level_hpa), ("isobaricInhPa", 100.0))
        self.assertEqual((m.step_range, m.end_step), ("6", 6.0))
        self.assertEqual(m.run, dt.datetime(2026, 10, 14, 6, tzinfo=dt.timezone.utc))
        self.assertEqual(m.valid, dt.datetime(2026, 10, 14, 12, tzinfo=dt.timezone.utc))
        self.assertEqual((m.ni, m.nj), (213, 177))
        # Rango, análisis, otros niveles y días
        m = ge.parse_inventory_line("5:10:d=2026101406:TMP:surface:0-6 hour ave fcst:")
        self.assertEqual((m.var, m.level_hpa, m.step_range, m.end_step), ("t", None, "0-6", 6.0))
        self.assertEqual(m.type_of_level, "surface")
        self.assertEqual(m.valid, m.run + dt.timedelta(hours=6))
        m = ge.parse_inventory_line("1:0:d=2026101406:VGRD:850 mb:anl:")
        self.assertEqual((m.var, m.step_range, m.valid), ("v", "0", m.run))
        m = ge.parse_inventory_line("1:0:d=2026101406:HGT:500 mb:2 day fcst:")
        self.assertEqual((m.var, m.step_range), (None, "48"))
        self.assertIsNone(ge.parse_inventory_line("basura"))

    def test_parse_grilla(self):
        from app import grib_engines as ge
        g = ge.parse_grid(self.GRID)
        self.assertEqual((g.ni, g.nj, g.j_positive), (213, 177, 1))
        self.assertEqual((g.lat1d[0], g.lat1d[-1]), (-64.0, -20.0))
        self.assertEqual((g.lon1d[0], g.lon1d[-1]), (285.0, 338.0))
        self.assertAlmostEqual(g.lon1d[1] - g.lon1d[0], 0.25)
        # Norte→sur y cruce del meridiano 0
        g = ge.parse_grid(self.GRID.replace("input WE:SN", "input WE:NS")
                          .replace("lat -64.000000 to -20.000000", "lat 20.000000 to -24.000000")
                          .replace("lon 285.000000 to 338.000000", "lon 350.000000 to 43.000000"))
        self.assertEqual(g.j_positive, 0)
        self.assertEqual((g.lat1d[0], g.lat1d[-1]), (20.0, -24.0))
        self.assertEqual((g.lon1d[0], g.lon1d[-1]), (350.0, 403.0))
        with self.assertRaises(ValueError):
            ge.parse_grid("1:0:grid_template=40:\n\tgaussian grid: (1536 x 768)")

    def test_motor_desconocido_y_wgrib2_ausente(self):
        from app import grib_engines as ge
        with self.assertRaises(ge.EngineUnavailable):
            ge.make_backend("otro")
        import shutil
        old = shutil.which
        old_env = os.environ.pop("WGRIB2", None)
        shutil.which = lambda *a, **k: None
        try:
            with self.assertRaises(ge.EngineUnavailable) as cm:
                ge.make_backend("wgrib2", "/no/existe/wgrib2")
            self.assertIn("Preferencias", str(cm.exception))
        finally:
            shutil.which = old
            if old_env is not None:
                os.environ["WGRIB2"] = old_env

    def test_lectura_real_con_wgrib2(self):
        from app import grib_engines as ge
        exe = ge.find_wgrib2()
        if exe is None or gr.ec is None:
            self.skipTest("sin wgrib2 (PATH o variable WGRIB2) o sin eccodes")
        tmp = tempfile.TemporaryDirectory()
        try:
            path = os.path.join(tmp.name, "s.grib2")
            _escribir_grib_sintetico(path)
            a = GribReader(path)
            b = GribReader(path, engine="wgrib2")
            self.assertEqual(b.engine, "wgrib2")
            self.assertIn("Motor: wgrib2", b.inventory_text())
            self.assertEqual([m.step_range for m in a.messages], [m.step_range for m in b.messages])
            self.assertEqual([m.valid for m in a.messages], [m.valid for m in b.messages])
            self.assertEqual((a.levels, a.variables), (b.levels, b.variables))
            np.testing.assert_allclose(a.lats, b.lats)
            np.testing.assert_allclose(a.lons, b.lons)
            for key in a.index:
                np.testing.assert_allclose(a.get_field(*key), b.get_field(*key), atol=1e-4)
        finally:
            tmp.cleanup()


class TestArchivoReal(unittest.TestCase):
    """Si hay un .grib2 real en la carpeta del proyecto, se inventaría."""

    def test_inventario_archivo_real(self):
        archivos = sorted(glob.glob(os.path.join(ROOT, "*.grib2")) +
                          glob.glob(os.path.join(ROOT, "*.grb2")))
        if not archivos or gr.ec is None:
            self.skipTest("sin archivo .grib2 en la carpeta o sin eccodes")
        r = GribReader(archivos[0])
        self.assertTrue(r.steps)
        self.assertTrue(r.levels)
        self.assertIn("GRILLA", r.inventory_text())


if __name__ == "__main__":
    unittest.main()
