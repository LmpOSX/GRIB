# -*- coding: utf-8 -*-
"""Tests offscreen de la ventana principal y los diálogos (Fase 2).

Se corren con QT_QPA_PLATFORM=offscreen. El desenfoque nativo de los
diálogos se anula (hace segfault en offscreen) y la configuración se aísla
en un directorio temporal.
"""
import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from app import config  # noqa: E402
from app.dialogs import glass_dialog  # noqa: E402

glass_dialog._apply_dialog_blur = lambda w: None

_app = QApplication.instance() or QApplication([])


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_cfg_path = config.CONFIG_PATH
        config.CONFIG_PATH = os.path.join(self._tmp.name, "config.json")
        self.w = None

    def tearDown(self):
        if self.w is not None:
            self.w.close()
            self.w.deleteLater()
            _app.processEvents()
        config.CONFIG_PATH = self._old_cfg_path
        self._tmp.cleanup()


class TestMainWindow(_Base):
    def _window(self):
        from app.main_window import MainWindow
        self.w = MainWindow()
        self.w.show()
        _app.processEvents()
        return self.w

    def test_abre_y_cierra(self):
        w = self._window()
        self.assertTrue(w.isVisible())
        self.assertEqual(w.windowTitle(), "Visor GRIB")
        self.assertTrue(w._welcome.isVisible())
        self.assertFalse(w._main_area.isVisible())
        w.close()
        self.assertTrue(os.path.exists(config.CONFIG_PATH))

    def test_menus(self):
        w = self._window()
        titles = [a.text() for a in w._menubar.actions()]
        self.assertEqual(titles, ["Archivo", "Vista", "Ayuda"])
        self.assertFalse(w._act_export_png.isEnabled())
        self.assertFalse(w._act_close.isEnabled())
        self.assertEqual(w._act_open.shortcut().toString(), "Ctrl+O")
        self.assertEqual(w._act_full.shortcut().toString(), "Ctrl+Shift+0")
        self.assertEqual(w._act_layer.shortcut().toString(), "Ctrl+D")

    def test_zoom_de_fuente_persistido(self):
        import json
        w = self._window()
        base = w._cfg["font_size"]
        w._font_size_up()
        self.assertEqual(w._cfg["font_size"], base + 1)
        with open(config.CONFIG_PATH) as fh:
            self.assertEqual(json.load(fh)["font_size"], base + 1)
        w._font_size_reset()
        self.assertEqual(w._cfg["font_size"], 13)
        w._font_size_down()
        self.assertEqual(w._cfg["font_size"], 12)

    def test_un_solo_escape(self):
        from PyQt6.QtGui import QShortcut
        w = self._window()
        escapes = [s for s in w.findChildren(QShortcut)
                   if s.key().toString() == "Esc"]
        self.assertEqual(len(escapes), 1)

    def test_recientes_faltante_se_elimina(self):
        w = self._window()
        w._cfg["recent_files"] = ["/ruta/que/no/existe.grib2"]
        w._refresh_recent_menu()
        from PyQt6.QtWidgets import QMessageBox
        old = QMessageBox.warning
        QMessageBox.warning = staticmethod(lambda *a, **k: None)
        try:
            w._open_recent("/ruta/que/no/existe.grib2")
        finally:
            QMessageBox.warning = old
        self.assertEqual(w._cfg["recent_files"], [])

    def test_objetos_del_stylesheet(self):
        w = self._window()
        names = {c.objectName() for c in w.findChildren(object)
                 if hasattr(c, "objectName")}
        for n in ("MainContainer", "AppMenuBar", "ContentPanel", "ActionBar",
                  "ActionSep", "WelcomeWidget"):
            self.assertIn(n, names)

    def test_tema_cambia_stylesheet(self):
        w = self._window()
        before = _app.styleSheet()
        w._apply_theme("#C0674D")
        self.assertNotEqual(before, _app.styleSheet())
        self.assertEqual(w._cfg["accent_color"], "#C0674D")


