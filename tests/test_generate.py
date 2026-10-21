# -*- coding: utf-8 -*-
"""Generador de GRIB a mano: módulo puro y diálogo «Generar GRIB…»."""
import datetime as dt
import os
import tempfile
import unittest

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

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

    def test_nombre_y_procedencia(self):
        self.assertEqual(gg.default_basename(RUN, 6, 0.25, "SAEF+SACF", "uv", "OACI"),
                         "generado_20261021_12z_f006_0p25_SAEF+SACF_OACI")
        self.assertEqual(gg.default_basename(RUN, 0, 1.0, "MANUAL", "dirspeed", "WAFS"),
                         "generado_20261021_12z_f000_1p00_MANUAL_WAFS_dirvel")

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
        d.table.item(2, 4).setText("250")
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

    def test_edicion_de_celdas(self):
        """Clic o Tab ponen la celda en edición con el valor preseleccionado;
        Presión se saltea; Enter aplica y Esc deja la fila elegida sin editar."""
        from PyQt6.QtCore import Qt as _Qt
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QAbstractItemView, QLineEdit
        from app.dialogs.generate_dialog import _CellDelegate, COL_P, COL_T, COL_SPD, COL_FL
        d = self._dialog(wafs_mode="INDRA")
        self.assertIsInstance(d.table.itemDelegate(), _CellDelegate)

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
        self.assertEqual(ed.alignment() & _Qt.AlignmentFlag.AlignHCenter, _Qt.AlignmentFlag.AlignHCenter)
        self.assertEqual(ed.geometry(), d.table.visualRect(d.table.model().index(2, COL_T)))
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
        # La columna Presión se saltea en el sentido del movimiento
        d.table.setCurrentCell(2, COL_FL)
        _app.processEvents()
        d.table.setCurrentCell(2, COL_P)
        _app.processEvents(); _app.processEvents()
        self.assertEqual(d.table.currentColumn(), COL_T)
        d.table.setCurrentCell(2, COL_P)
        _app.processEvents(); _app.processEvents()
        self.assertEqual(d.table.currentColumn(), COL_FL)

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
            d.table.item(0, 4).setText("270")
            d._copy_down()
            d.rb_fir.setChecked(True)
            d._set_all_areas(False)
            d._area_checks["SAEF"].setChecked(True)
            d.cb_res.setCurrentIndex(d.cb_res.findData(1.0))
            d._generate()
            _app.processEvents()
            self.assertIsNotNone(d.generated_path)
            self.assertTrue(os.path.exists(d.generated_path))
            self.assertIn("51 mensajes", d.lbl_status.text())
            prov = read_provenance(d.generated_path)
            self.assertEqual(prov["fuente"], "generado")
            self.assertEqual(prov["area"]["codigos"], ["SAEF"])
            self.assertEqual(len(prov["tabla"]), 17)
            self.assertEqual(win._cfg["generate_res_deg"], 1.0)
            self.assertEqual(win._cfg["download_area_codes"], ["SAEF"])
            win.open_file(d.generated_path)
            _app.processEvents()
            r = win._reader
            self.assertTrue(r.is_wafs)
            self.assertEqual(r.fl_mode, "OACI")
            self.assertEqual(len(r.levels), 17)
            self.assertIn("FUENTE: Generado a mano", win.panel.lbl_source.text())
            self.assertIn("área SAEF", win.panel.lbl_source.text())
            self.assertIn("1,00°", win.panel.lbl_source.text())
            u, v, _t, _ = r.get_level_fields(0, 300.0)
            from app.grib_reader import speed_dir_from_uv
            spd, direc = speed_dir_from_uv(float(u.mean()), float(v.mean()))
            self.assertAlmostEqual(spd, 30.0, delta=0.05)
            self.assertAlmostEqual(direc, 270.0, delta=0.1)
        finally:
            win.close()
            win.deleteLater()
            _app.processEvents()


if __name__ == "__main__":
    unittest.main()
