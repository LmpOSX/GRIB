# -*- coding: utf-8 -*-
"""Visor hexadecimal: el análisis byte a byte de un GRIB2 coincide con
ecCodes, y el diálogo pinta el tramo elegido y navega del volcado al árbol."""
import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from app import config  # noqa: E402
from app import grib_hex as gh  # noqa: E402
from app.dialogs import glass_dialog  # noqa: E402

glass_dialog._apply_dialog_blur = lambda w: None
_app = QApplication.instance() or QApplication([])

try:
    import pyproj  # noqa: F401
    import eccodes as ec
except Exception:  # pragma: no cover
    ec = None

if ec is not None:
    from tests.test_wafs import _grib


def _section(msg, number):
    return next(c for c in msg.children if c.name.startswith(f"Sección {number} "))


def _field(sec, name):
    return next(c for c in sec.children if c.name.startswith(name))


@unittest.skipIf(ec is None, "sin eccodes")
class TestAnalisis(unittest.TestCase):
    def test_mensajes_y_secciones(self):
        data = _grib([850, 500], steps=(6,))
        msgs = gh.scan_messages(data)
        self.assertEqual(len(msgs), 6)
        self.assertEqual(sum(s for _o, s in msgs), len(data))
        m = gh.parse_message(data, msgs[1][0], 1, 6)
        self.assertEqual(m.name, "Mensaje 2 de 6")
        self.assertEqual(m.size, msgs[1][1])
        names = [c.name.split(" · ")[0] for c in m.children]
        self.assertEqual(names, ["Sección 0", "Sección 1", "Sección 3", "Sección 4",
                                 "Sección 5", "Sección 6", "Sección 7", "Sección 8"])
        # Las secciones cubren el mensaje sin huecos ni solapamientos
        pos = m.offset
        for c in m.children:
            self.assertEqual(c.offset, pos)
            pos += c.size
        self.assertEqual(pos, m.end)
        self.assertEqual(_section(m, 8).children[0].value, b"7777")

    def test_campos_coinciden_con_eccodes(self):
        data = _grib([850, 500], steps=(6,), ni=7, nj=3, lat0=-20.0, lon0=290.0, dx=0.5)
        msgs = gh.scan_messages(data)
        for i, (off, size) in enumerate(msgs):
            m = gh.parse_message(data, off, i, len(msgs))
            gid = ec.codes_new_from_message(data[off:off + size])
            try:
                s1, s3, s4, s5 = (_section(m, k) for k in (1, 3, 4, 5))
                self.assertEqual(_field(s1, "Centro generador").value, ec.codes_get_long(gid, "centre"))
                self.assertEqual(_field(s1, "Versión de las tablas maestras").value, ec.codes_get(gid, "tablesVersion"))
                self.assertIn("2026-10-14 06:00:00", _field(s1, "Hora de referencia").text)
                self.assertEqual(_field(s3, "Ni").value, ec.codes_get(gid, "Ni"))
                self.assertEqual(_field(s3, "Nj").value, ec.codes_get(gid, "Nj"))
                self.assertEqual(_field(s3, "La1").value, -20_000_000)
                self.assertEqual(_field(s3, "Lo1").value, 290_000_000)
                self.assertEqual(_field(s3, "Di").value, 500_000)
                self.assertIn("3.0 = lat/lon regular", _field(s3, "Plantilla de grilla").text)
                self.assertEqual(_field(s4, "Plazo").value, 6)
                sup = _field(s4, "Primera superficie")
                self.assertEqual(sup.value, 100)
                self.assertEqual(sup.children[2].value, ec.codes_get(gid, "scaledValueOfFirstFixedSurface"))
                self.assertIn(f"{ec.codes_get(gid, 'level')} hPa", sup.text)
                par = _field(s4, "Parámetro")
                self.assertEqual(par.text.split(" ·")[0],
                                 {"u": "UGRD", "v": "VGRD", "t": "TMP"}[ec.codes_get(gid, "shortName")])
                self.assertAlmostEqual(_field(s5, "Valor de referencia R").value, ec.codes_get(gid, "referenceValue"), places=5)
                self.assertEqual(_field(s5, "Factor de escala binaria E").value, ec.codes_get(gid, "binaryScaleFactor"))
                self.assertEqual(_field(s5, "Factor de escala decimal D").value, ec.codes_get(gid, "decimalScaleFactor"))
                self.assertEqual(_field(s5, "Bits por valor").value, ec.codes_get(gid, "bitsPerValue"))
                # Primeros valores decodificados del empaquetado simple
                datos = _section(m, 7).children[-1]
                vals = ec.codes_get_values(gid)
                for k, v in enumerate(vals[:3]):
                    self.assertIn(f"{v:.6g}", datos.text)
                self.assertIn("TMP" if ec.codes_get(gid, "shortName") == "t" else "GRD", m.text)
            finally:
                ec.codes_release(gid)

    def test_generado_constante_y_centro_faltante(self):
        from app import grib_generate as gg
        data, _ = gg.generate_grib([{"fl": 50, "t_c": 5, "spd_kt": 20, "dir_deg": 270}],
                                   (-30, -32, -60, -58), 1.0, mode="OACI")
        m = gh.parse_message(data, 0)
        self.assertIn("65535 = faltante", _field(_section(m, 1), "Centro generador").text)
        self.assertIn("campo constante", _field(_section(m, 5), "Bits por valor").text)
        self.assertIn("= 278.15", _section(m, 7).children[-1].text)
        self.assertIn("capa 85000 Pa = 850 hPa", m.text)
        # find_at: el byte 23 es el subcentro; el 131 es el tipo de la primera superficie
        self.assertEqual(gh.find_at(m, 23).name, "Subcentro")
        self.assertEqual([n.name for n in gh.path_of(gh.find_at(m, 131))][1:],
                         ["Sección 4 · Definición del producto", "Primera superficie", "Tipo"])
        self.assertEqual(gh.hex_bytes(data, 131, 6), "64 00 00 01 4c 08")

    def test_ieee(self):
        data = _grib([500], steps=(6,), variables=("t",))
        gid = ec.codes_new_from_message(data)
        try:
            ec.codes_set(gid, "packingType", "grid_ieee")
            out = ec.codes_get_message(gid)
            vals = ec.codes_get_values(gid)
        finally:
            ec.codes_release(gid)
        m = gh.parse_message(out, 0)
        self.assertIn("5.4 = IEEE", _field(_section(m, 5), "Plantilla de empaquetado").text)
        self.assertIn(f"{vals[0]:.6g}", _section(m, 7).children[-1].text)

    def test_basura(self):
        self.assertEqual(gh.scan_messages(b"hola mundo, esto no es un GRIB"), [])
        with self.assertRaises(ValueError):
            gh.parse_message(b"xxxxxxxxxxxxxxxxxxxx", 0)


