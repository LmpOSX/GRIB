# -*- coding: utf-8 -*-
"""Niveles de presión que pide la descarga según el modo (INDRA, OACI,
OACI56, WAFS) y la casilla «Convertir a WAFS»: la función pura
fl_table.download_levels y los botones del diálogo «Obtener datos».
Se corren con QT_QPA_PLATFORM=offscreen."""
import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from app import config  # noqa: E402
from app import fl_table as flt  # noqa: E402
from app.gfs_download import ALL_LEVELS, EXTRA_LEVELS  # noqa: E402
from app.sources.ecmwf import ECMWF_LEVELS  # noqa: E402
from app.dialogs import glass_dialog  # noqa: E402

glass_dialog._apply_dialog_blur = lambda w: None
_app = QApplication.instance() or QApplication([])


class TestDownloadLevels(unittest.TestCase):
    def test_nominales_sin_convertir(self):
        r = flt.download_levels("INDRA", ALL_LEVELS, convert=False)
        self.assertEqual(r["levels"], [flt.nominal_hpa(fl) for fl in flt.INDRA14])
        self.assertEqual((r["missing"], r["interpolated"]), ([], False))
        r = flt.download_levels("OACI", ALL_LEVELS, convert=False)
        self.assertEqual(len(r["levels"]), 17)
        self.assertEqual(r["levels"][:4], [850, 750, 700, 600])
        self.assertIn(125, r["levels"])                   # FL480: intermedio del GFS
        # El ECMWF no tiene 750, 450, 350, 275, 225, 175 ni 125
        r = flt.download_levels("OACI", ECMWF_LEVELS, convert=False)
        self.assertEqual(r["levels"], [850, 700, 600, 500, 400, 300, 250, 200, 150, 100])
        self.assertEqual(r["missing"], [80, 210, 270, 320, 360, 410, 480])

    def test_rango_completo_para_interpolar(self):
        # Con conversión: de la ISA de FL050 (843,1) a la de FL600 (71,7) más
        # un nivel por fuera de cada extremo
        for mode, conv in (("INDRA", True), ("OACI", True), ("OACI56", False), ("WAFS", False)):
            r = flt.download_levels(mode, ALL_LEVELS, convert=conv)
            self.assertTrue(r["interpolated"], mode)
            self.assertEqual((r["levels"][0], r["levels"][-1], len(r["levels"])), (850, 70, 32), mode)
            self.assertNotIn(875, r["levels"])
            self.assertTrue(all(lv in r["levels"] for lv in EXTRA_LEVELS if lv < 850), mode)
        # Sin ampliar hasta FL600: hasta la ISA de FL530 (100,4) y el 100
        r = flt.download_levels("OACI", ALL_LEVELS, convert=True, extend=False)
        self.assertEqual((r["levels"][0], r["levels"][-1], len(r["levels"])), (850, 100, 31))
        r = flt.download_levels("OACI", ECMWF_LEVELS, convert=True)
        self.assertEqual(r["levels"], [850, 700, 600, 500, 400, 300, 250, 200, 150, 100, 50])
        # Sin niveles no hay nada que pedir
        self.assertEqual(flt.download_levels("OACI", [], convert=True)["levels"], [])


