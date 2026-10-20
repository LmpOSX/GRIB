# -*- coding: utf-8 -*-
"""Tests offscreen de la ventana con mapa (Fase 3): cambiar nivel, paso,
variable u opciones redibuja sobre un GribReader sintético; exportaciones;
hover; recuadro; capa de datos; Escape."""
import csv
import os
import tempfile
import unittest

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from app import config  # noqa: E402
from app.dialogs import glass_dialog  # noqa: E402
from tests.test_grib_reader import _reader_sintetico  # noqa: E402

glass_dialog._apply_dialog_blur = lambda w: None

_app = QApplication.instance() or QApplication([])


class _MapBase(unittest.TestCase):
    def setUp(self):
        from app.main_window import MainWindow
        self._tmp = tempfile.TemporaryDirectory()
        self._old_cfg_path = config.CONFIG_PATH
        config.CONFIG_PATH = os.path.join(self._tmp.name, "config.json")
        self.w = MainWindow()
        self.w.show()
        _app.processEvents()
        # Contador de redibujos
        self.draws = []
        orig = self.w.plot.draw

        def counted(*a, **k):
            self.draws.append(k.get("opts") or (a[5] if len(a) > 5 else None))
            return orig(*a, **k)
        self.w.plot.draw = counted
        self.reader = _reader_sintetico([850, 700, 500, 300, 200], shape=(5, 6))
        self.reader.path = os.path.join(self._tmp.name, "sintetico.grib2")
        self.w.load_reader(self.reader, self.reader.path)
        _app.processEvents()

    def tearDown(self):
        self.w.close()
        self.w.deleteLater()
        _app.processEvents()
        config.CONFIG_PATH = self._old_cfg_path
        self._tmp.cleanup()