class TestDialogos(_Base):
    def test_settings(self):
        from app.dialogs.settings_dialog import SettingsDialog
        cfg = dict(config.DEFAULTS)
        cfg.update({"accent_color": "#4A90D9", "opacity": 180, "projection": "mercator",
                    "map_stride": 3, "map_wind_style": "flechas", "map_label_size": 9, "map_grid_step": 5,
                    "map_label_units": False, "cache_max_mb": 123, "engine": "wgrib2",
                    "wgrib2_path": "/no/existe/wgrib2",
                    "sources": {"gfs": {"enabled": True, "params": {"resolucion": "0p50"}}}})
        self.w = SettingsDialog(None, cfg=cfg)
        self.w.show()
        _app.processEvents()
        self.assertTrue(self.w.isVisible())
        # Pestañas
        self.assertEqual([self.w.tabs.tabText(i) for i in range(self.w.tabs.count())],
                         list(SettingsDialog.TABS))
        # Carga los valores actuales
        v = self.w.values()
        self.assertEqual(v["projection"], "mercator")
        self.assertEqual(v["map_stride"], 3)
        self.assertEqual(v["map_wind_style"], "flechas")
        self.assertEqual((v["map_label_size"], v["map_label_units"]), (9, False))
        self.assertEqual(v["map_grid_step"], 5)
        self.assertEqual(v["cache_max_mb"], 123)
        self.assertEqual(v["engine"], "wgrib2")
        self.assertEqual(v["wgrib2_path"], "/no/existe/wgrib2")
        self.assertEqual(v["sources"]["gfs"]["params"]["resolucion"], "0p50")
        from app.grib_engines import find_wgrib2
        # La ruta no existe: sólo se encuentra si hay wgrib2 en el PATH / WGRIB2
        esperado = "Encontrado" if find_wgrib2() else "no encontrado"
        self.assertIn(esperado, self.w.lbl_wgrib2.text())
        # Fuentes: lista con el GFS habilitado; destildar lo deshabilita
        self.assertEqual(self.w.lst_sources.count(), len(__import__("app.sources", fromlist=["SOURCES"]).SOURCES))
        item = self.w.lst_sources.item(0)
        self.assertEqual(item.data(Qt.ItemDataRole.UserRole), "gfs")
        item.setCheckState(Qt.CheckState.Unchecked)
        self.assertFalse(self.w.values()["sources"]["gfs"]["enabled"])
        item.setCheckState(Qt.CheckState.Checked)
        # Cambios
        self.w._select_color("#5B8C5A")
        self.assertEqual(self.w.selected_color(), "#5B8C5A")
        self.w.rb_engine["eccodes"].setChecked(True)
        self.w.chk_fill.setChecked(True)
        v = self.w.values()
        self.assertEqual(v["accent_color"], "#5B8C5A")
        self.assertEqual(v["engine"], "eccodes")
        self.assertTrue(v["map_fill"])
        self.assertTrue(v["sources"]["gfs"]["enabled"])
        self.w.accept()
        self.assertFalse(self.w.isVisible())

    def test_ventana_aplica_preferencias(self):
        """Aplicar Preferencias cambia tema, CONFIG del panel y proyección, y
        persiste; las opciones del panel también se guardan al tocarlas."""
        from app.main_window import MainWindow
        self.w = MainWindow()
        self.w.show()
        _app.processEvents()
        vals = dict(self.w._cfg)
        vals.update({"accent_color": "#C0674D", "map_grid": True, "map_stride": 4, "map_wind_style": "curvas",
                     "projection": "mercator", "cache_max_days": 7,
                     "sources": {"gfs": {"enabled": True, "params": {"resolucion": "1p00"}}},
                     "engine": "eccodes"})
        self.w.apply_settings(vals)
        self.assertTrue(self.w.panel.chk_grid.isChecked())
        self.assertEqual(self.w.panel.spin_stride.value(), 4)
        self.assertEqual(self.w.panel.options()["wind_style"], "curvas")
        self.assertEqual(self.w.panel.projection(), "mercator")
        saved = config.load_config()
        self.assertEqual(saved["accent_color"], "#C0674D")
        self.assertEqual(saved["projection"], "mercator")
        self.assertEqual(saved["cache_max_days"], 7)
        self.assertEqual(saved["sources"]["gfs"]["params"]["resolucion"], "1p00")
        self.assertEqual(self.w.cb_source.currentData(), "gfs")
        self.assertTrue(saved["map_grid"])
        # Tocar CONFIG en el panel persiste el nuevo valor inicial
        self.w.panel.chk_extra.setChecked(True)
        _app.processEvents()
        self.assertTrue(config.load_config()["map_extra_info"])

    def test_motor_wgrib2_ausente_cae_a_eccodes(self):
        """Con motor wgrib2 configurado pero sin el programa, abrir un archivo
        avisa y sigue con ecCodes."""
        from app import grib_reader as gr
        if gr.ec is None:
            self.skipTest("sin eccodes")
        from app.main_window import MainWindow
        from app import main_window as mw
        from tests.test_grib_reader import _escribir_grib_sintetico
        path = os.path.join(self._tmp.name, "s.grib2")
        _escribir_grib_sintetico(path)
        self.w = MainWindow()
        self.w._cfg["engine"] = "wgrib2"
        self.w._cfg["wgrib2_path"] = os.path.join(self._tmp.name, "no_existe")
        avisos = []
        old_env = os.environ.pop("WGRIB2", None)
        old_which, old_warn = mw.QMessageBox.warning, None
        import shutil
        old_sw = shutil.which
        shutil.which = lambda *a, **k: None
        mw.QMessageBox.warning = staticmethod(lambda *a, **k: avisos.append(a[1]))
        try:
            self.w.open_file(path)
        finally:
            mw.QMessageBox.warning = old_which
            shutil.which = old_sw
            if old_env is not None:
                os.environ["WGRIB2"] = old_env
        self.assertEqual(avisos, ["wgrib2 no disponible"])
        self.assertIsNotNone(self.w._reader)
        self.assertEqual(self.w._reader.engine, "eccodes")
        self.assertIn("Motor: ecCodes", self.w._reader.inventory_text())

    def test_shortcuts(self):
        from app.dialogs.shortcuts_dialog import ShortcutsDialog, SHORTCUTS
        self.w = ShortcutsDialog(None)
        self.w.show()
        _app.processEvents()
        self.assertEqual(self.w._table.rowCount(), len(SHORTCUTS))
        self.w.accept()

    def test_about(self):
        from app.dialogs.about_dialog import AboutDialog
        from app.dialogs.glass_dialog import GlassDialog
        self.w = AboutDialog(None)
        self.assertIsInstance(self.w, GlassDialog)
        self.w.show()
        _app.processEvents()
        self.assertTrue(self.w.isVisible())
        self.w.accept()

    def test_todos_los_dialogos_son_glass(self):
        import inspect
        from PyQt6.QtWidgets import QDialog
        from app.dialogs import about_dialog, settings_dialog, shortcuts_dialog
        from app.dialogs.glass_dialog import GlassDialog
        for mod in (about_dialog, settings_dialog, shortcuts_dialog):
            for _, cls in inspect.getmembers(mod, inspect.isclass):
                if issubclass(cls, QDialog) and cls is not QDialog and cls.__module__ == mod.__name__:
                    self.assertTrue(issubclass(cls, GlassDialog), cls)