class TestBotonesDeModo(unittest.TestCase):
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
        from app.dialogs.download_dialog import DownloadDialog
        cfg = dict(config.DEFAULTS)
        cfg.update(kw)
        self.w = DownloadDialog(None, cfg=cfg, dest_dir=self._tmp.name)
        self.w.show()
        _app.processEvents()
        return self.w

    def _on(self):
        return [lv for lv, c in self.w.level_checks.items() if c.isChecked()]

    def test_arranca_con_el_modo_de_preferencias(self):
        d = self._dialog(wafs_mode="INDRA", wafs_convert=False)
        self.assertEqual(d._mode, "INDRA")
        self.assertTrue(d.mode_buttons["INDRA"].isChecked())
        self.assertFalse(d.chk_wafs.isChecked())
        self.assertEqual(self._on(), [flt.nominal_hpa(fl) for fl in flt.INDRA14])
        self.assertTrue(d.form.widget("niveles_intermedios").isChecked())   # 275/225/175
        self.assertIn("sin convertir", d.lbl_levels_hint.text())
        self.assertEqual(d.job().suffix, "")
        self.assertIsNone(d._wafs_options())

    def test_convertir_cambia_los_niveles_y_el_modo_va_en_las_opciones(self):
        d = self._dialog(wafs_mode="OACI", wafs_convert=False)
        self.assertEqual(len(self._on()), 17)
        d.chk_wafs.setChecked(True)
        self.assertEqual((len(self._on()), max(self._on()), min(self._on())), (32, 850, 70))
        self.assertIn("interpolar 17 FL", d.lbl_levels_hint.text())
        self.assertEqual(d._wafs_options()["mode"], "OACI")
        d.mode_buttons["INDRA"].click()
        self.assertEqual(d._wafs_options()["mode"], "INDRA")
        self.assertEqual(len(self._on()), 32)
        d.chk_wafs.setChecked(False)
        self.assertEqual(len(self._on()), 14)

    def test_oaci56_y_wafs_bloquean_la_casilla(self):
        d = self._dialog(wafs_convert=False)
        for mode in ("OACI56", "WAFS"):
            d.mode_buttons[mode].click()
            self.assertTrue(d.chk_wafs.isChecked(), mode)
            self.assertFalse(d.chk_wafs.isEnabled(), mode)
            self.assertIn("interpolado a presiones reales", d.chk_wafs.text())
            self.assertIn("siempre se interpolan", d.chk_wafs.toolTip())
            self.assertEqual(len(self._on()), 32, mode)
            self.assertEqual(d._wafs_options()["mode"], mode)
            self.assertEqual(d.job().suffix, "_wafs")
            self.assertIn("56 FL", d.lbl_levels_hint.text())
        self.assertIn("ISA en Pa", d.lbl_levels_hint.text())
        # Volver a OACI libera la casilla (queda tildada)
        d.mode_buttons["OACI"].click()
        self.assertTrue(d.chk_wafs.isEnabled())
        self.assertTrue(d.chk_wafs.isChecked())

    def test_a_mano_se_suma_y_todos_sale_del_modo(self):
        d = self._dialog(wafs_mode="OACI", wafs_convert=False)
        d.level_checks[1000].setChecked(True)
        self.assertEqual(d._mode, "OACI")
        self.assertEqual(len(self._on()), 18)
        self.assertIn(1000, d.job().levels)
        d.level_checks[750].setChecked(False)
        self.assertIn("sin nivel para FL080", d.lbl_levels_hint.text())
        todos = [b for b in d.mode_row_w.findChildren(type(d.mode_buttons["OACI"])) if b.text() == "Todos"][0]
        todos.click()
        # La línea de ayuda reserva dos renglones aunque el texto tenga uno
        self.assertGreaterEqual(d.lbl_levels_hint.minimumHeight(),
                                2 * d.lbl_levels_hint.fontMetrics().lineSpacing())
        self.assertEqual(d.mode_buttons["OACI56"].text(), "OACI (56)")
        self.assertEqual(d.mode_buttons["WAFS"].text(), "WAFS (56)")
        self.assertIsNone(d._mode)
        self.assertFalse(any(b.isChecked() for b in d.mode_buttons.values()))
        self.assertEqual(len(self._on()), len(ALL_LEVELS))
        self.assertIn("a mano", d.lbl_levels_hint.text())
        self.assertTrue(d.chk_wafs.isEnabled())
        d.chk_wafs.setChecked(True)
        self.assertEqual(d._wafs_options()["mode"], "OACI")    # el de Preferencias

    def test_intermedios_a_1p00_no_se_pueden(self):
        d = self._dialog(sources={"gfs": {"enabled": True, "params": {"resolucion": "1p00"}}})
        self.assertEqual(d._mode, "OACI")
        self.assertFalse(d.form.widget("niveles_intermedios").isChecked())
        self.assertFalse(d.level_checks[275].isEnabled())
        self.assertEqual(len(self._on()), 17)                  # 850–70 sin intermedios
        self.assertIn("faltan 15 de los 32", d.lbl_levels_hint.text())
        self.assertIsNone(d.source.validate(d.job()))
        d.form.widget("solo_0p25").setChecked(True)
        d.mode_buttons["OACI"].click()
        self.assertTrue(d.form.widget("niveles_intermedios").isChecked())
        self.assertEqual(len(self._on()), 32)

    def test_cambiar_de_fuente_reajusta_el_alto(self):
        from app.sources import get_source
        if get_source("smn_wrf") is None:
            self.skipTest("sin fuente SMN")
        d = self._dialog(sources={"smn_wrf": {"enabled": True}, "gfs": {"enabled": True}}, source="smn_wrf")
        if d.cb_source.findData("smn_wrf") < 0:
            self.skipTest("SMN no habilitada")
        d.cb_source.setCurrentIndex(d.cb_source.findData("smn_wrf"))
        _app.processEvents()
        h_smn = d.height()
        d.cb_source.setCurrentIndex(d.cb_source.findData("gfs"))
        _app.processEvents()
        # El alto natural, acotado a la pantalla (en offscreen la pantalla es
        # de 800 px y el tope de GlassDialog es pantalla − 40)
        cap = d.screen().availableGeometry().height() - 40
        want = min(d.sizeHint().height(), cap)
        self.assertGreater(d.height(), h_smn + 100)
        self.assertGreaterEqual(d.height(), want - 2)
        if d.sizeHint().height() <= cap:                                       # no aplastado
            self.assertEqual(d.level_grid_w.height(), d.level_grid_w.sizeHint().height())
        d.cb_source.setCurrentIndex(d.cb_source.findData("smn_wrf"))
        _app.processEvents()
        self.assertLess(d.height(), h_smn + 60)                               # vuelve a achicarse

    def test_otras_fuentes(self):
        from app.sources import get_source
        d = self._dialog(wafs_convert=False)
        for key, n_nominal, missing in (("ecmwf", 10, "FL080"), ("icon", 10, "FL080")):
            if get_source(key) is None or d.cb_source.findData(key) < 0:
                continue
            d.cb_source.setCurrentIndex(d.cb_source.findData(key))
            self.assertEqual(d._mode, "OACI")
            self.assertEqual(len(self._on()), n_nominal, key)
            self.assertIn(missing, d.lbl_levels_hint.text())
        if get_source("smn_wrf") is not None and d.cb_source.findData("smn_wrf") >= 0:
            d.cb_source.setCurrentIndex(d.cb_source.findData("smn_wrf"))
            self.assertFalse(d.mode_row_w.isVisibleTo(d))
            self.assertFalse(d.chk_wafs.isEnabled())
            self.assertEqual(d.lbl_levels_hint.text(), "")


if __name__ == "__main__":
    unittest.main()
