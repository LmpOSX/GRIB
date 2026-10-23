# -*- coding: utf-8 -*-
"""Bloque «Archivo a guardar»: recodificación (viento, decimales exactos,
etiqueta de capa, empaquetado, centro), el widget, la descarga, la
conversión al abrir, Generar GRIB y «Guardar como…»."""
import json
import os
import tempfile
import unittest

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from app import config  # noqa: E402
from app import fl_table as flt  # noqa: E402
from app import grib_encode as ge  # noqa: E402
from app import wafs_format as wf  # noqa: E402
from app import wind_format as wfm  # noqa: E402
from app.dialogs import glass_dialog  # noqa: E402

glass_dialog._apply_dialog_blur = lambda w: None
_app = QApplication.instance() or QApplication([])

try:
    import pyproj  # noqa: F401
    import eccodes as ec
except Exception:  # pragma: no cover
    ec = None

if ec is not None:
    from tests.test_wafs import _grib, _messages



def _keys(data):
    out = []
    for gid, _p, _s in wf.iter_messages(data):
        try:
            out.append({k: ec.codes_get(gid, k) for k in ("shortName", "decimalScaleFactor",
                                                          "binaryScaleFactor", "bitsPerValue",
                                                          "packingType")}
                       | {"centre": ec.codes_get_long(gid, "centre"), "pa": wf.level_pa(gid)})
        finally:
            ec.codes_release(gid)
    return out


class TestOpciones(unittest.TestCase):
    def test_normalizar_y_describir(self):
        o = ge.normalize({})
        self.assertEqual(o, {"wind": "uv", "dec_wind": None, "dec_temp": None, "label": "modo",
                             "packing": "origen", "centre": "origen"})
        self.assertTrue(ge.is_default({}))
        self.assertFalse(ge.is_default({"centre": "missing"}))
        o = ge.normalize({"save_wind": "dirspeed", "save_dec_wind": "1", "save_label": "isa_int",
                          "save_packing": "ieee", "save_centre": "missing", "save_dec_temp": 7})
        self.assertEqual(o["wind"], "dirspeed")
        self.assertEqual(o["dec_wind"], 1)
        self.assertEqual(o["dec_temp"], 2)                       # tope 2
        self.assertEqual(o["label"], "isa_int")
        self.assertEqual(ge.normalize({"label": "cualquiera"})["label"], "modo")
        cfg = dict(config.DEFAULTS, save_wind="dirspeed", save_dec_temp=0)
        self.assertEqual(ge.options_from_config(cfg)["dec_temp"], 0)
        self.assertIn("dirección y velocidad", ge.describe(cfg and ge.options_from_config(cfg)))

    def test_migracion_de_config(self):
        cfg = dict(config.DEFAULTS, download_wind_format="dirspeed")
        config._migrate_save(cfg)
        self.assertNotIn("download_wind_format", cfg)
        self.assertEqual(cfg["save_wind"], "dirspeed")

    def test_etiquetas(self):
        self.assertEqual(flt.label_pa_for(50, "nominal"), 85000)
        self.assertEqual(flt.label_pa_for(50, "isa"), 84310)
        self.assertEqual(flt.label_pa_for(50, "isa_int"), 84300)
        self.assertEqual(flt.label_pa_for(50, "modo", "WAFS"), 84310)
        self.assertEqual(flt.label_pa_for(50, "modo", "INDRA"), 85000)
        # ISA entera: los 56 FL se reconocen y un archivo así es modo WAFS
        for fl in flt.FLS:
            self.assertEqual(flt.fl_from_pa(flt.isa_int_pa(fl))[0], fl)
        det = flt.classify([flt.isa_int_pa(fl) for fl in flt.OACI17])
        self.assertEqual((det["mode"], det["labeled"]), ("WAFS", True))
        # Y no se confunde con nominales ni con ISA exacta
        self.assertEqual(flt.classify([flt.nominal_hpa(fl) * 100 for fl in flt.INDRA14])["mode"], "INDRA")
        self.assertEqual(flt.classify([flt.isa_pa(fl) for fl in flt.INDRA14])["mode"], "WAFS")