if __name__ == "__main__":
    unittest.main()


class TestPantallaCompleta(_Base):
    def test_disable_native_fullscreen_fuera_de_mac(self):
        from app import platform_blur
        import platform as _pl
        old = _pl.system
        _pl.system = lambda: "Linux"
        try:
            self.assertFalse(platform_blur.disable_native_fullscreen(None))
        finally:
            _pl.system = old


class TestDialogoDescarga(_Base):
    def _cfg(self, **kw):
        cfg = dict(config.DEFAULTS)
        cfg.update(kw)
        return cfg

    def test_abre_y_arma_job(self):
        from app.dialogs.download_dialog import DownloadDialog
        from app.dialogs.glass_dialog import GlassDialog
        self.w = DownloadDialog(None, cfg=self._cfg(), dest_dir=self._tmp.name,
                                region=(4.0, -64.0, -90.0, -22.0))
        self.assertIsInstance(self.w, GlassDialog)
        self.w.show()
        _app.processEvents()
        self.assertTrue(self.w.isVisible())
        self.assertEqual(self.w.source.key, "gfs")
        self.assertEqual(self.w.cb_run.count(), 12)
        job = self.w.job()
        self.assertIsNone(self.w.source.validate(job))
        self.assertEqual(job.steps, [6, 9, 12])
        self.assertEqual(set(job.variables), {"UGRD", "VGRD", "TMP"})
        self.assertEqual(job.levels[0], 850)
        self.assertEqual(job.params["resolucion"], "0p25")
        self.assertEqual(job.region, (4.0, -64.0, -90.0, -22.0))
        self.assertEqual(job.dest_dir, self._tmp.name)
        self.assertIn("3 plazo(s)", self.w.lbl_steps.text())
        # Plazos que la fuente no ofrece (cada 1 h hasta 120, cada 3 h después)
        self.w.h_from.setValue(121); self.w.h_to.setValue(125); self.w.h_step.setValue(1)
        self.assertIn("no ofrece", self.w.lbl_steps.text())
        self.assertIn("no ofrece", self.w.source.validate(self.w.job()))
        self.w.h_from.setValue(6); self.w.h_to.setValue(12); self.w.h_step.setValue(3)
        # Todo el globo deshabilita la zona
        self.w.chk_global.setChecked(True)
        self.assertFalse(self.w.lat_n.isEnabled())
        self.assertIsNone(self.w.job().region)
        # Sin pedir intermedios, sus casillas están deshabilitadas y vacías
        self.assertFalse(self.w.level_checks[275].isEnabled())
        self.assertNotIn(275, job.levels)
        # Con intermedios (parámetro de la fuente), "Los del visor" suma 275/225/175
        self.w.form.widget("niveles_intermedios").setChecked(True)
        self.assertTrue(self.w.level_checks[275].isEnabled())
        self.w._set_viewer_levels()
        self.assertEqual(self.w.job().params["niveles_intermedios"], True)
        self.assertEqual([lv for lv in self.w.job().levels if lv in (275, 225, 175)], [275, 225, 175])
        # A 1,00° se apagan
        res = self.w.form.widget("resolucion")
        res.setCurrentIndex(res.findData("1p00"))
        self.assertFalse(self.w.level_checks[275].isEnabled())
        self.assertIn("1,00°", self.w.source.validate(self.w.job()))
        # Salvo que se baje siempre 0,25° y se regrille
        self.w.form.widget("solo_0p25").setChecked(True)
        self.assertTrue(self.w.level_checks[275].isEnabled())
        self.w._set_viewer_levels()
        self.assertIsNone(self.w.source.validate(self.w.job()))
        self.assertIn("desde_0p25", self.w.source.default_basename(self.w.job()))
        # Niveles: ninguno → inválido
        self.w._set_levels([])
        self.assertIn("nivel", self.w.source.validate(self.w.job()).lower())
        self.w.reject()

    def test_valores_iniciales_de_preferencias(self):
        from app.dialogs.download_dialog import DownloadDialog
        cfg = self._cfg(download_merge=False, download_open=False, download_h_from=0,
                        download_h_to=24, download_h_step=6,
                        sources={"gfs": {"enabled": True, "params": {"resolucion": "0p50",
                                                                     "niveles_intermedios": True}}})
        self.w = DownloadDialog(None, cfg=cfg, dest_dir=self._tmp.name)
        job = self.w.job()
        self.assertEqual(job.params["resolucion"], "0p50")
        self.assertEqual(job.steps, [0, 6, 12, 18, 24])
        self.assertFalse(job.merge)
        self.assertFalse(self.w.chk_open.isChecked())
        self.assertEqual([lv for lv in job.levels if lv in (275, 225, 175)], [275, 225, 175])
        self.assertIsNone(self.w.source.validate(job))
        self.w.reject()

    def test_descarga_simulada_en_hilo(self):
        """El hilo del diálogo baja con la fuente (fetch simulado), escribe el
        archivo y la procedencia y acepta el diálogo."""
        from app.dialogs.download_dialog import DownloadDialog
        from app.dialogs import download_dialog as dd
        from app.sources import gfs as gfs_src
        from app.sources.cache import DownloadCache
        cfg = self._cfg(download_h_from=6, download_h_to=6)
        self.w = DownloadDialog(None, cfg=cfg, dest_dir=self._tmp.name)
        self.w.show()
        _app.processEvents()
        old_fetch = gfs_src.gfs.fetch
        gfs_src.gfs.fetch = lambda url, headers=None, chunk_cb=None, cancel=None, **k: b"GRIBxxxx"
        old_cache = dd.DownloadDialog._cache
        dd.DownloadDialog._cache = lambda self_: DownloadCache(os.path.join(self._tmp.name, "cache"))
        try:
            self.w._start()
            for _ in range(200):
                _app.processEvents()
                if not self.w._worker.isRunning() and self.w.downloaded_paths:
                    break
                self.w._worker.wait(50)
            _app.processEvents()
        finally:
            gfs_src.gfs.fetch = old_fetch
            dd.DownloadDialog._cache = old_cache
        self.assertEqual(len(self.w.downloaded_paths), 1)
        path = self.w.downloaded_paths[0]
        self.assertTrue(os.path.exists(path) and os.path.exists(path + ".json"))
        self.assertTrue(os.path.basename(path).startswith("gfs_"))

    def test_ventana_abre_el_dialogo_con_el_dominio(self):
        from app.main_window import MainWindow
        from app.dialogs import download_dialog as dd
        from tests.test_grib_reader import _reader_sintetico
        self.w = MainWindow()
        self.w.show()
        _app.processEvents()
        self.assertEqual(self.w.cb_source.currentData(), "gfs")
        self.assertIn("NOAA GFS", self.w.cb_source.currentText())
        r = _reader_sintetico([850, 700])
        r.path = os.path.join(self._tmp.name, "s.grib2")
        self.w.load_reader(r, r.path)
        self.assertIn("archivo local", self.w.panel.lbl_source.text())
        capturado = {}

        class FakeDlg:
            def __init__(self, parent, cfg=None, dest_dir=".", region=None, source_key=None,
                         regions_fn=None):
                capturado["region"] = region
                capturado["dest"] = dest_dir
                capturado["cfg"] = cfg
                capturado["source"] = source_key
                capturado["regions"] = regions_fn() if regions_fn else None
                self.downloaded_paths = []
                self.open_after = False
                self.source = None

            def enable_domain_button(self, region):
                capturado["btn"] = region

            def exec(self):
                return 0
        old = dd.DownloadDialog
        dd.DownloadDialog = FakeDlg
        try:
            self.w.get_data()
        finally:
            dd.DownloadDialog = old
        # El dominio del archivo va al botón «Dominio del archivo abierto»; no
        # fuerza el modo manual (se recuerda el último modo del bloque Área)
        self.assertIsNone(capturado["region"])
        self.assertEqual(capturado["btn"], (10.0, -10.0, -60.0, -30.0))
        self.assertIn("SAEF", capturado["regions"])
        self.assertEqual(capturado["source"], "gfs")
        self.assertIs(capturado["cfg"], self.w._cfg)

    def test_procedencia_en_status(self):
        from app.main_window import MainWindow
        from tests.test_grib_reader import _reader_sintetico
        self.w = MainWindow()
        self.w.show()
        _app.processEvents()
        r = _reader_sintetico([850, 700])
        r.path = os.path.join(self._tmp.name, "s.grib2")
        prov = {"fuente": "gfs", "nombre": "NOAA GFS", "modelo": "GFS (NCEP)",
                "corrida": "2026-10-14T06:00Z", "resolucion_final": "1p00",
                "resolucion_descargada": "0p25", "regrillado": "promedio"}
        self.w.load_reader(r, r.path, prov)
        txt = self.w.panel.lbl_source.text()
        self.assertIn("NOAA GFS", txt)
        self.assertIn("corrida 14/10 06Z", txt)
        self.assertIn("+6 h", txt)
        self.assertIn("(GFS)", txt)
        self.assertIn("1,00°", txt)
        self.assertIn("desde 0,25° (promedio)", txt)




