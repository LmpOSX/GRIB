# -*- coding: utf-8 -*-
"""Áreas de descarga por FIR (app/areas.py y su integración): coordenadas,
envolvente con una, varias y todas las FIR, margen, validación de rangos,
polo y cruce de Greenwich (pedido al servidor y recorte local), ida y
vuelta de exportar/importar la tabla, nombre y procedencia de la descarga,
bloque Área del diálogo, pestaña de Preferencias y rectángulos en el mapa.
"""
import datetime as dt
import json
import os
import tempfile
import unittest
from urllib.parse import urlparse, parse_qs

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from app import areas as A  # noqa: E402
from app import config  # noqa: E402
from app.dialogs import glass_dialog  # noqa: E402
from app.sources import DownloadJob, GFSSource, read_provenance  # noqa: E402

glass_dialog._apply_dialog_blur = lambda w: None
_app = QApplication.instance() or QApplication([])


def _areas(*codes):
    table = A.default_areas()
    return [a for a in table if a.code in codes] if codes else table


# ── Coordenadas ──────────────────────────────────────────────────────────────

class TestCoordenadas(unittest.TestCase):
    def test_formatos_aceptados(self):
        p = A.parse_coord
        self.assertAlmostEqual(p("-34.03", "lat"), -34.03)
        self.assertAlmostEqual(p("34,03", "lat"), 34.03)
        self.assertAlmostEqual(p("22°15'S", "lat"), -22.25)
        self.assertAlmostEqual(p("06240W", "lon"), -62.0 - 40 / 60)
        self.assertAlmostEqual(p("2215S", "lat"), -22.25)
        self.assertAlmostEqual(p("221530S", "lat"), -(22 + 15 / 60 + 30 / 3600))
        self.assertAlmostEqual(p("062°40'15\"W", "lon"), -(62 + 40 / 60 + 15 / 3600))
        self.assertAlmostEqual(p("34°01.8'S", "lat"), -34.03)
        self.assertAlmostEqual(p("22 15 30 S", "lat"), -(22 + 15 / 60 + 30 / 3600))
        self.assertAlmostEqual(p("S2215", "lat"), -22.25)
        self.assertAlmostEqual(p("10.5E", "lon"), 10.5)
        self.assertAlmostEqual(p("10.5O", "lon"), -10.5)       # O = oeste
        self.assertAlmostEqual(p("-90", "lat"), -90.0)
        for bad, kind in (("", "lat"), ("abc", "lat"), ("95", "lat"), ("22°15'W", "lat"),
                          ("-22S", "lat"), ("181", "lon"), ("2275S", "lat")):
            with self.assertRaises(A.CoordError, msg=bad):
                p(bad, kind)

    def test_formato_de_salida(self):
        self.assertEqual(A.format_coord(-34.03, "lat"), "-34.03")
        self.assertEqual(A.format_coord(-34.03, "lat", "gm"), "34°01.8'S")
        self.assertEqual(A.format_coord(-62.6667, "lon", "gm"), "062°40.0'W")
        self.assertEqual(A.format_coord(10.0, "lon", "gm"), "010°00.0'E")
        self.assertEqual(A.format_coord(-90.0, "lat", "gm"), "90°00.0'S")
        # ida y vuelta
        for v in (-34.03, -62.67, -10.0, 0.0, 45.5):
            kind = "lat" if abs(v) <= 90 else "lon"
            self.assertAlmostEqual(A.parse_coord(A.format_coord(v, kind, "gm"), kind), v, places=2)
            self.assertAlmostEqual(A.parse_coord(A.format_coord(v, kind), kind), v, places=2)


# ── Envolvente, margen y validación ──────────────────────────────────────────

