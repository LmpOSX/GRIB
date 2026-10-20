# -*- coding: utf-8 -*-
"""Esquema de fuentes: parámetros, corridas, descarga genérica (caché,
reintentos, validación, procedencia), regrillado/recorte local, credenciales
y los widgets/diálogos que se arman solos a partir de una fuente."""
import datetime as dt
import json
import os
import tempfile
import time
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
        now = dt.datetime(2026, 10, 14, 9, 0, tzinfo=dt.timezone.utc)    # 09:00Z → 06Z todavía no (lag 3,5 h)
        self.assertEqual(self.src.latest_run(now), (dt.date(2026, 10, 14), 0))
        now = dt.datetime(2026, 10, 14, 9, 30, tzinfo=dt.timezone.utc)   # 09:30Z → 06Z ya empezó
        self.assertEqual(self.src.latest_run(now), (dt.date(2026, 10, 14), 6))
        now = dt.datetime(2026, 10, 14, 15, 33, tzinfo=dt.timezone.utc)  # 15:33Z → 12Z (el caso del usuario)
        self.assertEqual(self.src.latest_run(now), (dt.date(2026, 10, 14), 12))
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
        self.assertNotIn("gfs", [x.key for x in enabled_sources(cfg)])
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
            old = time.time() - 60                        # "a" es la más vieja (misma marca en fs rápidos)
            os.utime(c.path_for("a"), (old, old))
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

            def steps(self, params=None, cycle=None):
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


# ═══════════════════════════ Etapa 2: fuentes nuevas ═══════════════════════════

class TestWAFS(unittest.TestCase):
    def setUp(self):
        from app.sources.wafs import WAFSSource
        self.src = WAFSSource()
        self.src._creds = {"token": "CLAVE"}

    def test_descripcion(self):
        s = self.src
        self.assertTrue(s.flight_levels and s.needs_credentials)
        self.assertIn("✓ FL", source_label(s))
        self.assertEqual(s.auth_kinds, ["token"])
        self.assertEqual(len(s.levels), 56)
        self.assertAlmostEqual(s.levels[0], 843.1, delta=0.1)      # FL050
        self.assertAlmostEqual(s.viewer_levels[6], 300.9, delta=0.1)  # F300
        steps = s.steps()
        self.assertEqual(steps[:3], [6, 7, 8]); self.assertIn(27, steps); self.assertNotIn(28, steps)
        self.assertIn(120, steps); self.assertNotIn(121, steps)

    def test_agrupamiento_y_pedidos(self):
        from app.sources.wafs import bundle_for
        self.assertEqual(bundle_for(6), (6, 8)); self.assertEqual(bundle_for(8), (6, 8))
        self.assertEqual(bundle_for(9), (9, 11)); self.assertEqual(bundle_for(24), (24, 26))
        self.assertEqual(bundle_for(27), (27, 33)); self.assertEqual(bundle_for(48), (45, 51))
        self.assertEqual(bundle_for(54), (54, 66)); self.assertEqual(bundle_for(120), (108, 120))
        job = _job(variables=["UV", "T"], levels=[300.9], steps=[6, 7])
        reqs = self.src.build_requests(job, 7)
        self.assertEqual(len(reqs), 2)
        self.assertTrue(reqs[0].url.endswith("kwbc_wafs_windtempgeo_0p25/items/YUVDYG006_008FLALL"))
        self.assertTrue(reqs[1].url.endswith("/items/YTDYG006_008FLALL"))
        self.assertEqual(reqs[0].headers["X-API-Key"], "CLAVE")
        # Londres
        job.params = {"centro": "egrr"}
        self.assertIn("egrr_wafs", self.src.build_requests(job, 6)[0].url)

    def test_sin_clave(self):
        self.src._creds = {}
        import shutil
        from app.sources import credentials as cr
        old = cr.get_all
        cr.get_all = lambda key: {"usuario": None, "clave": None, "token": None}
        try:
            with self.assertRaises(DownloadError) as cm:
                self.src.build_requests(_job(variables=["UV"], levels=[300.9]), 6)
            self.assertEqual(cm.exception.status, "credenciales")
            r = self.src.test_connection(fetch_fn=lambda *a, **k: b"GRIB")
            self.assertEqual(r.status, "credenciales")
        finally:
            cr.get_all = old

    def test_item_json_sigue_el_enlace_y_plazos_compartidos(self):
        pedidos = []

        def fetch(url, headers=None, chunk_cb=None, cancel=None, **kw):
            pedidos.append(url)
            if url.endswith("FLALL"):
                return (b'{"id":"x","links":[{"rel":"self","href":"a"},'
                        b'{"rel":"data","type":"application/x-grib2","href":"https://x/f.grib2"}]}')
            return b"GRIBdatos"
        tmp = tempfile.TemporaryDirectory()
        try:
            job = _job(variables=["UV"], levels=[300.9], steps=[6, 7, 8], dest_dir=tmp.name, region=None)
            # filtro/recorte requieren mensajes GRIB reales: se anulan
            from app.sources import wafs as wm
            old = wm.filter_grib
            wm.filter_grib = lambda data, **k: data
            try:
                paths = self.src.download(job, fetch_fn=fetch, retry_wait=0,
                                          credentials={"token": "CLAVE"})
            finally:
                wm.filter_grib = old
            # Tres plazos en un mismo archivo: un solo ítem (JSON + GRIB), no tres
            self.assertEqual(len(pedidos), 2)
            with open(paths[0], "rb") as fh:
                self.assertEqual(fh.read(), b"GRIBdatos")
        finally:
            tmp.cleanup()