class TestVentanaWAFS(_Base):
    """La ventana convierte a WAFS lo que abre y ofrece «Exportar a WAFS…»."""

    DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

    def test_abre_archivo_local_convertido(self):
        """Un archivo local en niveles de presión crudos se convierte al
        abrirlo (modo por defecto OACI, 17 FL; con OACI56 en la configuración,
        los 56); uno ya etiquetado por FL (como FDP_MULTI, 14 niveles
        nominales de INDRA) se abre tal cual."""
        import shutil
        from app.main_window import MainWindow
        from app import wafs_format as wf
        from tests.test_wafs import _grib
        src = os.path.join(self.DATA, "FDP_MULTI.grib2")
        if not os.path.isfile(src) or wf.ec is None:
            self.skipTest("sin datos de prueba o eccodes")
        local = os.path.join(self._tmp.name, "crudo.grib2")
        with open(local, "wb") as fh:
            fh.write(_grib([1000, 850, 700, 500, 400, 300, 250, 200, 150, 100], steps=(6, 9)))
        self.w = MainWindow()
        self.w.show()
        _app.processEvents()
        self.assertEqual(self.w._act_export_wafs.shortcut().toString(), "Ctrl+Shift+W")
        self.assertFalse(self.w._act_export_wafs.isEnabled())
        self.w.open_file(local)
        _app.processEvents()
        self.assertTrue(self.w._path.endswith("crudo_wafs.grib2"))
        self.assertTrue(os.path.exists(self.w._path + ".json"))
        self.assertTrue(os.path.exists(self.w._path + ".idx"))
        self.assertTrue(self.w._reader.is_wafs)
        self.assertEqual(self.w._reader.fl_mode, "OACI")
        self.assertEqual(len(self.w._reader.levels), 17)
        self.assertEqual(self.w._reader.fl_levels[210], 450)
        self.assertIn("WAFS FL050–FL530 · modo OACI (convertido)", self.w.panel.lbl_source.text())
        self.assertIn("corrida 14/10 06Z", self.w.panel.lbl_source.text())
        self.assertIn("(nivel exacto, modo OACI, etiqueta 300 hPa)", self.w.panel.lbl_level.text())
        self.assertEqual(self.w._current["info"]["mode"], "wafs")
        self.assertTrue(self.w._act_export_wafs.isEnabled())
        self.assertTrue(all(b.isEnabled() for b in self.w.panel._fl_buttons.values()))
        self.assertFalse(self.w.panel.cb_press.isEnabled())       # los 17 tienen botón
        # Con OACI56 en la configuración, la lista lleva los FL sin botón,
        # con etiqueta y presión exacta
        self.w._cfg["wafs_mode"] = "OACI56"
        local56 = os.path.join(self._tmp.name, "crudo56.grib2")
        shutil.copy(local, local56)
        self.w.open_file(local56)
        _app.processEvents()
        self.assertTrue(self.w._path.endswith("crudo56_wafs.grib2"))
        self.assertEqual(self.w._reader.fl_mode, "OACI56")
        self.assertEqual(len(self.w._reader.levels), 49)
        self.assertIn("WAFS FL050–FL530 · modo OACI56 (convertido)", self.w.panel.lbl_source.text())
        self.assertTrue(self.w.panel.cb_press.isEnabled())
        self.assertEqual(self.w.panel.cb_press.itemText(0), self.w.panel.P_COMBO_NONE)
        self.assertEqual(self.w.panel.lbl_press.text(), self.w.panel.P_LABEL_WAFS)
        self.assertEqual(self.w.panel.cb_press.itemText(1), "FL060 · 800 hPa (812 ISA)")
        self.w.panel.cb_press.setCurrentIndex(1)
        self.assertIn("F060 · etiqueta 800 hPa · 812.0 hPa ISA (nivel exacto, modo OACI56)",
                      self.w.panel.lbl_fl_p.text())
        self.assertIn("LEVEL: F060 = 81200 Pa ISA (nivel exacto, modo OACI56, etiqueta 800 hPa)",
                      self.w.panel.lbl_level.text())
        # Un archivo ya etiquetado se abre tal cual (no se vuelve a convertir)
        self.w.open_file(self.w._path)
        self.assertTrue(self.w._path.endswith("crudo56_wafs.grib2"))
        self.assertFalse(os.path.exists(os.path.join(self._tmp.name, "crudo56_wafs_wafs.grib2")))
        fdp = os.path.join(self._tmp.name, "FDP_MULTI.grib2")
        shutil.copy(src, fdp)
        self.w.open_file(fdp)
        self.assertEqual(self.w._path, fdp)
        self.assertEqual(self.w._reader.fl_mode, "INDRA")
        self.assertFalse(os.path.exists(os.path.join(self._tmp.name, "FDP_MULTI_wafs.grib2")))
        self.assertEqual([fl for fl, b in self.w.panel._fl_buttons.items() if not b.isEnabled()],
                         [80, 210, 480])
        # Sin conversión de archivos locales se abre el crudo e interpola
        self.w._cfg["wafs_convert_local"] = False
        self.w.open_file(local)
        self.assertEqual(self.w._path, local)
        self.assertEqual(self.w._current["info"]["mode"], "interp")
        # el FL activo había pasado a F050 al abrir el INDRA (F060 no estaba)
        self.assertIn("F050 = 843.1 hPa (ISA)", self.w.panel.lbl_level.text())
        self.assertIn("interpolado en ln(p) entre 850 y 700 hPa", self.w.panel.lbl_level.text())

    def test_dialogo_exportar_desde_la_ventana(self):
        import shutil
        from app.main_window import MainWindow
        from app.dialogs.export_wafs_dialog import ExportWafsDialog
        from app import wafs_format as wf
        src = os.path.join(self.DATA, "WAFS_like_test.grib2")
        if not os.path.isfile(src) or wf.ec is None:
            self.skipTest("sin datos de prueba o eccodes")
        local = os.path.join(self._tmp.name, "w.grib2")
        shutil.copy(src, local)
        self.w = MainWindow()
        self.w.show()
        self.w.open_file(local)
        _app.processEvents()
        out = os.path.join(self._tmp.name, "salida")
        dlg = ExportWafsDialog(self.w, reader=self.w._reader, cfg=self.w._cfg, dest_dir=out,
                               provenance=self.w._provenance)
        dlg.rb_sel_steps.setChecked(True)
        for c in dlg.step_checks[1:]:
            c.setChecked(False)
        dlg.rb_range_fl.setChecked(True)
        dlg.fl_min.setValue(300)
        dlg.fl_max.setValue(340)
        self.assertEqual(dlg.cb_mode.currentData(), "OACI")      # el de la configuración
        dlg.cb_mode.setCurrentIndex(dlg.cb_mode.findData("OACI56"))   # con OACI quedarían 300/320/340
        opts = dlg.options()
        self.assertEqual(opts["steps"], [6.0])
        self.assertEqual(opts["fls"], [300, 310, 320, 330, 340])
        self.assertEqual(opts["model"], "gfs")
        self.assertEqual(opts["mode"], "OACI56")
        dlg._start()
        for _ in range(400):
            _app.processEvents()
            if dlg._worker is not None and not dlg._worker.isRunning() and dlg.result:
                break
            dlg._worker.wait(50)
        _app.processEvents()
        self.assertIsNotNone(dlg.result)
        self.assertEqual([os.path.basename(p) for p in dlg.result["archivos"]],
                         ["gfs.t18z.wafs_1p00.f006.grib2"])
        self.assertTrue(dlg.result["verificacion"][0]["ok"])
        self.assertEqual(dlg.result["verificacion"][0]["mensajes"], 15)
        self.assertIn("Verificación OK", ExportWafsDialog.summary(dlg.result))
        dlg.close()
        dlg.deleteLater()

    def test_preferencias_wafs(self):
        from app.dialogs.settings_dialog import SettingsDialog
        self.w = SettingsDialog(None, cfg={"wafs_fl_max": 600, "wafs_extrapolate": True})
        self.w.show()
        _app.processEvents()
        self.assertIn("WAFS", [self.w.tabs.tabText(i) for i in range(self.w.tabs.count())])
        v = self.w.values()
        self.assertTrue(v["wafs_convert"])
        self.assertEqual(v["wafs_fl_max"], 600)
        self.assertTrue(v["wafs_extrapolate"])