class TestEnvolvente(unittest.TestCase):
    def test_una_fir(self):
        self.assertEqual(A.envelope(_areas("SAEF")), (-30.22, -46.0, -71.85, -10.0))
        self.assertEqual(A.envelope(_areas("SAEF"), 1.0), (-29.22, -47.0, -72.85, -9.0))

    def test_varias(self):
        env = A.envelope(_areas("SAEF", "SACF"))
        self.assertEqual(env, (-21.72, -46.0, -71.85, -10.0))
        env = A.envelope(_areas("SAEF", "SACF"), 1.0)
        self.assertEqual(env, (-20.72, -47.0, -72.85, -9.0))
        self.assertEqual(A.envelope(_areas("SARR", "SAMF")), (-22.25, -38.5, -71.21, -53.67))

    def test_todas_y_vacio(self):
        env = A.envelope(_areas())
        self.assertEqual(env, (-21.72, -90.0, -73.57, -10.0))
        self.assertIsNone(A.envelope([]))

    def test_margen_no_sale_de_rango(self):
        env = A.envelope(_areas("SAVF"), 1.0)
        self.assertEqual(env[1], -90.0)          # el polo no se pasa
        a = A.Area("X", "x", 89.5, -89.5, -179.5, 179.5)
        self.assertEqual(A.envelope([a], 2.0), (90.0, -90.0, -180.0, 180.0))
        self.assertEqual(A.envelope([a], 0.0), (89.5, -89.5, -179.5, 179.5))
        # el margen no se guarda sumado en la tabla
        self.assertEqual(_areas("SAEF")[0].north, -30.22)

    def test_validacion(self):
        self.assertIsNone(A.validate_area(_areas("SAEF")[0]))
        self.assertIn("norte", A.validate_area(A.Area("X", "", -40, -30, -70, -60)))
        self.assertIn("oeste", A.validate_area(A.Area("X", "", -30, -40, -60, -70)))
        self.assertIn("oeste", A.validate_area(A.Area("X", "", -30, -40, -60, -60)))
        self.assertIn("−90", A.validate_area(A.Area("X", "", -30, -95, -70, -60)))
        self.assertIn("Código", A.validate_area(A.Area("TOOLONG", "", -30, -40, -70, -60)))
        self.assertIn("Código", A.validate_area(A.Area("", "", -30, -40, -70, -60)))
        errs = A.validate_areas(_areas() + [_areas("SAEF")[0].copy()])
        self.assertEqual(len(errs), 1)
        self.assertIn("repetido", errs[0])
        self.assertEqual(A.validate_areas(_areas()), [])

    def test_polo_y_greenwich(self):
        env = A.envelope(_areas("SAVF"), 1.0)
        self.assertTrue(A.reaches_pole(env))
        self.assertFalse(A.crosses_greenwich(env))
        cruz = A.Area("TEST", "prueba", 10.0, -10.0, -20.0, 15.0)
        env = A.envelope([cruz], 1.0)
        self.assertEqual(env, (11.0, -11.0, -21.0, 16.0))
        self.assertTrue(A.crosses_greenwich(env))
        self.assertIsNone(A.validate_area(cruz))

    def test_redondeo_hacia_afuera(self):
        self.assertEqual(A.round_outward((-29.22, -47.0, -72.85, -9.0), 0.25), (-29.0, -47.0, -73.0, -9.0))
        self.assertEqual(A.round_outward((-29.22, -47.0, -72.85, -9.0), 1.0), (-29.0, -47.0, -73.0, -9.0))
        self.assertEqual(A.round_outward((-20.1, -89.9, -0.1, 0.1), 0.5), (-20.0, -90.0, -0.5, 0.5))
        self.assertEqual(A.round_outward((-20.0, -90.0, -73.0, -9.0), 0.25), (-20.0, -90.0, -73.0, -9.0))
        self.assertEqual(A.round_outward((89.9, -89.9, -179.9, 179.9), 0.25), (90.0, -90.0, -180.0, 180.0))
        self.assertEqual(A.round_outward((1.0, 0.0, 0.0, 1.0), None), (1.0, 0.0, 0.0, 1.0))

    def test_tamano_y_estimacion(self):
        s = A.region_size((-29.0, -47.0, -73.0, -9.0), 0.25)
        self.assertEqual((s["nlat"], s["nlon"], s["puntos"]), (73, 257, 73 * 257))
        self.assertAlmostEqual(s["dlat"], 18.0)
        self.assertAlmostEqual(s["dlon"], 64.0)
        self.assertEqual(A.region_size((1.0, 0.0, 0.0, 1.0))["puntos"], None)
        txt = A.describe_size((-29.0, -47.0, -73.0, -9.0), 0.25, n_messages=33)
        self.assertIn("73 × 257", txt)
        self.assertIn("MB", txt)
        self.assertIn("33 campos", txt)
        self.assertIn("desconocida", A.describe_size((1.0, 0.0, 0.0, 1.0), None))
        self.assertEqual(A.estimate_bytes(1000, 2), 2 * (2000 + 200))

    def test_etiqueta(self):
        self.assertEqual(A.area_tag(["SAEF", "SACF"], "fir"), "SAEF+SACF")
        self.assertEqual(A.area_tag([], "fir"), "MANUAL")
        self.assertEqual(A.area_tag(["SAEF"], "manual"), "MANUAL")

    def test_cobertura(self):
        reg = (-29.0, -47.0, -73.0, -9.0)
        self.assertEqual(A.check_coverage(reg, (-73.0, -9.0, -47.0, -29.0)), [])
        self.assertEqual(A.check_coverage(reg, (-80.0, 0.0, -60.0, -20.0)), [])
        faltan = A.check_coverage(reg, (-73.0, -9.5, -46.5, -29.0))
        self.assertEqual(len(faltan), 2)
        self.assertTrue(faltan[0].startswith("sur") and faltan[1].startswith("este"))
        self.assertEqual(A.check_coverage(None, (0, 1, 0, 1)), [])


# ── Tabla: configuración y archivos ──────────────────────────────────────────

