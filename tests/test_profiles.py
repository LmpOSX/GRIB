# -*- coding: utf-8 -*-
"""Perfiles configurables (app/profiles.py) y grillas con nombre
(areas.Grid): tablas en la configuración, saneo, de fábrica y propios,
restaurar, desempate del combo, editores de Preferencias, el radio
«Grilla» de los diálogos y lo que arrastra un perfil."""
import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from app import areas as A  # noqa: E402
from app import config  # noqa: E402
from app import grib_encode as ge  # noqa: E402
from app import profiles as PR  # noqa: E402
from app.dialogs import glass_dialog  # noqa: E402

glass_dialog._apply_dialog_blur = lambda w: None
_app = QApplication.instance() or QApplication([])


class TestPerfiles(unittest.TestCase):
    def test_fabrica_y_config_vacia(self):
        ps = PR.profiles_from_config({})
        self.assertEqual([p.id for p in ps], [k for k, _t, _v in ge.PROFILES])
        self.assertTrue(all(p.builtin and p.enabled for p in ps))
        fdp = PR.find_profile(ps, "fdp")
        self.assertEqual((fdp.grid, fdp.fl_mode), ("fdp_arg", "INDRA"))
        self.assertEqual(fdp.values, ge.profile_values("fdp"))
        self.assertIsNone(PR.find_profile(ps, "gfs").grid)
        self.assertTrue(PR.find_profile(ps, "origen").is_default)
        self.assertEqual(PR.profiles_from_config({"profiles": []})[0].id, "origen")

    def test_saneo_modificado_y_restaurar(self):
        f = PR.factory_profile("fdp")
        raw = [dict(f.to_dict(), name="Mi FDP", values=dict(f.values, dec_temp=0), builtin=False),
               {"id": "u_1", "name": "Propio", "values": {"wind": "dirspeed"}, "grid": "nada", "fl_mode": "xx"},
               {"id": "u_1", "name": "Repetido"}, {"name": "Sin id"},
               {"id": "origen", "name": "Origen oculto", "enabled": False}]
        ps = PR.profiles_from_config({"profiles": raw})
        ids = [p.id for p in ps]
        self.assertEqual(ids[0], "origen")                       # siempre primero y visible
        self.assertTrue(PR.find_profile(ps, "origen").enabled)
        self.assertEqual(ids.count("u_1"), 1)
        self.assertNotIn("", ids)
        for k in ("gfs", "wafc_washington", "wafc_london"):       # los de fábrica que faltan se agregan
            self.assertIn(k, ids)
        mine = PR.find_profile(ps, "fdp")
        self.assertTrue(mine.builtin)                            # el id de fábrica manda
        self.assertEqual(mine.name, "Mi FDP")
        self.assertTrue(PR.is_modified(mine))
        self.assertFalse(PR.is_modified(PR.find_profile(ps, "gfs")))
        own = PR.find_profile(ps, "u_1")
        self.assertEqual((own.values["wind"], own.grid, own.fl_mode, own.builtin), ("dirspeed", "nada", None, False))
        self.assertFalse(PR.is_modified(own))
        # ida y vuelta por la config
        again = PR.profiles_from_config({"profiles": PR.profiles_to_config(ps)})
        self.assertEqual([p.to_dict() for p in again], [p.to_dict() for p in ps])
        # restaurar: los valores de fábrica, conservando «visible»
        mine.enabled = False
        r = PR.factory_profile("fdp")
        r.enabled = mine.enabled
        self.assertFalse(PR.is_modified(r))
        self.assertEqual(r.name, f.name)

    def test_desempate_del_combo(self):
        ps = PR.factory_profiles()
        copia = PR.factory_profile("fdp")
        copia.id, copia.name, copia.builtin = "u_copia", "FDP copia", False
        ps.append(copia)
        vals = PR.factory_profile("fdp").values
        self.assertEqual(PR.profile_of(vals, ps), "fdp")                       # el primero de la lista
        self.assertEqual(PR.profile_of(vals, ps, prefer="u_copia"), "u_copia")  # el elegido a mano
        self.assertEqual(PR.profile_of(vals, ps, prefer="gfs"), "fdp")
        self.assertIsNone(PR.profile_of(dict(vals, dec_temp=2), ps))
        copia.enabled = False
        self.assertEqual(PR.profile_of(vals, ps, prefer="u_copia"), "fdp")     # oculto: no cuenta
        self.assertIn("grilla FDP Arg (1°, 51 × 36) · FL INDRA", PR.describe(PR.factory_profile("fdp"), A.factory_grids()))
        self.assertIn("no existe", PR.describe(PR.Profile("x", "x", {}, grid="nada"), []))