class TestECMWF(unittest.TestCase):
    def test_descripcion_y_pedidos(self):
        from app.sources.ecmwf import ECMWFSource
        s = ECMWFSource()
        self.assertEqual(s.region_filter, "local")
        self.assertEqual(s.steps(cycle=0)[-1], 240); self.assertEqual(s.steps(cycle=6)[-1], 90)
        self.assertIn(150, s.steps(cycle=12)); self.assertNotIn(147, s.steps(cycle=12))
        job = _job(variables=["u", "v", "t"], levels=[300, 250], steps=[6], params={"servidor": "aws"})
        self.assertIsNone(s.validate(job))
        self.assertIn("no ofrece", s.validate(_job(cycle=6, steps=[96], variables=["t"], levels=[300])))
        req = s.build_requests(job, 6)[0]
        self.assertTrue(req.url.startswith("ecmwf-opendata://aws/20261014/06/6?"))
        self.assertIn("levelist=300,250", req.url)
        self.assertEqual(s.default_basename(job), "ecmwf_20261014_06z_0p25")

    def test_fetch_usa_la_libreria(self):
        from app.sources import ecmwf as em
        llamadas = {}

        class FakeClient:
            def __init__(self, source, reintentos, espera):
                llamadas["source"], llamadas["reintentos"], llamadas["espera"] = source, reintentos, espera

            def retrieve(self, **kw):
                llamadas["kw"] = kw
                with open(kw["target"], "wb") as fh:
                    fh.write(b"GRIBecmwf")
        old = em._client
        em._client = FakeClient
        try:
            s = em.ECMWFSource()
            req = s.build_requests(_job(variables=["t"], levels=[500],
                                        params={"servidor": "azure", "reintentos": 7, "espera_s": 12}), 9)[0]
            self.assertNotIn("reintentos", req.url)        # no altera la clave de caché
            data = s.fetch_request(req, None)
        finally:
            em._client = old
        self.assertEqual(data, b"GRIBecmwf")
        self.assertEqual(llamadas["source"], "azure")
        self.assertEqual((llamadas["reintentos"], llamadas["espera"]), (7, 12))
        self.assertEqual((llamadas["kw"]["date"], llamadas["kw"]["time"], llamadas["kw"]["step"]),
                         ("20261014", 6, 9))
        self.assertEqual(llamadas["kw"]["levelist"], [500])

    def test_parametros_de_reintento_por_defecto(self):
        from app.sources.ecmwf import ECMWFSource, DEFAULT_RETRIES, DEFAULT_WAIT_S
        s = ECMWFSource()
        p = s.default_params()
        self.assertEqual((p["reintentos"], p["espera_s"]), (DEFAULT_RETRIES, DEFAULT_WAIT_S))
        self.assertLessEqual(DEFAULT_RETRIES, 20); self.assertLessEqual(DEFAULT_WAIT_S, 60)
        kinds = {q.key: q.kind for q in s.params}
        self.assertEqual((kinds["reintentos"], kinds["espera_s"]), ("int", "int"))

    def test_cliente_real_recibe_la_politica(self):
        try:
            import ecmwf.opendata  # noqa: F401
        except Exception:
            self.skipTest("sin ecmwf-opendata")
        from app.sources import ecmwf as em
        c = em._client("aws", 4, 9)
        self.assertEqual((c.maximum_retries, c.retry_after, c.use_server_retry_after), (4, 9, True))
        import multiurl.retry as R
        self.assertIs(R._logged_sleep, em._cancellable_sleep)

    def test_mensajes_de_reintento_a_texto(self):
        from app.sources.ecmwf import parse_retry_message as f
        self.assertEqual(f("Recovering from HTTP error [503 Slow Down], attempt 1 of 10"),
                         "servidor saturado (503 Slow Down), reintento 1 de 10")
        self.assertEqual(f("Recovering from HTTP error [502 Bad Gateway], attempt 2 of 10"),
                         "error del servidor (502 Bad Gateway), reintento 2 de 10")
        self.assertIn("error de conexión", f("Recovering from connection error [boom], attempt 3 of 10"))
        self.assertEqual(f("Retrying in 30 seconds"), "reintento en 30 s")
        self.assertIsNone(f("Downloading https://x"))

    def test_puente_a_la_ventana_de_avance_y_cancelacion(self):
        import logging
        from app.sources import ecmwf as em
        from app.sources.base import DownloadCancelled
        em._install_hooks()
        estados = []
        with em._retry_context(estados.append, lambda: False):
            logging.getLogger("multiurl.retry").warning(
                "Recovering from HTTP error [%s %s], attempt %s of %s", 503, "Slow Down", 1, 10)
            em._cancellable_sleep(0.05)
        self.assertEqual(estados[0], "servidor saturado (503 Slow Down), reintento 1 de 10")
        self.assertTrue(any(e.startswith("servidor saturado: reintento en") for e in estados[1:]))
        # Fuera del contexto no molesta
        logging.getLogger("multiurl.retry").warning("Retrying in 120 seconds")
        self.assertEqual(len([e for e in estados if "120" in e]), 0)
        # Cancelar corta la espera enseguida
        import time
        t0 = time.monotonic()
        with em._retry_context(None, lambda: True):
            with self.assertRaises(DownloadCancelled):
                em._cancellable_sleep(30)
        self.assertLess(time.monotonic() - t0, 2)

    def test_saturacion_persistente_explica(self):
        from app.sources import ecmwf as em
        from app.sources.base import DownloadError, DownloadCancelled

        class Saturado:
            def __init__(self, *a):
                pass

            def retrieve(self, **kw):
                raise RuntimeError("503 Server Error: Slow Down for url: https://x")

        class Cancelado(Saturado):
            def retrieve(self, **kw):
                raise DownloadCancelled()
        old = em._client
        s = em.ECMWFSource()
        req = s.build_requests(_job(variables=["t"], levels=[500]), 6)[0]
        try:
            em._client = Saturado
            with self.assertRaises(DownloadError) as cm:
                s.fetch_request(req, None)
            self.assertIn("saturado", str(cm.exception)); self.assertIn("10 reintentos", str(cm.exception))
            em._client = Cancelado
            with self.assertRaises(DownloadCancelled):
                s.fetch_request(req, None)
        finally:
            em._client = old

    def test_descarga_muestra_los_reintentos(self):
        """El texto que emite la librería llega al progress_cb de la descarga."""
        from app.sources import ecmwf as em
        import logging

        class Lento:
            def __init__(self, *a):
                pass

            def retrieve(self, **kw):
                logging.getLogger("multiurl.retry").warning(
                    "Recovering from HTTP error [503 Slow Down], attempt 1 of 10")
                with open(kw["target"], "wb") as fh:
                    fh.write(b"GRIB" + b"\0" * 60)
        old = em._client
        tmp = tempfile.TemporaryDirectory()
        mensajes = []
        try:
            em._client = Lento
            s = em.ECMWFSource()
            job = _job(variables=["t"], levels=[500], steps=[6], dest_dir=tmp.name, region=None)
            s.download(job, progress_cb=lambda i, n, msg, frac: mensajes.append(msg),
                       write_provenance=False)
        except Exception:
            pass
        finally:
            em._client = old
            tmp.cleanup()
        self.assertTrue(any("servidor saturado (503 Slow Down), reintento 1 de 10" in m for m in mensajes),
                        mensajes)