class TestTabla(unittest.TestCase):
    def test_config_y_defaults(self):
        self.assertEqual([a.code for a in A.areas_from_config({})], A.ARGENTINA_CODES)
        self.assertEqual([a.code for a in A.areas_from_config({"areas": []})], A.ARGENTINA_CODES)
        self.assertTrue(all(a.verify and a.enabled for a in A.areas_from_config({})))
        cfg = {"areas": A.areas_to_config(_areas("SAEF")) + [{"code": "zz", "name": "Prueba",
                                                                "north": 1, "south": 0, "west": 0,
                                                                "east": 1}]}
        got = A.areas_from_config(cfg)
        self.assertEqual([a.code for a in got], ["SAEF", "ZZ"])
        self.assertEqual(got[1].region, (1.0, 0.0, 0.0, 1.0))
        self.assertFalse(got[1].verify)
        self.assertEqual(A.find_area(got, "saef").name, "Ezeiza")
        self.assertIsNone(A.find_area(got, "XXXX"))

    def test_exportar_importar_json_y_csv(self):
        table = _areas() + [A.Area("SUEO", "Montevideo", -30.0, -40.0, -58.0, -50.0, enabled=False)]
        with tempfile.TemporaryDirectory() as d:
            for ext in ("json", "csv"):
                path = os.path.join(d, f"areas.{ext}")
                A.export_areas(path, table, margin=1.5)
                back, margin = A.import_areas(path)
                self.assertEqual([a.to_dict() for a in back], [a.to_dict() for a in table], ext)
                if ext == "json":
                    self.assertEqual(margin, 1.5)
                    with open(path, encoding="utf-8") as fh:
                        self.assertEqual(json.load(fh)["formato"], "visor-grib-areas")
                else:
                    self.assertIsNone(margin)
            # CSV con coordenadas en grados-minutos y sin cabecera
            path = os.path.join(d, "gm.csv")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("SAEF,Ezeiza,30°13.2'S,46°00'S,071°51'W,010°00'W,1,1\n")
            back, _m = A.import_areas(path)
            self.assertEqual(back[0].code, "SAEF")
            self.assertAlmostEqual(back[0].north, -30.22, places=2)
            self.assertAlmostEqual(back[0].east, -10.0)
            # archivos inválidos: aviso claro
            bad = os.path.join(d, "bad.json")
            with open(bad, "w") as fh:
                fh.write('{"areas": [{"code": "X", "north": -40, "south": -30, "west": -70, "east": -60}]}')
            with self.assertRaises(ValueError) as cm:
                A.import_areas(bad)
            self.assertIn("norte", str(cm.exception))
            with open(bad, "w") as fh:
                fh.write("no es json")
            with self.assertRaises(ValueError):
                A.import_areas(bad)


# ── Recorte local y pedido al servidor ───────────────────────────────────────

def _grib_global(res=1.0, lon0=0.0, lat0=90.0):
    """GRIB2 regular_ll global (lon desde lon0, lat descendente) con
    valores = lon + 1000·lat, para comprobar el recorte."""
    import eccodes as ec
    ni, nj = int(round(360 / res)), int(round(180 / res)) + 1
    lons = lon0 + res * np.arange(ni)
    lats = lat0 - res * np.arange(nj)
    LON, LAT = np.meshgrid(lons, lats)
    gid = ec.codes_grib_new_from_samples("regular_ll_pl_grib2")
    ec.codes_set(gid, "Ni", ni)
    ec.codes_set(gid, "Nj", nj)
    ec.codes_set(gid, "latitudeOfFirstGridPointInDegrees", float(lats[0]))
    ec.codes_set(gid, "longitudeOfFirstGridPointInDegrees", float(lons[0] % 360))
    ec.codes_set(gid, "latitudeOfLastGridPointInDegrees", float(lats[-1]))
    ec.codes_set(gid, "longitudeOfLastGridPointInDegrees", float(lons[-1] % 360))
    ec.codes_set(gid, "iDirectionIncrementInDegrees", res)
    ec.codes_set(gid, "jDirectionIncrementInDegrees", res)
    ec.codes_set(gid, "jScansPositively", 0)
    ec.codes_set(gid, "bitsPerValue", 24)
    ec.codes_set_values(gid, (((LON + 180) % 360 - 180) + 1000.0 * LAT).ravel())
    data = ec.codes_get_message(gid)
    ec.codes_release(gid)
    return data