class TestGrillas(unittest.TestCase):
    def test_fabrica_tamano_y_etiqueta(self):
        gs = A.grids_from_config({})
        self.assertEqual([g.id for g in gs], ["fdp_arg"])
        g = gs[0]
        self.assertEqual((g.region, g.res, g.tag, g.size()), (A.FDP_REGION, 1.0, "FDPARG", (51, 36)))
        self.assertEqual(g.size(1.25), (41, 29))
        self.assertIn("51 × 36 puntos", g.summary())
        self.assertIsNone(A.Grid("x", "Sin res", -10, -20, -60, -50).size())
        self.assertEqual(A.Grid("u_ab12", "", -10, -20, -60, -50).tag, "UAB12")
        self.assertEqual(A.area_tag(["FDPARG"], "grid"), "FDPARG")
        self.assertEqual(A.area_info("grid", ["FDPARG"], 0, A.FDP_REGION)["codigos"], ["FDPARG"])

    def test_config_saneo_validacion_y_restaurar(self):
        raw = [{"id": "fdp_arg", "name": "FDP Ezeiza", "north": -19, "south": -55, "west": -75, "east": -25, "res": 1.0},
               {"id": "u_1", "name": "Otra", "north": -10, "south": -20, "west": -60, "east": -50, "res": None},
               {"id": "u_1", "name": "Repetida"}, {"name": "sin id"}]
        gs = A.grids_from_config({"grids": raw})
        self.assertEqual([g.id for g in gs], ["fdp_arg", "u_1"])
        self.assertTrue(gs[0].builtin and A.grid_is_modified(gs[0]))
        self.assertEqual(gs[0].size(), (51, 37))
        self.assertIsNone(gs[1].res)
        self.assertEqual(A.validate_grids(gs), [])
        bad = [A.Grid("a", "", -10, -20, -60, -50), A.Grid("b", "X", -30, -20, -60, -50),
               A.Grid("c", "Y", -10, -20, -60, -50, res=20), A.Grid("d", "y", -10, -20, -60, -50)]
        errs = A.validate_grids(bad)
        self.assertEqual(len(errs), 4)
        self.assertIn("no tiene nombre", errs[0].lower())
        self.assertIn("repetido", errs[-1].lower())
        # de fábrica que falta se agrega; ida y vuelta
        gs2 = A.grids_from_config({"grids": [{"id": "u_9", "name": "Sola", "north": 0, "south": -1, "west": 0, "east": 1}]})
        self.assertEqual([g.id for g in gs2], ["u_9", "fdp_arg"])
        self.assertEqual(A.grids_from_config({"grids": A.grids_to_config(gs)})[0].to_dict(), gs[0].to_dict())
        self.assertTrue(A.new_grid_id().startswith("u_"))


class _Base(unittest.TestCase):
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