class TestCargaYRedibujo(_MapBase):
    def test_carga_muestra_mapa(self):
        self.assertEqual(len(self.draws), 1)
        self.assertTrue(self.w._main_area.isVisible())
        self.assertFalse(self.w._welcome.isVisible())
        self.assertIn("sintetico.grib2", self.w.windowTitle())
        self.assertIn("NIVELES (hPa): 850, 700, 500, 300, 200",
                      self.w.inventory.toPlainText())
        self.assertTrue(self.w._act_export_csv.isEnabled())
        self.assertIn("RUN:   12:00 13/10 UTC", self.w.panel.lbl_run.text())
        self.assertIn("F300 = 300.9 hPa", self.w.panel.lbl_level.text())
        self.assertIn("interpolado en ln(p) entre 500 y 300", self.w.panel.lbl_level.text())
        self.assertIn("VALIDITY [18:00–21:00] UTC", self.w.panel.lbl_valid_utc.text())

    def test_boton_de_nivel_redibuja(self):
        self.w.panel._fl_buttons[100].click()
        self.assertEqual(len(self.draws), 2)
        self.assertEqual(self.w.panel.sel_fl, 100)
        self.assertEqual(self.w.panel.level_mode, "fl")
        self.assertIn("F100 = 696.8 hPa", self.w.panel.lbl_level.text())
        self.assertIn("F100 (697 hPa) interp. 700/500 hPa", self.draws[-1]["title"])

    def test_fuera_de_rango_sin_extrapolar(self):
        # F530 = 100.4 hPa queda por encima del nivel más alto (200 hPa): el
        # botón se deshabilita en vez de extrapolar; también F390 (196.8),
        # F410, F450 y F480
        btns = self.w.panel._fl_buttons
        self.assertEqual([fl for fl, b in btns.items() if not b.isEnabled()], [390, 410, 450, 480, 530])
        self.assertEqual(self.w.panel.available_fls()[-1], 380)       # 206.5 hPa, el último dentro de 200
        # F050 = 843 hPa está dentro de 850–200: se interpola
        btns[50].click()
        self.assertIn("interpolado en ln(p) entre 850 y 700 hPa",
                      self.w.panel.lbl_level.text())
        # Con un archivo cuyo nivel más bajo es 700 hPa, F050 y F080 quedan grises
        # y el FL activo pasa al primero disponible con botón
        r = _reader_sintetico([700, 500, 300])
        r.path = self.reader.path
        self.w.load_reader(r, r.path)
        self.assertFalse(btns[50].isEnabled())
        self.assertFalse(btns[80].isEnabled())
        self.assertEqual(self.w.panel.sel_fl, 100)
        self.assertIn("F100 = 696.8 hPa (ISA)", self.w.panel.lbl_level.text())
        # La interpolación directa sigue extrapolando si se la llama (no desde la interfaz)
        self.assertTrue(r.fields_for_fl(0, 50)[3]["extrapolated"])

    def test_combo_de_presion_sin_interpolar(self):
        # La lista lleva primero los FL sin botón (interpolados) y, tras un
        # separador, los niveles del archivo sin interpolar
        items = self.w.panel._combo_items
        idx_700 = 1 + items.index(("p", 700.0))
        self.assertEqual(items[0], ("fl", 60))
        self.w.panel.cb_press.setCurrentIndex(idx_700)      # 700 hPa
        self.assertEqual(len(self.draws), 2)
        self.assertEqual(self.w.panel.level_mode, "p")
        self.assertEqual(self.w.panel.sel_p, 700.0)
        self.assertIn("LEVEL: 700 hPa (nivel del archivo", self.w.panel.lbl_level.text())
        self.assertFalse(any(b.isChecked() for b in self.w.panel._fl_buttons.values()))
        # Un FL de la lista: modo fl sin botón tildado
        self.w.panel.cb_press.setCurrentIndex(1)
        self.assertEqual((self.w.panel.level_mode, self.w.panel.sel_fl), ("fl", 60))
        self.assertFalse(any(b.isChecked() for b in self.w.panel._fl_buttons.values()))
        self.assertIn("F060 = 812.0 hPa (ISA)", self.w.panel.lbl_level.text())
        # Volver a FL con botón: el combo vuelve a la primera entrada
        self.w.panel._fl_buttons[300].click()
        self.assertEqual(self.w.panel.level_mode, "fl")
        self.assertEqual(self.w.panel.cb_press.currentIndex(), 0)
        self.assertEqual(self.w.panel.cb_press.itemText(0), self.w.panel.P_COMBO_NONE)
        self.assertEqual(self.w.panel.lbl_press.text(), self.w.panel.P_LABEL)
        self.assertEqual(len(self.draws), 4)

    def test_paso_redibuja(self):
        import datetime as dt
        from app.grib_reader import GribStep
        run = self.reader.steps[0].run
        self.reader.steps = [GribStep(str(h), run, run + dt.timedelta(hours=h))
                             for h in (6, 9, 12)]
        self.reader._compute_windows()
        for h in (9, 12):
            idx = (h - 6) // 3
            for var in ("u", "v", "t"):
                for lv in self.reader.levels:
                    self.reader.index[(idx, var, lv)] = object()
                    self.reader.cache[(idx, var, lv)] = self.reader.cache[(0, var, lv)]
        self.w.load_reader(self.reader, self.reader.path)
        n = len(self.draws)
        self.assertFalse(self.w.panel._steps_row.isVisible())   # 3 pasos: sin combo
        self.w.panel.rb_time[1].click()
        self.assertEqual(len(self.draws), n + 1)
        self.assertEqual(self.w.panel.step_index(), 1)
        self.assertIn("STEP:  [1] +9 h", self.w.panel.lbl_step.text())
        self.assertIn("VALIDITY [21:00–00:00] UTC", self.w.panel.lbl_valid_utc.text())

    def test_mas_de_tres_pasos_muestra_combo(self):
        import datetime as dt
        from app.grib_reader import GribStep
        run = self.reader.steps[0].run
        self.reader.steps = [GribStep(str(h), run, run + dt.timedelta(hours=h))
                             for h in (3, 6, 9, 12)]
        self.reader._compute_windows()
        for idx in range(1, 4):
            for var in ("u", "v", "t"):
                for lv in self.reader.levels:
                    self.reader.index[(idx, var, lv)] = object()
                    self.reader.cache[(idx, var, lv)] = self.reader.cache[(0, var, lv)]
        self.w.load_reader(self.reader, self.reader.path)
        _app.processEvents()
        self.assertTrue(self.w.panel._steps_row.isVisibleTo(self.w.panel))
        n = len(self.draws)
        self.w.panel.cb_steps.setCurrentIndex(3)
        self.assertEqual(len(self.draws), n + 1)
        self.assertEqual(self.w.panel.step_index(), 3)
        self.assertFalse(any(rb.isChecked() for rb in self.w.panel.rb_time))

    def test_variable_y_opciones_redibujan(self):
        n = len(self.draws)
        self.w.panel.rb_var[1].click()                      # Temperatura
        self.assertEqual(len(self.draws), n + 1)
        self.assertEqual(self.draws[-1]["mode"], "temperatura")
        self.w.panel.chk_extra.click()
        self.assertEqual(len(self.draws), n + 2)
        self.assertTrue(self.draws[-1]["extra_info"])
        self.w.panel.chk_grid.click()
        self.w.panel.chk_fill.click()
        self.assertEqual(len(self.draws), n + 4)
        self.w.panel.spin_stride.setValue(2)
        self.assertEqual(len(self.draws), n + 5)
        self.assertEqual(self.draws[-1]["stride"], 2)
        self.w.panel.btn_update.click()
        self.assertEqual(len(self.draws), n + 6)

    def test_estilos_de_viento(self):
        """Barbas / Flechas / Curvas redibujan, generan el artista esperado y
        quedan guardadas en la configuración."""
        from matplotlib.quiver import Barbs, Quiver
        from matplotlib.collections import LineCollection
        esperado = {"flechas": Quiver, "curvas": LineCollection, "barbas": Barbs}   # barbas ya está elegido
        for key, cls in esperado.items():
            n = len(self.draws)
            self.w.panel.cb_style.setCurrentIndex(self.w.panel.cb_style.findData(key))
            _app.processEvents()
            self.assertEqual(len(self.draws), n + 1)
            self.assertEqual(self.draws[-1]["wind_style"], key)
            self.w.plot.canvas.draw()
            tipos = [type(a) for a in self.w.plot._view_artists]
            self.assertIn(cls, tipos, (key, tipos))
            self.assertEqual(config.load_config()["map_wind_style"], key)
        # Con sólo temperatura no hay capa de viento en ningún estilo
        self.w.panel.rb_var[1].click()
        self.w.plot.canvas.draw()
        self.assertEqual(self.w.plot._view_artists, [])

    def test_cambiar_de_estilo_no_deja_huerfanos(self):
        """Las curvas son dos colecciones (líneas y chevrones de sentido), sin
        parches sueltos; al cambiar de estilo o redibujar no queda nada."""
        from matplotlib.patches import FancyArrowPatch
        from matplotlib.collections import LineCollection
        ax = self.w.plot.ax
        for key in ("curvas", "flechas", "curvas", "barbas"):
            self.w.panel.cb_style.setCurrentIndex(self.w.panel.cb_style.findData(key))
            self.w.plot.canvas.draw()
        self.assertEqual([a for a in ax.patches if isinstance(a, FancyArrowPatch)], [])
        self.assertEqual([a for a in ax.collections if isinstance(a, LineCollection)], [])
        self.w.panel.cb_style.setCurrentIndex(self.w.panel.cb_style.findData("curvas"))
        self.w.plot.canvas.draw()
        n1 = len(ax.collections)
        self.assertEqual(len(self.w.plot._view_artists), 2)          # líneas + chevrones
        self.assertTrue(all(isinstance(a, LineCollection) for a in self.w.plot._view_artists))
        self.assertGreater(len(self.w.plot._view_artists[1].get_segments()), 2)   # varias flechas
        self.w.panel.btn_update.click()
        self.w.plot.canvas.draw()
        self.assertEqual(len(ax.collections), n1)          # redibujar no acumula

    def test_flechas_solo_direccion(self):
        """Las flechas tienen largo fijo (vectores unitarios) y no se dibujan
        en calma."""
        from matplotlib.quiver import Quiver
        for lv in self.reader.levels:                       # calma en un punto
            self.reader.cache[(0, "u", float(lv))][0, 0] = 0.0
            self.reader.cache[(0, "v", float(lv))][0, 0] = 0.0
        self.w.redraw()
        self.w.panel.cb_style.setCurrentIndex(self.w.panel.cb_style.findData("flechas"))
        self.w.plot.canvas.draw()
        q = [a for a in self.w.plot._view_artists if isinstance(a, Quiver)][0]
        # Quiver guarda U/V rellenos con 1 donde están enmascarados y la
        # máscara aparte (Umask): el punto en calma debe estar enmascarado.
        mask = np.asarray(q.Umask, dtype=bool)
        mag = np.hypot(np.asarray(q.U), np.asarray(q.V))
        self.assertTrue(np.allclose(mag[~mask], 1.0, atol=1e-6))
        self.assertTrue(mask.any())                  # el punto en calma quedó sin flecha

    def test_rotulos_con_unidades_y_tamano(self):
        """Extra Info muestra unidades si está configurado y usa el tamaño de
        la configuración."""
        self.w.panel.rb_var[2].click()                     # viento + temperatura
        self.w.panel.chk_extra.setChecked(True)
        self.w.plot.canvas.draw()
        txts = list(self.w.plot.label_texts)
        self.assertTrue(txts and all("kt" in t and "°C" in t for t in txts), txts[:3])
        self.assertAlmostEqual(self.w.plot.label_fontsize, 7.0)
        self.assertEqual(len(self.w.plot._label_artists), 1)       # una sola colección
        vals = dict(self.w._cfg); vals.update({"map_label_units": False, "map_label_size": 11})
        self.w.apply_settings(vals)
        self.w.plot.canvas.draw()
        txts = list(self.w.plot.label_texts)
        self.assertTrue(txts and all("kt" not in t and t.endswith("°") for t in txts), txts[:3])
        self.assertAlmostEqual(self.w.plot.label_fontsize, 11.0)

    def test_alejar_achica_los_glifos_antes_de_ralear(self):
        """Al alejar la vista las flechas se acortan hasta la mitad y recién
        después se ralean; al acercar vuelven al tamaño nominal."""
        from matplotlib.quiver import Quiver
        from app import wind_plot
        plot = self.w.plot
        self.w.panel.cb_style.setCurrentIndex(self.w.panel.cb_style.findData("flechas"))
        plot.canvas.draw()
        nominal = 1.0 / (wind_plot.ARROW_LEN_IN * max(0.8, plot.font_scale))
        q = [a for a in plot._view_artists if isinstance(a, Quiver)][0]
        self.assertAlmostEqual(q.scale, nominal)           # acercado: tamaño nominal
        n_in = q.N
        ax = plot.ax
        x0, x1 = ax.get_xlim(); y0, y1 = ax.get_ylim()
        ax.set_xlim(x0 - (x1 - x0) * 40, x1 + (x1 - x0) * 40)
        ax.set_ylim(y0 - (y1 - y0) * 40, y1 + (y1 - y0) * 40)
        plot._on_view_settled()
        plot.canvas.draw()
        q = [a for a in plot._view_artists if isinstance(a, Quiver)][0]
        self.assertGreater(q.scale, nominal)               # flechas más cortas…
        self.assertLessEqual(q.scale, nominal / wind_plot.GLYPH_MIN_FACTOR + 1e-9)   # …hasta el mínimo
        self.assertLessEqual(q.N, n_in)                    # y raleadas si hizo falta
        f, stride = plot._fit_glyph(24.0, 4.0, 1)
        self.assertAlmostEqual(f, wind_plot.GLYPH_MIN_FACTOR)
        self.assertGreater(stride, 1)
        self.assertEqual(plot._fit_glyph(24.0, 40.0, 1), (1.0, 1))

    def test_integrador_vectorizado(self):
        """Las líneas de corriente salen del integrador propio (numpy): en un
        campo de rotación cierran una vuelta y no se superponen; con menos
        densidad hay menos líneas."""
        from app.wind_plot import integrate_streamlines
        xs = np.linspace(-10, 10, 80); ys = np.linspace(-8, 8, 60)
        X, Y = np.meshgrid(xs, ys)
        t2 = integrate_streamlines(xs, ys, -Y, X, density=2.0)
        t1 = integrate_streamlines(xs, ys, -Y, X, density=1.0)
        self.assertGreater(len(t2), len(t1) * 2)
        for pts in t2:
            self.assertTrue(np.isfinite(pts).all())
            self.assertTrue((pts[:, 0] >= xs[0] - 1e-9).all() and (pts[:, 0] <= xs[-1] + 1e-9).all())
        # campo nulo: ninguna trayectoria
        self.assertEqual(integrate_streamlines(xs, ys, 0 * X, 0 * Y), [])

    def test_curvas_con_densidad_y_sin_cartopy(self):
        from app import wind_plot
        self.w.panel.cb_style.setCurrentIndex(self.w.panel.cb_style.findData("curvas"))
        self.w.panel.spin_stride.setValue(4)
        self.w.plot.canvas.draw()
        self.assertTrue(self.w.plot._view_artists)
        # Muestreo bilineal usado para regrillar a la proyección
        x = np.array([0.0, 1.0, 2.0]); y = np.array([10.0, 11.0])
        f = np.array([[0.0, 1.0, 2.0], [10.0, 11.0, 12.0]])
        out = wind_plot._sample_bilinear(x, y, f, np.array([0.5, 1.5, 2.5, np.nan]),
                                         np.array([10.5, 10.0, 10.5, 10.5]))
        self.assertAlmostEqual(out[0], 5.5); self.assertAlmostEqual(out[1], 1.5)
        self.assertTrue(np.isnan(out[2])); self.assertTrue(np.isnan(out[3]))

    def test_capa_de_datos(self):
        n = len(self.draws)
        self.w.panel.btn_disable.click()
        self.assertEqual(len(self.draws), n + 1)
        self.assertFalse(self.draws[-1]["show_wind"])
        self.assertEqual(self.w.panel.btn_disable.text(), "Mostrar capa")
        self.assertFalse(self.w._act_layer.isChecked())
        self.assertIn("DESHABILITADA", self.w.panel.lbl_level.text())
        self.w.toggle_layer()
        self.assertTrue(self.draws[-1]["show_wind"])
        self.assertEqual(self.w.panel.btn_disable.text(), "Ocultar capa")

    def test_panel_entra_en_el_ancho(self):
        """Nada del panel impone un ancho mayor que el área con scroll, ni
        con fuente grande; STATUS va en la franja pegada al mapa."""
        side = self.w._side
        for size in (13, 18):
            vals = dict(self.w._cfg); vals["font_size"] = size
            self.w.apply_settings(vals)
            _app.processEvents()
            self.assertLessEqual(side.minimumSizeHint().width(), side.width(), size)
            self.assertLessEqual(self.w.panel.minimumSizeHint().width(), side.width(), size)
        self.assertEqual(list(self.w.panel._sections), ["TIME", "LEVEL", "VARIABLE", "VIENTO", "MAPA"])
        self.assertIsNot(self.w.panel.status.parentWidget(), self.w.panel)
        self.assertTrue(self.w.panel.status.isVisible())

    def test_panel_entra_en_el_alto_y_se_oculta(self):
        """Con la ventana por defecto el panel no necesita scroll vertical
        (el inventario absorbe el alto que sobra); el botón ▥ y Vista ▸
        Panel lateral lo ocultan y el mapa se ensancha; persiste."""
        w = self.w
        w.resize(1600, 1000)
        _app.processEvents()
        side = w._side
        self.assertLessEqual(side.minimumSizeHint().height(), side.height())
        self.assertLessEqual(side.minimumSizeHint().height(), 800)   # entra en una pantalla de 13"
        from PyQt6.QtWidgets import QScrollArea
        self.assertEqual(w.findChildren(QScrollArea), [])            # sólo el inventario se desplaza
        self.assertEqual(len(w.panel._fl_buttons), 17)
        map_w = w.plot.canvas.width()
        w._btn_panel.click()
        _app.processEvents()
        self.assertFalse(w._side.isVisible())
        self.assertFalse(w._act_panel.isChecked())
        self.assertGreater(w.plot.canvas.width(), map_w)
        self.assertFalse(config.load_config()["panel_visible"])
        w._act_panel.trigger()
        _app.processEvents()
        self.assertTrue(w._side.isVisible())
        self.assertTrue(w._btn_panel.isChecked())
        self.assertTrue(config.load_config()["panel_visible"])

    def test_grilla_de_grados(self):
        """10° sólo principales; 5° agrega secundarias a rayas; 1° principales
        cada 5° y secundarias punteadas. Se guarda y el menú Vista la refleja."""
        from app import wind_plot
        w = self.w
        self.assertEqual(wind_plot.WindPlot.grid_spacing(10), (10, None))
        self.assertEqual(wind_plot.WindPlot.grid_spacing(5), (10, 5))
        self.assertEqual(wind_plot.WindPlot.grid_spacing(1), (5, 1))
        for step, n in ((5, 2), (1, 2), (10, 1)):
            w.panel.cb_grid_step.setCurrentIndex(w.panel.cb_grid_step.findData(step))
            _app.processEvents()
            self.assertEqual(self.draws[-1]["grid_step"], step)
            self.assertEqual(config.load_config()["map_grid_step"], step)
            self.assertTrue(w._grid_actions[step].isChecked())
            if w.plot.use_cartopy:
                w.plot.canvas.draw()
                self.assertEqual(len(w.plot._gridliners), n, step)
                # Rótulos cada 10° con 10°, cada 5° con 5° y con 1° (nunca cada 1°)
                labeled = [gl for gl in w.plot._gridliners if gl.bottom_labels or gl.left_labels]
                self.assertEqual(len(labeled), 1, step)
                self.assertEqual(labeled[0].ylocator.tick_values(0, 10)[1] - labeled[0].ylocator.tick_values(0, 10)[0],
                                 wind_plot.WindPlot.label_spacing(step), step)
        self.assertEqual([wind_plot.WindPlot.label_spacing(s) for s in (10, 5, 1)], [10, 5, 5])
        w._grid_actions[1].trigger()
        self.assertEqual(w.panel.options()["grid_step"], 1)
        # Margen de inscripciones: los ejes no llegan al borde izquierdo ni al inferior
        pos = w.plot.ax.get_position()
        self.assertGreater(pos.x0 * w.plot.fig.get_figwidth() * w.plot.fig.dpi, 50)
        self.assertGreater(pos.y0 * w.plot.fig.get_figheight() * w.plot.fig.dpi, 28)
        # En Retina el lienzo corre al doble de dpi y el texto ocupa el doble de
        # píxeles: el margen (en px) se duplica para que «30°S» no quede en «0°S»
        left_px = pos.x0 * w.plot.fig.get_figwidth() * w.plot.fig.dpi
        old_dpi = w.plot.fig.dpi
        try:
            w.plot.fig.set_dpi(old_dpi * 2)
            w.plot._apply_margins()
            pos2 = w.plot.ax.get_position()
            self.assertAlmostEqual(pos2.x0 * w.plot.fig.get_figwidth() * w.plot.fig.dpi, 2 * left_px, delta=1.0)
        finally:
            w.plot.fig.set_dpi(old_dpi)
            w.plot._apply_margins()

    def test_menu_vista_sincronizado(self):
        """Vista ▸ Extra Info / Viento / Proyección reflejan y cambian el panel."""
        w = self.w
        self.assertFalse(w._act_extra.isChecked())
        w._act_extra.trigger()
        self.assertTrue(w.panel.chk_extra.isChecked())
        self.assertTrue(self.draws[-1]["extra_info"])
        w.panel.chk_extra.setChecked(False)
        self.assertFalse(w._act_extra.isChecked())
        w._style_actions["curvas"].trigger()
        self.assertEqual(w.panel.options()["wind_style"], "curvas")
        self.assertEqual(self.draws[-1]["wind_style"], "curvas")
        w.panel.cb_style.setCurrentIndex(w.panel.cb_style.findData("flechas"))
        self.assertTrue(w._style_actions["flechas"].isChecked())
        if w.plot.use_cartopy:
            w._proj_actions["mercator"].trigger()
            self.assertEqual(w.panel.projection(), "mercator")
            self.assertEqual(w.plot.proj_key, "mercator")
            self.assertEqual(config.load_config()["projection"], "mercator")
            w.panel.cb_proj.setCurrentIndex(w.panel.cb_proj.findData("platecarree"))
            self.assertTrue(w._proj_actions["platecarree"].isChecked())

    def test_tema_redibuja_con_paleta(self):
        n = len(self.draws)
        self.w._apply_theme("#5B8C5A")
        self.assertEqual(len(self.draws), n + 1)
        from app.theme import generate_palette
        self.assertEqual(self.w.plot.pal["bg"], generate_palette("#5B8C5A")["bg_data"].name())


