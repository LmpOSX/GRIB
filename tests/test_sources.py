# -*- coding: utf-8 -*-
"""Esquema de fuentes: parámetros, corridas, descarga genérica (caché,
reintentos, validación, procedencia), regrillado/recorte local, credenciales
y los widgets/diálogos que se arman solos a partir de una fuente."""
import datetime as dt
import json
import os
import tempfile
import unittest
import urllib.error

import numpy as np

from app import gfs_download as gfs
from app.sources import (GFSSource, DownloadJob, DownloadError, DownloadCancelled, Param,
                         Source, Request, TestResult, get_source, source_config,
                         set_source_config, enabled_sources, source_label, read_provenance)
from app.sources.base import fetch_with_retries, check_content, classify_exception
from app.sources.cache import DownloadCache
from app import regrid


def _job(**kw):
    base = dict(run_date=dt.date(2026, 10, 14), cycle=6, steps=[6, 9], variables=["UGRD", "VGRD", "TMP"],
                levels=[850, 700, 500], region=(4.0, -64.0, -90.0, -22.0), dest_dir=".", merge=True,
                params={})
    base.update(kw)
    return DownloadJob(**base)


class TestFuenteGFS(unittest.TestCase):
    def setUp(self):
        self.src = GFSSource()

    def test_descripcion(self):
        s = self.src
        self.assertEqual(s.key, "gfs")
        self.assertEqual(source_label(s), "NOAA GFS")
        self.assertFalse(s.flight_levels)
        self.assertEqual(s.default_params()["resolucion"], "0p25")
        steps = s.steps()
        self.assertEqual(steps[:3], [0, 1, 2])
        self.assertIn(123, steps)
        self.assertNotIn(122, steps)
        self.assertEqual(steps[-1], 384)

    def test_corridas(self):
        now = dt.datetime(2026, 10, 14, 10, 0, tzinfo=dt.timezone.utc)   # 10:00Z → 06Z ya está (lag 4,5 h)
        self.assertEqual(self.src.latest_run(now), (dt.date(2026, 10, 14), 0))
        now = dt.datetime(2026, 10, 14, 11, 0, tzinfo=dt.timezone.utc)
        self.assertEqual(self.src.latest_run(now), (dt.date(2026, 10, 14), 6))
        runs = self.src.available_runs(now, count=5)
        self.assertEqual(runs[0], (dt.date(2026, 10, 14), 6))
        self.assertEqual(runs[2], (dt.date(2026, 10, 13), 18))
        self.assertEqual(len(runs), 5)

    def test_validacion_y_pedidos(self):
        s = self.src
        self.assertIsNone(s.validate(_job()))
        self.assertIn("no ofrece", s.validate(_job(steps=[122])))
        self.assertIn("Ciclo", s.validate(_job(cycle=3)))
        self.assertIn("variable", s.validate(_job(variables=[])))
        reqs = s.build_requests(_job(), 6)
        self.assertEqual(len(reqs), 1)
        self.assertIn("filter_gfs_0p25.pl", reqs[0].url)
        self.assertIn("lev_850_mb=on", reqs[0].url)
        # Intermedios a 0,25°: dos pedidos
        job = _job(levels=[300, 275], params={"niveles_intermedios": True})
        reqs = s.build_requests(job, 6)
        self.assertEqual([r.tag for r in reqs], ["", "niveles intermedios"])
        # Sin el parámetro, el nivel intermedio se ignora
        job = _job(levels=[300, 275])
        self.assertEqual(len(s.build_requests(job, 6)), 1)
        # A 1,00° con intermedios: inválido salvo que se baje 0,25°
        job = _job(levels=[300, 275], params={"resolucion": "1p00", "niveles_intermedios": True})
        self.assertIn("1,00°", s.validate(job))
        job.params["solo_0p25"] = True
        self.assertIsNone(s.validate(job))
        self.assertEqual(s.download_resolution(job.params), "0p25")
        self.assertIn("filter_gfs_0p25.pl", s.build_requests(job, 6)[0].url)
        self.assertEqual(s.default_basename(job), "gfs_20261014_06z_1p00_desde_0p25")
        # Suavizado fuerza la bajada a 0,25°
        job = _job(params={"resolucion": "0p50", "suavizado": "promedio"})
        self.assertEqual(s.download_resolution(job.params), "0p25")
        self.assertTrue(s.default_basename(job).endswith("_0p50_desde_0p25_suav"))
        self.assertTrue(s.level_enabled(850, {}))
        self.assertFalse(s.level_enabled(275, {}))
        self.assertTrue(s.level_enabled(275, {"niveles_intermedios": True}))

    def test_configuracion(self):
        cfg = {}
        st = source_config(cfg, "gfs")
        self.assertTrue(st["enabled"])
        self.assertEqual(st["params"]["suavizado"], "ninguno")
        set_source_config(cfg, "gfs", enabled=False, params={"resolucion": "1p00", "basura": 1})
        st = source_config(cfg, "gfs")
        self.assertFalse(st["enabled"])
        self.assertEqual(st["params"]["resolucion"], "1p00")
        self.assertNotIn("basura", st["params"])
        self.assertEqual(enabled_sources(cfg), [])
        self.assertIs(get_source("gfs").__class__, GFSSource)
        self.assertIsNone(get_source("nada"))


