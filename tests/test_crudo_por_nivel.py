# -*- coding: utf-8 -*-
"""Crudo o por Nivel al abrir: las capas crudas de un modelo (850, 700,
500 hPa…) graban lo mismo que las etiquetas nominales INDRA/OACI, así que
el `.json` de procedencia decide; sin él, se deduce por el conjunto de capas."""
import json
import os
import tempfile
import unittest

from app import fl_table as flt
from app import wafs_format as wf
from app.grib_reader import GribReader

try:
    import pyproj  # noqa: F401
    import eccodes as ec
except Exception:  # pragma: no cover
    ec = None

if ec is not None:
    from tests.test_wafs import _grib

# Las capas de un GFS que coinciden con las 14 etiquetas nominales de INDRA
INDRA_HPA = sorted({flt.label_pa(fl, "INDRA") // 100 for fl in flt.INDRA14}, reverse=True)


def _write(path, data, prov=None):
    open(path, "wb").write(data)
    if prov is not None:
        with open(path + ".json", "w", encoding="utf-8") as fh:
            json.dump(prov, fh)


class TestProcedencia(unittest.TestCase):
    def test_que_dice_la_procedencia(self):
        f = flt.labeled_by_provenance
        self.assertIsNone(f(None))
        self.assertIsNone(f({}))
        self.assertIsNone(f({"fuente": "archivo local"}))
        self.assertIsNone(f({"fuente": "wafs"}))              # la fuente ya publica por Nivel
        self.assertFalse(f({"fuente": "gfs"}))                 # bajado sin convertir
        self.assertTrue(f({"fuente": "gfs", "wafs": {"formato": "WAFS", "convertido": True}}))
        self.assertTrue(f({"fuente": "generado"}))
        self.assertTrue(f({"fuente": "archivo local", "wafs": {"convertido": True}}))


@unittest.skipIf(ec is None, "sin eccodes")
class TestAlAbrir(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_gfs_crudo_con_capas_de_indra(self):
        data = _grib(INDRA_HPA)
        sin = os.path.join(self.tmp, "sin_json.grib2")
        con = os.path.join(self.tmp, "con_json.grib2")
        _write(sin, data)
        _write(con, data, {"fuente": "gfs", "modelo": "GFS 0.25°"})
        r = GribReader(sin)                                    # deducción: parece por Nivel
        self.assertTrue(r.fl_labeled)
        self.assertEqual(r.fl_decided_by, "deducción")
        self.assertIn("deducido de las capas", r.inventory_text())
        r = GribReader(con)                                    # la procedencia dice crudo
        self.assertFalse(r.fl_labeled)
        self.assertFalse(r.is_wafs)
        self.assertEqual(r.fl_decided_by, "procedencia")
        self.assertIn("según la procedencia son capas del modelo", r.inventory_text())
        self.assertIn(50, r.available_fls())                   # se interpolan

    def test_generado_con_pocos_niveles(self):
        from app import grib_generate as gg
        rows = [{"fl": 50, "t_c": 5, "spd_kt": 20, "dir_deg": 270},
                {"fl": 100, "t_c": -5, "spd_kt": 30, "dir_deg": 250}]
        data, info = gg.generate_grib(rows, (-30, -32, -60, -58), 1.0, mode="INDRA")
        p = os.path.join(self.tmp, "gen.grib2")
        gg.write_generated(p, data, gg.provenance(rows, info))
        r = GribReader(p)
        self.assertTrue(r.fl_labeled)
        self.assertEqual(sorted(r.fl_levels), [50, 100])
        os.remove(p + ".json")
        self.assertFalse(GribReader(p).fl_labeled)            # sin procedencia: dos capas no alcanzan

    def test_exportar_un_crudo_lo_convierte(self):
        data = _grib(INDRA_HPA)
        p = os.path.join(self.tmp, "crudo.grib2")
        prov = {"fuente": "gfs", "modelo": "GFS 0.25°"}
        _write(p, data, prov)
        msgs = []
        out = os.path.join(self.tmp, "out")
        res = wf.export_wafs(p, out, mode="INDRA", per_step=False, provenance=prov,
                             progress_cb=lambda f, m: msgs.append(m))
        self.assertTrue(any(m.startswith("Convirtiendo") for m in msgs), msgs)
        path = res["archivos"][0]
        prov_out = json.load(open(path + ".json", encoding="utf-8"))
        self.assertTrue(prov_out["wafs"]["convertido"])
        self.assertTrue(GribReader(path).fl_labeled)          # la salida ya cuenta como por Nivel
        # Sin procedencia se toma por Nivel y sólo se reetiqueta (comportamiento de siempre)
        msgs.clear()
        wf.export_wafs(p, os.path.join(self.tmp, "out2"), mode="INDRA", per_step=False,
                       progress_cb=lambda f, m: msgs.append(m))
        self.assertFalse(any(m.startswith("Convirtiendo") for m in msgs), msgs)


if __name__ == "__main__":
    unittest.main()
