# -*- coding: utf-8 -*-
"""Tests de la capa de límites de FIR: conversor AIP → GeoJSON, geometría
(pertenencia, punto interior, extremos, cobertura), carga de GeoJSON / KML
/ Shapefile, descarga (simulada) de VATSpy y openAIP, dibujo en todas las
proyecciones y la integración en la ventana (offscreen)."""
import json
import os
import tempfile
import unittest
import urllib.error

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import fir  # noqa: E402
from app import fir_aip  # noqa: E402
from app.sources.base import DownloadError  # noqa: E402
from app.sources.openaip_fir import OpenAipFirSource, code_for_name  # noqa: E402


# ── Conversor AIP ────────────────────────────────────────────────────────────
class TestAipCoordenadas(unittest.TestCase):
    def test_formatos_de_vertice(self):
        casos = {
            "2215S06240W": (-22.25, -62.666667),
            "221530S0624015W": (-22.258333, -62.670833),
            "2215.5S06240.2W": (-22.258333, -62.67),
            "S2215 W06240": (-22.25, -62.666667),
            "22°15'S 062°40'W": (-22.25, -62.666667),
            "22°15'30\"S 062°40'15\"W": (-22.258333, -62.670833),
            "22º 15' 30'' S 062º 40' 15'' W": (-22.258333, -62.670833),
            "22 15 S 062 40 W": (-22.25, -62.666667),
            "22 15 30 S 062 40 15 W": (-22.258333, -62.670833),
            "22.25S 62.6667W": (-22.25, -62.6667),
            "-22.25, -62.6667": (-22.25, -62.6667),
            "062°40'W 22°15'S": (-22.25, -62.666667),      # lon antes que lat
            "3917S-06307W": (-39.283333, -63.116667),
            "0430N07400W": (4.5, -74.0),                   # hemisferio norte
            "3400S01830E": (-34.0, 18.5),                  # este
        }
        for texto, (lat, lon) in casos.items():
            got = fir_aip.parse_aip_coord(texto)
            self.assertAlmostEqual(got[0], lat, places=5, msg=texto)
            self.assertAlmostEqual(got[1], lon, places=5, msg=texto)

    def test_errores(self):
        with self.assertRaises(fir_aip.AipParseError):
            fir_aip.parse_aip_coord("hasta el límite")
        with self.assertRaises(fir_aip.AipParseError):
            fir_aip.parse_aip_coord("2275S06240W")          # 75 minutos
        with self.assertRaises(fir_aip.AipParseError):
            fir_aip.parse_aip_coord("9915S06240W")          # 99° de latitud

    def test_texto_con_tramos_descriptos(self):
        txt = ("Desde 3917S06307W - 4600S04500W, siguiendo por el paralelo 46°00'S hasta "
               "4600S01000W,\nluego 9000S01000W - 9000S07000W; desde allí a lo largo del límite "
               "internacional con Chile hasta 3917S06307W. Límite vertical: FL 245.")
        items = fir_aip.parse_aip_text(txt)
        verts = [i for i in items if i["tipo"] == "vertice"]
        tramos = [i for i in items if i["tipo"] == "tramo"]
        self.assertEqual(len(verts), 6)
        self.assertEqual([i for i in items if i["tipo"] == "error"], [])
        self.assertEqual(len(tramos), 2)
        self.assertEqual(tramos[0]["despues_de"], 1)
        self.assertIn("paralelo 46°00'S", tramos[0]["texto"])
        self.assertEqual(tramos[1]["despues_de"], 4)
        self.assertIn("límite internacional", tramos[1]["texto"])
        self.assertEqual((verts[3]["lat"], verts[3]["lon"]), (-90.0, -10.0))

    def test_feature_geojson(self):
        txt = "3917S06307W - 4600S04500W - 4600S01000W - 9000S01000W - 9000S07000W - por la costa hasta 3917S06307W"
        f = fir_aip.aip_to_feature(txt, "savf")
        p = f["properties"]
        self.assertEqual(p["id"], "SAVF")
        self.assertEqual(p["name"], "Comodoro Rivadavia")
        self.assertTrue(p["oficial"])
        self.assertFalse(p["verificado"])
        self.assertEqual(p["n_vertices"], 6)
        self.assertEqual(len(p["tramos_pendientes"]), 1)
        ring = f["geometry"]["coordinates"][0]
        self.assertEqual(ring[0], ring[-1])             # anillo cerrado
        self.assertEqual(ring[0], [-63.11666666666667, -39.28333333333333])
        self.assertIn("1 tramo(s)", fir_aip.report(f))
        # el GeoJSON se carga como cualquier otro
        regs = fir.load_geojson(fir_aip.aip_to_geojson(txt, "SAVF"))
        self.assertEqual(regs[0].code, "SAVF")
        self.assertTrue(regs[0].official)
        self.assertTrue(regs[0].contains(-45.0, -60.0))
        with self.assertRaises(fir_aip.AipParseError):
            fir_aip.aip_to_feature("3917S06307W - 4600S04500W", "SAVF")

    def test_linea_de_comandos(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "v.txt")
            dst = os.path.join(d, "savf.geojson")
            with open(src, "w", encoding="utf-8") as fh:
                fh.write("3917S06307W\n4600S04500W\n4600S01000W\n9000S01000W\n")
            rc = fir_aip.main([src, "--codigo", "SAVF", "-o", dst])
            self.assertEqual(rc, 0)
            with open(dst, encoding="utf-8") as fh:
                obj = json.load(fh)
            self.assertEqual(obj["features"][0]["properties"]["id"], "SAVF")


