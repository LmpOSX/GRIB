# -*- coding: utf-8 -*-
"""Viento como U/V o como dirección y velocidad (WDIR/WIND): fórmulas,
conversión de archivos, lectura en el visor y conversión a WAFS."""
import os
import tempfile
import unittest

import numpy as np

from app import wind_format as wfm
from app import wafs_format as wf
from app.grib_reader import GribReader

try:
    import pyproj  # noqa: F401
    import eccodes as ec
except Exception:  # pragma: no cover
    ec = None

if ec is not None:
    from tests.test_wafs import _grib, _messages


def _short_names(data):
    out = []
    for gid, _pos, _size in wf.iter_messages(data):
        try:
            out.append(ec.codes_get(gid, "shortName"))
        finally:
            ec.codes_release(gid)
    return out


class TestFormulas(unittest.TestCase):
    def test_direccion_meteorologica(self):
        d, s = wfm.uv_to_dirspeed(0.0, -10.0)       # viento del norte
        self.assertAlmostEqual(float(d), 360.0 % 360.0)
        self.assertAlmostEqual(float(s), 10.0)
        d, s = wfm.uv_to_dirspeed(-10.0, 0.0)       # del este
        self.assertAlmostEqual(float(d), 90.0)
        d, s = wfm.uv_to_dirspeed(10.0, 10.0)       # hacia el NE → del SO
        self.assertAlmostEqual(float(d), 225.0)
        self.assertAlmostEqual(float(s), np.hypot(10, 10))
        d, _s = wfm.uv_to_dirspeed(0.0, 0.0)        # calma: 0, no NaN
        self.assertEqual(float(d), 0.0)

    def test_ida_y_vuelta(self):
        rng = np.random.default_rng(1)
        u = rng.normal(0, 20, 200)
        v = rng.normal(0, 20, 200)
        d, s = wfm.uv_to_dirspeed(u, v)
        self.assertTrue(np.all((d >= 0) & (d < 360)))
        u2, v2 = wfm.dirspeed_to_uv(d, s)
        np.testing.assert_allclose(u2, u, atol=1e-9)
        np.testing.assert_allclose(v2, v, atol=1e-9)