class TestRecorte(unittest.TestCase):
    def setUp(self):
        from app.grib_engines import ec
        if ec is None:
            self.skipTest("requiere eccodes")
        from app import regrid
        self.regrid = regrid

    def _read(self, data):
        from app.grib_reader import GribReader
        with tempfile.NamedTemporaryFile(suffix=".grib2", delete=False) as fh:
            fh.write(data)
            path = fh.name
        try:
            r = GribReader(path)
            _u, _v, t, _info = r.get_level_fields(0, r.levels[0])
            return r.lats, r.lons, t
        finally:
            os.remove(path)

    def test_hacia_afuera(self):
        data = _grib_global(1.0)
        out = self.regrid.crop_grib(data, (-29.3, -46.6, -72.4, -9.2))
        lats, lons, _f = self._read(out)
        self.assertEqual((lats.min(), lats.max()), (-47.0, -29.0))
        self.assertEqual((lons.min(), lons.max()), (-73.0, -9.0))
        self.assertEqual(self.regrid.grid_bbox(out), (-73.0, -9.0, -47.0, -29.0))
        # límites justo sobre la grilla: se conservan tal cual
        out = self.regrid.crop_grib(data, (-29.0, -47.0, -73.0, -9.0))
        self.assertEqual(self.regrid.grid_bbox(out), (-73.0, -9.0, -47.0, -29.0))
        self.assertEqual(A.check_coverage((-29.3, -46.6, -72.4, -9.2), self.regrid.grid_bbox(out)), [])

    def test_polo_sur(self):
        out = self.regrid.crop_grib(_grib_global(1.0), (-39.28, -90.0, -74.57, -9.0))
        lats, lons, t = self._read(out)
        self.assertEqual(lats.min(), -90.0)
        self.assertEqual(lats.max(), -39.0)
        self.assertEqual((lons.min(), lons.max()), (-75.0, -9.0))
        self.assertEqual(t.shape, (52, 67))

    def test_cruza_greenwich_en_grilla_0_360(self):
        """Zona 21W…16E sobre una grilla 0…359: el recorte se reordena para
        que quede contiguo y el lector la ve como −21…16."""
        out = self.regrid.crop_grib(_grib_global(1.0, lon0=0.0), (11.0, -11.0, -21.0, 16.0))
        lats, lons, t = self._read(out)
        self.assertEqual(self.regrid.grid_bbox(out), (-21.0, 16.0, -11.0, 11.0))
        self.assertEqual(len(lons), 38)
        self.assertTrue(np.all(np.diff(lons) == 1.0))
        self.assertEqual(t.shape, (23, 38))
        # los valores siguen a su longitud (lon + 1000·lat): sin columnas mezcladas
        LON, LAT = np.meshgrid(lons, lats)
        self.assertTrue(np.allclose(t, LON + 1000.0 * LAT, atol=0.1))
        # y en una grilla −180…180 el recorte es directo
        out2 = self.regrid.crop_grib(_grib_global(1.0, lon0=-180.0), (11.0, -11.0, -21.0, 16.0))
        _lats2, _lons2, t2 = self._read(out2)
        self.assertTrue(np.allclose(t2, t, atol=0.1))

    def test_zona_fuera(self):
        with self.assertRaises(ValueError):
            self.regrid.crop_grib(_grib_global(5.0), (95.0, 92.0, 0.0, 10.0))

    def test_pedido_al_servidor_gfs(self):
        """NOMADS: la zona viaja redondeada hacia afuera a la resolución
        pedida; polo y Greenwich van tal cual (negativos y positivos)."""
        src = GFSSource()
        job = DownloadJob(dt.date(2026, 10, 14), 6, [6], ["UGRD", "VGRD"], [500],
                          region=(-20.72, -90.0, -74.57, -9.0), params={"resolucion": "0p25"},
                          area_mode="fir", area_codes=["SAEF", "SAVF"], area_margin=1.0)
        self.assertIsNone(src.validate(job))
        q = parse_qs(urlparse(src.build_requests(job, 6)[0].url).query)
        self.assertEqual((q["toplat"], q["bottomlat"], q["leftlon"], q["rightlon"]),
                         (["-20.5"], ["-90"], ["-74.75"], ["-9"]))
        job.region = (11.0, -11.0, -21.0, 16.0)
        q = parse_qs(urlparse(src.build_requests(job, 6)[0].url).query)
        self.assertEqual((q["leftlon"], q["rightlon"]), (["-21"], ["16"]))
        job.params = {"resolucion": "1p00"}
        job.region = (-20.72, -90.0, -74.57, -9.0)
        q = parse_qs(urlparse(src.build_requests(job, 6)[0].url).query)
        self.assertEqual((q["toplat"], q["leftlon"]), (["-20"], ["-75"]))
        self.assertEqual(src.grid_resolution({"resolucion": "0p50"}), 0.5)


# ── Trabajo, nombre y procedencia ────────────────────────────────────────────

