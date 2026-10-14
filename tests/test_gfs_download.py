# -*- coding: utf-8 -*-
"""Tests del módulo de descarga GFS (sin red): URLs, validación, horas,
última corrida y descarga con un fetch simulado."""
import datetime as dt
import os
import tempfile
import unittest
import urllib.error
import urllib.parse

from app import gfs_download as gfs


def _spec(**kw):
    base = dict(date=dt.date(2026, 10, 13), cycle=12, hours=[6, 9, 12],
                variables=["UGRD", "VGRD", "TMP"], levels=[850, 700, 500],
                resolution="0p25", region=(4.0, -64.0, -90.0, -22.0),
                dest_dir=".", merge=True)
    base.update(kw)
    return gfs.DownloadSpec(**base)


class TestURL(unittest.TestCase):
    def test_url_filtro(self):
        url = gfs.build_url(_spec(), 6)
        self.assertTrue(url.startswith("https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl?"))
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query, keep_blank_values=True)
        self.assertEqual(q["dir"], ["/gfs.20261013/12/atmos"])
        self.assertEqual(q["file"], ["gfs.t12z.pgrb2.0p25.f006"])
        for k in ("var_UGRD", "var_VGRD", "var_TMP", "lev_850_mb", "lev_700_mb", "lev_500_mb"):
            self.assertEqual(q[k], ["on"], k)
        self.assertEqual(q["toplat"], ["4"]); self.assertEqual(q["bottomlat"], ["-64"])
        self.assertEqual(q["leftlon"], ["-90"]); self.assertEqual(q["rightlon"], ["-22"])
        self.assertIn("subregion", q)

    def test_resoluciones_y_global(self):
        url = gfs.build_url(_spec(resolution="0p50", region=None), 120)
        self.assertIn("filter_gfs_0p50.pl", url)
        self.assertIn("gfs.t12z.pgrb2full.0p50.f120", url)
        self.assertNotIn("subregion", url)
        url = gfs.build_url(_spec(resolution="1p00", cycle=0), 0)
        self.assertIn("gfs.t00z.pgrb2.1p00.f000", url)
        self.assertIn("%2F00%2Fatmos", url)