@unittest.skipIf(ec is None, "sin eccodes")
class TestConversionDeArchivos(unittest.TestCase):
    def test_uv_a_dirvel_y_vuelta(self):
        data = _grib([850, 500, 300], steps=(6, 9))
        self.assertEqual(wfm.detect(data), "uv")
        ds, info = wfm.convert(data, "dirspeed")
        self.assertEqual(info["viento"], "dirspeed")
        self.assertEqual(info["pares"], 6)                 # 3 niveles × 2 plazos
        self.assertEqual(wfm.detect(ds), "dirspeed")
        names = _short_names(ds)
        self.assertEqual(names.count("wdir"), 6)
        self.assertEqual(names.count("ws"), 6)
        self.assertEqual(names.count("t"), 6)              # la temperatura pasa tal cual
        self.assertEqual(len(names), len(_short_names(data)))
        # Mismo orden: donde había u hay wdir, donde había v hay ws
        orig = _short_names(data)
        self.assertEqual([{"u": "wdir", "v": "ws"}.get(n, n) for n in orig], names)
        # Valores: dirección y velocidad de los U/V originales
        src = {(n, pa, st): vals for n, pa, st, vals in _messages(data)}
        for n, pa, st, vals in _messages(ds):
            if n == "ws":
                np.testing.assert_allclose(vals, np.hypot(src[("u", pa, st)], src[("v", pa, st)]), atol=0.02)
            elif n == "wdir":
                d, _s = wfm.uv_to_dirspeed(src[("u", pa, st)], src[("v", pa, st)])
                np.testing.assert_allclose(vals, d, atol=0.02)
        # Y de vuelta a U/V, con los valores originales (a la precisión del empaquetado)
        back, info = wfm.convert(ds, "uv")
        self.assertEqual(info["pares"], 6)
        self.assertEqual(_short_names(back), orig)
        for n, pa, st, vals in _messages(back):
            np.testing.assert_allclose(vals, src[(n, pa, st)], atol=0.05)
        # Convertir al formato que ya tiene no toca nada
        same, info = wfm.convert(ds, "dirspeed")
        self.assertEqual(info["pares"], 0)
        self.assertEqual(same, ds)

    def test_sin_viento_o_sin_par(self):
        solo_t = _grib([500], variables=("t",))
        self.assertIsNone(wfm.detect(solo_t))
        out, info = wfm.convert(solo_t, "dirspeed")
        self.assertEqual(out, solo_t)
        solo_u = _grib([500], variables=("u", "t"))
        out, info = wfm.convert(solo_u, "dirspeed")
        self.assertEqual(info["sin_par"], 1)
        self.assertEqual(out, solo_u)

    def test_el_visor_lee_dirvel_como_uv(self):
        data = _grib([850, 700, 500, 300, 200], steps=(6,))
        ds, _ = wfm.convert(data, "dirspeed")
        with tempfile.TemporaryDirectory() as tmp:
            p_uv = os.path.join(tmp, "uv.grib2")
            p_ds = os.path.join(tmp, "ds.grib2")
            open(p_uv, "wb").write(data)
            open(p_ds, "wb").write(ds)
            r_uv = GribReader(p_uv)
            r_ds = GribReader(p_ds)
            self.assertEqual(r_uv.wind_format, "uv")
            self.assertEqual(r_ds.wind_format, "dirspeed")
            self.assertEqual(r_ds.variables, ["u", "v", "t"])
            self.assertEqual(r_ds.levels, r_uv.levels)
            self.assertEqual(r_ds.levels_for(0, "u"), r_uv.levels_for(0, "u"))
            for lv in r_uv.levels:
                u1, v1, t1, _ = r_uv.get_level_fields(0, lv)
                u2, v2, t2, _ = r_ds.get_level_fields(0, lv)
                np.testing.assert_allclose(u2, u1, atol=0.05)
                np.testing.assert_allclose(v2, v1, atol=0.05)
                np.testing.assert_allclose(t2, t1, atol=1e-6)
            self.assertIn("VIENTO: dirección y velocidad", r_ds.inventory_text())
            self.assertNotIn("VIENTO:", r_uv.inventory_text())

    def test_convertir_a_wafs_conserva_el_formato(self):
        data = _grib([1000, 850, 700, 500, 400, 300, 250, 200, 150, 100], steps=(6,))
        ds, _ = wfm.convert(data, "dirspeed")
        res = wf.convert_to_wafs(ds, mode="OACI")
        self.assertGreater(res.info["mensajes"], 0)
        self.assertEqual(res.info.get("viento"), "dirspeed")
        self.assertEqual(wfm.detect(res.data), "dirspeed")
        # Y el contenido coincide con convertir el U/V y pasar a dir/vel al final
        ref = wf.convert_to_wafs(data, mode="OACI").data
        ref_ds, _ = wfm.convert(ref, "dirspeed")
        a = {(n, pa, st): vals for n, pa, st, vals in _messages(res.data)}
        b = {(n, pa, st): vals for n, pa, st, vals in _messages(ref_ds)}
        self.assertEqual(set(a), set(b))
        for k in a:
            tol = 0.3 if k[0] == "wdir" else 0.05
            np.testing.assert_allclose(a[k], b[k], atol=tol)
        # El validador avisa que el WAFS operativo lleva U/V, pero no bloquea
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "ds_wafs.grib2")
            open(p, "wb").write(res.data)
            val = wf.validate_wafs(p)
            self.assertTrue(any("WDIR" in a_ or "dirección" in a_ for a_ in val["avisos"]))
            self.assertFalse(any("no es una variable WAFS" in a_ for a_ in val["avisos"]))


@unittest.skipIf(ec is None, "sin eccodes")
class TestDescargaDirVel(unittest.TestCase):
    """«Viento en el archivo: dirección y velocidad» en la descarga: el GFS
    baja U/V y al final cada par se reemplaza por WDIR/WIND; la procedencia
    y el nombre lo registran."""

    def test_descarga_convierte_el_viento(self):
        import datetime as dt
        from app.sources import GFSSource, DownloadJob
        from app.sources.base import read_provenance
        src = GFSSource()
        grib = _grib([850, 700, 500, 300, 200], steps=(6,))
        with tempfile.TemporaryDirectory() as tmp:
            for fmt, expect, suffix in (("dirspeed", "dirspeed", "_dirvel"), ("uv", "uv", "")):
                job = DownloadJob(run_date=dt.date(2026, 10, 14), cycle=6, steps=[6],
                                  variables=["UGRD", "VGRD", "TMP"], levels=[850, 700, 500, 300, 200],
                                  region=None, dest_dir=tmp, merge=True, params={},
                                  wind_format=fmt, suffix=suffix)
                paths = src.download(job, fetch_fn=lambda url, **k: grib, retry_wait=0)
                self.assertEqual(len(paths), 1)
                self.assertTrue(paths[0].endswith(suffix + ".grib2"), paths[0])
                self.assertEqual(wfm.detect(open(paths[0], "rb").read()), expect)
                prov = read_provenance(paths[0])
                self.assertEqual(prov["viento"], fmt)
                r = GribReader(paths[0])
                self.assertEqual(r.wind_format, expect)
                self.assertEqual(r.variables, ["u", "v", "t"])


if __name__ == "__main__":
    unittest.main()
