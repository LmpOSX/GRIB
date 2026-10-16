# -*- coding: utf-8 -*-
"""Formato WAFS: conversión, detección, validador, .idx, exportación y su
integración en la descarga y en la ventana principal.

Caso de referencia: tests/data/FDP_MULTI.grib2 (GFS 1°, 14 niveles, 3
plazos) debe convertirse en tests/data/WAFS_like_test.grib2, generado por
el conversor de referencia docs/referencia/make_wafs_like.py.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from app.grib_engines import ec
from app import wafs_format as wf

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SRC = os.path.join(DATA, "FDP_MULTI.grib2")
REF = os.path.join(DATA, "WAFS_like_test.grib2")

needs_eccodes = unittest.skipIf(ec is None, "requiere eccodes")


def _grib(levels_hpa, steps=(6,), variables=("u", "v", "t"), ni=5, nj=4, seed=0, lat0=10.0,
          lon0=280.0, dx=1.0):
    """GRIB2 sintético en niveles de presión con valores distintos por nivel."""
    rng = np.random.default_rng(seed)
    out = bytearray()
    spec = {"u": (0, 2, 2), "v": (0, 2, 3), "t": (0, 0, 0), "gh": (0, 3, 5), "r": (0, 1, 1)}
    for step in steps:
        for var in variables:
            for lv in levels_hpa:
                gid = ec.codes_grib_new_from_samples("regular_ll_pl_grib2")
                try:
                    d, c, n = spec[var]
                    ec.codes_set(gid, "discipline", d)
                    ec.codes_set(gid, "parameterCategory", c)
                    ec.codes_set(gid, "parameterNumber", n)
                    ec.codes_set(gid, "typeOfLevel", "isobaricInhPa")
                    ec.codes_set(gid, "level", lv)
                    ec.codes_set(gid, "dataDate", 20261014)
                    ec.codes_set(gid, "dataTime", 600)
                    ec.codes_set(gid, "stepUnits", "h")
                    ec.codes_set(gid, "forecastTime", step)
                    ec.codes_set(gid, "Ni", ni)
                    ec.codes_set(gid, "Nj", nj)
                    ec.codes_set(gid, "latitudeOfFirstGridPointInDegrees", lat0)
                    ec.codes_set(gid, "latitudeOfLastGridPointInDegrees", lat0 - dx * (nj - 1))
                    ec.codes_set(gid, "longitudeOfFirstGridPointInDegrees", lon0)
                    ec.codes_set(gid, "longitudeOfLastGridPointInDegrees", lon0 + dx * (ni - 1))
                    ec.codes_set(gid, "iDirectionIncrementInDegrees", dx)
                    ec.codes_set(gid, "jDirectionIncrementInDegrees", dx)
                    ec.codes_set(gid, "jScansPositively", 0)
                    base = {"u": 10.0, "v": -5.0, "t": 250.0, "gh": 5000.0, "r": 50.0}[var]
                    vals = base + np.log(lv) * 3.0 + rng.normal(0, 0.1, ni * nj)
                    ec.codes_set_values(gid, vals)
                    out += ec.codes_get_message(gid)
                finally:
                    ec.codes_release(gid)
    return bytes(out)


def _messages(src):
    """[(shortName, Pa, stepRange, valores)] de un archivo o bytes."""
    data = wf._load(src)
    out = []
    for gid, _pos, _size in wf.iter_messages(data):
        try:
            out.append((ec.codes_get(gid, "shortName"), wf.level_pa(gid),
                        str(ec.codes_get(gid, "stepRange")), np.asarray(ec.codes_get_values(gid))))
        finally:
            ec.codes_release(gid)
    return out


class TestTablaISA(unittest.TestCase):
    def test_valores_de_referencia_ncep(self):
        esperado = {530: 10040, 480: 12770, 450: 14750, 410: 17870, 390: 19680, 360: 22730,
                    340: 25000, 300: 30090, 240: 39270, 180: 50600, 100: 69680, 50: 84310}
        for fl, pa in esperado.items():
            self.assertEqual(wf.wafs_pa(fl), pa, f"FL{fl}")
            self.assertEqual(wf.FL_TABLE[fl], pa)

    def test_fl_desde_pa(self):
        self.assertEqual(wf.fl_from_pa(10040), 530)
        self.assertEqual(wf.fl_from_pa(10045), 530)        # dentro de la tolerancia (10 Pa)
        self.assertEqual(wf.fl_from_pa(10000), 530)        # 100 hPa: etiqueta nominal de FL530
        self.assertEqual(wf.fl_from_pa_col(10000), (530, "nominal"))
        self.assertEqual(wf.fl_from_pa_col(10040), (530, "isa"))
        self.assertEqual(wf.fl_from_pa(25000), 340)
        self.assertEqual(wf.fl_from_hpa(850), 50)          # nominal de FL050
        self.assertIsNone(wf.fl_from_hpa(1000))            # fuera de la tabla
        self.assertEqual(wf.FL_TABLE[290], 31490)          # literal del servidor

    def test_rango_de_fl(self):
        self.assertEqual(wf.fl_range([850, 100]), (50, 530))
        self.assertEqual(wf.fl_range([1000, 850, 100, 50]), (50, 600))     # la tabla empieza en F050
        self.assertEqual(wf.fl_range([1000, 850, 100, 50], extend=False), (50, 530))
        self.assertEqual(wf.fl_range([700, 300]), (50, 530))      # nunca se achica
        self.assertEqual(wf.fl_range([850, 100], 100, 300), (100, 300))   # rango explícito
        self.assertEqual(wf.fl_range([1000, 100], 100, 300), (100, 300))   # nada por debajo de F050 que ampliar

    def test_nombre_operativo(self):
        self.assertEqual(wf.wafs_filename(6, 9), "gfs.t06z.wafs_0p25.f009.grib2")
        self.assertEqual(wf.wafs_filename(18, 120, "gfs", "1p00"), "gfs.t18z.wafs_1p00.f120.grib2")


@needs_eccodes
class TestConversionReferencia(unittest.TestCase):
    """(1) convertir FDP_MULTI.grib2 en modo WAFS reproduce WAFS_like_test.grib2.

    Desde que la tabla de FL es la literal del servidor hay dos desvíos
    conocidos respecto del conversor de referencia (fórmula ISA redondeada):
    FL290 se etiqueta 31490 Pa (el conversor viejo daba 31480) y el dato se
    interpola a la ISA entera de la tabla (84310 Pa) en vez de a la fórmula
    (84306,1 Pa), lo que mueve los valores menos de 0,1 m/s y 0,05 K."""

    def test_reproduce_la_referencia(self):
        res = wf.convert_to_wafs(SRC, mode="WAFS")
        self.assertEqual(res.info["mensajes"], 441)
        self.assertEqual(res.info["fl_rango"], "FL050–FL530")
        self.assertEqual(res.info["modo"], "WAFS")
        got = _messages(res.data)
        ref = _messages(REF)
        self.assertEqual(len(got), len(ref))
        for a, b in zip(got, ref):
            self.assertEqual(a[0], b[0])
            self.assertEqual(a[2], b[2])
            self.assertEqual(wf.fl_from_pa(a[1]), wf.fl_from_pa(b[1]))
            if wf.fl_from_pa(a[1]) != 290:
                self.assertEqual(a[1], b[1])
            else:
                self.assertEqual((a[1], b[1]), (31490.0, 31480.0))
            np.testing.assert_allclose(a[3], b[3], rtol=0, atol=0.1)
        fls = sorted({wf.fl_from_pa(m[1]) for m in ref})
        self.assertEqual(fls, list(range(50, 531, 10)))

    def test_modo_por_defecto_etiqueta_nominal(self):
        res = wf.convert_to_wafs(SRC)                       # OACI56 por defecto
        self.assertEqual(res.info["modo"], "OACI56")
        pas = {m[1] for m in _messages(res.data)}
        self.assertIn(85000.0, pas)                          # FL050 = 850 hPa nominal
        self.assertNotIn(84310.0, pas)
        self.assertEqual(len(pas), 49)

    def test_ya_en_wafs_pasa_sin_cambios(self):
        """(4) un archivo etiquetado por FL no se reconvierte; FDP_MULTI tiene
        exactamente los 14 niveles nominales de INDRA y cuenta como tal."""
        self.assertTrue(wf.is_wafs(REF))
        self.assertTrue(wf.is_wafs(SRC))
        self.assertEqual(wf.detect_mode(SRC)["mode"], "INDRA")
        with open(REF, "rb") as fh:
            ref = fh.read()
        data, info = wf.convert_if_needed(ref)
        self.assertIs(data, ref)
        self.assertFalse(info["convertido"])
        self.assertEqual(info["modo"], "WAFS")
        self.assertEqual(info["fl_rango"], "FL050–FL530")
        # un GFS crudo con niveles nominales se convierte sólo forzando
        data2, info2 = wf.convert_if_needed(SRC, force=True, mode="WAFS")
        self.assertTrue(info2["convertido"])
        self.assertEqual(len(_messages(data2)), 441)

    def test_conversor_de_referencia_sigue_en_el_repo(self):
        p = os.path.join(HERE, "..", "docs", "referencia", "make_wafs_like.py")
        self.assertTrue(os.path.isfile(p))


@needs_eccodes
class TestConversionSintetica(unittest.TestCase):
    def test_extiende_el_rango_con_niveles_bajos_y_altos(self):
        """(3) niveles por debajo de 850 o por encima de 100 hPa amplían el rango."""
        res = wf.convert_to_wafs(_grib([1000, 925, 850, 500, 300, 100, 70, 50]))
        self.assertEqual((res.info["fl_min"], res.info["fl_max"]), (50, 600))    # la tabla empieza en F050
        fls = sorted({wf.fl_from_pa(m[1]) for m in _messages(res.data)})
        self.assertEqual(fls, list(range(50, 601, 10)))
        res2 = wf.convert_to_wafs(_grib([1000, 925, 850, 500, 300, 100, 70, 50]), extend=False)
        self.assertEqual((res2.info["fl_min"], res2.info["fl_max"]), (50, 530))

    def test_omite_fuera_de_rango_salvo_extrapolar(self):
        data = _grib([700, 500, 300])           # cubre ~FL100…FL300
        res = wf.convert_to_wafs(data)
        fls = sorted({wf.fl_from_pa(m[1]) for m in _messages(res.data)})
        self.assertEqual(fls[0], 100)
        self.assertEqual(fls[-1], 300)
        self.assertIn(50, res.info["fl_omitidos"])
        self.assertIn(530, res.info["fl_omitidos"])
        res = wf.convert_to_wafs(data, extrapolate=True)
        fls = sorted({wf.fl_from_pa(m[1]) for m in _messages(res.data)})
        self.assertEqual(fls, list(range(50, 531, 10)))
        self.assertTrue(res.info["extrapolados"])
        self.assertEqual(res.info["extrapolados"][0]["fl"], 50)
        self.assertEqual(res.info["extrapolados"][0]["nivel_hpa"], 700.0)
        # El extrapolado vale lo mismo que el nivel más cercano
        src = {(m[0], m[1]): m[3] for m in _messages(data)}
        got = {(m[0], wf.fl_from_pa(m[1])): m[3] for m in _messages(res.data)}
        np.testing.assert_allclose(got[("u", 50)], src[("u", 70000.0)], rtol=1e-3)

    def test_interpolacion_en_ln_p(self):
        data = _grib([500, 300])
        res = wf.convert_to_wafs(data)
        src = {(m[0], m[1]): m[3] for m in _messages(data)}
        got = {(m[0], wf.fl_from_pa(m[1])): m[3] for m in _messages(res.data)}
        pa = wf.isa_pa(240)                    # 39270 Pa, entre 500 y 300 hPa
        w = (np.log(pa / 100) - np.log(300)) / (np.log(500) - np.log(300))
        esperado = w * src[("t", 50000.0)] + (1 - w) * src[("t", 30000.0)]
        np.testing.assert_allclose(got[("t", 240)], esperado, atol=0.02)

    def test_humedad_solo_hasta_fl180_y_descartes(self):
        data = _grib([850, 500, 100], variables=("u", "v", "t", "r"))
        # un mensaje de superficie que no pertenece al WAFS
        gid = ec.codes_grib_new_from_samples("regular_ll_sfc_grib2")
        try:
            ec.codes_set(gid, "Ni", 5)
            ec.codes_set(gid, "Nj", 4)
            ec.codes_set_values(gid, np.zeros(20))
            data += ec.codes_get_message(gid)
        finally:
            ec.codes_release(gid)
        res = wf.convert_to_wafs(data)
        r_fls = sorted({wf.fl_from_pa(m[1]) for m in _messages(res.data) if m[0] == "r"})
        self.assertEqual(r_fls[-1], 180)
        self.assertEqual(res.info["descartados"], 1)

    def test_tabla_y_centro_opcionales(self):
        res = wf.convert_to_wafs(_grib([850, 100]), tables_version=25, centre=255)
        gid = ec.codes_new_from_message(res.data)
        try:
            self.assertEqual(ec.codes_get(gid, "tablesVersion"), 25)
            self.assertEqual(ec.codes_get_long(gid, "centre"), 255)
        finally:
            ec.codes_release(gid)

    def test_bytes_invalidos_no_rompen(self):
        data, info = wf.convert_if_needed(b"GRIBxxxx")
        self.assertEqual(data, b"GRIBxxxx")
        self.assertFalse(info["convertido"])


@needs_eccodes
class TestValidadorIdx(unittest.TestCase):
    def test_validador_acepta_la_referencia(self):
        rep = wf.validate_wafs(REF)
        self.assertTrue(rep["ok"], rep["avisos"])
        self.assertEqual(rep["mensajes"], 441)
        self.assertEqual(len(rep["niveles"]), 49)
        self.assertEqual(rep["niveles"][530], 10040)
        self.assertEqual(rep["plazos"], ["6", "9", "12"])
        self.assertEqual(rep["grilla"]["tipo"], "regular_ll")

    def test_validador_avisa_sin_bloquear(self):
        rep = wf.validate_wafs(_grib([1000, 850, 700]))    # 1000 hPa no es un FL
        self.assertFalse(rep["ok"])
        self.assertTrue(any("no es la presión ISA" in a for a in rep["avisos"]))
        self.assertEqual(rep["etiquetado"], False)
        rep = wf.validate_wafs(_grib([850, 700, 500, 250, 100]))   # nominales sueltos de un GFS
        self.assertTrue(any("faltan FL de INDRA" in a for a in rep["avisos"]))
        rep = wf.validate_wafs(SRC)                       # los 14 de INDRA: etiquetado
        self.assertEqual((rep["modo"], rep["etiquetado"]), ("INDRA", True))
        rep = wf.validate_wafs(wf.convert_to_wafs(_grib([850, 100], variables=("t",))).data)
        self.assertTrue(any("UGRD" in a for a in rep["avisos"]))

    def test_idx_como_wgrib2(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "w.grib2")
            with open(REF, "rb") as src, open(p, "wb") as dst:
                dst.write(src.read())
            idx = wf.write_idx(p)
            with open(idx) as fh:
                lines = fh.read().splitlines()
        self.assertEqual(len(lines), 441)
        self.assertEqual(lines[0], "1:0:d=2026101318:TMP:843.1 mb:6 hour fcst:")
        self.assertEqual(lines[1], "2:7916:d=2026101318:TMP:812 mb:6 hour fcst:")
        self.assertTrue(lines[49].startswith("50:365869:d=2026101318:UGRD:843.1 mb:"))


@needs_eccodes
class TestExportacion(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_ida_y_vuelta_sin_perdida(self):
        """(2) exportar → reabrir: mismos mensajes, niveles y valores."""
        res = wf.export_wafs(REF, self.tmp, per_step=True, idx=True, mode="WAFS")
        self.assertEqual([os.path.basename(p) for p in res["archivos"]],
                         ["gfs.t18z.wafs_1p00.f006.grib2", "gfs.t18z.wafs_1p00.f009.grib2",
                          "gfs.t18z.wafs_1p00.f012.grib2"])
        for v in res["verificacion"]:
            self.assertTrue(v["ok"], v["detalle"])
            self.assertEqual(v["mensajes"], 147)
            self.assertEqual(v["niveles"], 49)
            self.assertTrue(os.path.exists(v["archivo"] + ".idx"))
        self.assertEqual(res["avisos"], [])
        # Valores idénticos a los del archivo de origen (misma cuantización)
        ref = {(m[0], m[1], m[2]): m[3] for m in _messages(REF)}
        for p in res["archivos"]:
            for m in _messages(p):
                np.testing.assert_array_equal(m[3], ref[(m[0], m[1], m[2])])
        gid = ec.codes_new_from_message(wf._load(res["archivos"][0]))
        try:
            self.assertEqual(ec.codes_get(gid, "tablesVersion"), 25)
        finally:
            ec.codes_release(gid)

    def test_seleccion_recorte_y_archivo_unico(self):
        res = wf.export_wafs(REF, self.tmp, steps=[6, 12], fls=[300, 340], variables="basicas",
                             region=(0, -30, -80, -50), per_step=False, basename="sel")
        self.assertEqual([os.path.basename(p) for p in res["archivos"]], ["sel.grib2"])
        msgs = _messages(res["archivos"][0])
        self.assertEqual(len(msgs), 2 * 2 * 3)
        self.assertEqual({m[2] for m in msgs}, {"6", "12"})
        self.assertEqual({wf.fl_from_pa(m[1]) for m in msgs}, {300, 340})
        gid = ec.codes_new_from_message(wf._load(res["archivos"][0]))
        try:
            self.assertEqual(ec.codes_get(gid, "Ni"), 31)
            self.assertEqual(ec.codes_get(gid, "Nj"), 31)
        finally:
            ec.codes_release(gid)
        self.assertTrue(all(v["ok"] for v in res["verificacion"]))

    def test_regrillado_bilineal_a_0p25(self):
        res = wf.export_wafs(REF, self.tmp, steps=[6], fls=[300], regrid="0.25")
        self.assertIn("wafs_0p25", os.path.basename(res["archivos"][0]))
        gid = ec.codes_new_from_message(wf._load(res["archivos"][0]))
        try:
            self.assertEqual(ec.codes_get(gid, "Ni"), 69 * 4 - 3)
            self.assertAlmostEqual(ec.codes_get(gid, "iDirectionIncrementInDegrees"), 0.25)
            vals = np.asarray(ec.codes_get_values(gid)).reshape(69 * 4 - 3, 69 * 4 - 3)
        finally:
            ec.codes_release(gid)
        orig = [m for m in _messages(REF) if m[0] == "t" and m[2] == "6" and wf.fl_from_pa(m[1]) == 300][0]
        # Los puntos originales se conservan; los intermedios son el promedio de vecinos
        np.testing.assert_allclose(vals[::4, ::4], orig[3].reshape(69, 69), atol=0.05)
        np.testing.assert_allclose(vals[0, 2], (vals[0, 0] + vals[0, 4]) / 2, atol=0.05)
        self.assertTrue(res["verificacion"][0]["ok"])

    def test_exporta_desde_niveles_de_presion(self):
        """Lo cargado que todavía no está etiquetado por FL se convierte al
        exportar (con el modo pedido); lo etiquetado se reetiqueta."""
        crudo = os.path.join(self.tmp, "crudo.grib2")
        with open(crudo, "wb") as fh:
            fh.write(_grib([1000, 850, 700, 500, 400, 300, 250, 200, 150, 100]))
        res = wf.export_wafs(crudo, self.tmp, steps=[6], per_step=True, mode="OACI56")
        self.assertEqual(res["verificacion"][0]["niveles"], 49)
        self.assertEqual(wf.detect_mode(res["archivos"][0])["mode"], "OACI56")
        res = wf.export_wafs(SRC, self.tmp, steps=[6], per_step=True, mode="INDRA",
                             basename="indra")
        self.assertEqual(res["verificacion"][0]["niveles"], 14)
        self.assertTrue(wf.is_wafs(res["archivos"][0]))

    def test_convert_file_y_cli(self):
        dst = os.path.join(self.tmp, "salida.grib2")
        _p, info = wf.convert_file(SRC, dst, provenance={"fuente": "gfs", "nombre": "NOAA GFS"},
                                   force=True)
        self.assertTrue(info["convertido"])
        self.assertEqual(info["modo"], "OACI56")
        with open(dst + ".json", encoding="utf-8") as fh:
            prov = json.load(fh)
        self.assertEqual(prov["wafs"]["fl_rango"], "FL050–FL530")
        self.assertEqual(prov["corrida"], "2026-10-13T18:00Z")
        self.assertEqual(prov["plazos_h"], [6.0, 9.0, 12.0])
        self.assertTrue(os.path.exists(dst + ".idx"))
        out = subprocess.run([sys.executable, "-m", "app.wafs_format", SRC,
                              os.path.join(self.tmp, "cli.grib2"), "--fl-min", "100", "--fl-max", "300",
                              "--forzar", "--modo", "WAFS"],
                             capture_output=True, text=True, cwd=os.path.join(HERE, ".."))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("FL100–FL300", out.stdout)
        out = subprocess.run([sys.executable, "-m", "app.wafs_format", "--validar", REF],
                             capture_output=True, text=True, cwd=os.path.join(HERE, ".."))
        self.assertIn("OK", out.stdout)


@needs_eccodes
class TestLectorWAFS(unittest.TestCase):
    def test_lector_reconoce_niveles_exactos(self):
        from app.grib_reader import GribReader
        r = GribReader(REF)
        self.assertTrue(r.is_wafs)
        self.assertEqual(len(r.levels), 49)
        self.assertEqual(r.fl_levels[530], 100.4)
        self.assertEqual(r.level_label(300.9), "FL300 · 300.9 hPa")
        self.assertEqual(r.fl_mode, "WAFS")
        u, v, t, info = r.fields_for_fl(0, 300)
        self.assertEqual(info["mode"], "wafs")
        self.assertEqual(info["p"], 300.9)
        self.assertFalse(info["extrapolated"])
        self.assertIn("FORMATO: etiquetado por FL, modo WAFS", r.inventory_text())
        r2 = GribReader(SRC)                      # 14 niveles nominales: INDRA
        self.assertTrue(r2.is_wafs)
        self.assertEqual(r2.fl_mode, "INDRA")
        self.assertEqual(r2.fields_for_fl(0, 300)[3]["mode"], "wafs")
        self.assertEqual(r2.fields_for_fl(0, 300)[3]["label_hpa"], 300.0)
        self.assertEqual(r2.fl_text(300), "FL300 · 300 hPa (300.9 ISA)")


@needs_eccodes
class TestDescargaConvierte(unittest.TestCase):
    def test_fuente_de_altura_convierte_y_la_de_superficie_no(self):
        from app.sources.base import Source, Request, DownloadJob, read_provenance
        import datetime as dt

        class Fuente(Source):
            key, name, kind = "prueba", "Prueba", "altura"
            variables = [("u", "u")]
            levels = [850, 100]

            def build_requests(self, job, step):
                return [Request(f"http://x/{step}")]

        with open(SRC, "rb") as fh:
            src = fh.read()
        fetch = lambda url, headers=None, chunk_cb=None, cancel=None, **k: src   # noqa: E731
        with tempfile.TemporaryDirectory() as tmp:
            job = DownloadJob(dt.date(2026, 10, 13), 18, [6], ["u"], [850, 100], dest_dir=tmp)
            paths = Fuente().download(job, fetch_fn=fetch, retry_wait=0,
                                      wafs={"fl_min": 50, "fl_max": 530})
            self.assertTrue(paths[0].endswith("_wafs.grib2"))
            self.assertTrue(wf.is_wafs(paths[0]))
            prov = read_provenance(paths[0])
            self.assertTrue(prov["wafs"]["convertido"])
            self.assertEqual(prov["wafs"]["fl_rango"], "FL050–FL530")
            # Sin opciones: no se convierte (queda tal cual bajó)
            job2 = DownloadJob(dt.date(2026, 10, 13), 18, [6], ["u"], [850, 100], dest_dir=tmp,
                               basename="crudo")
            paths = Fuente().download(job2, fetch_fn=fetch, retry_wait=0)
            with open(paths[0], "rb") as fh:
                self.assertEqual(fh.read(), src)
            # Lo que ya es WAFS pasa igual si la fuente publica por FL; una fuente
            # en niveles crudos se convierte siempre (sus niveles pueden coincidir
            # con etiquetas nominales)
            with open(REF, "rb") as fh:
                ref = fh.read()

            class FuenteFL(Fuente):
                flight_levels = True

            job3 = DownloadJob(dt.date(2026, 10, 13), 18, [6], ["u"], [850, 100], dest_dir=tmp,
                               basename="ya")
            paths = FuenteFL().download(job3, fetch_fn=lambda *a, **k: ref, retry_wait=0,
                                        wafs={"fl_min": 50, "fl_max": 530})
            with open(paths[0], "rb") as fh:
                self.assertEqual(fh.read(), ref)
            self.assertFalse(read_provenance(paths[0])["wafs"]["convertido"])


if __name__ == "__main__":
    unittest.main()