# ── Geometría ────────────────────────────────────────────────────────────────
U_SHAPE = [(0, 0), (10, 0), (10, 10), (7, 10), (7, 3), (3, 3), (3, 10), (0, 10)]   # cóncavo


class TestGeometria(unittest.TestCase):
    def test_pertenencia(self):
        ring = np.array(U_SHAPE, dtype=float)
        inside = fir.points_in_ring(ring, [1.5, 5.0, 8.5, 20.0], [5.0, 5.0, 5.0, 5.0])
        self.assertEqual(list(inside), [True, False, True, False])

    def test_punto_interior_en_poligono_concavo(self):
        ring = np.array(U_SHAPE, dtype=float)
        cx, cy = ring[:, 0].mean(), ring[:, 1].mean()
        self.assertFalse(fir.points_in_ring(ring, [cx], [cy])[0])      # el centroide cae afuera
        p = fir.interior_point(ring)
        self.assertTrue(fir.points_in_ring(ring, [p[0]], [p[1]])[0])
        self.assertFalse(fir.points_in_ring(ring, [5.0], [5.0])[0])

    def test_densificar(self):
        ring = np.array([(0, 0), (10, 0), (10, 10)], dtype=float)
        dense = fir.densify(ring, step=1.0)
        self.assertGreater(len(dense), 25)
        self.assertTrue(np.allclose(dense[0], (0, 0)))
        polo = np.array([(0, -46), (10, -46), (0, -90)], dtype=float)
        self.assertEqual(len(fir.densify(polo, step=1.0)), 3 + 10)        # sólo el lado que no toca el polo

    def test_region_bbox_extremos_cobertura(self):
        r = fir.FirRegion("SAVF", polygons=[(np.array([(-73, -39), (-10, -46), (-10, -90), (-73, -90)]), [])])
        self.assertEqual(r.bbox, (-73.0, -10.0, -90.0, -39.0))
        self.assertEqual(r.extremes(), {"norte": -39.0, "sur": -90.0, "este": -10.0, "oeste": -73.0})
        self.assertEqual(fir.coverage(r, (-90, 0, -90, 0)), "completa")
        self.assertEqual(fir.coverage(r, (-90, -22, -64, 4)), "parcial")
        self.assertEqual(fir.coverage(r, (270, 338, -64, 4)), "parcial")         # grilla en 0–360
        self.assertEqual(fir.coverage(r, (0, 60, -30, 10)), "ninguna")
        self.assertEqual(fir.coverage(r, None), "sin grilla")
        self.assertEqual(fir.normalize_grid_bbox(270, 338, -64, 4), (-90.0, -22.0, -64.0, 4.0))

    def test_merge_y_feature(self):
        a = fir.FirRegion("SUEO", polygons=[(np.array([(0, 0), (1, 0), (1, 1)]), [])], label=(0.6, 0.3))
        b = fir.FirRegion("SUEO", polygons=[(np.array([(5, 5), (6, 5), (6, 6)]), [])])
        a.merge(b)
        self.assertEqual(len(a.polygons), 2)
        self.assertEqual(a.bbox, (0.0, 6.0, 0.0, 6.0))
        f = a.to_feature()
        self.assertEqual(f["geometry"]["type"], "MultiPolygon")
        self.assertEqual(f["properties"]["label_lon"], 0.6)
        self.assertEqual(a.label_point(), (0.6, 0.3))
        a.label = (3.0, 3.0)                 # fuera del polígono: se calcula uno interior
        self.assertTrue(a.contains(*a.label_point()))