class TestSMN(unittest.TestCase):
    def test_descripcion_y_pedidos(self):
        from app.sources.smn import SMNSource
        s = SMNSource()
        self.assertEqual(s.kind, "superficie")
        self.assertEqual(s.levels, [])
        self.assertEqual(s.steps()[-1], 72)
        job = DownloadJob(dt.date(2026, 10, 14), 6, [6], ["viento10", "T2"], [], (-30, -40, -70, -55), ".")
        self.assertIsNone(s.validate(job))
        req = s.build_requests(job, 6)[0]
        self.assertEqual(req.url, "https://smn-ar-wrf.s3.amazonaws.com/DATA/WRF/DET/2026/10/14/06/"
                                  "WRFDETAR_01H_20261014_06_006.nc")
        self.assertEqual(req.expect, "netcdf")

    @unittest.skipIf(regrid.ec is None, "eccodes no disponible")
    def test_conversion_netcdf_sintetico(self):
        try:
            import netCDF4
        except Exception:
            self.skipTest("sin netCDF4")
        from app.netcdf_convert import smn_wrf_to_grib, bin_regrid
        from app.grib_reader import GribReader
        tmp = tempfile.TemporaryDirectory()
        try:
            p = os.path.join(tmp.name, "s.nc")
            ds = netCDF4.Dataset(p, "w")
            ny, nx = 40, 30
            ds.createDimension("time", 1); ds.createDimension("y", ny); ds.createDimension("x", nx)
            t = ds.createVariable("time", "f8", ("time",)); t.units = "hours since 2026-10-14 06:00:00"; t[:] = [6.0]
            # grilla "Lambert" sintética: lat/lon 2D levemente rotadas, paso ~0,04°
            jj, ii = np.mgrid[0:ny, 0:nx]
            lat = ds.createVariable("lat", "f4", ("y", "x")); lon = ds.createVariable("lon", "f4", ("y", "x"))
            lat[:] = -40.0 + 0.04 * jj + 0.002 * ii
            lon[:] = -65.0 + 0.04 * ii - 0.002 * jj
            for name, val in (("magViento10", 10.0), ("dirViento10", 270.0), ("T2", 20.0), ("HR2", 50.0)):
                v = ds.createVariable(name, "f4", ("time", "y", "x")); v[:] = val
            ds.variables["T2"].units = "degree_Celsius"
            ds.close()
            data = open(p, "rb").read()
            out, info = smn_wrf_to_grib(data, region=None, res_deg=0.04, variables=("viento10", "T2", "HR2"))
            g = os.path.join(tmp.name, "s.grib2"); open(g, "wb").write(out)
            r = GribReader(g)
            self.assertEqual(r.kind, "superficie")
            self.assertTrue(r.has_surface)
            self.assertEqual(r.variables, ["u", "v", "t"])
            self.assertEqual(r.steps[0].step_range, "6")
            self.assertEqual(r.run_time(), dt.datetime(2026, 10, 14, 6, tzinfo=dt.timezone.utc))
            u, v, tt, inf = r.get_surface_fields(0)
            self.assertEqual(inf["mode"], "superficie")
            # viento de 270° a 10 m/s → u = +10, v ≈ 0; T 20 °C → 293,15 K
            self.assertAlmostEqual(float(np.nanmedian(u)), 10.0, places=3)
            self.assertAlmostEqual(float(np.nanmedian(v)), 0.0, places=3)
            self.assertAlmostEqual(float(np.nanmedian(tt)), 293.15, places=3)
            self.assertLess(np.isnan(u).mean(), 0.2)
            # Zona fuera del dominio
            with self.assertRaises(ValueError):
                smn_wrf_to_grib(data, region=(10, 0, 0, 10))
            # bin_regrid con un hueco se rellena
            lat1d = np.arange(-40, -38.4, 0.04); lon1d = np.arange(-65, -63.8, 0.04)
            f = np.full((ny, nx), 5.0); f[10, 10] = np.nan
            out2 = bin_regrid(np.asarray(netCDF4.Dataset(p).variables["lat"][:]), np.asarray(netCDF4.Dataset(p).variables["lon"][:]), f, lat1d, lon1d)
            self.assertFalse(np.isnan(out2[5:30, 5:25]).any())
        finally:
            tmp.cleanup()