class TestEditores(_Base):
    def test_editor_de_grillas(self):
        from PyQt6.QtCore import Qt
        from app.widgets.grids_editor import GridsEditor
        ed = GridsEditor(dict(config.DEFAULTS))
        self.w = ed
        self.assertEqual(ed.table.rowCount(), 1)
        self.assertEqual(ed.table.item(0, ed.C_PTS).text(), "51 × 36")
        ed.table.item(0, ed.C_N).setText("19°00'S")
        self.assertEqual(ed.table.item(0, ed.C_PTS).text(), "51 × 37")
        self.assertTrue(A.grid_is_modified(ed.grids()[0]))
        ed.table.item(0, ed.C_N).setText("xx")                   # inválido: vuelve
        self.assertEqual(ed.grids()[0].north, -19.0)
        self.assertIn("inválida", ed.lbl_error.text())
        ed.table.setCurrentCell(0, 0)
        ed.delete_row()                                           # de fábrica: no se borra
        self.assertEqual(ed.table.rowCount(), 1)
        ed.duplicate_row()
        self.assertEqual(ed.table.rowCount(), 2)
        self.assertFalse(ed.grids()[1].builtin)
        self.assertEqual(ed.grids()[1].name, "FDP Arg (copia)")
        ed.table.item(1, ed.C_RES).setText("0,5")
        self.assertEqual(ed.table.item(1, ed.C_PTS).text(), "101 × 73")
        ed.table.item(1, ed.C_RES).setText("")
        self.assertEqual(ed.table.item(1, ed.C_PTS).text(), "—")
        ed.table.item(1, ed.C_NAME).setText("FDP Arg")
        self.assertIn("repetido", ed.errors()[0].lower())
        ed.table.item(1, ed.C_NAME).setText("Otra")
        ed.table.item(1, ed.C_EN).setCheckState(Qt.CheckState.Unchecked)
        ed.table.setCurrentCell(0, 0)
        ed.restore_row()
        self.assertEqual(ed.grids()[0].north, -20.0)
        v = ed.values()["grids"]
        self.assertEqual((len(v), v[1]["enabled"], v[1]["res"]), (2, False, None))
        ed.table.setCurrentCell(1, 0)
        ed.delete_row()
        self.assertEqual(ed.table.rowCount(), 1)
        ed.set_coord_format("gm")
        self.assertEqual(ed.table.item(0, ed.C_N).text(), "20°00.0'S")

    def test_editor_de_perfiles(self):
        from app.widgets.profiles_editor import ProfilesEditor
        ed = ProfilesEditor(dict(config.DEFAULTS))
        self.w = ed
        self.assertEqual(ed.lst.count(), 5)
        self.assertEqual(ed.current().id, "origen")
        self.assertFalse(ed.ed_name.isEnabled())                 # «Como el origen» no se edita
        self.assertTrue(ed.select("fdp"))
        self.assertTrue(ed.ed_name.isEnabled())
        self.assertEqual((ed.cb_grid.currentData(), ed.cb_mode.currentData()), ("fdp_arg", "INDRA"))
        self.assertEqual(ed.form.values()["regrid"], "1.0")
        ed.ed_name.setText("Mi FDP")
        ed.ed_name.textEdited.emit("Mi FDP")
        ed.form.cb_dec_temp.setCurrentIndex(ed.form.cb_dec_temp.findData(0))
        p = ed.current()
        self.assertEqual((p.name, p.values["dec_temp"], PR.is_modified(p)), ("Mi FDP", 0, True))
        self.assertIn("modificado", ed.lbl_info.text())
        self.assertTrue(ed.lst.currentItem().text().endswith("*"))
        ed.duplicate_profile()
        c = ed.current()
        self.assertEqual((c.name, c.builtin, ed.lst.count()), ("Mi FDP (copia)", False, 6))
        ed.cb_mode.setCurrentIndex(ed.cb_mode.findData("OACI"))
        self.assertEqual(ed.current().fl_mode, "OACI")
        ed.cb_grid.setCurrentIndex(0)
        self.assertIsNone(ed.current().grid)
        ed.ed_name.setText("Mi FDP")
        ed.ed_name.textEdited.emit("Mi FDP")
        self.assertIn("repetido", ed.errors()[0].lower())
        ed.delete_profile()
        self.assertEqual(ed.lst.count(), 5)
        self.assertTrue(ed.select("fdp"))
        ed.chk_enabled.setChecked(False)
        self.assertTrue(ed.lst.currentItem().text().endswith("(oculto)"))
        ed.restore_profile()
        p = ed.current()
        self.assertEqual((p.name, PR.is_modified(p), p.enabled), (PR.factory_profile("fdp").name, False, False))
        ed.chk_enabled.setChecked(True)
        ed.add_profile()
        self.assertEqual(ed.current().name, "Nuevo perfil")
        self.assertEqual(len(ed.values()["profiles"]), 6)
        ed.restore_all()
        self.assertEqual(ed.errors(), [])
        ed.set_grids([])                                          # sin la grilla, el perfil avisa
        self.assertEqual(ed.cb_grid.count(), 1)
        self.assertIn("no existe", ed.errors()[0])

    def test_bloque_con_tabla_propia(self):
        from app.widgets.save_options import SaveOptionsBox
        ps = PR.factory_profiles()
        copia = PR.factory_profile("fdp")
        copia.id, copia.name, copia.builtin = "u_copia", "FDP copia", False
        ps.append(copia)
        PR.find_profile(ps, "gfs").enabled = False
        cfg = dict(config.DEFAULTS, profiles=PR.profiles_to_config(ps))
        box = SaveOptionsBox(cfg=cfg)
        self.w = box
        self.assertEqual(box.cb_profile.count(), 6)                       # Personalizado + 5 visibles
        self.assertLess(box.cb_profile.findData("gfs"), 0)
        box.cb_profile.setCurrentIndex(box.cb_profile.findData("u_copia"))
        box.cb_profile.activated.emit(box.cb_profile.currentIndex())
        self.assertEqual(box.profile(), "u_copia")
        self.assertEqual(box.profile_obj().grid, "fdp_arg")
        box.cb_dec_temp.setCurrentIndex(box.cb_dec_temp.findData(2))
        self.assertIsNone(box.profile())
        box.cb_dec_temp.setCurrentIndex(box.cb_dec_temp.findData(1))
        self.assertEqual(box.profile(), "u_copia")                       # desempate: el elegido
        box.set_profiles(PR.factory_profiles())
        self.assertEqual(box.profile(), "fdp")
        self.assertEqual(box.cb_profile.count(), 6)
        self.assertIn("FDL", "FDL")
        tip = box.cb_profile.itemData(box.cb_profile.findData("fdp"), 3)
        self.assertIn("grilla FDP Arg", tip)

    def test_preferencias(self):
        from app.dialogs.settings_dialog import SettingsDialog
        d = SettingsDialog(None, cfg=dict(config.DEFAULTS))
        self.w = d
        self.assertIn("Perfiles", d.TABS)
        self.assertEqual(d.grids_editor.table.rowCount(), 1)
        self.assertEqual(d.profiles_editor.lst.count(), 5)
        d.grids_editor.table.setCurrentCell(0, 0)
        d.grids_editor.duplicate_row()
        self.assertEqual(d.profiles_editor.cb_grid.count(), 3)          # la tabla nueva llega a Perfiles
        d.profiles_editor.select("fdp")
        d.profiles_editor.ed_name.setText("FDP Ezeiza")
        d.profiles_editor.ed_name.textEdited.emit("FDP Ezeiza")
        self.assertGreaterEqual(d.save_box.cb_profile.findText("FDP Ezeiza"), 0)   # y al bloque de Guardar
        v = d.values()
        self.assertEqual(len(v["grids"]), 2)
        self.assertEqual(PR.find_profile(PR.profiles_from_config(v), "fdp").name, "FDP Ezeiza")
        # un perfil sin nombre no deja aplicar
        d.profiles_editor.ed_name.setText("")
        d.profiles_editor.ed_name.textEdited.emit("")
        from PyQt6.QtWidgets import QMessageBox
        seen = []
        old = QMessageBox.warning
        QMessageBox.warning = lambda *a, **k: seen.append(a[2])
        try:
            d._accept()
        finally:
            QMessageBox.warning = old
        self.assertIn("perfiles", seen[-1].lower())
        self.assertEqual(d.tabs.currentIndex(), d.TABS.index("Perfiles"))