# ── Carga ────────────────────────────────────────────────────────────────────
class TestCarga(unittest.TestCase):
    def test_copia_incluida(self):
        self.assertTrue(os.path.isfile(fir.BUNDLED_FILE))
        regs = {r.code: r for r in fir.load_geojson(fir.BUNDLED_FILE)}
        self.assertEqual(sorted(regs), sorted(fir.ALL_CODES))
        self.assertEqual(len(regs["SUEO"].polygons), 2)           # continental + oceánica, unidas
        self.assertEqual(regs["SAVF"].bbox[2], -90.0)             # hasta el polo
        self.assertEqual(regs["SAEF"].bbox[1], -10.0)             # sector oceánico hasta 10° W
        for r in regs.values():
            self.assertTrue(r.contains(*r.label_point()), r.code)
            self.assertFalse(r.official)
        self.assertTrue(regs["SACF"].contains(-64.2, -31.4))      # Córdoba
        self.assertTrue(regs["SAEF"].contains(-58.4, -34.6))      # Buenos Aires
        self.assertFalse(regs["SARR"].contains(-58.4, -34.6))
        info = fir.file_info(fir.BUNDLED_FILE)
        self.assertEqual(info["n"], 14)
        self.assertEqual(info["fuente"], "VATSpy")

    def test_filtrar_vatspy(self):
        with open(fir.BUNDLED_FILE, encoding="utf-8") as fh:
            obj = json.load(fh)
        sub = fir.filter_vatspy(obj, ["SAEF", "SUEO"])
        self.assertEqual(sorted(f["properties"]["id"] for f in sub["features"]), ["SAEF", "SUEO", "SUEO"])
        self.assertEqual(sub["_visor"]["licencia"], "CC BY-SA 4.0")
        self.assertIn("NO oficiales", sub["_visor"]["aviso"])

    def test_guardar_y_recargar(self):
        regs = fir.load_geojson(fir.BUNDLED_FILE, codes=["SAVF", "SAMF"])
        with tempfile.TemporaryDirectory() as d:
            p = fir.save_geojson(regs, os.path.join(d, "x.geojson"), {"fuente": "prueba"})
            back = fir.load_geojson(p)
            self.assertEqual(sorted(r.code for r in back), ["SAMF", "SAVF"])
            self.assertEqual(back[0].source, "VATSpy")          # la feature conserva su fuente
            self.assertEqual(fir.load_geojson(p, source_override="x")[0].source, "x")
            self.assertEqual({r.code: r.n_vertices for r in back},
                             {r.code: r.n_vertices for r in regs})

    def test_kml(self):
        kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<Placemark><name>FIR Ezeiza SAEF</name><Polygon><outerBoundaryIs><LinearRing>