@unittest.skipIf(regrid.ec is None, "eccodes no disponible")
class TestICON(unittest.TestCase):
    def test_descripcion_y_pedidos(self):
        from app.sources.icon import IconSource
        s = IconSource()
        self.assertEqual(s.steps(cycle=0)[-1], 180); self.assertEqual(s.steps(cycle=6)[-1], 120)
        self.assertIn(78, s.steps()); self.assertNotIn(79, s.steps()); self.assertIn(81, s.steps())
        self.assertEqual(len(s.available_runs()), 4)
        job = _job(variables=["U", "T"], levels=[500, 300], steps=[6])
        reqs = s.build_requests(job, 6)
        self.assertEqual(len(reqs), 4)
        self.assertEqual(reqs[0].url, "https://opendata.dwd.de/weather/nwp/icon/grib/06/u/"
                                      "icon_global_icosahedral_pressure-level_2026101406_006_500_U.grib2.bz2")
        self.assertIn("/t/", reqs[2].url)

    def test_regrillado_con_pesos_sinteticos(self):
        import bz2
        import eccodes as ec
        from app.sources import icon as ic
        from app.grib_reader import GribReader
        # "Icosaédrica" sintética de 12 celdas con valor = índice; destino 4x3
        ni, nj = 4, 3
        index = np.array([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11])
        weights = {"ni": ni, "nj": nj, "index": index,
                   "lat1d": np.array([-10.0, 0.0, 10.0]), "lon1d": np.array([0.0, 90.0, 180.0, 270.0])}
        gid = ec.codes_grib_new_from_samples("regular_ll_pl_grib2")
        ec.codes_set(gid, "Ni", 12); ec.codes_set(gid, "Nj", 1)
        ec.codes_set(gid, "typeOfLevel", "isobaricInhPa"); ec.codes_set(gid, "level", 300)
        ec.codes_set(gid, "dataDate", 20261014); ec.codes_set(gid, "dataTime", 600)
        ec.codes_set(gid, "stepUnits", "m"); ec.codes_set(gid, "forecastTime", 360)
        ec.codes_set(gid, "discipline", 0); ec.codes_set(gid, "parameterCategory", 2); ec.codes_set(gid, "parameterNumber", 2)
        ec.codes_set_values(gid, np.arange(12, dtype=float))
        src = ec.codes_get_message(gid); ec.codes_release(gid)
        out = ic.icosahedral_to_latlon(src, weights)
        tmp = tempfile.TemporaryDirectory()
        try:
            p = os.path.join(tmp.name, "r.grib2"); open(p, "wb").write(out)
            r = GribReader(p)
            self.assertEqual((r.grid["ni"], r.grid["nj"]), (4, 3))
            self.assertEqual(r.steps[0].step_range, "6")
            self.assertEqual(r.levels, [300.0])
            u = r.get_field(0, "u", 300.0)
            # lon 0..270 → normalizadas −180..90: columnas reordenadas (180→−180, 270→−90, 0, 90)
            self.assertEqual(list(r.lons), [-180.0, -90.0, 0.0, 90.0])
            self.assertEqual(list(u[0]), [2.0, 3.0, 0.0, 1.0])
            # fetch_request descomprime bz2 y la prueba de conexión acepta el comienzo de un bz2
            s = ic.IconSource()
            data = s.fetch_request(Request("https://x/a.grib2.bz2"), lambda url, headers=None, chunk_cb=None, cancel=None: bz2.compress(b"GRIBxx"))
            self.assertEqual(data, b"GRIBxx")
            data = s.fetch_request(Request("https://x/a.grib2.bz2"), lambda url, headers=None, max_bytes=None: b"BZh91AY", max_bytes=10)
            self.assertEqual(data, b"GRIB")
        finally:
            tmp.cleanup()