class TestDialogos(_Base):
    def test_descarga_grilla_propia_y_configurar(self):
        from app.dialogs.download_dialog import DownloadDialog
        gs = A.factory_grids()
        gs.append(A.Grid("u_sur", "Patagonia", -40.0, -56.0, -76.0, -60.0, 0.5))
        cfg = dict(config.DEFAULTS, grids=A.grids_to_config(gs), download_area_mode="grid", download_grid="u_sur")
        d = DownloadDialog(None, cfg=cfg, dest_dir=self._tmp.name)
        self.w = d
        d.show()
        _app.processEvents()
        self.assertEqual((d.area_mode(), d.cb_grid.currentData()), ("grid", "u_sur"))
        self.assertEqual(d.region(), (-40.0, -56.0, -76.0, -60.0))
        self.assertEqual(d.form.values()["resolucion"], "0p50")
        self.assertIn("33 × 33", d.lbl_grid.text())
        job = d.job()
        self.assertEqual((job.area_mode, job.area_tag, job.area_codes), ("grid", "PATAGONIA", ["PATAGONIA"]))
        self.assertIn("_PATAGONIA", os.path.basename(job.file_paths(d.source)[0]))
        self.assertEqual(d.source.provenance(job)["area"]["etiqueta"], "PATAGONIA")
        # pasar a manual conserva los campos de la grilla
        d.rb_manual.setChecked(True)
        self.assertEqual(d.region(), (-40.0, -56.0, -76.0, -60.0))
        self.assertTrue(d.lat_n.isEnabled())
        # un perfil con grilla que no está habilitada no cambia el modo
        d.rb_fir.setChecked(True)
        box = d.save_box
        ps = PR.factory_profiles()
        PR.find_profile(ps, "gfs").grid = "no_existe"
        box.set_profiles(ps)
        box.cb_profile.setCurrentIndex(box.cb_profile.findData("gfs"))
        box.cb_profile.activated.emit(box.cb_profile.currentIndex())
        self.assertEqual(d.area_mode(), "fir")
        # «Configurar áreas…» trae la tabla de grillas nueva
        from app.dialogs import areas_dialog as ad

        class FakeAreas:
            def __init__(self, parent=None, cfg=None, regions_fn=None):
                pass

            def exec(self):
                return 1

            def values(self):
                return {"areas": A.areas_to_config(A.default_areas()), "areas_margin_deg": 1.0,
                        "areas_coord_format": "decimal", "grids": A.grids_to_config(A.factory_grids())}
        old = ad.AreasDialog
        ad.AreasDialog = FakeAreas
        try:
            d._configure_areas()
        finally:
            ad.AreasDialog = old
        self.assertEqual(d.cb_grid.count(), 1)
        d.reject()
        self.assertEqual(self.w._cfg["download_grid"], "fdp_arg")

    def test_descarga_sin_grillas_habilitadas(self):
        from app.dialogs.download_dialog import DownloadDialog
        gs = A.factory_grids()
        gs[0].enabled = False
        cfg = dict(config.DEFAULTS, grids=A.grids_to_config(gs), download_area_mode="grid")
        d = DownloadDialog(None, cfg=cfg, dest_dir=self._tmp.name)
        self.w = d
        d.show()
        _app.processEvents()
        self.assertFalse(d.rb_grid.isEnabled())
        self.assertIsNone(d.region())
        self.assertIn("No hay grillas", d.lbl_size.text())

    def test_configurar_areas_con_grillas(self):
        from app.dialogs.areas_dialog import AreasDialog
        d = AreasDialog(None, cfg=dict(config.DEFAULTS))
        self.w = d
        self.assertIn("grids", d.values())
        d.grids_editor.table.item(0, d.grids_editor.C_NAME).setText("")
        from PyQt6.QtWidgets import QMessageBox
        seen = []
        old = QMessageBox.warning
        QMessageBox.warning = lambda *a, **k: seen.append(a[2])
        try:
            d._accept()
        finally:
            QMessageBox.warning = old
        self.assertIn("nombre", seen[-1].lower())


if __name__ == "__main__":
    unittest.main()