class TestDescargaConArea(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _job(self, **kw):
        base = dict(run_date=dt.date(2026, 10, 14), cycle=6, steps=[6], variables=["UGRD", "VGRD"],
                    levels=[500], region=(-29.22, -47.0, -72.85, -9.0), dest_dir=self.tmp.name,
                    params={"resolucion": "1p00"}, area_mode="fir", area_codes=["SAEF"],
                    area_margin=1.0)
        base.update(kw)
        return DownloadJob(**base)

    def test_nombre_con_codigos(self):
        src = GFSSource()
        job = self._job(area_codes=["SAEF", "SACF"])
        self.assertEqual(job.area_tag, "SAEF+SACF")
        self.assertTrue(job.file_paths(src)[0].endswith("gfs_20261014_06z_1p00_SAEF+SACF.grib2"))
        job = self._job(area_mode="manual")
        self.assertTrue(job.file_paths(src)[0].endswith("_MANUAL.grib2"))
        job = self._job(region=None)
        self.assertTrue(job.file_paths(src)[0].endswith("gfs_20261014_06z_1p00.grib2"))
        job = self._job(basename="propio", suffix="_wafs")
        self.assertTrue(job.file_paths(src)[0].endswith("propio_wafs.grib2"))
        # el modo 'fir' sin códigos cae a MANUAL
        self.assertEqual(self._job(area_codes=[]).area_tag, "MANUAL")

    def test_procedencia_y_validacion_de_cobertura(self):
        from app.grib_engines import ec
        if ec is None:
            self.skipTest("requiere eccodes")
        src = GFSSource()
        served = {"data": _grib_global(1.0)}

        def fetch(url, headers=None, chunk_cb=None, cancel=None, **kw):
            return served["data"]
        # El servidor devuelve el globo entero (cubre la zona)
        paths = src.download(self._job(), fetch_fn=fetch, retry_wait=0)
        prov = read_provenance(paths[0])
        area = prov["area"]
        self.assertEqual(area["etiqueta"], "SAEF")
        self.assertEqual(area["modo"], "fir")
        self.assertEqual(area["codigos"], ["SAEF"])
        self.assertEqual(area["margen_deg"], 1.0)
        self.assertEqual(area["zona_pedida"], [-29.22, -47.0, -72.85, -9.0])
        self.assertEqual(area["zona_servidor"], [-29.0, -47.0, -73.0, -9.0])
        self.assertTrue(area["cubre"])
        self.assertNotIn("aviso", area)
        self.assertIs(src.last_provenance["area"]["cubre"], True)
        # El servidor recortó más chico que lo pedido → aviso
        from app import regrid
        served["data"] = regrid.crop_grib(_grib_global(1.0), (-30.0, -45.0, -70.0, -20.0))
        paths = src.download(self._job(basename="chico"), fetch_fn=fetch, retry_wait=0)
        area = read_provenance(paths[0])["area"]
        self.assertFalse(area["cubre"])
        self.assertIn("más chica", area["aviso"])
        self.assertIn("norte", area["aviso"])
        self.assertIn("este", area["aviso"])
        self.assertEqual(area["zona_obtenida"], [-30.0, -45.0, -70.0, -20.0])


# ── Interfaz ─────────────────────────────────────────────────────────────────

class _QtBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_cfg = config.CONFIG_PATH
        config.CONFIG_PATH = os.path.join(self._tmp.name, "config.json")
        from PyQt6.QtWidgets import QMessageBox
        self._msgbox = (QMessageBox.critical, QMessageBox.warning, QMessageBox.information)
        self.messages = []
        for name in ("critical", "warning", "information"):
            setattr(QMessageBox, name,
                    staticmethod(lambda *a, _n=name, **k: self.messages.append((_n, a[2] if len(a) > 2 else "")) or 0))
        self.w = None

    def tearDown(self):
        if self.w is not None:
            self.w.close()
            self.w.deleteLater()
            _app.processEvents()
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.critical, QMessageBox.warning, QMessageBox.information = self._msgbox
        config.CONFIG_PATH = self._old_cfg
        self._tmp.cleanup()

    def _cfg(self, **kw):
        cfg = dict(config.DEFAULTS)
        cfg.update(kw)
        return cfg


class TestDialogoDescargaArea(_QtBase):
    def _dialog(self, **kw):
        from app.dialogs.download_dialog import DownloadDialog
        self.cfg = self._cfg(**kw)
        self.w = DownloadDialog(None, cfg=self.cfg, dest_dir=self._tmp.name)
        self.w.show()
        _app.processEvents()
        return self.w

    def test_modo_por_fir_recalcula_la_envolvente(self):
        d = self._dialog()
        self.assertTrue(d.rb_fir.isChecked())
        self.assertEqual(sorted(d._area_checks), sorted(A.ARGENTINA_CODES))
        self.assertTrue(all(c.isChecked() for c in d._area_checks.values()))
        self.assertFalse(d.lat_n.isEnabled())
        self.assertEqual(d.region(), (-20.72, -90.0, -74.57, -9.0))
        # SAEF sola: su caja + 1°
        d._set_all_areas(False)
        self.assertIn("al menos una", d.lbl_size.text())
        d._area_checks["SAEF"].setChecked(True)
        self.assertEqual(d.region(), (-29.22, -47.0, -72.85, -9.0))
        self.assertEqual(d.lat_n.text(), "-29.22")
        # SAEF + SACF
        d._area_checks["SACF"].setChecked(True)
        self.assertEqual(d.region(), (-20.72, -47.0, -72.85, -9.0))
        self.assertEqual(d.selected_codes(), ["SACF", "SAEF"])      # orden de la tabla
        self.assertEqual(d.job().area_tag, "SACF+SAEF")
        # margen
        d.spin_margin.setValue(0.0)
        self.assertEqual(d.region(), (-21.72, -46.0, -71.85, -10.0))
        d.spin_margin.setValue(1.0)
        # tamaño: puntos y MB a la resolución elegida
        txt = d.lbl_size.text()
        self.assertIn("Δlat 26.28°", txt)
        self.assertIn("0.25°", txt)
        self.assertIn("MB", txt)
        self.assertIn("margen 1° incluido", txt)
        self.assertIn("puntos", txt)
        # Todas / Ninguna
        d.btn_all.click()
        self.assertEqual(len(d.selected_codes()), 5)
        self.assertIn("llega al polo", d.lbl_size.text())
        d.btn_none.click()
        self.assertEqual(d.selected_codes(), [])
        # sin FIR marcadas no se puede descargar
        d._start()
        self.assertEqual(self.messages[-1][0], "warning")
        self.assertIn("Marcá", self.messages[-1][1])

    def test_pasar_a_manual_copia_los_campos(self):
        d = self._dialog()
        d._set_all_areas(False)
        d._area_checks["SAEF"].setChecked(True)
        d.rb_manual.setChecked(True)
        self.assertTrue(d.lat_n.isEnabled())
        self.assertFalse(d.fir_box.isVisible())
        self.assertEqual(d.region(), (-29.22, -47.0, -72.85, -9.0))
        d.lat_n.setText("30°00'S")
        d.lat_n.editingFinished.emit()
        self.assertEqual(d.region()[0], -30.0)
        self.assertEqual(d.job().area_tag, "MANUAL")
        self.assertEqual(d.job().area_mode, "manual")
        d.lon_w.setText("basura")
        d.lon_w.editingFinished.emit()
        self.assertEqual(d.lon_w.value(), -72.85)                 # vuelve al valor anterior
        self.assertIn("inválida", d.lbl_size.text())
        d.chk_global.setChecked(True)
        self.assertIsNone(d.region())
        self.assertFalse(d.lat_n.isEnabled())
        # el modo y la zona manual se recuerdan al cerrar
        d.chk_global.setChecked(False)
        d.reject()
        self.assertEqual(self.cfg["download_area_mode"], "manual")
        self.assertEqual(self.cfg["download_manual_region"], [-30.0, -47.0, -72.85, -9.0])
        self.assertEqual(self.cfg["download_area_codes"], ["SAEF"])

    def test_recuerda_la_seleccion(self):
        d = self._dialog(download_area_mode="fir", download_area_codes=["SAVF"],
                         areas_margin_deg=0.5, areas_coord_format="gm")
        self.assertEqual(d.selected_codes(), ["SAVF"])
        self.assertEqual(d.region(), (-38.78, -90.0, -74.07, -9.5))
        self.assertEqual(d.lat_n.text(), "38°46.8'S")
        self.assertIn("llega al polo", d.lbl_size.text())
        d.rb_manual.setChecked(True)
        d.set_region(11.0, -11.0, -21.0, 16.0)
        self.assertIn("Greenwich", d.lbl_size.text())
        job = d.job()
        self.assertEqual(job.region, (11.0, -11.0, -21.0, 16.0))
        self.assertIsNone(d.source.validate(job))

    def test_areas_deshabilitadas_y_configurar(self):
        table = A.areas_to_config(A.default_areas())
        table[0]["enabled"] = False
        table.append({"code": "TEST", "name": "Prueba", "north": -30, "south": -35, "west": -60,
                      "east": -55, "enabled": True, "verify": False})
        d = self._dialog(areas=table, download_area_codes=["TEST"])
        self.assertNotIn("SARR", d._area_checks)
        self.assertIn("TEST", d._area_checks)
        self.assertEqual(d.region(), (-29.0, -36.0, -61.0, -54.0))
        self.assertEqual(d._area_checks["SAEF"].toolTip(), A.VERIFY_NOTE)
        # «Configurar áreas…» (diálogo simulado) actualiza las casillas
        from app.dialogs import areas_dialog as ad

        class FakeAreas:
            def __init__(self, parent=None, cfg=None, regions_fn=None):
                pass

            def exec(self):
                return 1

            def values(self):
                t = [dict(x) for x in table]
                t[0]["enabled"] = True
                return {"areas": t, "areas_margin_deg": 2.0, "areas_coord_format": "gm"}
        old = ad.AreasDialog
        ad.AreasDialog = FakeAreas
        try:
            d._configure_areas()
        finally:
            ad.AreasDialog = old
        self.assertIn("SARR", d._area_checks)
        self.assertEqual(d.selected_codes(), ["TEST"])
        self.assertEqual(d.spin_margin.value(), 2.0)
        self.assertEqual(d.region(), (-28.0, -37.0, -62.0, -53.0))
        self.assertEqual(d.lat_n.text(), "28°00.0'S")

    def test_descarga_con_area_escribe_etiqueta(self):
        from app.dialogs import download_dialog as dd
        from app.sources import gfs as gfs_src
        from app.sources.cache import DownloadCache
        d = self._dialog(download_h_from=6, download_h_to=6, download_area_codes=["SAEF", "SACF"],
                         wafs_convert=False)
        old_fetch = gfs_src.gfs.fetch
        gfs_src.gfs.fetch = lambda url, headers=None, chunk_cb=None, cancel=None, **k: b"GRIBxxxx"
        old_cache = dd.DownloadDialog._cache
        dd.DownloadDialog._cache = lambda self_: DownloadCache(os.path.join(self._tmp.name, "cache"))
        try:
            d._start()
            for _ in range(200):
                _app.processEvents()
                if not d._worker.isRunning() and d.downloaded_paths:
                    break
                d._worker.wait(50)
            _app.processEvents()
        finally:
            gfs_src.gfs.fetch = old_fetch
            dd.DownloadDialog._cache = old_cache
        self.assertEqual(len(d.downloaded_paths), 1)
        path = d.downloaded_paths[0]
        self.assertIn("_SACF+SAEF", os.path.basename(path))
        prov = read_provenance(path)
        self.assertEqual(prov["area"]["etiqueta"], "SACF+SAEF")
        self.assertEqual(prov["area"]["zona_pedida"], [-20.72, -47.0, -72.85, -9.0])
        self.assertEqual(self.cfg["download_area_codes"], ["SACF", "SAEF"])


class TestPreferenciasAreas(_QtBase):
    def test_pestana_y_tabla(self):
        from app.dialogs.settings_dialog import SettingsDialog
        from PyQt6.QtCore import Qt
        self.w = SettingsDialog(None, cfg=self._cfg())
        self.assertIn("Áreas / FIR", self.w.TABS)
        ed = self.w.areas_editor
        self.assertEqual(ed.table.rowCount(), 5)
        self.assertEqual(ed.table.item(0, ed.C_CODE).text(), "SARR")
        self.assertEqual(ed.table.item(0, ed.C_N).text(), "-22.25")
        self.assertEqual(ed.table.item(0, ed.C_VER).checkState(), Qt.CheckState.Checked)
        self.assertEqual(ed.table.item(0, ed.C_VER).toolTip(), A.VERIFY_NOTE)
        # editar con grados-minutos
        ed.table.item(0, ed.C_N).setText("22°00'S")
        self.assertAlmostEqual(ed.areas()[0].north, -22.0)
        self.assertEqual(ed.table.item(0, ed.C_N).text(), "-22.00")
        # inválido: vuelve y avisa
        ed.table.item(0, ed.C_N).setText("xx")
        self.assertEqual(ed.table.item(0, ed.C_N).text(), "-22.00")
        self.assertTrue(ed.lbl_error.isVisible() or ed.lbl_error.text())
        self.assertIn("inválida", ed.lbl_error.text())
        # norte < sur: aviso claro y Aplicar no cierra
        ed.table.item(0, ed.C_S).setText("-10")
        self.assertIn("norte", ed.errors()[0])
        self.w._accept()
        self.assertEqual(self.messages[-1][0], "warning")
        self.assertIn("norte", self.messages[-1][1])
        ed.table.item(0, ed.C_S).setText("-30.7")
        self.assertEqual(ed.errors(), [])
        # formato de salida
        ed.cb_format.setCurrentIndex(ed.cb_format.findData("gm"))
        self.assertEqual(ed.table.item(0, ed.C_N).text(), "22°00.0'S")
        self.assertEqual(ed.values()["areas_coord_format"], "gm")
        # agregar / borrar
        r = ed.add_row()
        ed.table.item(r, ed.C_CODE).setText("sueo")
        ed.table.item(r, ed.C_NAME).setText("Montevideo")
        self.assertEqual(ed.areas()[-1].code, "SUEO")
        self.assertEqual(ed.table.rowCount(), 6)
        ed.table.setCurrentCell(r, 0)
        ed.delete_row()
        self.assertEqual(ed.table.rowCount(), 5)
        ed.spin_margin.setValue(1.5)
        vals = self.w.values()
        self.assertEqual(vals["areas_margin_deg"], 1.5)
        self.assertEqual(vals["areas"][0]["north"], -22.0)
        self.assertEqual(len(vals["areas"]), 5)

    def test_exportar_importar_desde_el_editor(self):
        from app.widgets.areas_editor import AreasEditor
        ed = AreasEditor(self._cfg())
        self.w = ed
        r = ed.add_row()
        ed.table.item(r, ed.C_CODE).setText("TEST")
        path = os.path.join(self._tmp.name, "t.csv")
        A.export_areas(path, ed.areas(), margin=2.0)
        ed.reset_defaults()
        self.assertEqual(ed.table.rowCount(), 6)      # las cinco + TEST se conserva
        ed.set_areas(A.default_areas())
        self.assertTrue(ed.load_file(path))
        self.assertEqual([a.code for a in ed.areas()][-1], "TEST")
        self.assertFalse(ed.load_file(os.path.join(self._tmp.name, "no.json")))
        self.assertEqual(self.messages[-1][0], "warning")

    def test_extremos_de_la_capa_fir(self):
        from app.widgets.areas_editor import AreasEditor
        from app import fir
        regs = {r.code: r for r in fir.load_geojson(fir.BUNDLED_FILE)}
        ed = AreasEditor(self._cfg(), regions_fn=lambda: regs)
        self.w = ed
        ed.table.setCurrentCell(3, 0)          # SAEF
        ed.fill_from_fir()
        a = ed.areas()[3]
        e = regs["SAEF"].extremes()
        self.assertAlmostEqual(a.north, e["norte"])
        self.assertAlmostEqual(a.east, e["este"])
        self.assertTrue(a.verify)              # VATSpy no es oficial


class TestMapaYVentana(_QtBase):
    def _window(self):
        from app.main_window import MainWindow
        from tests.test_grib_reader import _reader_sintetico
        self.w = MainWindow()
        self.w.show()
        _app.processEvents()
        self.reader = _reader_sintetico([850, 700], shape=(69, 69))
        self.reader.lats = np.arange(-64.0, 4.1, 1.0)
        self.reader.lons = np.arange(-90.0, -21.9, 1.0)
        self.reader.path = os.path.join(self._tmp.name, "s.grib2")
        self.w.load_reader(self.reader, self.reader.path)
        _app.processEvents()
        return self.w

    def test_rectangulos_en_el_mapa(self):
        w = self._window()
        self.assertFalse(w.plot.area_visible())
        self.assertFalse(w._act_area.isChecked())
        w._cfg["download_area_codes"] = ["SAEF", "SACF"]
        w.set_area_draw(True)
        self.assertTrue(w._act_area.isChecked())
        self.assertTrue(w.plot.area_visible())
        # con un archivo sin procedencia el marco es el recuadro de su grilla
        env, boxes = w.area_layer_geometry()
        self.assertEqual((env, boxes), ((4.0, -64.0, -90.0, -22.0), []))
        w.plot.canvas.draw()
        self.assertEqual(len(w.plot._area_artists), 1)        # sólo la envolvente
        # sin archivo, el marco es la última selección del bloque Área
        w._file_close()
        env, boxes = w.area_layer_geometry()
        self.assertEqual(env, (-20.72, -47.0, -72.85, -9.0))
        self.assertEqual([c for c, _r in boxes], ["SAEF", "SACF"])
        w.plot.canvas.draw()
        texts = [t.get_text() for t in w.plot._area_artists if hasattr(t, "get_text")]
        self.assertEqual(sorted(texts), ["SACF", "SAEF"])
        self.assertEqual(len(w.plot._area_artists), 3)        # una colección + dos códigos
        # con la capa FIR activa, los rectángulos se suman a los contornos
        w.set_fir_enabled(True)
        w.plot.canvas.draw()
        self.assertTrue(w.plot.fir_visible())
        self.assertTrue(w.plot.area_visible())
        # modo manual: sólo la envolvente
        w._cfg["download_area_mode"] = "manual"
        w._cfg["download_manual_region"] = [11.0, -11.0, -21.0, 16.0]
        w._apply_area_layer()
        env, boxes = w.area_layer_geometry()
        self.assertEqual((env, boxes), ((11.0, -11.0, -21.0, 16.0), []))
        # todas las proyecciones, con el polo (archivo abierto: marco de la grilla)
        from app.wind_plot import PROJECTIONS
        w._cfg["download_area_mode"] = "fir"
        w._cfg["download_area_codes"] = ["SAVF"]
        w.load_reader(self.reader, self.reader.path)
        for key, _name in PROJECTIONS:
            w.set_projection(key)
            w.plot.canvas.draw()
            self.assertTrue(w.plot.area_visible(), key)
        w.set_projection("platecarree")
        w.set_area_draw(False)
        self.assertFalse(w.plot.area_visible())
        self.assertFalse(w._cfg["download_area_draw"])
        self.assertTrue(os.path.exists(config.CONFIG_PATH))

    def test_status_muestra_el_area(self):
        w = self._window()
        prov = {"fuente": "gfs", "nombre": "NOAA GFS", "modelo": "GFS (NCEP)",
                "corrida": "2026-10-14T06:00Z", "resolucion_final": "0p25",
                "area": {"modo": "fir", "codigos": ["SAEF", "SACF"], "etiqueta": "SAEF+SACF",
                         "cubre": True}}
        w.load_reader(self.reader, self.reader.path, prov)
        self.assertIn("área SAEF+SACF", w.panel.lbl_source.text())
        prov["area"]["cubre"] = False
        w.load_reader(self.reader, self.reader.path, prov)
        self.assertIn("área SAEF+SACF (incompleta)", w.panel.lbl_source.text())

    def test_menu_areas_y_preferencias(self):
        w = self._window()
        texts = [a.text() for a in w._menu_fir.actions()]
        self.assertIn("Rectángulos del área de descarga", texts)
        self.assertIn("Áreas de descarga…", texts)
        from app.dialogs import areas_dialog as ad

        class FakeAreas:
            def __init__(self, parent=None, cfg=None, regions_fn=None):
                FakeAreas.regions = regions_fn()

            def exec(self):
                return 1

            def values(self):
                t = A.areas_to_config(A.default_areas())
                t[3]["north"] = -29.0
                return {"areas": t, "areas_margin_deg": 0.5, "areas_coord_format": "decimal"}
        old = ad.AreasDialog
        ad.AreasDialog = FakeAreas
        try:
            w.open_areas_dialog()
        finally:
            ad.AreasDialog = old
        self.assertIn("SAEF", FakeAreas.regions)
        self.assertEqual(w._cfg["areas_margin_deg"], 0.5)
        self.assertEqual(A.find_area(A.areas_from_config(w._cfg), "SAEF").north, -29.0)
        # Preferencias aplica la tabla y la capa (sin archivo: marco de la selección)
        w._file_close()
        w.apply_settings({"areas": A.areas_to_config(A.default_areas()), "areas_margin_deg": 2.0,
                          "download_area_draw": True})
        self.assertTrue(w.plot.area_visible())
        env, _boxes = w.area_layer_geometry()
        self.assertEqual(env, (-19.72, -90.0, -75.57, -8.0))

    def test_marco_sigue_al_archivo(self):
        """Al abrir un archivo el marco pasa a ser el de ese archivo (zona
        pedida de su procedencia o recuadro de su grilla); al abrir otro se
        reemplaza, y al cerrar vuelve el de la última selección."""
        from tests.test_grib_reader import _reader_sintetico
        w = self._window()
        w._cfg["download_area_codes"] = ["SAVF"]
        w.set_area_draw(True)
        prov = {"fuente": "gfs", "area": A.area_info("fir", ["SAEF", "SACF"], 1.0,
                                                      (-20.72, -47.0, -72.85, -9.0))}
        r1 = _reader_sintetico([850, 700], shape=(69, 69))
        r1.lats = np.arange(-64.0, 4.1, 1.0)
        r1.lons = np.arange(-90.0, -21.9, 1.0)
        r1.path = os.path.join(self._tmp.name, "a.grib2")
        w.load_reader(r1, r1.path, prov)
        env, boxes = w.area_layer_geometry()
        self.assertEqual(env, (-20.72, -47.0, -72.85, -9.0))
        self.assertEqual([c for c, _r in boxes], ["SAEF", "SACF"])
        w.plot.canvas.draw()
        self.assertEqual(len(w.plot._area_artists), 3)
        # otro archivo, sin procedencia: marco de su grilla y nada del anterior
        r2 = _reader_sintetico([850, 700], shape=(21, 31))
        r2.lats = np.arange(-50.0, -29.9, 1.0)
        r2.lons = np.arange(-75.0, -44.9, 1.0)
        r2.path = os.path.join(self._tmp.name, "b.grib2")
        w.load_reader(r2, r2.path, None)
        env, boxes = w.area_layer_geometry()
        self.assertEqual((env, boxes), ((-30.0, -50.0, -75.0, -45.0), []))
        w.plot.canvas.draw()
        self.assertEqual(len(w.plot._area_artists), 1)
        texts = [t.get_text() for t in w.plot._area_artists if hasattr(t, "get_text")]
        self.assertEqual(texts, [])
        # procedencia manual: envolvente sola
        w.load_reader(r1, r1.path, {"area": A.area_info("manual", [], 0.0, (0.0, -60.0, -80.0, -30.0))})
        self.assertEqual(w.area_layer_geometry(), ((0.0, -60.0, -80.0, -30.0), []))
        # cerrar: vuelve la selección del bloque Área
        w._file_close()
        env, boxes = w.area_layer_geometry()
        self.assertEqual([c for c, _r in boxes], ["SAVF"])
        # con los rectángulos apagados, nada en ningún caso
        w.set_area_draw(False)
        w.load_reader(r1, r1.path, prov)
        self.assertEqual(w.area_layer_geometry(), (None, []))


if __name__ == "__main__":
    unittest.main()