@unittest.skipIf(ec is None, "sin eccodes")
class TestDialogo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = config.CONFIG_PATH
        config.CONFIG_PATH = os.path.join(self._tmp.name, "config.json")
        self.path = os.path.join(self._tmp.name, "a.grib2")
        self.data = _grib([850, 500], steps=(6,))
        with open(self.path, "wb") as fh:
            fh.write(self.data)
        from app.dialogs.hex_dialog import HexViewerDialog
        self.w = HexViewerDialog(None, path=self.path, cfg=dict(config.DEFAULTS))
        self.w.show()
        _app.processEvents()

    def tearDown(self):
        self.w.close()
        self.w.deleteLater()
        _app.processEvents()
        config.CONFIG_PATH = self._old
        self._tmp.cleanup()

    def test_arbol_y_seleccion(self):
        w = self.w
        self.assertEqual(w.tree.topLevelItemCount(), 6)
        self.assertIn("6 mensajes", w.lbl_info.text())
        # Al abrir queda elegido el primer mensaje, pintado entero con el color del nivel 0
        self.assertEqual(w.hex.selection(), (0, w._messages[0][1]))
        self.assertEqual(w.hex.path(), [(0, w._messages[0][1], 0)])
        # Desplegar el segundo mensaje («+») lo desarrolla pero no cambia lo pintado
        it = w.tree.topLevelItem(1)
        self.assertEqual(it.childCount(), 0)
        it.setExpanded(True)
        _app.processEvents()
        self.assertEqual(it.childCount(), 8)
        self.assertIn("UGRD", it.text(1))
        self.assertEqual(w.hex.path(), [(0, w._messages[0][1], 0)])
        self.assertIs(w.tree.currentItem(), w.tree.topLevelItem(0))
        sec4 = it.child(3)
        sup = next(sec4.child(k) for k in range(sec4.childCount()) if sec4.child(k).text(0) == "Primera superficie")
        w.tree.setCurrentItem(sup)
        _app.processEvents()
        node = w.current_node()
        self.assertEqual(node.name, "Primera superficie")
        self.assertEqual(w.hex.selection(), (node.offset, 6))
        # Se pinta toda la ruta: mensaje (nivel 0), sección 4 (nivel 1) y el campo (nivel 2)
        path = w.hex.path()
        self.assertEqual([k for _o, _s, k in path], [0, 1, 2])
        self.assertEqual(path[0][:2], tuple(w._messages[1]))
        self.assertEqual(path[1][:2], (node.parent.offset, node.parent.size))
        self.assertEqual(path[2][:2], (node.offset, 6))
        # Los subcampos (tipo / factor / valor) no se pintan hasta elegirlos
        self.assertEqual(sup.childCount(), 3)
        w.tree.setCurrentItem(sup.child(2))
        _app.processEvents()
        self.assertEqual([k for _o, _s, k in w.hex.path()], [0, 1, 2, 3])
        self.assertEqual(w.hex.selection(), (node.offset + 2, 4))
        # Cada renglón lleva el cuadrito del color de su nivel
        self.assertFalse(it.icon(0).isNull())
        self.assertEqual(sec4.icon(0).cacheKey(), it.child(0).icon(0).cacheKey())
        self.assertNotEqual(sec4.icon(0).cacheKey(), sup.icon(0).cacheKey())
        w.tree.setCurrentItem(sup)
        _app.processEvents()
        self.assertIn("64 00 00 00 c3 50", w.lbl_detail.text())    # el segundo mensaje es 500 hPa
        self.assertIn("capa 50000 Pa = 500 hPa", w.lbl_detail.text())
        self.assertIn("Mensaje 2 de 6 ▸ Sección 4", w.lbl_detail.text())

    def test_clic_en_un_byte_abre_el_arbol(self):
        w = self.w
        off = w._messages[3][0]
        w.select_byte(off + 23)                                 # subcentro del cuarto mensaje
        _app.processEvents()
        node = w.current_node()
        self.assertEqual(node.name, "Subcentro")
        self.assertEqual([n.name for n in gh.path_of(node)][0], "Mensaje 4 de 6")
        self.assertTrue(w.tree.topLevelItem(3).isExpanded())
        self.assertEqual(w.hex.selection(), (off + 23, 2))
        # «Ir al byte» en hexadecimal
        w.ed_goto.setText(f"0x{off + 158:x}")
        w._goto()
        self.assertEqual(w.current_node().name, "Factor de escala binaria E")
        # Fuera del archivo no cambia nada
        w.select_byte(10 ** 9)
        self.assertEqual(w.current_node().name, "Factor de escala binaria E")

    def test_byte_bajo_el_cursor(self):
        w = self.w
        from PyQt6.QtCore import QPoint
        hv = w.hex
        hv.resize(hv.sizeHint())
        _app.processEvents()
        r = hv._byte_rect(0x15, 0)
        self.assertEqual(hv.byte_at(QPoint(r.center().x(), r.center().y())), 0x15)
        a = hv._ascii_rect(0x21, 0)
        self.assertEqual(hv.byte_at(QPoint(a.center().x(), a.center().y())), 0x21)
        self.assertIsNone(hv.byte_at(QPoint(2, 2)))             # columna de la posición

    def test_colores_del_tema(self):
        from app.theme import hex_colors
        c = hex_colors("#4a90d9")
        self.assertEqual(len(c["levels"]), 8)
        self.assertEqual(len({x.name() for x in c["levels"]}), 8)
        self.assertIsNotNone(self.w.hex._colors)


if __name__ == "__main__":
    unittest.main()