@unittest.skipIf(ec is None, "sin eccodes")
class TestRecodificar(unittest.TestCase):
    def setUp(self):
        self.raw = _grib([1000, 850, 700, 500, 400, 300, 250, 200, 150, 100], steps=(6,))
        self.wafs = wf.convert_to_wafs(self.raw, mode="OACI").data

    def test_sin_cambios(self):
        out, info = ge.recode(self.raw, {}, labeled=False)
        self.assertEqual(out, self.raw)
        self.assertFalse(info["etiqueta_aplicada"])

    def test_decimales_exactos(self):
        out, _ = ge.recode(self.wafs, {"dec_wind": 1, "dec_temp": 0}, labeled=True, mode="OACI")
        for k, (n, _pa, _st, vals) in zip(_keys(out), _messages(out)):
            self.assertEqual(k["binaryScaleFactor"], 0)
            if n in ("u", "v"):
                self.assertEqual(k["decimalScaleFactor"], 1)
                np.testing.assert_allclose(vals, np.round(vals, 1), atol=1e-4)
            elif n == "t":
                self.assertEqual(k["decimalScaleFactor"], 0)
                np.testing.assert_array_equal(vals, np.round(vals))
        # Los valores siguen siendo los de antes, a menos de medio decimal
        a = {(n, pa): v for n, pa, _s, v in _messages(self.wafs)}
        for n, pa, _s, v in _messages(out):
            np.testing.assert_allclose(v, a[(n, pa)], atol=0.051 if n in ("u", "v") else 0.51)
        # Un campo constante se deja exacto (0 bits, D = 0)
        from app import grib_generate as gg
        gen, _ = gg.generate_grib([{"fl": 50, "t_c": 5.37, "spd_kt": 20, "dir_deg": 270}],
                                  (-30, -32, -60, -58), 1.0)
        out, _ = ge.recode(gen, {"dec_temp": 1, "dec_wind": 1}, labeled=True)
        self.assertEqual(out, gen)

    def test_viento_etiqueta_empaquetado_centro(self):
        opts = {"wind": "dirspeed", "label": "isa_int", "packing": "ieee", "centre": "missing"}
        out, info = ge.recode(self.wafs, opts, labeled=True, mode="OACI")
        self.assertTrue(info["etiqueta_aplicada"])
        self.assertEqual(wfm.detect(out), "dirspeed")
        ks = _keys(out)
        self.assertTrue(all(k["packingType"] == "grid_ieee" for k in ks))
        self.assertTrue(all(k["centre"] == 65535 for k in ks))
        self.assertEqual({k["pa"] for k in ks} & {84300, 75300, 69700, 30100}, {84300, 75300, 69700, 30100})
        det = wf.detect_mode(out)
        self.assertEqual((det["mode"], det["labeled"]), ("WAFS", True))
        self.assertGreater(len(out), len(self.wafs))                 # IEEE ocupa más
        # Los valores no cambian (IEEE los guarda tal cual)
        ds, _ = wfm.convert(self.wafs, "dirspeed")
        a = {(n, pa and flt.fl_from_pa(pa)[0]): v for n, pa, _s, v in _messages(ds)}
        for n, pa, _s, v in _messages(out):
            np.testing.assert_allclose(v, a[(n, flt.fl_from_pa(pa)[0])], atol=1e-4)
        # Etiqueta nominal sobre un WAFS en ISA
        w2 = wf.convert_to_wafs(self.raw, mode="WAFS").data
        out, _ = ge.recode(w2, {"label": "nominal"}, labeled=True, mode="WAFS")
        self.assertIn(85000, {k["pa"] for k in _keys(out)})
        # En un crudo la etiqueta no se toca
        out, info = ge.recode(self.raw, {"label": "isa"}, labeled=False)
        self.assertEqual(out, self.raw)
        self.assertFalse(info["etiqueta_aplicada"])

    def test_descarga_aplica_el_bloque(self):
        import datetime as dt
        from app.sources import GFSSource, DownloadJob
        from app.sources.base import read_provenance
        from app.grib_reader import GribReader
        src = GFSSource()
        with tempfile.TemporaryDirectory() as tmp:
            job = DownloadJob(run_date=dt.date(2026, 10, 14), cycle=6, steps=[6],
                              variables=["UGRD", "VGRD", "TMP"],
                              levels=[1000, 850, 700, 500, 400, 300, 250, 200, 150, 100],
                              region=None, dest_dir=tmp, merge=True, params={}, suffix="_wafs",
                              save_opts={"wind": "dirspeed", "dec_temp": 0, "centre": "missing"})
            self.assertEqual(job.wind_format, "dirspeed")
            paths = src.download(job, fetch_fn=lambda url, **k: self.raw, retry_wait=0,
                                 wafs={"mode": "OACI"})
            data = open(paths[0], "rb").read()
            self.assertEqual(wfm.detect(data), "dirspeed")
            ks = _keys(data)
            self.assertTrue(all(k["centre"] == 65535 for k in ks))
            self.assertTrue(all(k["decimalScaleFactor"] == 0 and k["binaryScaleFactor"] == 0
                                for k in ks if k["shortName"] == "t"))
            prov = read_provenance(paths[0])
            self.assertEqual(prov["viento"], "dirspeed")
            self.assertEqual(prov["guardado"]["centre"], "missing")
            self.assertIn("sin centro", prov["guardado"]["descripcion"])
            r = GribReader(paths[0])
            self.assertTrue(r.fl_labeled)
            self.assertEqual(r.wind_format, "dirspeed")

    def test_conversion_al_abrir_aplica_el_bloque(self):
        from app.sources.base import read_provenance
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "crudo.grib2")
            open(p, "wb").write(self.raw)
            dst = wf.converted_path_for(p)
            _d, info = wf.convert_file(p, dst, force=True, mode="OACI",
                                       save_opts={"wind": "dirspeed", "label": "isa"})
            self.assertTrue(info["convertido"])
            self.assertEqual(info["guardado"]["label"], "isa")
            data = open(dst, "rb").read()
            self.assertEqual(wfm.detect(data), "dirspeed")
            self.assertEqual(wf.detect_mode(data)["mode"], "WAFS")      # etiqueta ISA forzada
            self.assertEqual(read_provenance(dst)["guardado"]["wind"], "dirspeed")

    def test_guardar_como(self):
        from app.dialogs.save_as_dialog import save_recoded, default_save_name
        from app.grib_reader import GribReader
        from app.sources.base import read_provenance
        self.assertEqual(default_save_name("/x/gfs_wafs.grib2", {}), "gfs_wafs_rec.grib2")
        self.assertEqual(default_save_name("/x/a_rec.grib2", {"wind": "dirspeed"}), "a_rec_dirvel.grib2")
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "w.grib2")
            open(p, "wb").write(self.wafs)
            dst = os.path.join(tmp, "w_rec.grib2")
            info = save_recoded(p, dst, {"dec_wind": 2, "packing": "simple", "centre": "missing"},
                                labeled=True, mode="OACI", provenance={"fuente": "gfs", "modelo": "GFS"})
            self.assertEqual(info["bytes"], os.path.getsize(dst))
            self.assertTrue(os.path.exists(dst + ".json") and os.path.exists(dst + ".idx"))
            prov = read_provenance(dst)
            self.assertEqual(prov["fuente"], "gfs")
            self.assertTrue(prov["por_nivel"])
            self.assertEqual(prov["guardado"]["dec_wind"], 2)
            self.assertEqual(prov["archivo_original"], os.path.abspath(p))
            r = GribReader(dst)
            self.assertTrue(r.fl_labeled)
            self.assertEqual(r.fl_mode, "OACI")