class TestRecuadroYCursor(_MapBase):
    def test_recuadro_y_todo_el_dominio(self):
        self.w.apply_extent(-55.0, -40.0, -8.0, 2.0)
        self.w.plot.canvas.draw()            # emite draw_event → entradas del recuadro
        _app.processEvents()
        # La vista se amplía para llenar el área: el recuadro pedido queda contenido
        self.assertLessEqual(float(self.w.panel.ent_lonmin.text()), -55.0)
        self.assertGreaterEqual(float(self.w.panel.ent_lonmax.text()), -40.0)
        self.assertLessEqual(float(self.w.panel.ent_latmin.text()), -8.0)
        self.assertGreaterEqual(float(self.w.panel.ent_latmax.text()), 2.0)
        self.assertLess(float(self.w.panel.ent_lonmax.text()), -20.0)   # pero no es el dominio entero
        self.w.full_extent()
        self.w.plot.canvas.draw()
        _app.processEvents()
        self.assertLessEqual(float(self.w.panel.ent_lonmin.text()), -60.0)
        self.assertLessEqual(float(self.w.panel.ent_latmin.text()), -10.0)
        self.assertGreaterEqual(float(self.w.panel.ent_latmax.text()), 10.0)

    def test_recuadro_desde_el_panel(self):
        p = self.w.panel
        p.ent_latmin.setText("-9"); p.ent_latmax.setText("1")
        p.ent_lonmin.setText("-58"); p.ent_lonmax.setText("-35")
        p._apply_extent()
        ext = self.w.plot.get_extent()
        self.assertLessEqual(ext[0], -58.0 + 1e-6)
        self.assertGreaterEqual(ext[1], -35.0 - 1e-6)
        self.assertLessEqual(ext[2], -9.0 + 1e-6)
        self.assertGreaterEqual(ext[3], 1.0 - 1e-6)
        # y con la proporción del área del mapa
        x0, x1 = self.w.plot.ax.get_xlim(); y0, y1 = self.w.plot.ax.get_ylim()
        bb = self.w.plot.ax.bbox
        self.assertAlmostEqual((x1 - x0) / (y1 - y0), bb.width / bb.height, places=3)

    def test_recuadro_invalido_avisa(self):
        avisos = []
        old = QMessageBox.warning
        QMessageBox.warning = staticmethod(lambda *a, **k: avisos.append(a[2]))
        try:
            p = self.w.panel
            p.ent_latmin.setText("5"); p.ent_latmax.setText("1")
            p._apply_extent()
        finally:
            QMessageBox.warning = old
        self.assertEqual(len(avisos), 1)

    def test_texto_del_cursor(self):
        lats, lons = self.reader.lats, self.reader.lons
        txt = self.w.cursor_text(float(lons[2]), float(lats[1]))
        self.assertIn(f"punto ({lats[1]:.2f}, {lons[2]:.2f})", txt)
        self.assertIn("Viento", txt)
        self.assertIn("°C", txt)
        txt_fuera = self.w.cursor_text(100.0, 80.0)
        self.assertNotIn("punto", txt_fuera)

    def test_pan_por_arrastre(self):
        class E:
            pass
        plot = self.w.plot
        x0, x1 = plot.ax.get_xlim()
        # Botón izquierdo dentro del mapa: arrastre horizontal
        e = E(); e.button = 1; e.inaxes = plot.ax; e.dblclick = False
        e.x, e.y = 300, 300; e.xdata, e.ydata = -50.0, -2.0
        plot._on_press(e)
        self.assertTrue(plot._panning)
        e2 = E(); e2.button = 1; e2.inaxes = plot.ax; e2.x, e2.y = 360, 300
        plot._on_motion(e2)
        plot._on_release(e2)
        self.assertFalse(plot._panning)
        nx0, nx1 = plot.ax.get_xlim()
        self.assertLess(nx0, x0)                    # la vista se corrió hacia el oeste
        self.assertAlmostEqual(nx1 - nx0, x1 - x0, places=6)   # sin cambiar el zoom
        # Botón derecho o fuera del mapa: no arrastra
        e3 = E(); e3.button = 3; e3.inaxes = plot.ax; e3.dblclick = False
        plot._on_press(e3)
        self.assertFalse(plot._panning)

    def test_vista_llena_el_canvas(self):
        plot = self.w.plot
        x0, x1 = plot.ax.get_xlim()
        y0, y1 = plot.ax.get_ylim()
        bw, bh = plot.ax.bbox.width, plot.ax.bbox.height
        self.assertAlmostEqual((x1 - x0) / (y1 - y0), bw / bh, places=3)
        # El dominio completo sigue visible
        ext = plot.get_extent()
        self.assertLessEqual(ext[0], float(self.reader.lons.min()) + 1e-6)
        self.assertGreaterEqual(ext[1], float(self.reader.lons.max()) - 1e-6)
        self.assertLessEqual(ext[2], float(self.reader.lats.min()) + 1e-6)
        self.assertGreaterEqual(ext[3], float(self.reader.lats.max()) - 1e-6)