class TestGenerica(unittest.TestCase):
    def test_plantilla_y_listas(self):
        from app.sources.generic import expand_template, parse_int_list, GenericSource
        d = dt.date(2026, 10, 14)
        self.assertEqual(expand_template("http://h/{YYYYMMDD}/{HH}/m_{YYYYMMDDHH}_f{FFF}_{FF}.grib2", d, 6, 9),
                         "http://h/20261014/06/m_2026101406_f009_09.grib2")
        self.assertEqual(expand_template("ftp://h/{date:%Y}/{cycle:02d}/{step:03d}", d, 0, 120), "ftp://h/2026/00/120")
        self.assertEqual(parse_int_list("0,6,12", []), [0, 6, 12])
        self.assertEqual(parse_int_list("6-18/6", []), [6, 12, 18])
        self.assertEqual(parse_int_list("", [1, 2]), [1, 2])
        s = GenericSource()
        job = DownloadJob(d, 6, [6], [], [], None, ".", params={"plantilla": "sin esquema", "ciclos": "0,6"})
        self.assertIn("http://", s.validate(job))
        job.params["plantilla"] = "https://h/{FFF}.grib2"
        self.assertIsNone(s.validate(job))
        self.assertIn("Ciclo", s.validate(DownloadJob(d, 12, [6], [], [], None, ".", params=job.params)))
        self.assertTrue(s.build_requests(job, 6)[0].url.endswith("/006.grib2"))

    def test_http_con_autenticacion_basica(self):
        """Servidor HTTP local que exige usuario/clave: la fuente baja con las
        credenciales y recorta nada (GRIB mínimo falso con recorte apagado)."""
        import base64
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from app.sources.generic import GenericSource
        token = base64.b64encode(b"luis:secreta").decode()

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.headers.get("Authorization") != "Basic " + token:
                    self.send_response(401); self.end_headers(); return
                if not self.path.endswith("/f006.grib2"):
                    self.send_response(404); self.end_headers(); return
                body = b"GRIBfalso"
                self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers()
                self.wfile.write(body)
        srv = HTTPServer(("127.0.0.1", 0), H)
        th = threading.Thread(target=srv.serve_forever, daemon=True); th.start()
        tmp = tempfile.TemporaryDirectory()
        try:
            port = srv.server_address[1]
            s = GenericSource()
            params = {"plantilla": f"http://127.0.0.1:{port}/{{YYYYMMDD}}/f{{FFF}}.grib2", "ciclos": "0,6,12,18",
                      "plazos": "6,12", "formato": "grib", "recortar": False}
            job = DownloadJob(dt.date(2026, 10, 14), 6, [6], [], [], None, tmp.name, params=params)
            # Sin credenciales: 401 → credenciales
            with self.assertRaises(DownloadError) as cm:
                s.download(job, retry_wait=0, credentials={"auth": "ninguna"})
            self.assertEqual(cm.exception.status, "credenciales")
            paths = s.download(job, retry_wait=0, credentials={"auth": "usuario", "usuario": "luis", "clave": "secreta"})
            self.assertEqual(open(paths[0], "rb").read(), b"GRIBfalso")
            self.assertEqual(read_provenance(paths[0])["formato"], "grib")
            # Plazo inexistente → no publicado
            job2 = DownloadJob(dt.date(2026, 10, 14), 6, [12], [], [], None, tmp.name, params=params)
            with self.assertRaises(DownloadError) as cm:
                s.download(job2, retry_wait=0, credentials={"auth": "usuario", "usuario": "luis", "clave": "secreta"})
            self.assertEqual(cm.exception.status, "no_publicado")
            # Probar conexión (última corrida → plazo 6)
            r = s.test_connection(params, credentials={"auth": "usuario", "usuario": "luis", "clave": "secreta"})
            self.assertTrue(r.ok, r)
            r = s.test_connection(params, credentials={"auth": "token", "token": "x"})
            self.assertEqual(r.status, "credenciales")
        finally:
            srv.shutdown(); tmp.cleanup()

    def test_transportes(self):
        from app.sources.transport import auth_headers, fetch_any
        self.assertEqual(auth_headers("token", {"token": "abc"}), {"Authorization": "Bearer abc"})
        self.assertTrue(auth_headers("usuario", {"usuario": "a", "clave": "b"})["Authorization"].startswith("Basic "))
        self.assertEqual(auth_headers("ninguna", {"token": "abc"}), {})
        with self.assertRaises(ValueError):
            fetch_any("gopher://x")


class TestRegistroEtapa2(unittest.TestCase):
    def test_registro(self):
        from app.sources import SOURCES
        keys = [s.key for s in SOURCES]
        self.assertEqual(keys, ["gfs", "wafs", "ecmwf", "icon", "smn_wrf", "generica"])
        cfg = {}
        habilitadas = [s.key for s in enabled_sources(cfg)]
        self.assertNotIn("wafs", habilitadas); self.assertNotIn("generica", habilitadas)
        self.assertIn("ecmwf", habilitadas)
        # Las de superficie no mezclan niveles
        self.assertEqual([s.key for s in SOURCES if s.kind == "superficie"], ["smn_wrf"])
