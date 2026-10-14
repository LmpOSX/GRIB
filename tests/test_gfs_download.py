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
        self.assertIn("no esté publicada", str(cm.exception))

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