class TestDescargaGenerica(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = GFSSource()

    def tearDown(self):
        self.tmp.cleanup()

    def test_cache_reintentos_y_procedencia(self):
        llamadas = []

        def fetch(url, headers=None, chunk_cb=None, cancel=None, **kw):
            llamadas.append(url)
            if len(llamadas) == 1:
                raise urllib.error.URLError("corte")          # reintenta
            if chunk_cb:
                chunk_cb(4, 8)
            return b"GRIB" + url[-4:].encode()
        cache = DownloadCache(os.path.join(self.tmp.name, "cache"), max_mb=10, max_days=1)
        job = _job(dest_dir=self.tmp.name)
        eventos = []
        paths = self.src.download(job, progress_cb=lambda *a: eventos.append(a), fetch_fn=fetch,
                                  cache=cache, retry_wait=0)
        self.assertEqual(len(llamadas), 3)                       # 1 fallo + 2 plazos
        self.assertEqual(len(paths), 1)
        self.assertEqual(eventos[-1][2], "Descarga completa")
        self.assertTrue(any("MB" in e[2] for e in eventos))
        prov = read_provenance(paths[0])
        self.assertEqual(prov["fuente"], "gfs")
        self.assertEqual(prov["corrida"], "2026-10-14T06:00Z")
        self.assertEqual(prov["plazos_h"], [6, 9])
        self.assertEqual(prov["resolucion_final"], "0p25")
        # Segunda vez: todo desde caché, sin pedidos
        n = len(llamadas)
        self.src.download(job, fetch_fn=fetch, cache=cache, retry_wait=0)
        self.assertEqual(len(llamadas), n)
        self.assertEqual(len(cache.entries()), 2)

    def test_no_publicado_y_credenciales(self):
        def f404(url, **kw):
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        with self.assertRaises(DownloadError) as cm:
            self.src.download(_job(dest_dir=self.tmp.name), fetch_fn=f404, retry_wait=0)
        self.assertEqual(cm.exception.status, "no_publicado")
        self.assertIn("corrida anterior", str(cm.exception))

        def f403(url, **kw):
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
        with self.assertRaises(DownloadError) as cm:
            self.src.download(_job(dest_dir=self.tmp.name), fetch_fn=f403, retry_wait=0)
        self.assertEqual(cm.exception.status, "credenciales")
        self.assertFalse(os.path.exists(_job(dest_dir=self.tmp.name).file_paths(self.src)[0]))

    def test_sin_red_tras_reintentos(self):
        intentos = []

        def caido(url, **kw):
            intentos.append(url)
            raise urllib.error.URLError("sin red")
        with self.assertRaises(DownloadError) as cm:
            self.src.download(_job(dest_dir=self.tmp.name, steps=[6]), fetch_fn=caido, retry_wait=0)
        self.assertEqual(cm.exception.status, "sin_red")
        self.assertEqual(len(intentos), 3)

    def test_contenido_invalido_y_cancelacion(self):
        with self.assertRaises(DownloadError) as cm:
            self.src.download(_job(dest_dir=self.tmp.name), fetch_fn=lambda url, **k: b"<html>404", retry_wait=0)
        self.assertEqual(cm.exception.status, "contenido")
        with self.assertRaises(DownloadCancelled):
            self.src.download(_job(dest_dir=self.tmp.name), cancel=lambda: True,
                              fetch_fn=lambda url, **k: b"GRIB", retry_wait=0)
        self.assertEqual(check_content(b"CDF\x02xx", "netcdf", "x"), None)
        self.assertEqual(classify_exception(TimeoutError())[0], "sin_red")

    def test_prueba_de_conexion(self):
        ok = self.src.test_connection(fetch_fn=lambda url, headers=None, max_bytes=None, **k: b"GRIBxx")
        self.assertTrue(ok.ok)
        self.assertIn("disponible", ok.message)

        def f404(url, **kw):
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        r = self.src.test_connection(fetch_fn=f404)
        self.assertEqual(r.status, "no_publicado")
        self.assertIn("no publicado", str(r).lower())

        def caido(url, **kw):
            raise urllib.error.URLError("x")
        self.assertEqual(self.src.test_connection(fetch_fn=caido).status, "sin_red")

    def test_fetch_with_retries(self):
        n = {"i": 0}

        def f(url, headers=None, chunk_cb=None, cancel=None):
            n["i"] += 1
            if n["i"] < 3:
                raise urllib.error.HTTPError(url, 503, "busy", {}, None)
            return b"ok"
        self.assertEqual(fetch_with_retries(f, "u", retry_wait=0), b"ok")
        self.assertEqual(n["i"], 3)
        n["i"] = 0

        def f404(url, headers=None, chunk_cb=None, cancel=None):
            n["i"] += 1
            raise urllib.error.HTTPError(url, 404, "nf", {}, None)
        with self.assertRaises(urllib.error.HTTPError):
            fetch_with_retries(f404, "u", retry_wait=0)
        self.assertEqual(n["i"], 1)


class TestCache(unittest.TestCase):
    def test_vencimiento_y_tamano(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            c = DownloadCache(os.path.join(tmp.name, "c"), max_mb=0.00001, max_days=1)
            c.put("a", b"x" * 10)
            c.put("b", b"y" * 10)
            self.assertEqual(c.get("a"), b"x" * 10)
            self.assertIsNone(c.get("otra"))
            c.cleanup()                                   # 20 bytes > 10e-6 MB → borra el más viejo
            self.assertEqual(len(c.entries()), 1)
            p = c.path_for("b")
            os.utime(p, (0, 0))                           # muy viejo → vencido
            self.assertIsNone(c.get("b"))
            c.put("c", b"z")
            self.assertEqual(c.clear(), 1)
        finally:
            tmp.cleanup()


class TestFuenteNueva(unittest.TestCase):
    """Una fuente nueva sólo define sus atributos y build_requests."""

    def test_fuente_minima(self):
        class Demo(Source):
            key, name, model = "demo", "Demo", "modelo demo"
            kind = "superficie"
            flight_levels = True
            cycles = [0, 12]
            file_ext = ".nc"
            expect = "netcdf"
            region_filter = "ninguno"
            params = [Param("res", "Res", "choice", "a", choices=[("a", "A"), ("b", "B")]),
                      Param("n", "N", "int", 3, lo=1, hi=9)]

            def steps(self, params=None):
                return [0, 24, 48]

            def build_requests(self, job, step):
                return [Request(f"http://x/{job.run_date:%Y%m%d}{job.cycle:02d}/{step}.nc",
                                expect="netcdf")]
        d = Demo()
        self.assertEqual(source_label(d), "Demo  ✓ FL")
        self.assertEqual(d.merged_params({"n": 5, "zzz": 1}), {"res": "a", "n": 5})
        job = DownloadJob(dt.date(2026, 1, 1), 12, [24], region=None, dest_dir=".")
        self.assertIsNone(d.validate(job))
        self.assertIn("Ciclo", d.validate(DownloadJob(dt.date(2026, 1, 1), 6, [24])))
        tmp = tempfile.TemporaryDirectory()
        try:
            job.dest_dir = tmp.name
            paths = d.download(job, fetch_fn=lambda url, **k: b"CDF\x02dato", retry_wait=0)
            self.assertTrue(paths[0].endswith("demo_20260101_12z.nc"))
            self.assertEqual(read_provenance(paths[0])["tipo"], "superficie")
        finally:
            tmp.cleanup()


@unittest.skipIf(regrid.ec is None, "eccodes no disponible")
class TestRegrillado(unittest.TestCase):
    def setUp(self):
        from tests.test_grib_reader import _escribir_grib_sintetico
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "f.grib2")
        # 0,25° sintético: 17×13 puntos, lat 0…−3, lon 270…274
        _escribir_grib_sintetico(self.path, steps=(6,), levels=(500,), ni=17, nj=13)

    def tearDown(self):
        self.tmp.cleanup()

    def _escribir_fino(self):
        import eccodes as ec
        lats = np.linspace(0, -3, 13)
        lons = np.linspace(270, 274, 17)
        LON, LAT = np.meshgrid(lons, lats)
        gid = ec.codes_grib_new_from_samples("regular_ll_pl_grib2")
        ec.codes_set(gid, "Ni", 17); ec.codes_set(gid, "Nj", 13)
        ec.codes_set(gid, "latitudeOfFirstGridPointInDegrees", 0.0)
        ec.codes_set(gid, "longitudeOfFirstGridPointInDegrees", 270.0)
        ec.codes_set(gid, "latitudeOfLastGridPointInDegrees", -3.0)
        ec.codes_set(gid, "longitudeOfLastGridPointInDegrees", 274.0)
        ec.codes_set(gid, "iDirectionIncrementInDegrees", 0.25)
        ec.codes_set(gid, "jDirectionIncrementInDegrees", 0.25)
        ec.codes_set(gid, "jScansPositively", 0)
        ec.codes_set_values(gid, (LON - 270.0 + 10.0 * LAT).ravel())   # plano: u = Δlon + 10·lat
        data = ec.codes_get_message(gid)
        ec.codes_release(gid)
        return data

    def test_submuestreo_y_promedio(self):
        data = self._escribir_fino()
        for factor, method, n in ((2, "ninguno", (9, 7)), (4, "ninguno", (5, 4)), (4, "promedio", (5, 4))):
            out = regrid.regrid_grib(data, factor, method)
            p = os.path.join(self.tmp.name, f"r{factor}{method}.grib2")
            open(p, "wb").write(out)
            import eccodes as ec
            gid = ec.codes_new_from_message(out)
            ni, nj = ec.codes_get(gid, "Ni"), ec.codes_get(gid, "Nj")
            di = ec.codes_get(gid, "iDirectionIncrementInDegrees")
            vals = np.asarray(ec.codes_get_double_array(gid, "values")).reshape(nj, ni)
            ec.codes_release(gid)
            self.assertEqual((ni, nj), n, (factor, method))
            self.assertAlmostEqual(di, 0.25 * factor)
            # Campo plano: submuestreo y promedio (lejos del borde) dan el mismo plano
            # punto (lat −1, lon 272) → fila 1 (factor 4) / columna 2: valor 2 − 10
            if factor == 4:
                self.assertAlmostEqual(vals[1, 2], 2.0 - 10.0, places=6)

    def test_promedio_suaviza(self):
        import eccodes as ec
        data = self._escribir_fino()
        gid = ec.codes_new_from_message(data)
        vals = np.asarray(ec.codes_get_double_array(gid, "values")).reshape(13, 17)
        vals[6, 8] += 100.0                                   # un pico en el centro
        ec.codes_set_values(gid, vals.ravel())
        data = ec.codes_get_message(gid)
        ec.codes_release(gid)
        sub = regrid.regrid_grib(data, 2, "ninguno")
        prom = regrid.regrid_grib(data, 2, "promedio")
        g1 = ec.codes_new_from_message(sub); v1 = np.asarray(ec.codes_get_double_array(g1, "values")).reshape(7, 9)
        g2 = ec.codes_new_from_message(prom); v2 = np.asarray(ec.codes_get_double_array(g2, "values")).reshape(7, 9)
        ec.codes_release(g1); ec.codes_release(g2)
        base = 2.0 - 15.0                                                  # Δlon 2 + 10·(−1,5)
        self.assertAlmostEqual(v1[3, 4] - base, 100.0, places=4)   # el submuestreo conserva el pico
        self.assertAlmostEqual(v2[3, 4] - base, 25.0, places=3)    # el promedio lo reparte (peso 1 de 4)

    def test_recorte(self):
        import eccodes as ec
        data = self._escribir_fino()
        out = regrid.crop_grib(data, (-1.0, -2.0, -89.0, -87.0))   # lon 271…273
        gid = ec.codes_new_from_message(out)
        self.assertEqual((ec.codes_get(gid, "Ni"), ec.codes_get(gid, "Nj")), (9, 5))
        self.assertEqual(ec.codes_get(gid, "longitudeOfFirstGridPointInDegrees"), 271.0)
        self.assertEqual(ec.codes_get(gid, "latitudeOfFirstGridPointInDegrees"), -1.0)
        ec.codes_release(gid)
        with self.assertRaises(ValueError):
            regrid.crop_grib(data, (50.0, 40.0, 0.0, 10.0))


class TestCredenciales(unittest.TestCase):
    def test_llavero_en_memoria(self):
        try:
            import keyring
            from keyring.backend import KeyringBackend
        except Exception:
            self.skipTest("sin keyring")
        from app.sources import credentials as cr

        class Mem(KeyringBackend):
            priority = 1
            store = {}

            def get_password(self, service, user):
                return self.store.get((service, user))

            def set_password(self, service, user, pw):
                self.store[(service, user)] = pw

            def delete_password(self, service, user):
                self.store.pop((service, user), None)
        old = keyring.get_keyring()
        keyring.set_keyring(Mem())
        try:
            self.assertTrue(cr.available())
            cr.set("demo", "usuario", "luis")
            cr.set("demo", "token", "abc123")
            self.assertEqual(cr.get("demo", "usuario"), "luis")
            self.assertEqual(cr.get_all("demo")["token"], "abc123")
            self.assertEqual(cr.masked("abc123"), "••••••")
            self.assertEqual(cr.masked(None), "(sin definir)")
            cr.delete("demo")
            self.assertIsNone(cr.get("demo", "usuario"))
            with self.assertRaises(ValueError):
                cr.set("demo", "otro", "x")
        finally:
            keyring.set_keyring(old)


class TestWidgetsDeFuente(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        from app.dialogs import glass_dialog
        glass_dialog._apply_dialog_blur = lambda w: None
        cls.app = QApplication.instance() or QApplication([])

    def test_params_form(self):
        from app.widgets.params_form import ParamsForm
        src = GFSSource()
        f = ParamsForm(src.params, {"resolucion": "1p00", "suavizado": "promedio"})
        v = f.values()
        self.assertEqual(v["resolucion"], "1p00")
        self.assertEqual(v["suavizado"], "promedio")
        self.assertFalse(v["solo_0p25"])
        cambios = []
        f.changed.connect(lambda: cambios.append(1))
        f.widget("solo_0p25").setChecked(True)
        self.assertTrue(f.values()["solo_0p25"])
        self.assertTrue(cambios)
        f.set_values({"resolucion": "0p50"})
        self.assertEqual(f.values()["resolucion"], "0p50")

    def test_dialogo_de_fuente(self):
        from app.dialogs.source_config_dialog import SourceConfigDialog
        from app.dialogs.glass_dialog import GlassDialog
        from app.sources import gfs as gm
        src = GFSSource()
        cfg = {"sources": {"gfs": {"enabled": False, "params": {"resolucion": "0p50"}}}}
        d = SourceConfigDialog(None, src, cfg)
        self.assertIsInstance(d, GlassDialog)
        d.show()
        self.app.processEvents()
        self.assertFalse(d.chk_enabled.isChecked())
        self.assertEqual(d.params()["resolucion"], "0p50")
        d.chk_enabled.setChecked(True)
        # Probar conexión con fetch simulado (hilo)
        old = gm.gfs.fetch
        gm.gfs.fetch = lambda url, headers=None, max_bytes=None, **k: b"GRIBok"
        try:
            d._test()
            for _ in range(100):
                self.app.processEvents()
                if hasattr(d, "last_test"):
                    break
                d._worker.wait(50)
            self.app.processEvents()
        finally:
            gm.gfs.fetch = old
        self.assertTrue(d.last_test.ok)
        self.assertIn("✔", d.lbl_test.text())
        d.accept()
        self.assertTrue(d.enabled())
        d.deleteLater()
        self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