<coordinates>-60,-30,0 -50,-30,0 -50,-40,0 -60,-40,0 -60,-30,0</coordinates>
</LinearRing></outerBoundaryIs></Polygon></Placemark>
<Placemark><name>Otra</name><ExtendedData><Data name="id"><value>SAMF</value></Data></ExtendedData>
<MultiGeometry><Polygon><outerBoundaryIs><LinearRing>
<coordinates>-70,-30 -65,-30 -65,-35 -70,-35</coordinates></LinearRing></outerBoundaryIs>
<innerBoundaryIs><LinearRing><coordinates>-68,-32 -67,-32 -67,-33 -68,-33</coordinates></LinearRing></innerBoundaryIs>
</Polygon></MultiGeometry></Placemark>
</Document></kml>"""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "fir.kml")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(kml)
            regs = {r.code: r for r in fir.load_any(p)}
        self.assertEqual(sorted(regs), ["SAEF", "SAMF"])
        self.assertEqual(regs["SAEF"].name, "Ezeiza")
        self.assertTrue(regs["SAEF"].contains(-55, -35))
        self.assertTrue(regs["SAMF"].contains(-66, -31))
        self.assertFalse(regs["SAMF"].contains(-67.5, -32.5))      # agujero

    def test_shapefile(self):
        try:
            import shapefile
        except Exception:
            self.skipTest("sin pyshp")
        with tempfile.TemporaryDirectory() as d:
            base = os.path.join(d, "fir")
            with shapefile.Writer(base, shapeType=shapefile.POLYGON) as w:
                w.field("ICAO", "C", 4)
                w.field("NAME", "C", 40)
                w.poly([[(-60, -30), (-50, -30), (-50, -40), (-60, -40), (-60, -30)]])
                w.record("SAEF", "Ezeiza")
            regs = fir.load_any(base + ".shp")
        self.assertEqual(regs[0].code, "SAEF")
        self.assertTrue(regs[0].contains(-55, -35))

    def test_prioridad_de_fuentes(self):
        old = fir.DATA_DIR
        with tempfile.TemporaryDirectory() as d:
            fir.DATA_DIR = os.path.join(d, "fir")
            try:
                regs, notes = fir.load_layer({})
                self.assertEqual(len(regs), 14)
                self.assertIn("copia incluida", regs["SAEF"].source)
                # descarga de VATSpy: tapa a la copia incluida
                saef = fir.load_geojson(fir.BUNDLED_FILE, codes=["SAEF"])
                fir.save_geojson(saef, fir.data_file(fir.VATSPY_FILE), {"fuente": "VATSpy"})
                regs, _ = fir.load_layer({})
                self.assertEqual(regs["SAEF"].source, "VATSpy (descargado)")
                # archivo propio (AIP): reemplaza sólo a las FIR que trae
                user = os.path.join(d, "aip.geojson")
                with open(user, "w", encoding="utf-8") as fh:
                    json.dump(fir_aip.aip_to_geojson("3917S06307W - 4600S04500W - 4600S01000W - 9000S01000W - 9000S07000W",
                                                     "SAVF"), fh)
                regs, notes = fir.load_layer({"fir_user_file": user})
                self.assertTrue(regs["SAVF"].official)
                self.assertEqual(regs["SAVF"].n_vertices, 5)
                self.assertEqual(regs["SAEF"].source, "VATSpy (descargado)")
                self.assertTrue(any("archivo propio: 1 FIR" in n for n in notes))
                regs, notes = fir.load_layer({"fir_user_file": os.path.join(d, "no.geojson")})
                self.assertTrue(any("no encontrado" in n for n in notes))
            finally:
                fir.DATA_DIR = old


# ── Descargas simuladas ──────────────────────────────────────────────────────
class TestDescarga(unittest.TestCase):
    def test_vatspy(self):
        with open(fir.BUNDLED_FILE, "rb") as fh:
            data = fh.read()
        calls = []

        def fetch(url, headers=None, chunk_cb=None, cancel=None, **kw):
            calls.append(url)
            if chunk_cb:
                chunk_cb(len(data), len(data))
            return data
        msgs = []
        with tempfile.TemporaryDirectory() as d:
            dest = os.path.join(d, "v.geojson")
            path, found, missing = fir.download_vatspy(fetch, progress_cb=lambda m, f: msgs.append((m, f)),
                                                       codes=["SAEF", "SAVF", "XXXX"], dest=dest)
            self.assertEqual(calls, [fir.VATSPY_URL])
            self.assertEqual(found, ["SAEF", "SAVF"])
            self.assertEqual(missing, ["XXXX"])
            self.assertEqual(fir.file_info(path)["n"], 2)
        self.assertEqual(msgs[-1][1], 1.0)
        self.assertTrue(any("MB" in m for m, _f in msgs))

    def test_vatspy_html_de_error(self):
        def fetch(url, headers=None, chunk_cb=None, cancel=None, **kw):
            return b"<html><body>Rate limit exceeded</body></html>"
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(DownloadError) as cm:
                fir.download_vatspy(fetch, dest=os.path.join(d, "v.geojson"))
        self.assertIn("no es JSON", str(cm.exception))
        self.assertIn("Rate limit", str(cm.exception))

    def test_openaip_codigos_y_urls(self):
        self.assertEqual(code_for_name("EZEIZA FIR"), "SAEF")
        self.assertEqual(code_for_name("FIR Comodoro Rivadavia"), "SAVF")
        self.assertEqual(code_for_name("CORDOBA"), "SACF")
        self.assertEqual(code_for_name("SARR"), "SARR")
        self.assertIsNone(code_for_name("TMA BAIRES"))
        src = OpenAipFirSource()
        self.assertEqual(src.key, "openaip_fir")
        self.assertTrue(src.needs_credentials)
        self.assertEqual(src.auth_kinds, ["token"])
        url = src.url({"pais": "ar"}, page=2)
        self.assertIn("country=AR", url)
        self.assertIn("page=2", url)
        self.assertIn("type=10", url)
        self.assertNotIn("type=11", url)
        self.assertIn("type=11", src.url({"incluir_uir": True}))
        self.assertEqual(src.headers({"token": "K"})["x-openaip-api-key"], "K")

    def test_openaip_probar_y_descargar(self):
        src = OpenAipFirSource()
        pages = {
            1: {"totalCount": 2, "totalPages": 2, "items": [
                {"_id": "1", "name": "EZEIZA FIR", "geometry": {"type": "Polygon", "coordinates": [[[-60, -30], [-50, -30], [-50, -40], [-60, -40], [-60, -30]]]}},
                {"_id": "2", "name": "ZONA RARA", "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}}]},
            2: {"totalCount": 2, "totalPages": 2, "items": [
                {"_id": "3", "name": "Comodoro Rivadavia FIR", "geometry": {"type": "Polygon", "coordinates": [[[-70, -40], [-10, -46], [-10, -90], [-70, -90], [-70, -40]]]}}]},
        }
        seen = []

        def fetch(url, headers=None, **kw):
            seen.append(headers.get("x-openaip-api-key"))
            if not headers.get("x-openaip-api-key"):
                raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
            import urllib.parse
            page = int(dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query)).get("page", 1))
            return json.dumps(pages[page]).encode()
        self.assertEqual(src.test_connection({}, {}, fetch_fn=fetch).status, "credenciales")
        self.assertEqual(src.test_connection({}, {"token": ""}, fetch_fn=fetch).status, "credenciales")
        res = src.test_connection({}, {"token": "K"}, fetch_fn=fetch)
        self.assertEqual(res.status, "ok")
        self.assertIn("2 FIR", res.message)

        def fetch_vacio(url, headers=None, **kw):
            return b'{"totalCount": 0, "items": []}'
        self.assertEqual(src.test_connection({}, {"token": "K"}, fetch_fn=fetch_vacio).status, "no_publicado")
        with tempfile.TemporaryDirectory() as d:
            dest = os.path.join(d, "o.geojson")
            path, regs, unknown = src.download_firs({}, {"token": "K"}, fetch_fn=fetch, dest=dest)
            self.assertEqual(sorted(r.code for r in regs), ["SAEF", "SAVF"])
            self.assertEqual(unknown, ["ZONA RARA"])
            back = fir.load_geojson(path)
            self.assertEqual(back[0].source, "openAIP")
            with self.assertRaises(DownloadError):
                src.download_firs({}, {}, fetch_fn=fetch, dest=dest)


# ── Dibujo e integración en la ventana (offscreen) ───────────────────────────
from PyQt6.QtWidgets import QApplication  # noqa: E402
from app import config  # noqa: E402
from app.dialogs import glass_dialog  # noqa: E402

glass_dialog._apply_dialog_blur = lambda w: None
_app = QApplication.instance() or QApplication([])


class TestDibujo(unittest.TestCase):
    def setUp(self):
        from app.wind_plot import WindPlot
        self.plot = WindPlot()
        self.plot.canvas.resize(900, 700)
        self.regs = {r.code: r for r in fir.load_geojson(fir.BUNDLED_FILE)}
        self.lats = np.arange(-64, 4.1, 1.0)
        self.lons = np.arange(-90, -21.9, 1.0)
        X, Y = np.meshgrid(self.lons, self.lats)
        self.u, self.v, self.t = 10 + 0 * X, 5 + 0 * Y, 250 + 0 * X

    def _draw(self, **opts):
        o = {"mode": "viento"}
        o.update(opts)
        self.plot.draw(self.lats, self.lons, self.u, self.v, self.t, o)
        self.plot.canvas.draw()

    def test_todas_las_proyecciones_con_polo(self):
        from app.wind_plot import PROJECTIONS
        self.plot.set_fir(self.regs, fir.ARGENTINA_CODES, fir.NEIGHBOR_CODES)
        for key, _name in PROJECTIONS:
            self.plot.set_projection(key, self.lons, self.lats)
            self._draw()
            # 2 colecciones (Argentina, vecinas) + 14 etiquetas
            self.assertEqual(len(self.plot._fir_artists), 16, key)
            for a in self.plot._fir_artists:
                self.assertIs(a.axes, self.plot.ax)
            # la geometría proyectada queda cacheada y se reutiliza
            key0 = self.plot._fir_key
            self._draw(keep_view=True)
            self.assertEqual(self.plot._fir_key, key0)
            self.assertEqual(len(self.plot._fir_cache), 14)

    def test_seleccion_estilo_y_hit(self):
        self.plot.set_projection("platecarree", self.lons, self.lats)
        self.plot.set_fir(self.regs, ["SAEF", "SAVF"], [], {"color": "#ff0000", "fill_alpha": 0.2})
        self._draw()
        self.assertEqual(len(self.plot._fir_artists), 3)
        coll = self.plot._fir_artists[0]
        self.assertTrue(np.allclose(coll.get_facecolor()[0], (1, 0, 0, 0.2)))
        self.assertEqual([r.code for r in self.plot.fir_at_lonlat(-58.4, -34.6)], ["SAEF"])
        self.assertEqual(self.plot.fir_at_lonlat(-64.2, -31.4), [])          # Córdoba no está seleccionada
        self.assertEqual([r.code for r in self.plot.fir_at_lonlat(-40.0, -50.0)], ["SAVF"])
        v0 = self.regs["SAVF"].rings[0][0]
        x, y = self.plot.ax.transData.transform([v0])[0]
        self.assertEqual(sorted(r.code for r in self.plot.fir_near_edge(x, y)), ["SAEF", "SAVF"])
        x, y = self.plot.ax.transData.transform([[-61.0, -37.0]])[0]    # interior de Ezeiza
        self.assertEqual(self.plot.fir_near_edge(x, y), [])
        from matplotlib.backend_bases import MouseEvent
        ev = MouseEvent("motion_notify_event", self.plot.canvas, x, y)
        inside, edges = self.plot.fir_hit(ev)
        self.assertEqual([r.code for r in inside], ["SAEF"])
        self.assertEqual(edges, [])
        # sin selección no queda nada dibujado
        self.plot.set_fir(self.regs, [], [])
        self._draw()
        self.assertEqual(self.plot._fir_artists, [])

    def test_clic_sin_arrastre(self):
        from matplotlib.backend_bases import MouseEvent
        self.plot.set_projection("platecarree", self.lons, self.lats)
        self.plot.set_fir(self.regs, fir.ARGENTINA_CODES, [])
        self._draw()
        clicks = []
        self.plot.on_click = clicks.append
        x, y = self.plot.ax.transData.transform([[-58.4, -34.6]])[0]
        self.plot._on_press(MouseEvent("button_press_event", self.plot.canvas, x, y, button=1))
        self.plot._on_release(MouseEvent("button_release_event", self.plot.canvas, x + 1, y, button=1))
        self.assertEqual(len(clicks), 1)
        self.plot._on_press(MouseEvent("button_press_event", self.plot.canvas, x, y, button=1))
        self.plot._on_motion(MouseEvent("motion_notify_event", self.plot.canvas, x + 40, y + 30, button=1))
        self.plot._on_release(MouseEvent("button_release_event", self.plot.canvas, x + 40, y + 30, button=1))
        self.assertEqual(len(clicks), 1)                 # arrastre: no es clic


class TestVentana(unittest.TestCase):
    def setUp(self):
        from app.main_window import MainWindow
        from tests.test_grib_reader import _reader_sintetico
        self._tmp = tempfile.TemporaryDirectory()
        self._old_cfg = config.CONFIG_PATH
        self._old_dir = fir.DATA_DIR
        config.CONFIG_PATH = os.path.join(self._tmp.name, "config.json")
        fir.DATA_DIR = os.path.join(self._tmp.name, "fir")
        # Los avisos modales bloquearían el test: se registran en vez de mostrarse
        from PyQt6.QtWidgets import QMessageBox
        self._msgbox = (QMessageBox.critical, QMessageBox.warning, QMessageBox.information)
        self.messages = []
        for name in ("critical", "warning", "information"):
            setattr(QMessageBox, name,
                    staticmethod(lambda *a, _n=name, **k: self.messages.append((_n, a[2] if len(a) > 2 else "")) or 0))
        self.w = MainWindow()
        self.w.show()
        _app.processEvents()
        # Grilla sintética de Sudamérica (4° N – 64° S, 90° W – 22° W, 1°)
        self.reader = _reader_sintetico([850, 700, 500, 300, 200], shape=(69, 69))
        self.reader.lats = np.arange(-64.0, 4.1, 1.0)
        self.reader.lons = np.arange(-90.0, -21.9, 1.0)
        self.reader.path = os.path.join(self._tmp.name, "s.grib2")
        self.w.load_reader(self.reader, self.reader.path)
        _app.processEvents()

    def tearDown(self):
        self.w.close()
        self.w.deleteLater()
        _app.processEvents()
        config.CONFIG_PATH = self._old_cfg
        fir.DATA_DIR = self._old_dir
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.critical, QMessageBox.warning, QMessageBox.information = self._msgbox
        self._tmp.cleanup()

    def _event(self, lon, lat):
        from matplotlib.backend_bases import MouseEvent
        x, y = self.w.plot.ax.transData.transform([[lon, lat]])[0]
        return MouseEvent("motion_notify_event", self.w.plot.canvas, x, y)

    def test_menu_panel_y_configuracion(self):
        w = self.w
        self.assertEqual(len(w._fir_regions), 14)
        self.assertFalse(w._cfg["fir_enabled"])
        self.assertEqual(w.plot._fir_artists, [])
        w._act_fir.trigger()
        _app.processEvents()
        self.assertTrue(w._cfg["fir_enabled"])
        self.assertTrue(w.panel.chk_fir.isChecked())
        self.assertTrue(w.panel.chk_fir_nb.isEnabled())
        self.assertEqual(len(w.plot._fir_artists), 6)          # 1 colección + 5 etiquetas
        w.panel.chk_fir_nb.click()
        _app.processEvents()
        self.assertTrue(w._cfg["fir_neighbors"])
        self.assertTrue(w._act_fir_nb.isChecked())
        self.assertEqual(len(w.plot._fir_artists), 16)
        with open(config.CONFIG_PATH) as fh:
            saved = json.load(fh)
        self.assertTrue(saved["fir_enabled"] and saved["fir_neighbors"])
        w.panel.chk_fir.click()
        _app.processEvents()
        self.assertFalse(w._cfg["fir_enabled"])
        self.assertFalse(w._act_fir.isChecked())
        self.assertEqual(w.plot._fir_artists, [])

    def test_hover_y_clic(self):
        w = self.w
        w._cfg.update({"fir_enabled": True, "fir_neighbors": True})
        w._apply_fir_layer()
        _app.processEvents()
        ev = self._event(-64.2, -31.4)                       # Córdoba
        txt = w.fir_hover_text(ev)
        self.assertIn("FIR Córdoba (SACF)", txt)
        w._on_motion(ev)
        self.assertIn("Córdoba (SACF)", w._statusbar.currentMessage())
        self.assertIn("Lat", w._statusbar.currentMessage())
        w._on_map_click(ev)
        msg = w._statusbar.currentMessage()
        self.assertTrue(msg.startswith("FIR Córdoba (SACF): N -21.72°"), msg)
        self.assertIn("la grilla cubre la FIR completa", msg)
        w._on_map_click(self._event(-40.0, -50.0))           # Comodoro: hasta el polo
        self.assertIn("la grilla cubre la FIR parcialmente", w._statusbar.currentMessage())
        v0 = w._fir_regions["SAVF"].rings[0][0]              # vértice del límite Ezeiza/Comodoro
        self.assertIn("límite SAEF · SAVF", w.fir_hover_text(self._event(*v0)))
        self.assertEqual(w.fir_hover_text(self._event(-85.0, 0.0)), "")

    def test_dialogo_fir(self):
        from app.dialogs.fir_dialog import FirDialog
        from app.dialogs.glass_dialog import GlassDialog
        w = self.w
        dlg = FirDialog(w, cfg=w._cfg, regions=w._fir_regions, notes=w._fir_notes, grid_bbox=w._grid_bbox())
        self.assertIsInstance(dlg, GlassDialog)
        dlg.show()
        _app.processEvents()
        self.assertEqual(dlg.tabs.count(), 4)
        self.assertEqual(dlg.table.rowCount(), 14)
        self.assertEqual(dlg.table.item(0, 1).text(), "SARR")
        self.assertEqual(dlg.table.item(0, 2).text(), "-22.25°")          # norte de Resistencia
        self.assertEqual(dlg.coverage["SACF"], "completa")
        self.assertEqual(dlg.coverage["SAVF"], "parcial")                 # llega al polo
        self.assertEqual(dlg.coverage["FAJO"], "ninguna")
        dlg.chk_enabled.setChecked(True)
        it = next(dlg.lst.item(i) for i in range(dlg.lst.count())
                  if dlg.lst.item(i).data(0x0100) == "SAVF")
        from PyQt6.QtCore import Qt
        it.setCheckState(Qt.CheckState.Unchecked)
        dlg.spin_fill.setValue(25)
        v = dlg.values()
        self.assertTrue(v["fir_enabled"])
        self.assertNotIn("SAVF", v["fir_active"])
        self.assertEqual(v["fir_fill_alpha"], 0.25)
        w._cfg.update(v)
        w._apply_fir_layer()
        _app.processEvents()
        self.assertEqual(len(w.plot._fir_artists), 5)          # 1 colección + 4 etiquetas
        dlg.close()

    def test_convertir_aip_y_archivo_propio(self):
        from app.dialogs.aip_convert_dialog import AipConvertDialog
        from app.dialogs.fir_dialog import FirDialog
        w = self.w
        a = AipConvertDialog(w, start_dir=self._tmp.name)
        a.show()
        _app.processEvents()
        a.cb_code.setCurrentIndex(4)                         # SAVF
        a.text.setPlainText("3917S06307W - 4600S04500W - 4600S01000W - 9000S01000W - 9000S07000W - "
                            "a lo largo del límite internacional hasta 3917S06307W")
        self.assertTrue(a.convert())
        self.assertIn("6 vértices", a.report.toPlainText())
        p = a.save_to(os.path.join(self._tmp.name, "savf.geojson"))
        a.close()
        d = FirDialog(w, cfg=w._cfg, regions=w._fir_regions)
        self.assertTrue(d.set_user_file(p))
        self.assertTrue(os.path.isfile(d._user_file))
        self.assertTrue(d._user_file.startswith(fir.DATA_DIR))
        w._cfg.update(d.values())
        d.close()
        w._load_fir_layer()
        self.assertTrue(w._fir_regions["SAVF"].official)
        self.assertEqual(w._fir_regions["SAVF"].n_vertices, 5)
        self.assertFalse(w._fir_regions["SAEF"].official)
        d2 = FirDialog(w, cfg=w._cfg, regions=w._fir_regions)
        self.assertFalse(d2.set_user_file(os.path.join(self._tmp.name, "nada.geojson")))
        self.assertEqual(self.messages[-1][0], "critical")
        d2.close()

    def test_preferencias_fuentes_openaip(self):
        from app.dialogs.settings_dialog import SettingsDialog
        from app.dialogs.source_config_dialog import SourceConfigDialog
        dlg = SettingsDialog(self.w, cfg=self.w._cfg)
        dlg.show()
        _app.processEvents()
        self.assertEqual(dlg.btn_openaip.text(), "Configurar…")
        sc = SourceConfigDialog(dlg, OpenAipFirSource(), dlg._wrap())
        sc.show()
        _app.processEvents()
        self.assertEqual(sc.params()["auth"], "token")
        self.assertEqual(sc.params()["pais"], "AR")
        self.assertTrue(sc.ed_token.isEnabled())
        sc.close()
        dlg.close()


if __name__ == "__main__":
    unittest.main()