class TestNivelesIntermedios(unittest.TestCase):
    def test_0p25_pide_dos_productos(self):
        s = _spec(levels=[300, 275, 250, 225])
        self.assertEqual(s.extra_levels, [275, 225])
        self.assertEqual(s.main_levels, [300, 250])
        urls = gfs.build_urls(s, 6)
        self.assertEqual(len(urls), 2)
        (u1, t1), (u2, t2) = urls
        self.assertIn("filter_gfs_0p25.pl", u1)
        self.assertEqual(t1, "")
        q1 = urllib.parse.parse_qs(urllib.parse.urlparse(u1).query, keep_blank_values=True)
        self.assertEqual(sorted(k for k in q1 if k.startswith("lev_")), ["lev_250_mb", "lev_300_mb"])
        self.assertIn("filter_gfs_0p25b.pl", u2)
        self.assertIn("gfs.t12z.pgrb2b.0p25.f006", u2)
        self.assertEqual(t2, "niveles intermedios")
        q2 = urllib.parse.parse_qs(urllib.parse.urlparse(u2).query, keep_blank_values=True)
        self.assertEqual(sorted(k for k in q2 if k.startswith("lev_")), ["lev_225_mb", "lev_275_mb"])
        self.assertEqual(q2["toplat"], ["4"])          # misma zona en los dos
        self.assertEqual(gfs.build_url(s, 6), u1)

    def test_0p50_un_solo_producto_con_intermedios(self):
        s = _spec(resolution="0p50", levels=[300, 275])
        urls = gfs.build_urls(s, 6)
        self.assertEqual(len(urls), 1)
        self.assertIn("pgrb2full.0p50", urls[0][0])
        self.assertIn("lev_275_mb=on", urls[0][0])
        self.assertIsNone(s.validate())

    def test_1p00_no_tiene_intermedios(self):
        s = _spec(resolution="1p00", levels=[300, 275])
        self.assertIn("1,00°", s.validate())
        self.assertIsNone(_spec(resolution="1p00", levels=[300]).validate())
        self.assertIn("no ofrece", _spec(levels=[300, 290]).validate())
        self.assertTrue(gfs.extra_levels_available("0p25"))
        self.assertFalse(gfs.extra_levels_available("1p00"))
        self.assertEqual(len(gfs.ALL_LEVELS), 42)
        self.assertEqual(gfs.ALL_LEVELS[:4], [1000, 975, 950, 925])

    def test_descarga_une_los_dos_productos(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            s = _spec(levels=[300, 275], hours=[6, 9], dest_dir=tmp.name)
            pedidas = []

            def fake_fetch(url, chunk_cb=None, cancel=None):
                pedidas.append(url)
                return b"GRIBb" if "pgrb2b" in url else b"GRIBa"
            paths = gfs.download(s, fetch_fn=fake_fetch)
            self.assertEqual(len(pedidas), 4)
            with open(paths[0], "rb") as fh:
                self.assertEqual(fh.read(), b"GRIBaGRIBb" * 2)
        finally:
            tmp.cleanup()


class TestSpec(unittest.TestCase):
    def test_nombre_y_rutas(self):
        s = _spec(dest_dir="/tmp/x")
        self.assertEqual(s.basename, "gfs_20261013_12z_0p25")
        self.assertEqual(s.file_paths(), ["/tmp/x/gfs_20261013_12z_0p25.grib2"])
        s = _spec(dest_dir="/tmp/x", merge=False, basename="mi")
        self.assertEqual([os.path.basename(p) for p in s.file_paths()],
                         ["mi_f006.grib2", "mi_f009.grib2", "mi_f012.grib2"])

    def test_validacion(self):
        self.assertIsNone(_spec().validate())
        self.assertIn("ciclo", _spec(cycle=5).validate().lower())
        self.assertIn("hora", _spec(hours=[]).validate().lower())
        self.assertIn("variable", _spec(variables=[]).validate().lower())
        self.assertIn("nivel", _spec(levels=[]).validate().lower())
        self.assertIn("Latitud", _spec(region=(-64, 4, -90, -22)).validate())
        self.assertIn("Longitud", _spec(region=(4, -64, -90, -90)).validate())
        self.assertIn("inválido", _spec(basename="a/b").validate())
        self.assertEqual(_spec(hours=[12, 6, 6]).hours, [6, 12])

    def test_ultima_corrida(self):
        now = dt.datetime(2026, 10, 13, 15, 0, tzinfo=dt.timezone.utc)
        self.assertEqual(gfs.latest_cycle(now), (dt.date(2026, 10, 13), 6))
        now = dt.datetime(2026, 10, 13, 2, 0, tzinfo=dt.timezone.utc)
        self.assertEqual(gfs.latest_cycle(now), (dt.date(2026, 10, 12), 18))


class TestDescarga(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_une_pasos_y_progreso(self):
        urls = []

        def fake_fetch(url, chunk_cb=None, cancel=None):
            urls.append(url)
            data = b"GRIB" + url.encode()[-20:]
            chunk_cb(len(data), len(data))
            return data

        eventos = []
        s = _spec(dest_dir=self.tmp.name)
        paths = gfs.download(s, progress_cb=lambda *a: eventos.append(a), fetch_fn=fake_fetch)
        self.assertEqual(len(urls), 3)
        self.assertEqual(paths, s.file_paths())
        with open(paths[0], "rb") as fh:
            data = fh.read()
        self.assertEqual(data.count(b"GRIB"), 3)
        self.assertEqual(eventos[-1][3], 1.0)
        self.assertTrue(all(0.0 <= e[3] <= 1.0 for e in eventos))

    def test_archivos_separados(self):
        s = _spec(dest_dir=self.tmp.name, merge=False, hours=[3, 6])
        paths = gfs.download(s, fetch_fn=lambda url, chunk_cb=None, cancel=None: b"GRIBxx")
        self.assertEqual(len(paths), 2)
        self.assertTrue(all(os.path.exists(p) for p in paths))

    def test_respuesta_no_grib(self):
        s = _spec(dest_dir=self.tmp.name)
        with self.assertRaises(gfs.DownloadError) as cm:
            gfs.download(s, fetch_fn=lambda url, chunk_cb=None, cancel=None: b"<html>error</html>")
        self.assertIn("no es un GRIB", str(cm.exception))
        self.assertFalse(os.path.exists(s.file_paths()[0]))   # sin archivo a medias

    def test_404_corrida_no_disponible(self):
        def fetch_404(url, chunk_cb=None, cancel=None):
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        s = _spec(dest_dir=self.tmp.name)
        with self.assertRaises(gfs.DownloadError) as cm:
            gfs.download(s, fetch_fn=fetch_404)
        self.assertIn("404", str(cm.exception))
        self.assertIn("no esté publicad", str(cm.exception))

    def test_cancelacion(self):
        s = _spec(dest_dir=self.tmp.name)
        with self.assertRaises(gfs.DownloadCancelled):
            gfs.download(s, cancel=lambda: True,
                         fetch_fn=lambda url, chunk_cb=None, cancel=None: b"GRIBxx")
        self.assertFalse(os.path.exists(s.file_paths()[0]))

    def test_spec_invalida(self):
        with self.assertRaises(gfs.DownloadError):
            gfs.download(_spec(levels=[], dest_dir=self.tmp.name), fetch_fn=lambda *a, **k: b"GRIB")


if __name__ == "__main__":
    unittest.main()