class TestExportar(_MapBase):
    def test_nombre_por_defecto(self):
        self.assertEqual(self.w._default_name("png"), "sintetico_paso0_F300.png")
        self.w.panel.cb_press.setCurrentIndex(1 + self.w.panel._combo_items.index(("p", 850.0)))
        self.assertEqual(self.w._default_name("csv"), "sintetico_paso0_850hPa.csv")

    def test_csv(self):
        path = os.path.join(self._tmp.name, "salida.csv")
        self.w.write_csv(path)
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        nj, ni = len(self.reader.lats), len(self.reader.lons)
        self.assertEqual(len(rows), 4 + nj * ni)
        self.assertEqual(rows[3], ["lat", "lon", "u_ms", "v_ms", "velocidad_kt",
                                   "direccion_deg", "t_c"])
        self.assertEqual(rows[2][3], "FL interpolado")
        first = rows[4]
        self.assertEqual(first[0], f"{self.reader.lats[0]:.3f}")
        self.assertEqual(first[1], f"{self.reader.lons[0]:.3f}")
        self.assertTrue(float(first[4]) > 0)

    def test_png(self):
        path = os.path.join(self._tmp.name, "salida.png")
        self.w.write_png(path)
        self.assertTrue(os.path.getsize(path) > 1000)


