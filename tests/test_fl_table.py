# -*- coding: utf-8 -*-
"""Tabla de niveles de vuelo del generador WAFS: unicidad y monotonía de las
etiquetas OACI56, nominales OACI16 intactos, clasificación de archivos por
modo, conversión y exportación en los cuatro modos con ida y vuelta, y la
selección de nivel (botonera de 16 + lista) en el panel."""
import os
import shutil
import tempfile
import unittest

from app import fl_table as flt

HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(HERE, "data", "WAFS_like_test.grib2")      # modo WAFS (ISA en Pa)
FDP = os.path.join(HERE, "data", "FDP_MULTI.grib2")            # 14 niveles nominales INDRA

try:
    import eccodes  # noqa: F401
    HAVE_EC = True
except Exception:
    HAVE_EC = False
needs_eccodes = unittest.skipUnless(HAVE_EC, "requiere eccodes")

# Nominales del Anexo 3 de OACI para los 16 FL de referencia
ANEXO3 = {50: 850, 80: 750, 100: 700, 140: 600, 180: 500, 240: 400, 270: 350, 300: 300,
          320: 275, 340: 250, 360: 225, 390: 200, 410: 175, 450: 150, 480: 125, 530: 100}


class TestTabla(unittest.TestCase):
    def test_56_filas_literales(self):
        self.assertEqual(len(flt.FL_TABLE), 56)
        self.assertEqual(flt.FLS, list(range(50, 601, 10)))
        self.assertEqual(flt.FL_TABLE[50], (84310, 850))
        self.assertEqual(flt.FL_TABLE[290], (31490, 315))     # literal, no recalculado
        self.assertEqual(flt.FL_TABLE[530], (10040, 100))
        self.assertEqual(flt.FL_TABLE[600], (7170, 60))

    def test_oaci56_unicas_y_decrecientes(self):
        labels = [flt.nominal_hpa(fl) for fl in flt.FLS]
        self.assertEqual(len(set(labels)), 56)
        self.assertEqual(labels, sorted(labels, reverse=True))
        isas = [flt.isa_pa(fl) for fl in flt.FLS]
        self.assertEqual(isas, sorted(isas, reverse=True))
        self.assertEqual(len(set(isas)), 56)

    def test_oaci16_conservan_el_nominal_del_anexo_3(self):
        self.assertEqual(flt.OACI16, sorted(ANEXO3))
        for fl, hpa in ANEXO3.items():
            self.assertEqual(flt.nominal_hpa(fl), hpa, f"FL{fl:03d}")
        self.assertEqual(flt.INDRA14, [fl for fl in flt.OACI16 if fl not in (80, 480)])
        self.assertEqual(len(flt.INDRA14), 14)

    def test_modos(self):
        self.assertEqual(flt.MODES, ["INDRA", "OACI", "OACI56", "WAFS"])
        self.assertEqual(flt.DEFAULT_MODE, "OACI56")
        self.assertEqual(flt.mode_fls("INDRA"), flt.INDRA14)
        self.assertEqual(flt.mode_fls("oaci"), flt.OACI16)
        self.assertEqual(flt.mode_fls("OACI56"), flt.FLS)
        self.assertEqual(flt.mode_fls("WAFS"), flt.FLS)
        with self.assertRaises(ValueError):
            flt.normalize_mode("GFS")
        self.assertEqual(flt.label_pa(50, "WAFS"), 84310)
        self.assertEqual(flt.label_pa(50, "OACI56"), 85000)
        self.assertEqual(flt.label_text(530, "WAFS"), "10040 Pa")
        self.assertEqual(flt.label_text(530, "INDRA"), "100 hPa")
        rows = flt.table_rows("INDRA")
        self.assertEqual(len(rows), 14)
        self.assertEqual(rows[0], (50, 84310, 85000, "850 hPa"))

    def test_fl_desde_pa(self):
        self.assertEqual(flt.fl_from_pa(84310), (50, "isa"))
        self.assertEqual(flt.fl_from_pa(84315), (50, "isa"))          # tolerancia
        self.assertEqual(flt.fl_from_pa(31480), (290, "isa"))         # redondeo viejo de 0,1 hPa
        self.assertEqual(flt.fl_from_pa(85000), (50, "nominal"))
        self.assertEqual(flt.fl_from_pa(25000), (340, "isa"))         # coincide en las dos columnas
        self.assertEqual(flt.fl_from_pa(10000), (530, "nominal"))
        self.assertEqual(flt.fl_from_pa(10040), (530, "isa"))
        self.assertEqual(flt.fl_from_pa(100000), (None, None))
        self.assertEqual(flt.fl_from_pa(None), (None, None))

    def test_clasificacion(self):
        isa = [flt.isa_pa(fl) for fl in flt.FLS]
        self.assertEqual(flt.classify(isa)["mode"], "WAFS")
        self.assertTrue(flt.classify(isa)["labeled"])
        self.assertEqual(flt.classify(isa[:5])["mode"], "WAFS")
        indra = [flt.nominal_hpa(fl) * 100 for fl in flt.INDRA14]
        c = flt.classify(indra)
        self.assertEqual((c["mode"], c["labeled"], c["column"]), ("INDRA", True, "nominal"))
        oaci = [flt.nominal_hpa(fl) * 100 for fl in flt.OACI16]
        self.assertEqual(flt.classify(oaci)["mode"], "OACI")
        o56 = [flt.nominal_hpa(fl) * 100 for fl in flt.FLS]
        self.assertEqual(flt.classify(o56)["mode"], "OACI56")
        self.assertTrue(flt.classify(o56)["labeled"])
        # un GFS crudo con 850/700/500/250/100 coincide con nominales pero no alcanza
        gfs = [85000, 70000, 50000, 25000, 10000]
        c = flt.classify(gfs)
        self.assertEqual(c["mode"], "INDRA")
        self.assertFalse(c["labeled"])
        # 1000 hPa no está en ninguna columna
        c = flt.classify([100000, 85000, 70000])
        self.assertIsNone(c["mode"])
        self.assertEqual(c["unrecognized"], [100000])
        self.assertEqual(c["fls"][85000], 50)
        # sólo 250 hPa no es un archivo por FL
        self.assertFalse(flt.classify([25000])["labeled"])
        self.assertEqual(flt.classify([])["mode"], None)


