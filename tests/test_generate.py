# -*- coding: utf-8 -*-
"""Generador de GRIB a mano: módulo puro y diálogo «Generar GRIB…»."""
import datetime as dt
import os
import tempfile
import unittest

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QPushButton  # noqa: E402

from app import config  # noqa: E402
from app import fl_table as flt  # noqa: E402
from app import grib_generate as gg  # noqa: E402
from app.dialogs import glass_dialog  # noqa: E402

glass_dialog._apply_dialog_blur = lambda w: None
_app = QApplication.instance() or QApplication([])

try:
    import pyproj  # noqa: F401
    import eccodes as ec
except Exception:  # pragma: no cover
    ec = None

RUN = dt.datetime(2026, 10, 21, 12, tzinfo=dt.timezone.utc)
ZONE = (-20.3, -45.7, -75.2, -50.1)


def _rows(mode):
    return [{"fl": fl, "t_c": gg.isa_temp_c(fl), "spd_kt": 20 + fl / 10.0, "dir_deg": (250 + fl / 5.0) % 360}
            for fl in flt.mode_fls(mode)]


class TestGenerador(unittest.TestCase):
    def test_temperatura_isa(self):
        self.assertAlmostEqual(gg.isa_temp_c(0), 15.0)
        self.assertAlmostEqual(gg.isa_temp_c(50), 15.0 - 0.0065 * 5000 * 0.3048, places=3)
        self.assertAlmostEqual(gg.isa_temp_c(360), 15.0 - 0.0065 * 36000 * 0.3048, places=3)
        self.assertEqual(gg.isa_temp_c(400), -56.5)
        self.assertEqual(gg.isa_temp_c(600), -56.5)

    def test_grilla(self):
        lats, lons, zone = gg.grid_axes(ZONE, 0.5)
        self.assertEqual(zone, (-20.0, -46.0, -75.5, -50.0))      # hacia afuera, a 0,5°
        self.assertEqual(float(lats[0]), -20.0)
        self.assertEqual(float(lats[-1]), -46.0)
        self.assertEqual(len(lats), 53)
        self.assertEqual(len(lons), 52)
        self.assertEqual(float(lons[0]), -75.5)
        self.assertTrue(np.all(np.diff(lats) < 0))                  # descendentes
        self.assertTrue(np.all(np.diff(lons) > 0))
        lats, lons, zone = gg.grid_axes((-30.0, -40.0, -70.0, -60.0), 1.0)
        self.assertEqual((len(lats), len(lons)), (11, 11))
        # 1,25° y la vuelta completa: 288 × 145 sin repetir el meridiano de corte
        lats, lons, zone = gg.grid_axes((90, -90, -180, 180), 1.25)
        self.assertEqual((len(lons), len(lats)), (288, 145))
        self.assertEqual((float(lons[0]), float(lons[-1])), (-180.0, 178.75))
        self.assertEqual(zone, (90.0, -90.0, -180.0, 178.75))
        self.assertEqual(len(gg.grid_axes((90, -90, -180, 180), 0.25)[1]), 1440)
        self.assertIn((1.25, "1,25° (WAFS clásico)"), gg.RESOLUTIONS)
        self.assertIn("_1p25_", gg.default_basename(RUN, 36, 1.25, "MANUAL", "uv", "OACI"))

    def test_validacion(self):
        ok, err = gg.validate_rows([{"fl": 300, "t_c": -40, "spd_kt": 50, "dir_deg": 270},
                                    {"fl": 500, "t_c": -55, "spd_kt": 30, "dir_deg": 360}])
        self.assertIsNone(err)
        self.assertEqual([r["fl"] for r in ok], [500, 300])        # descendentes
        self.assertEqual(ok[0]["dir_deg"], 0.0)                     # 360 → 0
        self.assertIn("no está en la tabla", gg.validate_rows([{"fl": 305, "t_c": 0, "spd_kt": 0, "dir_deg": 0}])[1])
        self.assertIn("repetido", gg.validate_rows([{"fl": 300, "t_c": 0, "spd_kt": 0, "dir_deg": 0}] * 2)[1])
        self.assertIn("velocidad", gg.validate_rows([{"fl": 300, "t_c": 0, "spd_kt": 500, "dir_deg": 0}])[1])
        self.assertIn("dirección", gg.validate_rows([{"fl": 300, "t_c": 0, "spd_kt": 5, "dir_deg": 370}])[1])
        self.assertIn("no son números", gg.validate_rows([{"fl": 300, "t_c": "x", "spd_kt": 5, "dir_deg": 0}])[1])
        self.assertIn("al menos un FL", gg.validate_rows([])[1])
        # Aumentos por grado: optativos (0), acotados
        self.assertEqual((ok[0]["spd_inc"], ok[0]["dir_inc"]), (0.0, 0.0))
        ok, err = gg.validate_rows([{"fl": 300, "t_c": 0, "spd_kt": 40, "dir_deg": 30, "spd_inc": 5, "dir_inc": None}])
        self.assertIsNone(err)
        self.assertEqual((ok[0]["spd_inc"], ok[0]["dir_inc"]), (5.0, 0.0))
        self.assertIn("kt por grado", gg.validate_rows([{"fl": 300, "t_c": 0, "spd_kt": 0, "dir_deg": 0, "spd_inc": 101}])[1])
        self.assertIn("° por grado", gg.validate_rows([{"fl": 300, "t_c": 0, "spd_kt": 0, "dir_deg": 0, "dir_inc": -1}])[1])

    def test_aumento_por_grado(self):
        """«+5/°»: el valor de la fila en la primera celda del archivo y 5 más
        por cada grado de latitud y de longitud; la esquina la fija el orden
        de las celdas. El ejemplo: 50S–64S, 30W–40W, N→S O→E → 50S/40W vale
        40/30, 51S/40W y 50S/39W 45/35, 51S/39W 50/40."""
        lats, lons, _ = gg.grid_axes((-50, -64, -40, -30), 1.0)
        spd = gg.gradient_values(40, 5, lats, lons, "ns_we")
        self.assertEqual(spd.shape, (15, 11))
        self.assertEqual(spd[0, 0], 40.0)                           # 50S/40W
        self.assertEqual((spd[1, 0], spd[0, 1], spd[1, 1]), (45.0, 45.0, 50.0))
        self.assertEqual(spd[-1, -1], 40.0 + 5 * (14 + 10))         # 64S/30W
        self.assertEqual(gg.gradient_values(40, 5, lats, lons, "origen")[0, 0], 40.0)   # «como el origen» = N→S, O→E
        self.assertEqual(gg.gradient_values(40, 5, lats, lons, "sn_ew")[-1, -1], 40.0)  # S→N, E→O: 64S/30W
        self.assertEqual(gg.gradient_values(40, 5, lats, lons, "sn_we")[-1, 0], 40.0)   # 64S/40W
        self.assertEqual(gg.gradient_values(40, 5, lats, lons, "ns_ew")[0, -1], 40.0)   # 50S/30W
        self.assertTrue(np.all(gg.gradient_values(40, 0, lats, lons, "sn_ew") == 40.0))  # sin aumento, uniforme
        # A 0,25° cada celda suma un cuarto: sigue siendo por grado
        lats, lons, _ = gg.grid_axes((-50, -64, -40, -30), 0.25)
        self.assertEqual(gg.gradient_values(40, 5, lats, lons)[0, 1], 41.25)
        self.assertEqual(gg.gradient_values(40, 5, lats, lons)[4, 4], 50.0)
        self.assertEqual(gg.origin_corner("sn_ew"), ("S", "E"))
        self.assertEqual(gg.origin_corner(None), ("N", "O"))

    @unittest.skipIf(ec is None, "sin eccodes")
    def test_aumento_en_el_archivo(self):
        """Por capa: una fila uniforme y otra en aumento; con otro orden de
        celdas, tras `recode`, la primera celda del archivo sigue siendo la
        del valor de la fila. La dirección da la vuelta en 360."""
        from app import grib_encode as ge
        from app.wafs_format import iter_messages
        rows = [{"fl": 300, "t_c": -40, "spd_kt": 40, "dir_deg": 30, "spd_inc": 5, "dir_inc": 5},
                {"fl": 200, "t_c": -20, "spd_kt": 20, "dir_deg": 350, "dir_inc": 5},
                {"fl": 100, "t_c": 0, "spd_kt": 10, "dir_deg": 90}]
        zone = (-50, -64, -40, -30)
        for scan in ("origen", "sn_ew"):
            data, info = gg.generate_grib(rows, zone, 1.0, mode="OACI", run=RUN, step_h=6,
                                          wind_format="dirspeed", scan=scan)
            self.assertEqual(info["aumento"]["fls"], [300, 200])
            self.assertEqual(info["aumento"]["esquina"], "NO" if scan == "origen" else "SE")
            self.assertEqual(info["aumento"]["origen"], [-50.0, -40.0] if scan == "origen" else [-64.0, -30.0])
            if scan != "origen":
                data, _ = ge.recode(data, {"wind": "dirspeed", "scan": scan}, labeled=True, mode="OACI")
            got = {}
            for gid, _pos, _size in iter_messages(data):
                try:
                    key = (ec.codes_get(gid, "shortName"), ec.codes_get(gid, "scaledValueOfFirstFixedSurface"))
                    got[key] = (np.asarray(ec.codes_get_values(gid)).reshape(15, 11), ec.codes_get(gid, "bitsPerValue"),
                                ec.codes_get(gid, "latitudeOfFirstGridPointInDegrees"))
                finally:
                    ec.codes_release(gid)
            self.assertEqual(len(got), 9)
            pa = {fl: flt.label_pa(fl, "OACI") for fl in (300, 200, 100)}
            lat0 = -50.0 if scan == "origen" else -64.0
            ws, bits, lat = got[("ws", pa[300])]
            self.assertEqual(lat, lat0)
            self.assertGreater(bits, 0)                             # ya no es constante
            self.assertAlmostEqual(ws[0, 0] / gg.KT_TO_MS, 40.0, places=3)
            self.assertAlmostEqual(ws[1, 0] / gg.KT_TO_MS, 45.0, places=3)
            self.assertAlmostEqual(ws[0, 1] / gg.KT_TO_MS, 45.0, places=3)
            self.assertAlmostEqual(ws[1, 1] / gg.KT_TO_MS, 50.0, places=3)
            wdir = got[("wdir", pa[300])][0]
            self.assertAlmostEqual(wdir[0, 0], 30.0, places=3)
            self.assertAlmostEqual(wdir[1, 1], 40.0, places=3)
            # FL200: sólo la dirección aumenta, y da la vuelta (350 + 10 → 0)
            ws2, bits2, _ = got[("ws", pa[200])]
            self.assertEqual(bits2, 0)                              # uniforme: exacto, 0 bits
            self.assertAlmostEqual(float(ws2[3, 3]) / gg.KT_TO_MS, 20.0, places=3)
            wdir2 = got[("wdir", pa[200])][0]
            self.assertAlmostEqual(wdir2[0, 0], 350.0, places=3)
            self.assertAlmostEqual(wdir2[1, 1], 0.0, places=3)
            self.assertAlmostEqual(wdir2[2, 1], 5.0, places=3)
            # FL100: uniforme del todo
            self.assertEqual(got[("ws", pa[100])][1], 0)
            self.assertEqual(got[("wdir", pa[100])][1], 0)
        # Sin aumentos, `info` no lo menciona y la procedencia tampoco
        data, info = gg.generate_grib(rows[2:], zone, 1.0, mode="OACI", run=RUN, step_h=6)
        self.assertNotIn("aumento", info)
        self.assertNotIn("aumento", gg.provenance(rows[2:], info))
        # Con U/V el visor recupera velocidad y dirección en cada celda
        from app.grib_reader import GribReader, speed_dir_from_uv
        data, info = gg.generate_grib(rows, zone, 1.0, mode="OACI", run=RUN, step_h=6, scan="ns_we")
        prov = gg.provenance(rows, info)
        self.assertEqual(prov["aumento"]["fls"], [300, 200])
        self.assertEqual(prov["tabla"][0]["spd_inc"], 5.0)
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "g.grib2")
            gg.write_generated(p, data, prov)
            r = GribReader(p)
            u, v, _t, _ = r.get_level_fields(0, 300.0)
            # el visor normaliza las latitudes ascendentes: 50S/40W es la última fila
            s00, d00 = speed_dir_from_uv(float(u[-1, 0]), float(v[-1, 0]))
            s11, d11 = speed_dir_from_uv(float(u[-2, 1]), float(v[-2, 1]))
            self.assertAlmostEqual(s00, 40.0, delta=0.01)
            self.assertAlmostEqual(d00, 30.0, delta=0.01)
            self.assertAlmostEqual(s11, 50.0, delta=0.01)
            self.assertAlmostEqual(d11, 40.0, delta=0.01)

    def test_nombre_y_procedencia(self):
        self.assertEqual(gg.default_basename(RUN, 6, 0.25, "SAEF+SACF", "uv", "OACI"),
                         "generado_20261021_12z_f006_0p25_SAEF+SACF_OACI")
        self.assertEqual(gg.default_basename(RUN, 0, 1.0, "MANUAL", "dirspeed", "WAFS"),
                         "generado_20261021_12z_f000_1p00_MANUAL_WAFS_dirvel")
        self.assertEqual(gg.default_basename(RUN, 6, 0.5, "SAEF", "uv", "INDRA", steps=[6, 9, 12]),
                         "generado_20261021_12z_f006-f012_0p50_SAEF_INDRA")
        self.assertEqual(gg.steps_from(6, 12, 3), [6, 9, 12])
        self.assertEqual(gg.steps_from(12, 6, 3), [6, 9, 12])
        self.assertEqual(gg.steps_from(6, 6, 3), [6])

    @unittest.skipIf(ec is None, "sin eccodes")
    def test_varios_plazos(self):
        from app.grib_reader import GribReader
        rows = _rows("INDRA")
        data, info = gg.generate_grib(rows, ZONE, 1.0, mode="INDRA", run=RUN, steps=[6, 9, 12])
        self.assertEqual(info["mensajes"], 3 * 14 * 3)
        self.assertEqual(info["plazos_h"], [6, 9, 12])
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "p.grib2")
            gg.write_generated(p, data, gg.provenance(rows, info))
            r = GribReader(p)
            self.assertEqual([s.hours for s in r.steps], [6, 9, 12])
            self.assertEqual(len(r.levels), 14)
            from app.sources.base import read_provenance
            self.assertEqual(read_provenance(p)["plazos_h"], [6, 9, 12])

    @unittest.skipIf(ec is None, "sin eccodes")
    def test_genera_y_el_visor_lo_lee(self):
        from app.grib_reader import GribReader, speed_dir_from_uv
        from app.sources.base import read_provenance
        with tempfile.TemporaryDirectory() as tmp:
            for mode, n in (("INDRA", 14), ("OACI", 17), ("OACI56", 56), ("WAFS", 56)):
                for wfmt in ("uv", "dirspeed"):
                    rows = _rows(mode)
                    data, info = gg.generate_grib(rows, ZONE, 0.5, mode=mode, run=RUN, step_h=6,
                                                  wind_format=wfmt)
                    self.assertEqual(info["mensajes"], 3 * n)
                    self.assertEqual(info["modo"], mode)
                    self.assertEqual(info["viento"], wfmt)
                    self.assertEqual(info["grilla"], {"ni": 52, "nj": 53, "resolucion_deg": 0.5})
                    p = os.path.join(tmp, f"{mode}_{wfmt}.grib2")
                    prov = gg.provenance(rows, info, "fir", ["SAEF"], 1.0, ZONE)
                    gg.write_generated(p, data, prov)
                    self.assertTrue(os.path.exists(p + ".json"))
                    self.assertTrue(os.path.exists(p + ".idx"))
                    self.assertEqual(read_provenance(p)["fuente"], "generado")
                    self.assertEqual(read_provenance(p)["area"]["etiqueta"], "SAEF")
                    self.assertEqual(read_provenance(p)["wafs"]["modo"], mode)
                    r = GribReader(p)
                    self.assertTrue(r.is_wafs)
                    self.assertEqual(r.fl_mode, mode)
                    self.assertEqual(len(r.levels), n)
                    self.assertEqual(r.wind_format, wfmt)
                    self.assertEqual(r.variables, ["u", "v", "t"])
                    self.assertEqual(r.steps[0].valid, RUN + dt.timedelta(hours=6))
                    self.assertEqual(r.run_time(), RUN)
                    # Cada nivel: uniforme, con la T, la velocidad y la dirección de su fila
                    for row in rows:
                        p_hpa = flt.label_pa(row["fl"], mode) / 100.0
                        u, v, t, _ = r.get_level_fields(0, p_hpa)
                        self.assertIsNotNone(u, (mode, row["fl"]))
                        self.assertLess(float(np.ptp(u)), 1e-6)
                        self.assertAlmostEqual(float(t.mean()) - 273.15, row["t_c"], delta=0.02)
                        spd, d = speed_dir_from_uv(float(u.mean()), float(v.mean()))
                        self.assertAlmostEqual(spd, row["spd_kt"], delta=0.05)
                        self.assertAlmostEqual(d % 360, row["dir_deg"] % 360, delta=0.1)
                    # Etiquetas: nominales ×100 en INDRA/OACI/OACI56, ISA en WAFS
                    if mode == "WAFS":
                        self.assertIn(300.9, [round(lv, 1) for lv in r.levels])
                    else:
                        self.assertIn(300.0, r.levels)

    @unittest.skipIf(ec is None, "sin eccodes")
    def test_campos_constantes_sin_aviso_de_wgrib2(self):
        """Los campos son constantes: 0 bits por punto, referencia = el dato y
        factor decimal 0, así wgrib2 no avisa de la codificación simple."""
        import shutil
        import subprocess
        data, _info = gg.generate_grib([{"fl": 300, "t_c": -44.3, "spd_kt": 57, "dir_deg": 242}],
                                       (-30, -40, -70, -60), 1.0, mode="WAFS", run=RUN, step_h=6)
        gid = ec.codes_new_from_message(data)
        try:
            self.assertEqual(ec.codes_get(gid, "bitsPerValue"), 0)
            self.assertEqual(ec.codes_get(gid, "decimalScaleFactor"), 0)
            self.assertEqual(ec.codes_get_long(gid, "centre"), 65535)       # «Missing value»
            self.assertEqual(ec.codes_get(gid, "tablesVersion"), 25)
            self.assertAlmostEqual(float(ec.codes_get_values(gid)[0]), -44.3 + 273.15, places=4)
        finally:
            ec.codes_release(gid)
        exe = shutil.which("wgrib2")
        if not exe:
            self.skipTest("sin wgrib2")
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "c.grib2")
            open(p, "wb").write(data)
            r = subprocess.run([exe, "-s", p], capture_output=True, text=True)
            self.assertNotIn("may differ from WMO standard", r.stderr)
            self.assertIn("TMP:300.9 mb", r.stdout)

    @unittest.skipIf(ec is None, "sin eccodes")
    def test_errores(self):
        with self.assertRaises(ValueError):
            gg.generate_grib([{"fl": 305, "t_c": 0, "spd_kt": 0, "dir_deg": 0}], ZONE, 1.0)