@unittest.skipIf(ec is None, "sin eccodes")
class TestDialogos(unittest.TestCase):
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

    def test_widget(self):
        from app.widgets.save_options import SaveOptionsBox
        cfg = dict(config.DEFAULTS, save_wind="dirspeed", save_dec_wind=1, save_centre="missing")
        self.w = SaveOptionsBox(cfg=cfg)
        self.w.show()
        v = self.w.values()
        self.assertEqual((v["wind"], v["dec_wind"], v["dec_temp"], v["centre"]), ("dirspeed", 1, None, "missing"))
        self.assertEqual(self.w.config_values()["save_dec_wind"], 1)
        self.w.set_values({"label": "isa_int", "packing": "ieee"})
        self.assertEqual(self.w.values()["label"], "isa_int")
        self.assertEqual(self.w.values()["wind"], "uv")
        self.w.set_labeled(False)
        self.assertFalse(self.w.cb_label.isEnabled())
        self.w.set_labeled(True)
        self.assertTrue(self.w.cb_label.isEnabled())
        compact = SaveOptionsBox(cfg=cfg, show_decimals=False, show_centre=False, compact=True)
        compact.show()
        self.assertTrue(compact.cb_dec_wind.isHidden())
        self.assertTrue(compact.cb_centre.isHidden())
        self.assertFalse(compact.cb_label.isHidden())
        compact.close()

    def test_preferencias_guardan_el_bloque(self):
        from app.dialogs.settings_dialog import SettingsDialog
        self.w = SettingsDialog(None, cfg=dict(config.DEFAULTS))
        self.w.show()
        _app.processEvents()
        self.assertIn("Guardar", [self.w.tabs.tabText(i) for i in range(self.w.tabs.count())])
        self.w.save_box.cb_wind.setCurrentIndex(self.w.save_box.cb_wind.findData("dirspeed"))
        self.w.save_box.cb_dec_temp.setCurrentIndex(self.w.save_box.cb_dec_temp.findData(1))
        v = self.w.values()
        self.assertEqual(v["save_wind"], "dirspeed")
        self.assertEqual(v["save_dec_temp"], 1)
        self.assertEqual(v["save_label"], "modo")

    def test_generar_con_el_bloque(self):
        from app.dialogs.generate_dialog import GenerateGribDialog
        from app.grib_reader import GribReader
        from app.sources.base import read_provenance
        cfg = dict(config.DEFAULTS, save_label="isa", save_packing="ieee")
        self.w = GenerateGribDialog(None, cfg=cfg, dest_dir=self._tmp.name)
        self.w.show()
        _app.processEvents()
        self.assertTrue(self.w.save_box.cb_dec_wind.isHidden())
        self.assertEqual(self.w.save_options()["label"], "isa")
        self.w._on_mode_clicked("INDRA")
        self.w.chk_open.setChecked(False)
        self.w._generate()
        p = self.w.generated_path
        self.assertTrue(p and os.path.exists(p))
        ks = _keys(open(p, "rb").read())
        self.assertTrue(all(k["packingType"] == "grid_ieee" for k in ks))
        self.assertIn(84310, {k["pa"] for k in ks})                  # ISA aunque el modo sea INDRA
        self.assertEqual(read_provenance(p)["guardado"]["packing"], "ieee")
        r = GribReader(p)
        self.assertTrue(r.fl_labeled)
        self.assertEqual(cfg["save_packing"], "ieee")

    def test_guardar_como_dialogo(self):
        from app.dialogs.save_as_dialog import SaveAsDialog
        from app.grib_reader import GribReader
        raw = _grib([1000, 850, 700, 500, 400, 300, 250, 200, 150, 100], steps=(6,))
        p = os.path.join(self._tmp.name, "w.grib2")
        open(p, "wb").write(wf.convert_to_wafs(raw, mode="OACI").data)
        r = GribReader(p)
        cfg = dict(config.DEFAULTS)
        self.w = SaveAsDialog(None, path=p, reader=r, cfg=cfg, dest_dir=self._tmp.name,
                              provenance={"fuente": "gfs"})
        self.w.show()
        _app.processEvents()
        self.assertTrue(self.w.save_box.cb_label.isEnabled())
        self.assertTrue(self.w.output_path().endswith("w_rec.grib2"))
        self.w.save_box.cb_wind.setCurrentIndex(self.w.save_box.cb_wind.findData("dirspeed"))
        self.assertTrue(self.w.output_path().endswith("w_rec_dirvel.grib2"))
        self.w.save_box.cb_centre.setCurrentIndex(self.w.save_box.cb_centre.findData("missing"))
        self.w._save()
        self.assertTrue(self.w.saved_path and os.path.exists(self.w.saved_path))
        ks = _keys(open(self.w.saved_path, "rb").read())
        self.assertTrue(all(k["centre"] == 65535 for k in ks))
        self.assertEqual(cfg["save_centre"], "missing")
        # Un crudo: la etiqueta queda deshabilitada
        p2 = os.path.join(self._tmp.name, "raw.grib2")
        open(p2, "wb").write(raw)
        d2 = SaveAsDialog(None, path=p2, reader=GribReader(p2), cfg=cfg, dest_dir=self._tmp.name)
        self.assertFalse(d2.save_box.cb_label.isEnabled())
        d2.close()


if __name__ == "__main__":
    unittest.main()