@needs_eccodes
class TestConversionYExportacion(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_deteccion_de_los_archivos_de_prueba(self):
        from app import wafs_format as wf
        d = wf.detect_mode(REF)
        self.assertEqual((d["mode"], d["labeled"], d["column"]), ("WAFS", True, "isa"))
        d = wf.detect_mode(FDP)
        self.assertEqual((d["mode"], d["labeled"], d["column"]), ("INDRA", True, "nominal"))
        self.assertEqual(sorted(d["fls"].values()), flt.INDRA14)
        self.assertTrue(wf.is_wafs(FDP))

    def test_conversion_por_modo(self):
        """Convertir un archivo crudo en cada modo: las etiquetas grabadas
        son las del modo y los FL los que abarca."""
        from app import wafs_format as wf
        src = wf.relabel(REF, "WAFS")        # mismo dato, lo tratamos como origen
        for mode in flt.MODES:
            res = wf.convert_to_wafs(FDP, mode=mode, fl_min=50, fl_max=530)
            self.assertEqual(res.info["modo"], mode)
            det = flt.classify(wf.level_pas(res.data))
            self.assertEqual(det["mode"], mode, mode)
            self.assertTrue(det["labeled"], mode)
            fls = sorted(set(det["fls"].values()))
            self.assertEqual(fls, [fl for fl in flt.mode_fls(mode) if 50 <= fl <= 530], mode)
            for pa, fl in det["fls"].items():
                self.assertEqual(pa, flt.label_pa(fl, mode))
        self.assertIsNotNone(src)

    def test_forzar_conversion_de_niveles_crudos(self):
        from app import wafs_format as wf
        data, info = wf.convert_if_needed(FDP)
        self.assertFalse(info["convertido"])              # parece INDRA: se respeta
        self.assertEqual(info["modo"], "INDRA")
        data2, info2 = wf.convert_if_needed(FDP, force=True, mode="OACI")
        self.assertTrue(info2["convertido"])              # lo que baja de GFS se convierte igual
        self.assertEqual(info2["modo"], "OACI")
        self.assertEqual(flt.classify(wf.level_pas(data2))["mode"], "OACI")

    def test_ida_y_vuelta_en_los_cuatro_modos(self):
        """Exportar → leer recupera el mismo FL (y el mismo dato) en los cuatro modos."""
        import numpy as np
        from app import wafs_format as wf
        from app.grib_reader import GribReader
        r0 = GribReader(REF)
        u0, _v, _t, _i = r0.fields_for_fl(0, 300)
        for mode in flt.MODES:
            res = wf.export_wafs(REF, os.path.join(self.tmp, mode), per_step=False, mode=mode,
                                 basename="x.grib2")
            self.assertEqual(res["modo"], mode)
            self.assertEqual(res["avisos"], [])
            r = GribReader(res["archivos"][0])
            self.assertTrue(r.fl_labeled)
            self.assertEqual(r.fl_mode, mode)
            want = [fl for fl in flt.mode_fls(mode) if fl in r0.fl_levels]
            self.assertEqual(sorted(r.fl_levels), want, mode)
            u, _v, _t, info = r.fields_for_fl(0, 300)
            self.assertEqual(info["mode"], "wafs")
            self.assertEqual(info["p"], 300.9)
            np.testing.assert_allclose(u, u0, rtol=0, atol=1e-6)
            if mode != "WAFS":
                self.assertEqual(info["label_hpa"], 300.0)
                self.assertEqual(r.fl_text(300), "FL300 · 300 hPa (300.9 ISA)")
            else:
                self.assertEqual(r.fl_text(300), "FL300 · 300.9 hPa")
        # reetiquetar INDRA → OACI56 no inventa niveles: quedan los 14
        res = wf.export_wafs(FDP, os.path.join(self.tmp, "re"), per_step=False, mode="OACI56",
                             basename="y.grib2")
        r = GribReader(res["archivos"][0])
        self.assertEqual(sorted(r.fl_levels), flt.INDRA14)
        self.assertEqual(r.fl_mode, "INDRA")       # el modo que explica lo que hay

    def test_lector_crudo_interpola_a_la_isa_exacta(self):
        from tests.test_grib_reader import _reader_sintetico
        r = _reader_sintetico([850, 700, 500, 400, 300, 250, 200, 150, 100], shape=(9, 9))
        self.assertFalse(r.fl_labeled)
        self.assertEqual(r.fl_mode, "INDRA")        # coincide con nominales, pero faltan FL de INDRA
        self.assertIn("faltan FL de INDRA", r.inventory_text())
        self.assertEqual(r.available_fls(), [fl for fl in flt.FLS if 100 <= flt.isa_pa(fl) / 100 <= 850])
        self.assertNotIn(540, r.available_fls())        # 95,7 hPa: fuera, no se extrapola
        self.assertIn(530, r.available_fls())
        _u, _v, _t, info = r.fields_for_fl(0, 300)
        self.assertEqual(info["mode"], "interp")
        self.assertEqual(info["p"], 300.9)
        self.assertEqual(info["bracket"], (400, 300))
        self.assertIn("FORMATO: niveles de presión crudos", r.inventory_text())


class _QtBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global _app
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        _app = QApplication.instance() or QApplication([])
        from app.dialogs import glass_dialog
        glass_dialog._apply_dialog_blur = lambda w: None
        cls.tmp = tempfile.mkdtemp()
        from app import config
        cls._old = config.CONFIG_PATH
        config.CONFIG_PATH = os.path.join(cls.tmp, "config.json")

    @classmethod
    def tearDownClass(cls):
        from app import config
        config.CONFIG_PATH = cls._old
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        from app.main_window import MainWindow
        self.w = MainWindow()
        self.w.show()
        _app.processEvents()

    def tearDown(self):
        self.w.close()
        self.w.deleteLater()
        _app.processEvents()


@needs_eccodes
class TestSeleccionDeNivel(_QtBase):
    def _open(self, name):
        dst = os.path.join(self.tmp, name)
        shutil.copy(os.path.join(HERE, "data", name), dst)
        self.w.open_file(dst)
        _app.processEvents()
        return self.w.panel

    def test_botonera_fija_y_deshabilitados(self):
        p = self._open("FDP_MULTI.grib2")
        self.assertEqual(list(p._fl_buttons), flt.OACI16)
        self.assertEqual([fl for fl, b in p._fl_buttons.items() if not b.isEnabled()], [80, 480])
        self.assertEqual(p.cb_press.count(), 1)                    # nada fuera de la botonera
        self.assertEqual(p.sel_fl, 300)
        self.assertIn("F300 · etiqueta 300 hPa · 300.9 hPa ISA", p.lbl_fl_p.text())
        self.assertIn("modo INDRA", p.lbl_fl_p.text())
        self.assertIn("modo INDRA", p.lbl_level.text())
        self.assertIn("WAFS FL050–FL530 · modo INDRA", p.lbl_source.text())
        self.assertEqual(self.w._path.endswith("FDP_MULTI.grib2"), True)   # no se convierte
        p = self._open("WAFS_like_test.grib2")
        self.assertEqual([fl for fl, b in p._fl_buttons.items() if not b.isEnabled()], [])
        self.assertEqual(p.cb_press.count(), 1 + 49 - 16)            # los otros 33 FL
        self.assertEqual(p.cb_press.itemText(1), "FL060 · 812 hPa")

    def test_lista_y_botonera_se_excluyen(self):
        p = self._open("WAFS_like_test.grib2")
        p.cb_press.setCurrentIndex(1)                                 # FL060
        self.assertEqual((p.level_mode, p.sel_fl), ("fl", 60))
        self.assertFalse(any(b.isChecked() for b in p._fl_buttons.values()))
        self.assertIn("F060 · etiqueta 800 hPa · 812.0 hPa ISA", p.lbl_fl_p.text())
        self.assertIn("F060", self.w.panel.lbl_level.text())
        p._fl_buttons[300].click()
        self.assertEqual((p.level_mode, p.sel_fl), ("fl", 300))
        self.assertEqual(p.cb_press.currentIndex(), 0)
        self.assertTrue(p._fl_buttons[300].isChecked())
        p.select_fl(70)
        self.assertEqual(p.sel_fl, 70)
        self.assertEqual(p.cb_press.currentIndex(), 2)
        with self.assertRaises(ValueError):
            p.select_fl(610)
        p.cb_press.setCurrentIndex(0)                                 # vuelve al botón
        self.assertIn(p.sel_fl, flt.OACI16)
        self.assertTrue(p._fl_buttons[p.sel_fl].isChecked())

    def test_archivo_crudo_lista_fl_y_niveles(self):
        from tests.test_grib_reader import _reader_sintetico
        r = _reader_sintetico([850, 700, 500, 300, 250, 200, 100], shape=(9, 9))
        r.path = os.path.join(self.tmp, "s.grib2")
        self.w.load_reader(r, r.path)
        p = self.w.panel
        self.assertEqual([fl for fl, b in p._fl_buttons.items() if not b.isEnabled()], [])
        kinds = [k for k, _v in p._combo_items]
        self.assertEqual(kinds.count("fl"), 56 - 16 - 7)              # F540–F600 fuera del rango
        self.assertIn("sep", kinds)
        self.assertEqual(kinds.count("p"), 7)
        self.assertIn("interpolado", p.lbl_fl_p.text())
        p.cb_press.setCurrentIndex(p.cb_press.count() - 1)            # 100 hPa del archivo
        self.assertEqual((p.level_mode, p.sel_p), ("p", 100))
        self.assertIn("sin interpolar", p.lbl_level.text())
        p._fl_buttons[530].click()
        self.assertEqual(p.level_mode, "fl")
        self.assertIn("F530 = 100.4 hPa (ISA)", p.lbl_level.text())

    def test_dialogos_de_modo(self):
        from app.dialogs.export_wafs_dialog import ExportWafsDialog
        from app.dialogs.settings_dialog import SettingsDialog
        from app.dialogs.fl_table_dialog import FlTableDialog
        self._open("WAFS_like_test.grib2")
        d = ExportWafsDialog(self.w, reader=self.w._reader, cfg=self.w._cfg, dest_dir=self.tmp)
        self.assertEqual(d.cb_mode.currentData(), "OACI56")
        self.assertIn("modo WAFS", d.lbl_mode.text())
        d.cb_mode.setCurrentIndex(d.cb_mode.findData("INDRA"))
        self.assertEqual(d.options()["mode"], "INDRA")
        t = FlTableDialog(d, mode="INDRA")
        self.assertEqual(t.table.rowCount(), 14)
        self.assertEqual(t.table.item(0, 0).text(), "F050")
        self.assertEqual(t.table.item(0, 2).text(), "850 hPa")
        t.cb_mode.setCurrentIndex(t.cb_mode.findData("WAFS"))
        self.assertEqual(t.table.rowCount(), 56)
        self.assertEqual(t.table.item(0, 2).text(), "84310 Pa")
        s = SettingsDialog(self.w, cfg=self.w._cfg)
        self.assertEqual(s.cb_wafs_mode.currentData(), "OACI56")
        s.cb_wafs_mode.setCurrentIndex(s.cb_wafs_mode.findData("WAFS"))
        v = s.values()
        self.assertEqual(v["wafs_mode"], "WAFS")
        from app import wafs_format as wf
        self.assertEqual(wf.options_from_config(v)["mode"], "WAFS")


if __name__ == "__main__":
    unittest.main()