class TestDialogoGenerar(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = config.CONFIG_PATH
        config.CONFIG_PATH = os.path.join(self._tmp.name, "config.json")
        self.w = None

    def tearDown(self):
        if self.w is not None:
            self.w.close()
            self.w.deleteLater()
            _app.processEvents()
        config.CONFIG_PATH = self._old
        self._tmp.cleanup()

    def _dialog(self, **kw):
        from app.dialogs.generate_dialog import GenerateGribDialog
        cfg = dict(config.DEFAULTS)
        cfg.update(kw)
        self.w = GenerateGribDialog(None, cfg=cfg, dest_dir=self._tmp.name)
        self.w.show()
        _app.processEvents()
        return self.w

    def _fls(self):
        return [r["fl"] for r in self.w._rows(strict=False)]

    def test_perfil_fdp_lleva_la_grilla_a_1_grado(self):
        """Generar no regrilla: el perfil FDP cambia la resolución de la
        grilla a 1° (la única que lee el FDP de INDRA)."""
        d = self._dialog(generate_res_deg=0.25)
        self.assertEqual(d.resolution(), 0.25)
        box = d.save_box
        box.cb_profile.setCurrentIndex(box.cb_profile.findData("fdp"))
        box.cb_profile.activated.emit(box.cb_profile.currentIndex())
        self.assertEqual(d.resolution(), 1.0)
        # y la grilla FDP Arg (modo Grilla): 51 × 36 puntos; y el modo INDRA
        from app import areas as A
        self.assertEqual(d.area_mode(), "grid")
        self.assertEqual(d.region(), A.FDP_REGION)
        self.assertEqual(d._mode, "INDRA")
        lats, lons, _zone = gg.grid_axes(d.region(), d.resolution())
        self.assertEqual((len(lons), len(lats)), (51, 36))
        self.assertIn("grilla 51 × 36 puntos", d.lbl_size.text())
        box.cb_profile.setCurrentIndex(box.cb_profile.findData("gfs"))     # sin regrillado: no la toca
        box.cb_profile.activated.emit(box.cb_profile.currentIndex())
        self.assertEqual(d.resolution(), 1.0)
        # El radio «Grilla» a mano elige la zona y la resolución, también desde «Por FIR»
        d.rb_fir.setChecked(True)
        d.cb_res.setCurrentIndex(d.cb_res.findData(0.25))
        d.rb_grid.setChecked(True)
        self.assertEqual((d.area_mode(), d.region(), d.resolution()), ("grid", A.FDP_REGION, 1.0))
        self.assertIn("grilla 51 × 36 puntos", d.lbl_size.text())
        self.assertTrue(d.output_path().endswith("_FDPARG_INDRA.grib2"))

    def test_tabla_por_modo(self):
        d = self._dialog(wafs_mode="INDRA")
        self.assertEqual(d._mode, "INDRA")
        self.assertTrue(d.mode_buttons["INDRA"].isChecked())
        self.assertEqual(self._fls(), sorted(flt.INDRA14, reverse=True))
        self.assertIn("(nominal)", d.table.item(0, 1).text())
        # T arranca en la ISA del FL; viento 0
        row0 = d._rows()[0]
        self.assertAlmostEqual(row0["t_c"], round(gg.isa_temp_c(row0["fl"]), 1), delta=0.05)
        self.assertEqual(row0["spd_kt"], 0.0)
        self.assertEqual(d._selected_row(), 13)                    # al entrar, elegida la última (abajo)
        d.mode_buttons["OACI"].click()
        self.assertEqual(len(self._fls()), 17)
        self.assertEqual(d._selected_row(), 16)
        d.mode_buttons["WAFS"].click()
        self.assertEqual(len(self._fls()), 56)
        self.assertNotIn("nominal", d.table.item(0, 1).text())     # etiqueta ISA
        self.assertIn("modo WAFS", d.lbl_levels.text())
        # Al cambiar de modo se conservan los valores escritos en los FL comunes
        d.table.item(0, 3).setText("80")                            # FL600 viento 80 kt
        d.mode_buttons["OACI56"].click()
        self.assertEqual(d._rows()[0]["spd_kt"], 80.0)
        self.assertIn("(nominal)", d.table.item(0, 1).text())

    def test_botones_de_la_tabla(self):
        d = self._dialog(wafs_mode="OACI")
        d.table.selectRow(2)
        d.table.item(2, 2).setText("-33.3")
        d.table.item(2, 3).setText("45")
        d.table.item(2, 5).setText("250")
        d._copy_down()
        rows = d._rows()
        self.assertTrue(all(r["spd_kt"] == 45.0 and r["dir_deg"] == 250.0 and r["t_c"] == -33.3
                            for r in rows[2:]))
        self.assertNotEqual(rows[0]["spd_kt"], 45.0)                # las de arriba no
        d._fill_isa()
        self.assertAlmostEqual(d._rows()[2]["t_c"], gg.isa_temp_c(rows[2]["fl"]), delta=0.05)
        # Agregar: FL+10 encima de la elegida (aunque exista), con su viento;
        # la elegida sigue siéndolo; los botones de modo se destildan
        n = d.table.rowCount()
        d._select_row(3)                                            # FL410 (60 kt / 250° tras copiar)
        d._add_row()
        self.assertEqual(d.table.rowCount(), n + 1)
        self.assertEqual(self._fls()[3], 420)
        self.assertEqual(d._rows(strict=False)[3]["spd_kt"], 45.0)
        self.assertAlmostEqual(d._rows(strict=False)[3]["t_c"], gg.isa_temp_c(420), delta=0.05)
        self.assertEqual(d._selected_row(), 4)                      # FL410 sigue elegida
        self.assertFalse(d.mode_buttons["OACI"].isChecked())
        self.assertEqual(d._mode, "OACI")                           # el etiquetado sigue siendo del modo
        d._select_row(4)
        d._add_row()                                                # FL420 otra vez: repetido
        self.assertEqual(self._fls()[4], 420)
        self.assertEqual(d.table.item(4, 1).text(), "repetido")
        self.assertEqual(d.table.item(3, 1).text(), "repetido")
        self.assertEqual(d._selected_row(), 5)                      # FL410 sigue elegida
        # Quitar: se va la elegida y pasa a la de abajo
        d._select_row(4)                                            # el FL420 repetido
        d._remove_row()
        self.assertEqual(d._selected_row(), 4)
        self.assertEqual(self._fls()[4], 410)
        self.assertNotEqual(d.table.item(3, 1).text(), "repetido")
        d._select_row(3)
        d._remove_row()
        self.assertEqual(d.table.rowCount(), n)
        self.assertEqual(self._fls()[3], 410)
        self.assertTrue(d.mode_buttons["OACI"].isChecked())         # vuelve a coincidir
        # Quitar la última de abajo elige la nueva última; sin filas, nada
        d._select_row(d.table.rowCount() - 1)
        d._remove_row()
        self.assertEqual(d._selected_row(), d.table.rowCount() - 1)
        while d.table.rowCount():
            d._remove_row()
        self.assertIsNone(d._selected_row())
        d._add_row()                                                # sin filas: FL050 elegida
        self.assertEqual(self._fls(), [50])
        self.assertEqual(d._selected_row(), 0)

    def test_aumento_en_la_tabla(self):
        """Columnas «Aumento»: casilla + «+5/°» con flechas, por fila; por
        defecto sin tildar (0). Copiar hacia abajo y Agregar FL las llevan;
        el modo las conserva; Tab saltea esas columnas."""
        from app.dialogs.generate_dialog import (_IncCell, COL_SPD, COL_SPD_INC, COL_DIR, COL_DIR_INC,
                                                 COL_FL)
        d = self._dialog(wafs_mode="INDRA")
        cell = d.table.cellWidget(0, COL_SPD_INC)
        self.assertIsInstance(cell, _IncCell)
        self.assertFalse(cell.chk.isChecked())
        self.assertFalse(cell.spin.isEnabled())
        self.assertEqual(cell.spin.value(), 5)
        self.assertEqual(cell.spin.text(), "+5/°")
        self.assertEqual(cell.spin.maximum(), 100)
        self.assertEqual(d.table.cellWidget(0, COL_DIR_INC).spin.maximum(), 180)
        self.assertTrue(all(r["spd_inc"] == 0.0 and r["dir_inc"] == 0.0 for r in d._rows()))
        cell.chk.setChecked(True)
        self.assertTrue(cell.spin.isEnabled())
        self.assertEqual(d._rows()[0]["spd_inc"], 5.0)
        cell.spin.setValue(8)
        self.assertEqual(d._rows()[0]["spd_inc"], 8.0)
        cell.chk.setChecked(False)
        self.assertEqual(d._rows()[0]["spd_inc"], 0.0)
        self.assertEqual(cell.spin.value(), 8)                      # destildar no borra el número
        cell.set_value(5)
        d.table.cellWidget(0, COL_DIR_INC).set_value(10)
        self.assertEqual((d._rows()[0]["spd_inc"], d._rows()[0]["dir_inc"]), (5.0, 10.0))
        self.assertEqual(d._rows()[1]["spd_inc"], 0.0)              # por capa
        d._select_row(0)
        d._copy_down()
        self.assertTrue(all(r["spd_inc"] == 5.0 and r["dir_inc"] == 10.0 for r in d._rows()))
        d.table.cellWidget(3, COL_DIR_INC).set_value(0)
        d._select_row(3)
        d._add_row()                                                # hereda el viento y sus aumentos
        self.assertEqual((d._rows()[3]["spd_inc"], d._rows()[3]["dir_inc"]), (5.0, 0.0))
        d.mode_buttons["OACI"].click()                              # se conservan por FL
        self.assertEqual(d._rows()[0]["dir_inc"], 10.0)
        self.assertEqual(d._rows()[0]["spd_inc"], 5.0)
        # Tab: Viento → Aumento se saltea hasta Dir; tras el último Aumento, FL de la fila siguiente
        d.table.setCurrentCell(2, COL_SPD)
        _app.processEvents(); _app.processEvents()
        d.table.setCurrentCell(2, COL_SPD_INC)
        _app.processEvents(); _app.processEvents()
        self.assertEqual((d.table.currentRow(), d.table.currentColumn()), (2, COL_DIR))
        d.table.setCurrentCell(2, COL_DIR_INC)
        _app.processEvents(); _app.processEvents()
        self.assertEqual((d.table.currentRow(), d.table.currentColumn()), (3, COL_FL))
        d.table.setCurrentCell(3, COL_DIR)
        _app.processEvents(); _app.processEvents()
        d.table.setCurrentCell(3, COL_SPD_INC)                      # hacia atrás: Viento
        _app.processEvents(); _app.processEvents()
        self.assertEqual((d.table.currentRow(), d.table.currentColumn()), (3, COL_SPD))
        last = d.table.rowCount() - 1
        d.table.setCurrentCell(last, COL_DIR)
        _app.processEvents(); _app.processEvents()
        d.table.setCurrentCell(last, COL_DIR_INC)                   # última fila: se queda en Dir
        _app.processEvents(); _app.processEvents()
        self.assertEqual((d.table.currentRow(), d.table.currentColumn()), (last, COL_DIR))

    def test_edicion_de_celdas(self):
        """Clic o Tab ponen la celda en edición con el valor preseleccionado;
        Presión se saltea; Enter aplica y Esc deja la fila elegida sin editar."""
        from PyQt6.QtCore import Qt as _Qt
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QAbstractItemView, QLineEdit
        from app.dialogs.generate_dialog import _CellDelegate, COL_P, COL_T, COL_SPD, COL_FL
        d = self._dialog(wafs_mode="INDRA")
        self.assertIsInstance(d.table.itemDelegate(), _CellDelegate)
        # Al entrar hay fila elegida pero sin edición (la eligió el programa)
        _app.processEvents(); _app.processEvents()
        self.assertEqual(d._selected_row(), 13)
        self.assertNotEqual(d.table.state(), QAbstractItemView.State.EditingState)

        def editor():
            # el editor vivo (los anteriores quedan hasta el deleteLater)
            _app.processEvents()
            eds = [e for e in d.table.findChildren(QLineEdit, "TableCellEditor") if e.isVisible()]
            return eds[-1] if eds else None
        d.table.setCurrentCell(2, COL_T)
        _app.processEvents(); _app.processEvents()
        self.assertEqual(d.table.state(), QAbstractItemView.State.EditingState)
        ed = editor()
        self.assertIsNotNone(ed)
        self.assertEqual(ed.text(), d.table.item(2, COL_T).text())
        self.assertEqual(ed.selectedText(), ed.text())              # preseleccionado
        self.assertEqual(ed.cursorPosition(), len(ed.text()))       # cursor a la derecha
        self.assertEqual(ed.alignment() & _Qt.AlignmentFlag.AlignRight, _Qt.AlignmentFlag.AlignRight)
        self.assertEqual(ed.geometry(), d.table.visualRect(d.table.model().index(2, COL_T)))
        # (el fondo opaco lo pone la hoja de estilos, que en la suite completa
        # desactiva autoFillBackground: no se comprueba ese atributo)
        # ← suelta la selección y deja el cursor para insertar; Backspace borra un carácter
        QTest.keyClick(ed, _Qt.Key.Key_Left)
        self.assertEqual(ed.selectedText(), "")
        cur = d.table.item(2, COL_T).text()                         # p. ej. «-56.5»
        self.assertEqual(ed.cursorPosition(), len(cur) - 1)         # un lugar a la izquierda del final
        QTest.keyClick(ed, _Qt.Key.Key_Backspace)                   # borra el carácter anterior
        self.assertEqual(ed.text(), cur[:-2] + cur[-1])
        QTest.keyClicks(ed, "9")                                    # inserta donde está el cursor
        self.assertEqual(ed.text(), cur[:-2] + "9" + cur[-1])
        ed.setText(cur); ed.selectAll()
        # Una tecla reemplaza; Enter aplica
        QTest.keyClicks(ed, "-41.5")
        QTest.keyClick(ed, _Qt.Key.Key_Return)
        _app.processEvents()
        self.assertEqual(d.table.item(2, COL_T).text(), "-41.5")
        # Tab pasa a la celda siguiente y la abre en edición
        QTest.keyClick(d.table, _Qt.Key.Key_Tab)
        _app.processEvents(); _app.processEvents()
        self.assertEqual((d.table.currentRow(), d.table.currentColumn()), (2, COL_SPD))
        self.assertEqual(d.table.state(), QAbstractItemView.State.EditingState)
        # Esc: sale de la edición sin cambiar, la fila sigue elegida
        ed = editor()
        QTest.keyClicks(ed, "99")
        QTest.keyClick(ed, _Qt.Key.Key_Escape)
        _app.processEvents()
        self.assertNotEqual(d.table.state(), QAbstractItemView.State.EditingState)
        self.assertEqual(d.table.item(2, COL_SPD).text(), "0")
        self.assertEqual(d._selected_row(), 2)
        self.assertTrue(d.isVisible())                              # Esc no cierra el diálogo
        # Esc llegando al diálogo mientras se edita: sale de la edición y nada más
        d.table.setCurrentCell(2, COL_T)
        _app.processEvents(); _app.processEvents()
        self.assertEqual(d.table.state(), QAbstractItemView.State.EditingState)
        QTest.keyClick(d, _Qt.Key.Key_Escape)
        _app.processEvents()
        self.assertTrue(d.isVisible())
        self.assertNotEqual(d.table.state(), QAbstractItemView.State.EditingState)
        self.assertEqual(d._selected_row(), 2)
        # Esc con el foco en la tabla sin editar: tampoco cierra
        d.table.setFocus()
        QTest.keyClick(d.table, _Qt.Key.Key_Escape)
        _app.processEvents()
        self.assertTrue(d.isVisible())
        # Quitar un nivel deja la fila elegida sin edición
        d._remove_row()
        _app.processEvents(); _app.processEvents()
        self.assertEqual(d._selected_row(), 2)
        self.assertNotEqual(d.table.state(), QAbstractItemView.State.EditingState)
        # La columna Presión se saltea en el sentido del movimiento
        d.table.setCurrentCell(2, COL_FL)
        _app.processEvents()
        d.table.setCurrentCell(2, COL_P)
        _app.processEvents(); _app.processEvents()
        self.assertEqual(d.table.currentColumn(), COL_T)
        d.table.setCurrentCell(2, COL_P)
        _app.processEvents(); _app.processEvents()
        self.assertEqual(d.table.currentColumn(), COL_FL)

    def test_global_a_1p25(self):
        """Botón «Global» y 1,25°: 288 × 145 puntos, como el WAFS clásico."""
        d = self._dialog(download_area_mode="manual")
        btn = [b for b in d.findChildren(QPushButton) if b.text() == "Global"][0]
        btn.click()
        d.cb_res.setCurrentIndex(d.cb_res.findData(1.25))
        self.assertEqual(d.region(), (90.0, -90.0, -180.0, 180.0))
        self.assertIn("grilla 288 × 145 puntos", d.lbl_size.text())
        self.assertIn("_1p25_MANUAL_", d.output_path())

    def test_area_y_grilla(self):
        d = self._dialog(download_area_mode="manual", download_manual_region=[-20.3, -45.7, -75.2, -50.1])
        self.assertEqual(d.area_mode(), "manual")
        self.assertEqual(d.region(), (-20.3, -45.7, -75.2, -50.1))
        self.assertIn("grilla 102 × 103 puntos", d.lbl_size.text())      # 0,25°: 75.25W–50W × 20.25S–45.75S
        self.assertIn("20.25S–45.75S, 75.25W–50W", d.lbl_size.text())
        d.cb_res.setCurrentIndex(d.cb_res.findData(1.0))
        self.assertIn("grilla 27 × 27 puntos", d.lbl_size.text())        # 1°: 76W–50W × 20S–46S
        self.assertIn("20S–46S, 76W–50W", d.lbl_size.text())
        d.rb_fir.setChecked(True)
        d._set_all_areas(False)
        self.assertIn("Marcá al menos una FIR", d.lbl_size.text())
        d._area_checks["SAEF"].setChecked(True)
        env = d.fir_envelope()
        self.assertIsNotNone(env)
        self.assertEqual(d.region(), env)
        self.assertIn("margen 1° incluido", d.lbl_size.text())
        self.assertTrue(d.output_path().endswith("_1p00_SAEF_OACI.grib2"), d.output_path())
        d.cb_wind.setCurrentIndex(d.cb_wind.findData("dirspeed"))
        self.assertTrue(d.output_path().endswith("_SAEF_OACI_dirvel.grib2"))
        d.name.setText("mio")
        self.assertTrue(d.output_path().endswith(os.path.join(self._tmp.name, "mio.grib2")))

    @unittest.skipIf(ec is None, "sin eccodes")
    def test_genera_y_abre_en_el_visor(self):
        from app.main_window import MainWindow
        from app.sources.base import read_provenance
        win = MainWindow()
        win.show()
        _app.processEvents()
        try:
            self.assertEqual(win._act_generate.shortcut().toString(), "Ctrl+G")
            from app.dialogs.generate_dialog import GenerateGribDialog
            d = GenerateGribDialog(win, cfg=win._cfg, dest_dir=self._tmp.name)
            self.w = d
            d.show()
            _app.processEvents()
            d.mode_buttons["OACI"].click()
            d.table.selectRow(0)
            d.table.item(0, 3).setText("30")
            d.table.item(0, 5).setText("270")
            d._copy_down()
            d.rb_fir.setChecked(True)
            d._set_all_areas(False)
            d._area_checks["SAEF"].setChecked(True)
            d.cb_res.setCurrentIndex(d.cb_res.findData(1.0))
            d._generate()
            _app.processEvents()
            self.assertIsNotNone(d.generated_path)
            self.assertTrue(os.path.exists(d.generated_path))
            self.assertIn("153 mensajes", d.lbl_status.text())      # 17 niveles × 3 campos × 3 plazos (6, 9, 12)
            self.assertIn("_f006-f012_", d.generated_path)
            self.assertEqual(d.hours(), [6, 9, 12])
            self.assertIn("3 plazo(s)", d.lbl_valid.text())
            prov = read_provenance(d.generated_path)
            self.assertEqual(prov["fuente"], "generado")
            self.assertEqual(prov["area"]["codigos"], ["SAEF"])
            self.assertEqual(len(prov["tabla"]), 17)
            self.assertEqual(prov["tabla"][0]["spd_inc"], 0.0)
            self.assertNotIn("aumento", prov)
            self.assertEqual(win._cfg["generate_res_deg"], 1.0)
            self.assertEqual(win._cfg["download_area_codes"], ["SAEF"])
            win.open_file(d.generated_path)
            _app.processEvents()
            r = win._reader
            self.assertTrue(r.is_wafs)
            self.assertEqual(r.fl_mode, "OACI")
            self.assertEqual(len(r.levels), 17)
            self.assertEqual([s.hours for s in r.steps], [6, 9, 12])
            self.assertIn("FUENTE: Generado a mano", win.panel.lbl_source.text())
            self.assertIn("área SAEF", win.panel.lbl_source.text())
            self.assertIn("1,00°", win.panel.lbl_source.text())
            u, v, _t, _ = r.get_level_fields(0, 300.0)
            from app.grib_reader import speed_dir_from_uv
            spd, direc = speed_dir_from_uv(float(u.mean()), float(v.mean()))
            self.assertAlmostEqual(spd, 30.0, delta=0.05)
            self.assertAlmostEqual(direc, 270.0, delta=0.1)
            # Con aumento en una capa y orden S→N, O→E: la esquina SO vale lo de la fila
            from app.dialogs.generate_dialog import COL_SPD_INC
            d.table.cellWidget(0, COL_SPD_INC).set_value(5)         # FL530
            d.save_box.cb_scan.setCurrentIndex(d.save_box.cb_scan.findData("sn_we"))
            d.name.setText("aumento")
            d._generate()
            _app.processEvents()
            prov = read_provenance(d.generated_path)
            self.assertEqual(prov["aumento"]["fls"], [530])
            self.assertEqual(prov["aumento"]["esquina"], "SO")
            self.assertEqual(prov["guardado"]["scan"], "sn_we")
            win.open_file(d.generated_path)
            _app.processEvents()
            r = win._reader
            self.assertEqual(len(r.levels), 17)
            u, v, _t, _ = r.get_level_fields(0, 100.0)              # FL530 = 100 hPa nominal
            zone = prov["zona"]
            lat_sw, lon_sw = zone[1], zone[2]
            lats_r, lons_r = r.lats, r.lons
            j = int(np.argmin(np.abs(np.asarray(lats_r) - lat_sw)))
            i = int(np.argmin(np.abs(np.asarray(lons_r) - lon_sw)))
            s_sw, _ = speed_dir_from_uv(float(u[j, i]), float(v[j, i]))
            self.assertAlmostEqual(s_sw, 30.0, delta=0.05)
            j2 = int(np.argmin(np.abs(np.asarray(lats_r) - (lat_sw + 2.0))))
            i2 = int(np.argmin(np.abs(np.asarray(lons_r) - (lon_sw + 1.0))))
            s2, d2 = speed_dir_from_uv(float(u[j2, i2]), float(v[j2, i2]))
            self.assertAlmostEqual(s2, 45.0, delta=0.05)            # 2° de latitud y 1° de longitud: +15
            self.assertAlmostEqual(d2, 270.0, delta=0.1)
            u, v, _t, _ = r.get_level_fields(0, 300.0)
            self.assertLess(float(np.ptp(np.hypot(u, v))), 1e-6)    # las demás capas, uniformes
        finally:
            win.close()
            win.deleteLater()
            _app.processEvents()


if __name__ == "__main__":
    unittest.main()
