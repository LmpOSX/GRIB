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
                             "packing": "origen", "centre": "origen", "sub_centre": None, "scan": "origen",
                             "rows": "origen", "lons": "origen", "regrid": "origen", "tables": "origen"})
        self.assertEqual(ge.normalize({"centre": 74, "sub_centre": "5"})["centre"], "74")
        self.assertEqual(ge.normalize({"sub_centre": "5"})["sub_centre"], 5)
        self.assertIsNone(ge.normalize({"sub_centre": -1})["sub_centre"])
        self.assertEqual(ge.normalize({"centre": "zzz"})["centre"], "origen")
        self.assertIn("centro 74 · egrr · U.K. Met Office - Exeter, subcentro 5",
                      ge.describe({"centre": "74", "sub_centre": 5}))
        self.assertIn("empaquetado JPEG 2000", ge.describe({"packing": "jpeg"}))
        self.assertEqual(ge.normalize({"save_tables": 4})["tables"], "4")
        self.assertEqual(ge.normalize({"tables": "99"})["tables"], "origen")
        self.assertFalse(ge.is_default({"tables": "25"}))
        self.assertIn("tablas versión 4", ge.describe({"tables": "4"}))
        self.assertEqual(ge.normalize({"regrid": "ninguno"})["regrid"], "origen")
        self.assertEqual(ge.normalize({"save_regrid": "1.25"})["regrid"], "1.25")
        self.assertEqual(ge.normalize({"regrid": "3"})["regrid"], "origen")
        self.assertFalse(ge.is_default({"regrid": "0.5"}))
        self.assertEqual(ge.regrid_res({"regrid": "1.25"}), 1.25)
        self.assertIsNone(ge.regrid_res({}))
        self.assertTrue(ge.describe({"regrid": "1.25"}).startswith("regrillado a 1,25°"))
        # El motor pasa sin tocarse (desde la config, sin prefijo)
        o = ge.options_from_config(dict(config.DEFAULTS, engine="wgrib2", wgrib2_path="/x/wgrib2"))
        self.assertEqual((o["engine"], o["wgrib2_path"]), ("wgrib2", "/x/wgrib2"))
        self.assertFalse(ge.is_default({"lons": "0_360"}))
        self.assertEqual(ge.normalize({"save_lons": "m180"})["lons"], "m180")
        self.assertEqual(ge.normalize({"lons": "zzz"})["lons"], "origen")
        self.assertIn("longitudes desde Greenwich (0…360)", ge.describe({"lons": "0_360"}))
        self.assertTrue(ge.is_default({}))
        self.assertFalse(ge.is_default({"centre": "missing"}))
        self.assertFalse(ge.is_default({"scan": "sn_ew"}))
        self.assertFalse(ge.is_default({"rows": "intercaladas"}))
        self.assertEqual(ge.normalize({"save_scan": "sn_we", "save_rows": "intercaladas"})["scan"], "sn_we")
        self.assertEqual(ge.normalize({"scan": "zzz", "rows": "zzz"})["scan"], "origen")
        self.assertIn("celdas S→N, E→O, filas intercaladas", ge.describe({"scan": "sn_ew", "rows": "intercaladas"}))
        self.assertEqual(ge.scan_text(0, 0, 0), "N→S, O→E")
        self.assertEqual(ge.scan_text(1, 1, 1), "S→N, E→O, filas intercaladas")
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

    def test_perfiles(self):
        """Cada perfil se reconoce por sus valores; un cambio lo vuelve
        personalizado. FDP es la grilla del boletín GTS; los dos WAFS sólo
        difieren en dónde empieza la vuelta."""
        for key, _text, vals in ge.PROFILES:
            self.assertEqual(ge.profile_of(vals), key)
        self.assertEqual(ge.profile_of({}), "origen")
        lon = ge.profile_values("fdp")
        self.assertEqual((lon["regrid"], lon["scan"], lon["lons"], lon["dec_wind"], lon["tables"]),
                         ("1.25", "sn_we", "0_360", 1, "4"))
        self.assertIsNone(ge.profile_of(dict(lon, dec_temp=2)))
        self.assertIsNone(ge.profile_values("zzz"))
        was, lnd = ge.profile_values("wafc_washington"), ge.profile_values("wafc_london")
        self.assertEqual((was["regrid"], was["label"], was["lons"]), ("0.25", "isa", "m180"))
        self.assertEqual(dict(was, lons="0_360"), lnd)

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

    def test_longitudes_de_una_grilla_global(self):
        """«Desde Greenwich» rota las columnas de una grilla global para que
        empiece en 0°; «desde 180°W», en 180°. Cada valor sigue en su
        longitud; con S→N, O→E queda la grilla del WAFS de WAFC London. En
        una grilla regional no cambia nada."""
        import datetime as _dt
        from app import grib_generate as gg
        rows = [{"fl": 100, "t_c": 0, "spd_kt": 30, "dir_deg": 250, "spd_inc": 2}]
        data, _ = gg.generate_grib(rows, (90, -90, -180, 180), 1.25, mode="OACI",
                                   run=_dt.datetime(2026, 10, 24, tzinfo=_dt.timezone.utc), step_h=36)

        def grid(b):
            gid = ec.codes_new_from_message(b)
            try:
                return ({k: ec.codes_get(gid, k) for k in ("Ni", "Nj", "longitudeOfFirstGridPointInDegrees",
                         "longitudeOfLastGridPointInDegrees", "latitudeOfFirstGridPointInDegrees",
                         "scanningMode")},
                        np.asarray(ec.codes_get_values(gid)).reshape(ec.codes_get(gid, "Nj"), ec.codes_get(gid, "Ni")))
            finally:
                ec.codes_release(gid)
        k0, v0 = grid(data)
        self.assertEqual((k0["Ni"], k0["Nj"]), (288, 145))
        self.assertEqual(k0["longitudeOfFirstGridPointInDegrees"], 180.0)    # −180
        out, _ = ge.recode(data, {"lons": "0_360", "scan": "sn_we"}, labeled=True, mode="OACI")
        k1, v1 = grid(out)
        self.assertEqual(k1["longitudeOfFirstGridPointInDegrees"], 0.0)
        self.assertEqual(k1["longitudeOfLastGridPointInDegrees"], 358.75)
        self.assertEqual(k1["latitudeOfFirstGridPointInDegrees"], -90.0)
        self.assertEqual(k1["scanningMode"], 64)                              # como el boletín YUXM70 EGRR
        # 0° estaba en la columna 144 (desde −180) de la fila 90N; ahora en la 0 de la última fila
        np.testing.assert_allclose(v1[::-1][:, 0], v0[:, 144])
        np.testing.assert_allclose(v1[::-1][:, 143], v0[:, 287])
        back, _ = ge.recode(out, {"lons": "m180"}, labeled=True, mode="OACI")
        k2, v2 = grid(back)
        self.assertEqual(k2["longitudeOfFirstGridPointInDegrees"], 180.0)
        np.testing.assert_allclose(v2, v1[:, list(range(144, 288)) + list(range(0, 144))])
        # E→O también: la del oeste queda última
        ew, _ = ge.recode(data, {"lons": "0_360", "scan": "ns_ew"}, labeled=True, mode="OACI")
        k3, v3 = grid(ew)
        self.assertEqual(k3["longitudeOfLastGridPointInDegrees"], 0.0)
        np.testing.assert_allclose(v3[:, -1], v0[:, 144])
        # Regional: nada que rotar
        reg, _ = ge.recode(self.wafs, {"lons": "0_360"}, labeled=True, mode="OACI")
        self.assertEqual(reg, self.wafs)

    def test_regrillado_en_el_bloque(self):
        """El perfil FDP lleva un global de 1° a la grilla de
        los boletines YUXM de EGRR: 288 × 145 desde 90S/0E, barrido 64, un
        decimal. Si el origen está en dirección y velocidad se regrilla
        sobre U/V y se vuelve a dirección y velocidad."""
        import datetime as _dt
        from app import grib_generate as gg
        rows = [{"fl": 100, "t_c": 0, "spd_kt": 30, "dir_deg": 250, "spd_inc": 2}]
        data, _ = gg.generate_grib(rows, (90, -90, -180, 180), 1.0, mode="OACI",
                                   run=_dt.datetime(2026, 10, 24, tzinfo=_dt.timezone.utc), step_h=36)
        out, info = ge.recode(data, ge.profile_values("fdp"), labeled=True, mode="OACI")
        self.assertEqual(info["regrillado_con"], "eccodes")
        for gid, _p, _s in wf.iter_messages(out):
            try:
                self.assertEqual((ec.codes_get(gid, "Ni"), ec.codes_get(gid, "Nj")), (288, 145))
                self.assertEqual(ec.codes_get(gid, "scanningMode"), 64)
                self.assertEqual(ec.codes_get(gid, "latitudeOfFirstGridPointInDegrees"), -90.0)
                self.assertEqual(ec.codes_get(gid, "longitudeOfFirstGridPointInDegrees"), 0.0)
                self.assertEqual(ec.codes_get(gid, "longitudeOfLastGridPointInDegrees"), 358.75)
                if ec.codes_get(gid, "shortName") in ("u", "v"):     # la TMP es constante: exacta
                    self.assertEqual(ec.codes_get(gid, "decimalScaleFactor"), 1)
                self.assertEqual(wf.level_pa(gid), 70000)
                self.assertEqual((ec.codes_get(gid, "tablesVersion"), ec.codes_get(gid, "localTablesVersion")),
                                 (4, 0))
            finally:
                ec.codes_release(gid)
        # Ya en la grilla: no se toca
        again, _ = ge.recode(out, {"regrid": "1.25"}, labeled=True, mode="OACI")
        self.assertEqual(again, out)
        # Dirección y velocidad: vuelve igual que por U/V
        ds, _ = ge.recode(data, {"wind": "dirspeed"}, labeled=True, mode="OACI")
        a, _ = ge.recode(data, {"wind": "dirspeed", "regrid": "1.25"}, labeled=True, mode="OACI")
        b, _ = ge.recode(ds, {"wind": "dirspeed", "regrid": "1.25"}, labeled=True, mode="OACI")
        self.assertEqual(wfm.detect(b), "dirspeed")
        va = {m[:3]: m[3] for m in _messages(a)}
        vb = {m[:3]: m[3] for m in _messages(b)}
        for k in va:
            np.testing.assert_allclose(va[k], vb[k], atol=0.05)

    def test_version_de_tablas(self):
        """La versión de tablas cambia sólo la sección 1: centro, subcentro y
        valores quedan iguales; los parámetros estándar, sin tablas locales."""
        src = _keys(self.wafs)
        out, _ = ge.recode(self.wafs, {"tables": "4"}, labeled=True, mode="OACI")
        for gid, _p, _s in wf.iter_messages(out):
            try:
                self.assertEqual(ec.codes_get(gid, "tablesVersion"), 4)
                self.assertEqual(ec.codes_get(gid, "localTablesVersion"), 0)
            finally:
                ec.codes_release(gid)
        self.assertEqual([(k["centre"], k["shortName"]) for k in _keys(out)],
                         [(k["centre"], k["shortName"]) for k in src])
        for a, b in zip(_messages(self.wafs), _messages(out)):
            np.testing.assert_array_equal(a[3], b[3])
        same, _ = ge.recode(out, {"tables": "4"}, labeled=True, mode="OACI")
        self.assertEqual(same, out)

    def test_jpeg_centro_y_subcentro(self):
        """JPEG 2000 sin pérdida (plantilla 5.40) con los decimales pedidos,
        como los boletines de WAFC London; centro y subcentro a elección."""
        out, _ = ge.recode(self.wafs, {"packing": "jpeg", "dec_wind": 1, "dec_temp": 1,
                                       "centre": "74", "sub_centre": 5}, labeled=True, mode="OACI")
        ref, _ = ge.recode(self.wafs, {"packing": "simple", "dec_wind": 1, "dec_temp": 1},
                           labeled=True, mode="OACI")
        for gid, _p, _s in wf.iter_messages(out):
            try:
                self.assertEqual(ec.codes_get(gid, "dataRepresentationTemplateNumber"), 40)
                self.assertEqual(ec.codes_get(gid, "typeOfCompressionUsed"), 0)
                self.assertEqual(ec.codes_get(gid, "centre"), "egrr")
                self.assertEqual(ec.codes_get(gid, "subCentre"), 5)
            finally:
                ec.codes_release(gid)
        for a, b in zip(_messages(ref), _messages(out)):
            np.testing.assert_allclose(a[3], b[3], atol=1e-6)          # sin pérdida
        self.assertEqual([k["decimalScaleFactor"] for k in _keys(out)],
                         [k["decimalScaleFactor"] for k in _keys(ref)])
        # De JPEG a simple: los valores no cambian
        back, _ = ge.recode(out, {"packing": "simple"}, labeled=True, mode="OACI")
        for a, b in zip(_messages(out), _messages(back)):
            np.testing.assert_allclose(a[3], b[3], atol=1e-6)
        # Un campo constante (Generar GRIB) también
        import datetime as _dt
        from app import grib_generate as gg
        data, _ = gg.generate_grib([{"fl": 100, "t_c": 0, "spd_kt": 30, "dir_deg": 250}],
                                   (10, -10, -10, 10), 1.0, mode="OACI",
                                   run=_dt.datetime(2026, 10, 24, tzinfo=_dt.timezone.utc), step_h=6)
        cj, _ = ge.recode(data, {"packing": "jpeg"}, labeled=True, mode="OACI")
        for a, b in zip(_messages(data), _messages(cj)):
            np.testing.assert_allclose(a[3], b[3], atol=1e-6)

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

    def test_orden_de_las_celdas(self):
        """Cambiar el modo de barrido reordena los valores y corrige las
        esquinas: el campo orientado que lee el visor es el mismo, y
        cell_index sigue apuntando al valor de cada celda."""
        import eccodes as ec
        from app.grib_reader import GribReader
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "src.grib2")
        with open(src, "wb") as fh:
            fh.write(self.raw)
        ref = GribReader(src)
        u0 = ref.get_field(0, "u", 850)
        for scan, rows in (("sn_ew", "intercaladas"), ("ns_ew", "origen"), ("sn_we", "consecutivas"),
                           ("origen", "intercaladas")):
            out, info = ge.recode(self.raw, {"scan": scan, "rows": rows}, labeled=False)
            self.assertNotEqual(out, self.raw)
            gid = ec.codes_new_from_message(out)
            try:
                i_neg, j_pos = ec.codes_get(gid, "iScansNegatively"), ec.codes_get(gid, "jScansPositively")
                alt = ec.codes_get(gid, "alternativeRowScanning")
                la1 = ec.codes_get(gid, "latitudeOfFirstGridPointInDegrees")
                lo1 = ec.codes_get(gid, "longitudeOfFirstGridPointInDegrees")
                raw = ec.codes_get_double_array(gid, "values")
            finally:
                ec.codes_release(gid)
            if scan != "origen":
                self.assertEqual((j_pos, i_neg), (int(scan.startswith("sn")), int(scan.endswith("ew"))))
            self.assertEqual(alt, int(rows == "intercaladas"))
            if scan.startswith("sn"):
                self.assertEqual(la1, float(ref.lats.min()))
            if scan.endswith("ew"):
                self.assertAlmostEqual(((lo1 + 180) % 360) - 180, float(ref.lons.max()), places=6)
            dst = os.path.join(tmp, f"{scan}_{rows}.grib2")
            with open(dst, "wb") as fh:
                fh.write(out)
            r = GribReader(dst)
            self.assertEqual(bool(r.grid["alt_rows"]), rows == "intercaladas")
            np.testing.assert_allclose(r.get_field(0, "u", 850), u0, atol=1e-6)
            np.testing.assert_allclose(r.get_field(0, "t", 500), ref.get_field(0, "t", 500), atol=1e-6)
            # cell_index: el valor crudo k de la celda (j, i) es el del campo orientado
            # (el primer mensaje del archivo es U en 1000 hPa)
            u1000 = ref.get_field(0, "u", 1000)
            for j, i in ((0, 0), (1, 2), (2, 4), (3, 1)):
                self.assertAlmostEqual(raw[r.cell_index(j, i)], u1000[j, i], places=6)
            if scan == "sn_ew" and rows == "intercaladas":
                self.assertIn("S→N, E→O, filas intercaladas", r.inventory_text())
                self.assertIn("filas intercaladas", r.scan_text())
        # Pedir lo que ya tiene no cambia nada
        out, _ = ge.recode(self.raw, {"scan": "ns_we", "rows": "consecutivas"}, labeled=False)
        self.assertEqual(out, self.raw)
        self.assertEqual(ref.scan_text(), "N→S, O→E")

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
        # Regrillar al bajar: la grilla de 1° sale a 0,5° y el nombre lo dice
        with tempfile.TemporaryDirectory() as tmp:
            job = DownloadJob(run_date=dt.date(2026, 10, 14), cycle=6, steps=[6],
                              variables=["UGRD", "VGRD", "TMP"],
                              levels=[1000, 850, 700, 500, 400, 300, 250, 200, 150, 100],
                              region=None, dest_dir=tmp, merge=True, params={}, suffix="_wafs",
                              save_opts={"regrid": "0.5", "scan": "sn_we"})
            paths = src.download(job, fetch_fn=lambda url, **k: self.raw, retry_wait=0,
                                 wafs={"mode": "OACI"})
            self.assertIn("_a0p50_wafs", os.path.basename(paths[0]))
            for gid, _p, _s in wf.iter_messages(open(paths[0], "rb").read()):
                try:
                    self.assertEqual((ec.codes_get(gid, "Ni"), ec.codes_get(gid, "Nj")), (9, 7))
                    self.assertEqual(ec.codes_get(gid, "jScansPositively"), 1)
                finally:
                    ec.codes_release(gid)
            self.assertIn("regrillado a 0,5°", read_provenance(paths[0])["guardado"]["descripcion"])

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
        self.w.set_values({"label": "isa_int", "packing": "ieee", "lons": "0_360"})
        self.assertEqual(self.w.values()["label"], "isa_int")
        self.assertEqual(self.w.values()["lons"], "0_360")
        self.assertEqual(self.w.config_values()["save_lons"], "0_360")
        self.assertEqual(self.w.values()["wind"], "uv")
        self.w.set_labeled(False)
        self.assertFalse(self.w.cb_label.isEnabled())
        self.w.set_labeled(True)
        self.assertTrue(self.w.cb_label.isEnabled())
        # Perfil: arranca en «Personalizado» aunque la config coincida con uno
        self.assertEqual(self.w.profile(), None)
        cfg_fdp = dict(config.DEFAULTS, **{"save_" + k: v for k, v in ge.profile_values("fdp").items()})
        box_fdp = SaveOptionsBox(cfg=cfg_fdp)
        self.assertIsNone(box_fdp.profile())
        self.assertEqual(box_fdp.values()["regrid"], "1.25")
        box_fdp.close()
        self.w.cb_profile.setCurrentIndex(self.w.cb_profile.findData("fdp"))
        self.w.cb_profile.activated.emit(self.w.cb_profile.currentIndex())
        v = self.w.values()
        self.assertEqual((v["regrid"], v["scan"], v["lons"], v["packing"], v["tables"]),
                         ("1.25", "sn_we", "0_360", "jpeg", "4"))
        self.assertEqual(self.w.profile(), "fdp")
        self.w.cb_dec_temp.setCurrentIndex(self.w.cb_dec_temp.findData(2))
        self.assertIsNone(self.w.profile())
        self.w.set_values({})
        self.assertEqual(self.w.profile(), "origen")
        # Centro de la tabla C-11 y subcentro
        self.w.cb_centre.setCurrentIndex(self.w.cb_centre.findData("74"))
        self.w.sp_sub_centre.setValue(5)
        self.assertEqual((self.w.values()["centre"], self.w.values()["sub_centre"]), ("74", 5))
        self.assertEqual(self.w.config_values()["save_sub_centre"], 5)
        self.assertIsNone(self.w.profile())
        self.w.sp_sub_centre.setValue(-1)
        self.assertIsNone(self.w.values()["sub_centre"])
        self.assertIn("U.K. Met Office", self.w.cb_centre.currentText())
        compact = SaveOptionsBox(cfg=dict(cfg, save_regrid="0.5", save_centre="74"), show_decimals=False,
                                 show_centre=False, compact=True, show_regrid=False)
        compact.show()
        self.assertTrue(compact.cb_regrid.isHidden())
        self.assertEqual(compact.values()["regrid"], "origen")          # Generar no regrilla
        self.assertEqual(compact.config_values()["save_regrid"], "0.5")  # pero no pisa Preferencias
        self.assertEqual(compact.values()["centre"], "origen")          # ni toca el centro
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