class TestCierreYValidacion(_MapBase):
    def test_cerrar_archivo_vuelve_a_bienvenida(self):
        self.w._file_close()
        self.assertTrue(self.w._welcome.isVisible())
        self.assertFalse(self.w._main_area.isVisible())
        self.assertIsNone(self.w._reader)
        self.assertEqual(self.w.windowTitle(), "Visor GRIB")
        self.assertFalse(self.w._act_close.isEnabled())

    def test_sin_viento_solo_temperatura(self):
        r = _reader_sintetico([850, 700])
        r.variables = ["t"]
        old = QMessageBox.warning
        QMessageBox.warning = staticmethod(lambda *a, **k: None)
        try:
            self.assertTrue(self.w._accept_reader(r))
        finally:
            QMessageBox.warning = old
        self.assertEqual(self.w.panel.mode(), "temperatura")

    def test_sin_datos_no_abre(self):
        r = _reader_sintetico([850])
        r.variables = []
        old = QMessageBox.critical
        QMessageBox.critical = staticmethod(lambda *a, **k: None)
        try:
            self.assertFalse(self.w._accept_reader(r))
        finally:
            QMessageBox.critical = old


if __name__ == "__main__":
    unittest.main()


class TestProyeccion(_MapBase):
    def test_combo_cambia_proyeccion_y_persiste(self):
        import json
        from app.wind_plot import HAVE_CARTOPY
        if not HAVE_CARTOPY:
            self.skipTest("cartopy no disponible")
        n = len(self.draws)
        idx = self.w.panel.cb_proj.findData("stereo")
        self.w.panel.cb_proj.setCurrentIndex(idx)
        self.assertEqual(self.w.plot.proj_key, "stereo")
        self.assertEqual(len(self.draws), n + 1)
        with open(config.CONFIG_PATH) as fh:
            self.assertEqual(json.load(fh)["projection"], "stereo")
        # Centro de la proyección = centro del dominio del archivo
        self.assertAlmostEqual(self.w.plot.proj.proj4_params["lon_0"],
                               float(self.reader.lons.mean()), places=3)
        # El cursor convierte coordenadas proyectadas a lon/lat
        x, y = self.w.plot.proj.transform_point(-45.0, -2.5, self.w.plot.data_crs)
        lon, lat = self.w.plot.to_lonlat(x, y)
        self.assertAlmostEqual(lon, -45.0, places=4)
        self.assertAlmostEqual(lat, -2.5, places=4)
        self.assertIn("Lat   -2.50   Lon   -45.00", self.w.cursor_text(lon, lat))
        # Volver a lat/lon: las coordenadas son directas
        self.w.panel.cb_proj.setCurrentIndex(self.w.panel.cb_proj.findData("platecarree"))
        self.assertEqual(self.w.plot.proj_key, "platecarree")
        self.assertEqual(self.w.plot.to_lonlat(-50.0, -10.0), (-50.0, -10.0))

    def test_todas_las_proyecciones_dibujan(self):
        from app.wind_plot import HAVE_CARTOPY, PROJECTIONS
        if not HAVE_CARTOPY:
            self.skipTest("cartopy no disponible")
        for key, _name in PROJECTIONS:
            self.w.set_projection(key)
            self.assertTrue(self.w.plot.has_data, key)
            ext = self.w.plot.get_extent()
            self.assertEqual(len(ext), 4, key)

    def test_proyeccion_guardada_se_restaura(self):
        from app.wind_plot import HAVE_CARTOPY
        if not HAVE_CARTOPY:
            self.skipTest("cartopy no disponible")
        from app.main_window import MainWindow
        self.w._cfg["projection"] = "spstereo"
        config.save_config(self.w._cfg)
        w2 = MainWindow()
        try:
            self.assertEqual(w2.panel.projection(), "spstereo")
            self.assertEqual(w2.plot.proj_key, "spstereo")
        finally:
            w2.close()
            w2.deleteLater()
            _app.processEvents()
