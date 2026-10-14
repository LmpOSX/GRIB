#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
grib_viewer.py
==============

Visor de escritorio para archivos GRIB2 de viento y temperatura generados a
partir de GFS (o cualquier modelo con campos U/V/T en niveles de presión).

Características principales
---------------------------
* Lectura de GRIB2 con los bindings Python de ecCodes, iterando mensaje por
  mensaje (robusto frente a archivos con distintos typeOfLevel o pasos).
* Inventario del archivo: corrida, pasos, horas de validez, variables, niveles
  y grilla, mostrado en un panel de texto.
* Interfaz tkinter con mapa matplotlib embebido (cartopy si está disponible).
* Selección de paso (Current / Next / Advanced o combo con todos los pasos).
* Selección de nivel de vuelo (FL) con conversión ISA a presión e
  interpolación lineal en ln(p), o selección directa de un nivel de presión.
* Barbas de viento en nudos coloreadas por velocidad, contornos de
  temperatura, fondo de velocidad, grilla, "Extra Info" (valores al lado de
  cada barba), zoom/pan, exportación a PNG y CSV.

Uso
---
    python grib_viewer.py [archivo.grib2]

Clases
------
* GribReader : lectura, inventario, cache de campos e interpolación vertical.
* WindPlot   : dibujo del mapa (matplotlib + cartopy opcional).
* App        : interfaz gráfica (tkinter).
"""

import csv
import os
import sys
import traceback

import numpy as np

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from matplotlib.backends.backend_tkagg import NavigationToolbar2Tk

# Lógica sin interfaz y dibujo del mapa, extraídos a app/ (Fase 1 de la
# migración a PyQt6). Este archivo conserva sólo la interfaz Tkinter.
from app.grib_reader import (ECCODES_HELP, FLIGHT_LEVELS, KELVIN, GribReader,
                             ec, fl_to_hpa, fmt_dt, speed_dir_from_uv)
from app.wind_plot import HAVE_CARTOPY, WindPlot

# Colores de la interfaz Tk (estilo pantalla ATC)
UI_BG = "#1b1b1b"
UI_BG2 = "#2a2a2a"
UI_FG = "#e8e8e8"
UI_ACCENT = "#2d7dd2"
UI_TITLE = "#9ecbff"


# ---------------------------------------------------------------------------
# Interfaz gráfica
# ---------------------------------------------------------------------------
class App(tk.Tk):
    """Ventana principal: mapa a la izquierda y panel de controles a la
    derecha, imitando el panel de un sistema ATC."""

    TIME_LABELS = ["Current (+0)", "Next (+1)", "Advanced (+2)"]
    P_COMBO_NONE = "(interpolar por FL)"

    def __init__(self, path=None):
        super().__init__()
        self.title("Visor GRIB2 – Viento y Temperatura (GFS)")
        self.geometry("1380x860")
        self.minsize(1000, 650)
        self.configure(bg=UI_BG)

        self.reader = None
        self.step_idx = 0
        self.level_mode = "fl"          # 'fl' o 'p'
        self.sel_fl = 300
        self.sel_p = None
        self.wind_enabled = True
        self.current = None             # dict con campos actuales para hover/CSV
        self._updating_ui = False       # evita redibujos recursivos
        self._fl_buttons = {}

        self._setup_style()
        self._build_ui()
        self._bind_events()

        if path:
            self.after(150, lambda: self.open_file(path))

    # ------------------------------------------------------------- estilo
    def _setup_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=UI_BG, foreground=UI_FG, fieldbackground=UI_BG2,
                        bordercolor="#444444", lightcolor=UI_BG, darkcolor=UI_BG)
        style.configure("TFrame", background=UI_BG)
        style.configure("TLabel", background=UI_BG, foreground=UI_FG)
        style.configure("Title.TLabel", background=UI_BG, foreground=UI_TITLE,
                        font=("TkDefaultFont", 10, "bold"))
        style.configure("Status.TLabel", background="#101010", foreground="#9ff09f",
                        font=("TkFixedFont", 10))
        style.configure("TLabelframe", background=UI_BG, foreground=UI_FG, bordercolor="#555555")
        style.configure("TLabelframe.Label", background=UI_BG, foreground=UI_TITLE,
                        font=("TkDefaultFont", 10, "bold"))
        style.configure("TButton", background="#3a3a3a", foreground=UI_FG, padding=3)
        style.map("TButton", background=[("active", "#4a4a4a"), ("pressed", "#555555")])
        style.configure("FL.TButton", background="#3a3a3a", foreground=UI_FG, padding=2,
                        width=6)
        style.configure("Sel.FL.TButton", background=UI_ACCENT, foreground="#ffffff", padding=2,
                        width=6)
        style.map("Sel.FL.TButton", background=[("active", UI_ACCENT)])
        style.configure("TCheckbutton", background=UI_BG, foreground=UI_FG)
        style.map("TCheckbutton", background=[("active", UI_BG)])
        style.configure("TRadiobutton", background=UI_BG, foreground=UI_FG)
        style.map("TRadiobutton", background=[("active", UI_BG)])
        style.configure("TEntry", fieldbackground=UI_BG2, foreground=UI_FG, insertcolor=UI_FG)
        style.configure("TCombobox", fieldbackground=UI_BG2, foreground=UI_FG,
                        background="#3a3a3a", arrowcolor=UI_FG)
        style.map("TCombobox", fieldbackground=[("readonly", UI_BG2)],
                  foreground=[("readonly", UI_FG)])
        style.configure("TSpinbox", fieldbackground=UI_BG2, foreground=UI_FG,
                        background="#3a3a3a", arrowcolor=UI_FG)
        self.option_add("*TCombobox*Listbox.background", UI_BG2)
        self.option_add("*TCombobox*Listbox.foreground", UI_FG)

    # ------------------------------------------------------------ widgets
    def _build_ui(self):
        # Contenedor principal: mapa (izquierda) + panel (derecha)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self)
        left.grid(row=0, column=0, sticky="nsew")
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        self.plot = WindPlot(left)
        self.plot.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        tb_frame = ttk.Frame(left)
        tb_frame.grid(row=1, column=0, sticky="ew")
        self.toolbar = NavigationToolbar2Tk(self.plot.canvas, tb_frame, pack_toolbar=False)
        self.toolbar.config(background=UI_BG)
        self.toolbar.pack(side=tk.LEFT, fill=tk.X)
        self.toolbar.update()

        # Panel derecho con scroll (por si la pantalla es baja)
        right_outer = ttk.Frame(self, width=360)
        right_outer.grid(row=0, column=1, sticky="ns")
        right_outer.rowconfigure(0, weight=1)
        self._panel_canvas = tk.Canvas(right_outer, bg=UI_BG, highlightthickness=0, width=350)
        vsb = ttk.Scrollbar(right_outer, orient="vertical", command=self._panel_canvas.yview)
        self._panel_canvas.configure(yscrollcommand=vsb.set)
        self._panel_canvas.grid(row=0, column=0, sticky="ns")
        vsb.grid(row=0, column=1, sticky="ns")
        panel = ttk.Frame(self._panel_canvas)
        self._panel_window = self._panel_canvas.create_window((0, 0), window=panel, anchor="nw")
        panel.bind("<Configure>", lambda e: self._panel_canvas.configure(
            scrollregion=self._panel_canvas.bbox("all")))
        self._panel_canvas.bind("<Configure>", lambda e: self._panel_canvas.itemconfigure(
            self._panel_window, width=e.width))

        row = 0
        # --- Abrir archivo
        fr = ttk.Frame(panel)
        fr.grid(row=row, column=0, sticky="ew", padx=6, pady=(8, 4))
        row += 1
        ttk.Button(fr, text="Abrir GRIB...", command=self.open_dialog).pack(side=tk.LEFT)
        self.lbl_file = ttk.Label(fr, text="(sin archivo)", foreground="#bbbbbb")
        self.lbl_file.pack(side=tk.LEFT, padx=8)

        # --- STATUS
        st = ttk.LabelFrame(panel, text="STATUS")
        st.grid(row=row, column=0, sticky="ew", padx=6, pady=4)
        row += 1
        self.lbl_run = ttk.Label(st, text="RUN: --", style="Status.TLabel")
        self.lbl_step = ttk.Label(st, text="STEP: --", style="Status.TLabel")
        self.lbl_valid_utc = ttk.Label(st, text="VALIDITY [--:-- – --:--] UTC", style="Status.TLabel")
        self.lbl_valid_loc = ttk.Label(st, text="LOCAL    [--:-- – --:--]", style="Status.TLabel")
        self.lbl_level = ttk.Label(st, text="LEVEL: --", style="Status.TLabel", wraplength=320,
                                   justify=tk.LEFT)
        for w in (self.lbl_run, self.lbl_step, self.lbl_valid_utc, self.lbl_valid_loc, self.lbl_level):
            w.pack(fill=tk.X, padx=4, pady=1)

        # --- TIME
        tf = ttk.LabelFrame(panel, text="TIME")
        tf.grid(row=row, column=0, sticky="ew", padx=6, pady=4)
        row += 1
        self.var_time = tk.IntVar(value=0)
        self.rb_time = []
        self.lbl_time = []
        for i, txt in enumerate(self.TIME_LABELS):
            rb = ttk.Radiobutton(tf, text=txt, value=i, variable=self.var_time,
                                 command=self._on_time_radio)
            rb.grid(row=i, column=0, sticky="w", padx=4, pady=1)
            lb = ttk.Label(tf, text="--", foreground="#9ff09f")
            lb.grid(row=i, column=1, sticky="w", padx=6)
            self.rb_time.append(rb)
            self.lbl_time.append(lb)
        self.fr_steps = ttk.Frame(tf)
        ttk.Label(self.fr_steps, text="Todos los pasos:").pack(side=tk.LEFT, padx=4)
        self.cb_steps = ttk.Combobox(self.fr_steps, state="readonly", width=26)
        self.cb_steps.pack(side=tk.LEFT)
        self.cb_steps.bind("<<ComboboxSelected>>", self._on_step_combo)
        self.fr_steps.grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 2))
        self.fr_steps.grid_remove()

        # --- LEVEL
        lf = ttk.LabelFrame(panel, text="LEVEL")
        lf.grid(row=row, column=0, sticky="ew", padx=6, pady=4)
        row += 1
        grid_fr = ttk.Frame(lf)
        grid_fr.pack(fill=tk.X, padx=2, pady=2)
        for k, fl in enumerate(FLIGHT_LEVELS):
            b = ttk.Button(grid_fr, text=f"F{fl:03d}", style="FL.TButton",
                           command=lambda f=fl: self.select_fl(f))
            b.grid(row=k // 4, column=k % 4, padx=2, pady=2, sticky="ew")
            self._fl_buttons[fl] = b
        for c in range(4):
            grid_fr.columnconfigure(c, weight=1)
        pf = ttk.Frame(lf)
        pf.pack(fill=tk.X, padx=4, pady=(4, 4))
        ttk.Label(pf, text="Nivel de presión:").pack(side=tk.LEFT)
        self.cb_press = ttk.Combobox(pf, state="readonly", width=18,
                                     values=[self.P_COMBO_NONE])
        self.cb_press.current(0)
        self.cb_press.pack(side=tk.LEFT, padx=6)
        self.cb_press.bind("<<ComboboxSelected>>", self._on_press_combo)
        self.lbl_fl_p = ttk.Label(lf, text="", foreground="#bbbbbb")
        self.lbl_fl_p.pack(anchor="w", padx=6, pady=(0, 4))

        # --- Variable
        vf = ttk.LabelFrame(panel, text="VARIABLE")
        vf.grid(row=row, column=0, sticky="ew", padx=6, pady=4)
        row += 1
        self.var_mode = tk.StringVar(value="viento")
        for txt, val in (("Viento", "viento"), ("Temperatura", "temperatura"),
                         ("Viento + Temperatura", "ambos")):
            ttk.Radiobutton(vf, text=txt, value=val, variable=self.var_mode,
                            command=self.redraw).pack(side=tk.LEFT, padx=4, pady=2)

        # --- CONFIG
        cf = ttk.LabelFrame(panel, text="CONFIG")
        cf.grid(row=row, column=0, sticky="ew", padx=6, pady=4)
        row += 1
        self.var_extra = tk.BooleanVar(value=False)
        self.var_grid = tk.BooleanVar(value=False)
        self.var_fill = tk.BooleanVar(value=False)
        ttk.Checkbutton(cf, text="Extra Info (kt / °C junto a cada barba)",
                        variable=self.var_extra, command=self.redraw).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=4)
        ttk.Checkbutton(cf, text="Grilla lat/lon del archivo", variable=self.var_grid,
                        command=self.redraw).grid(row=1, column=0, columnspan=3, sticky="w", padx=4)
        ttk.Checkbutton(cf, text="Fondo de velocidad (contornos rellenos)",
                        variable=self.var_fill, command=self.redraw).grid(
            row=2, column=0, columnspan=3, sticky="w", padx=4)
        ttk.Label(cf, text="Densidad: cada N puntos").grid(row=3, column=0, sticky="w", padx=4, pady=3)
        self.var_stride = tk.IntVar(value=1)
        self.sp_stride = ttk.Spinbox(cf, from_=1, to=10, width=4, textvariable=self.var_stride,
                                     command=self.redraw, wrap=False)
        self.sp_stride.grid(row=3, column=1, sticky="w", padx=4)
        self.sp_stride.bind("<Return>", lambda e: self.redraw())
        bf = ttk.Frame(cf)
        bf.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(4, 4))
        ttk.Button(bf, text="Update", command=self.redraw).pack(side=tk.LEFT, padx=4)
        self.btn_disable = ttk.Button(bf, text="Disable", command=self.toggle_wind)
        self.btn_disable.pack(side=tk.LEFT, padx=4)

        # --- Recuadro (extensión)
        ef = ttk.LabelFrame(panel, text="RECUADRO (lat/lon)")
        ef.grid(row=row, column=0, sticky="ew", padx=6, pady=4)
        row += 1
        self.ent_latmin = self._labeled_entry(ef, "lat min", 0, 0)
        self.ent_latmax = self._labeled_entry(ef, "lat max", 0, 2)
        self.ent_lonmin = self._labeled_entry(ef, "lon min", 1, 0)
        self.ent_lonmax = self._labeled_entry(ef, "lon max", 1, 2)
        bf2 = ttk.Frame(ef)
        bf2.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(4, 4))
        ttk.Button(bf2, text="Aplicar recuadro", command=self.apply_extent).pack(side=tk.LEFT, padx=4)
        ttk.Button(bf2, text="Todo el dominio", command=self.full_extent).pack(side=tk.LEFT, padx=4)

        # --- Exportar
        xf = ttk.Frame(panel)
        xf.grid(row=row, column=0, sticky="ew", padx=6, pady=4)
        row += 1
        ttk.Button(xf, text="Exportar PNG", command=self.export_png).pack(side=tk.LEFT, padx=4)
        ttk.Button(xf, text="Exportar CSV", command=self.export_csv).pack(side=tk.LEFT, padx=4)

        # --- Inventario
        inv = ttk.LabelFrame(panel, text="INVENTARIO")
        inv.grid(row=row, column=0, sticky="nsew", padx=6, pady=4)
        row += 1
        self.txt_inv = ScrolledText(inv, height=14, width=44, bg="#101010", fg="#dddddd",
                                    insertbackground=UI_FG, font=("TkFixedFont", 9),
                                    wrap=tk.NONE, relief=tk.FLAT)
        self.txt_inv.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        self._set_inventory("Sin archivo abierto.\n\n" +
                            ("" if ec is not None else ECCODES_HELP) +
                            ("" if HAVE_CARTOPY else "\ncartopy no instalado: el mapa se dibuja sin costas.\n"))
        panel.columnconfigure(0, weight=1)

        # --- Barra de estado inferior
        self.lbl_status = ttk.Label(self, text="Listo.", style="Status.TLabel", anchor="w")
        self.lbl_status.grid(row=1, column=0, columnspan=2, sticky="ew")

        self._refresh_fl_buttons()
        self._update_level_label()

    def _labeled_entry(self, parent, text, r, c):
        ttk.Label(parent, text=text).grid(row=r, column=c, sticky="e", padx=(6, 2), pady=2)
        e = ttk.Entry(parent, width=9)
        e.grid(row=r, column=c + 1, sticky="w", padx=(0, 6), pady=2)
        e.bind("<Return>", lambda ev: self.apply_extent())
        return e

    def _bind_events(self):
        self.plot.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.plot.canvas.mpl_connect("draw_event", self._on_draw)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        try:
            self.quit()
        finally:
            self.destroy()

    # ------------------------------------------------------------ archivo
    def open_dialog(self):
        path = filedialog.askopenfilename(
            title="Abrir archivo GRIB2",
            filetypes=[("GRIB", "*.grib2 *.grb2 *.grib *.grb"), ("Todos", "*.*")])
        if path:
            self.open_file(path)

    def open_file(self, path):
        if ec is None:
            messagebox.showerror("eccodes no disponible", ECCODES_HELP)
            return
        self.set_status(f"Leyendo {os.path.basename(path)} ...")
        self.update_idletasks()
        try:
            reader = GribReader(path)
        except Exception as exc:
            traceback.print_exc()
            messagebox.showerror("Error al abrir el archivo",
                                 f"No se pudo leer el archivo:\n{path}\n\n{exc}")
            self.set_status("Error al abrir el archivo.")
            return

        if "u" not in reader.variables or "v" not in reader.variables:
            if "t" in reader.variables:
                messagebox.showwarning(
                    "Sin viento",
                    "El archivo no contiene componentes U/V del viento en niveles de "
                    "presión. Sólo se podrá mostrar temperatura.")
                self.var_mode.set("temperatura")
            else:
                messagebox.showerror(
                    "Sin datos de viento",
                    "El archivo no contiene componentes U/V (UGRD/VGRD) ni temperatura "
                    "en niveles de presión.")
                self.set_status("Archivo sin U/V.")
                return

        self.reader = reader
        self.step_idx = 0
        self.current = None
        self.lbl_file.config(text=os.path.basename(path))
        self._set_inventory(reader.inventory_text())
        self._populate_controls()
        self.redraw(keep_extent=False)
        self.set_status(f"Archivo cargado: {path}")

    def _set_inventory(self, text):
        self.txt_inv.config(state=tk.NORMAL)
        self.txt_inv.delete("1.0", tk.END)
        self.txt_inv.insert(tk.END, text)
        self.txt_inv.config(state=tk.DISABLED)

    def _populate_controls(self):
        """Llena los controles de paso y nivel según el inventario."""
        r = self.reader
        self._updating_ui = True
        try:
            # Pasos
            n = len(r.steps)
            for i in range(3):
                if i < n:
                    self.rb_time[i].state(["!disabled"])
                    self.lbl_time[i].config(text=r.steps[i].label())
                else:
                    self.rb_time[i].state(["disabled"])
                    self.lbl_time[i].config(text="--")
            self.var_time.set(0)
            self.cb_steps.config(values=[f"[{i}] {s.label()}" for i, s in enumerate(r.steps)])
            if n > 0:
                self.cb_steps.current(0)
            if n > 3:
                self.fr_steps.grid()
            else:
                self.fr_steps.grid_remove()
            # Niveles de presión
            vals = [self.P_COMBO_NONE] + [f"{lv:g} hPa" for lv in r.levels]
            self.cb_press.config(values=vals)
            self.cb_press.current(0)
            self.level_mode = "fl"
            self.sel_p = None
            # Recuadro
            self._fill_extent_entries([r.lons.min(), r.lons.max(), r.lats.min(), r.lats.max()])
        finally:
            self._updating_ui = False
        self._refresh_fl_buttons()

    # ---------------------------------------------------------- callbacks
    def _on_time_radio(self):
        if self._updating_ui:
            return
        self.step_idx = int(self.var_time.get())
        if self.reader and self.reader.steps:
            self.cb_steps.current(min(self.step_idx, len(self.reader.steps) - 1))
        self.redraw()

    def _on_step_combo(self, _event=None):
        if self._updating_ui:
            return
        idx = self.cb_steps.current()
        if idx < 0:
            return
        self.step_idx = idx
        if idx < 3:
            self.var_time.set(idx)
        else:
            self.var_time.set(-1)
        self.redraw()

    def select_fl(self, fl):
        self.sel_fl = fl
        self.level_mode = "fl"
        self.sel_p = None
        self._updating_ui = True
        try:
            self.cb_press.current(0)
        finally:
            self._updating_ui = False
        self._refresh_fl_buttons()
        self._update_level_label()
        self.redraw()

    def _on_press_combo(self, _event=None):
        if self._updating_ui:
            return
        idx = self.cb_press.current()
        if idx <= 0 or self.reader is None:
            self.level_mode = "fl"
            self.sel_p = None
        else:
            self.level_mode = "p"
            self.sel_p = self.reader.levels[idx - 1]
        self._refresh_fl_buttons()
        self._update_level_label()
        self.redraw()

    def _refresh_fl_buttons(self):
        for fl, b in self._fl_buttons.items():
            sel = (self.level_mode == "fl" and fl == self.sel_fl)
            b.configure(style="Sel.FL.TButton" if sel else "FL.TButton")

    def _update_level_label(self):
        if self.level_mode == "fl":
            self.lbl_fl_p.config(text=f"F{self.sel_fl:03d} ≈ {fl_to_hpa(self.sel_fl):.1f} hPa (ISA)")
        else:
            self.lbl_fl_p.config(text=f"Nivel del archivo: {self.sel_p:g} hPa (sin interpolar)")

    def toggle_wind(self):
        self.wind_enabled = not self.wind_enabled
        self.btn_disable.config(text="Disable" if self.wind_enabled else "Enable")
        self.redraw()

    def apply_extent(self):
        try:
            lat0 = float(self.ent_latmin.get())
            lat1 = float(self.ent_latmax.get())
            lon0 = float(self.ent_lonmin.get())
            lon1 = float(self.ent_lonmax.get())
        except ValueError:
            messagebox.showwarning("Recuadro", "Ingrese valores numéricos en lat/lon min/max.")
            return
        if lat1 <= lat0 or lon1 <= lon0:
            messagebox.showwarning("Recuadro", "Los máximos deben ser mayores que los mínimos.")
            return
        if self.plot.has_data:
            self.plot.set_extent([lon0, lon1, lat0, lat1])

    def full_extent(self):
        if self.reader is None:
            return
        r = self.reader
        self.plot.set_extent([float(r.lons.min()), float(r.lons.max()),
                              float(r.lats.min()), float(r.lats.max())])
        self.toolbar.update()

    def _fill_extent_entries(self, extent):
        lon0, lon1, lat0, lat1 = extent
        for ent, val in ((self.ent_latmin, lat0), (self.ent_latmax, lat1),
                         (self.ent_lonmin, lon0), (self.ent_lonmax, lon1)):
            ent.delete(0, tk.END)
            ent.insert(0, f"{val:.2f}")

    def _on_draw(self, _event):
        """Tras cada dibujo (zoom/pan incluidos) refleja la extensión en los
        campos del recuadro."""
        if self.plot.has_data:
            ext = self.plot.get_extent()
            if ext:
                self._fill_extent_entries(ext)

    def _on_motion(self, event):
        """Muestra lat/lon y valores bajo el cursor en la barra de estado."""
        if event.inaxes is not self.plot.ax or event.xdata is None or event.ydata is None:
            return
        lon, lat = float(event.xdata), float(event.ydata)
        txt = f"Lat {lat:7.2f}   Lon {lon:8.2f}"
        cur = self.current
        if cur is not None and self.reader is not None:
            lons, lats = self.reader.lons, self.reader.lats
            i = int(np.argmin(np.abs(lons - lon)))
            j = int(np.argmin(np.abs(lats - lat)))
            dlon = float(abs(lons[1] - lons[0])) if len(lons) > 1 else 1.0
            dlat = float(abs(lats[1] - lats[0])) if len(lats) > 1 else 1.0
            if abs(lons[i] - lon) <= dlon and abs(lats[j] - lat) <= dlat:
                txt += f"   | punto ({lats[j]:.2f}, {lons[i]:.2f})"
                if cur["spd"] is not None:
                    s = cur["spd"][j, i]
                    d = cur["dir"][j, i]
                    if not np.isnan(s):
                        txt += f"   | Viento {s:5.1f} kt / {d:5.1f}°"
                    else:
                        txt += "   | Viento: sin dato"
                if cur["t"] is not None:
                    tv = cur["t"][j, i]
                    if not np.isnan(tv):
                        txt += f"   | T {tv - KELVIN:6.1f} °C"
        self.set_status(txt)

    def set_status(self, text):
        self.lbl_status.config(text=text)

    # ------------------------------------------------------------- dibujo
    def redraw(self, keep_extent=True):
        """Recalcula los campos del paso/nivel seleccionados y redibuja."""
        if self._updating_ui:
            return
        if self.reader is None:
            self.plot.draw_empty()
            return
        r = self.reader
        if not r.steps:
            return
        self.step_idx = max(0, min(self.step_idx, len(r.steps) - 1))
        step = r.steps[self.step_idx]

        try:
            if self.level_mode == "p" and self.sel_p is not None:
                u, v, t, info = r.get_level_fields(self.step_idx, self.sel_p)
            else:
                u, v, t, info = r.interp_to_pressure(self.step_idx, fl_to_hpa(self.sel_fl))
        except Exception as exc:
            traceback.print_exc()
            messagebox.showerror("Error de lectura", f"No se pudieron leer los campos:\n{exc}")
            return

        spd = direc = None
        if u is not None and v is not None:
            spd, direc = speed_dir_from_uv(u, v)
        self.current = {"u": u, "v": v, "t": t, "spd": spd, "dir": direc, "info": info,
                        "step": step}

        # Textos de STATUS
        self._update_status_panel(step, info, u, v, t)

        # Título del mapa
        run = r.run_time()
        if self.level_mode == "p":
            lvl_txt = f"{info['p']:g} hPa"
        else:
            lvl_txt = f"F{self.sel_fl:03d} ({info['p']:.0f} hPa)"
            if info["extrapolated"]:
                lvl_txt += f" → nivel más cercano {info['nearest']:g} hPa"
            elif info["bracket"]:
                lvl_txt += f" interp. {info['bracket'][0]:g}/{info['bracket'][1]:g} hPa"
        mode_txt = {"viento": "Viento", "temperatura": "Temperatura",
                    "ambos": "Viento + Temperatura"}[self.var_mode.get()]
        title = (f"Corrida {fmt_dt(run)}Z  {step.label()}  |  {lvl_txt}  |  {mode_txt}")

        try:
            stride = int(self.var_stride.get())
        except (tk.TclError, ValueError):
            stride = 1
        extent = self.plot.get_extent() if (keep_extent and self.plot.has_data) else None
        opts = {
            "mode": self.var_mode.get(),
            "show_wind": self.wind_enabled,
            "extra_info": self.var_extra.get(),
            "grid": self.var_grid.get(),
            "fill": self.var_fill.get(),
            "stride": stride,
            "extent": extent,
            "title": title,
        }
        try:
            self.plot.draw(r.lats, r.lons, u, v, t, opts)
        except Exception as exc:
            traceback.print_exc()
            messagebox.showerror("Error al dibujar", f"No se pudo dibujar el mapa:\n{exc}")
            return
        if extent is None:
            self.toolbar.update()

    def _update_status_panel(self, step, info, u, v, t):
        run = self.reader.run_time()
        self.lbl_run.config(text=f"RUN:   {fmt_dt(run)} UTC" if run else "RUN: --")
        h = step.hours
        hs = f"+{h:g} h" if h is not None else step.step_range
        self.lbl_step.config(text=f"STEP:  [{self.step_idx}] {hs}  (stepRange {step.step_range})")
        ws, we = step.window_start, step.window_end
        self.lbl_valid_utc.config(
            text=f"VALIDITY [{fmt_dt(ws, False)}–{fmt_dt(we, False)}] UTC  {ws.strftime('%d/%m/%Y') if ws else ''}")
        if ws is not None and we is not None:
            ls = ws.astimezone()
            le = we.astimezone()
            tzname = ls.tzname() or "local"
            self.lbl_valid_loc.config(
                text=f"LOCAL    [{fmt_dt(ls, False)}–{fmt_dt(le, False)}] {tzname}  {ls.strftime('%d/%m/%Y')}")
        else:
            self.lbl_valid_loc.config(text="LOCAL    [--:-- – --:--]")

        if self.level_mode == "p":
            lvl = f"LEVEL: {info['p']:g} hPa (nivel del archivo)"
        else:
            lvl = f"LEVEL: F{self.sel_fl:03d} = {info['p']:.1f} hPa (ISA)"
            if info["extrapolated"]:
                lvl += f"\n  extrapolado / nivel más cercano: {info['nearest']:g} hPa"
            elif info["bracket"]:
                lvl += f"\n  interpolado en ln(p) entre {info['bracket'][0]:g} y {info['bracket'][1]:g} hPa"
        missing = [n for n, f in (("U", u), ("V", v), ("T", t)) if f is None]
        if missing:
            lvl += f"\n  sin datos de: {', '.join(missing)}"
        if not self.wind_enabled:
            lvl += "\n  capa de datos DESHABILITADA"
        self.lbl_level.config(text=lvl)

    # ---------------------------------------------------------- exportar
    def export_png(self):
        if not self.plot.has_data:
            messagebox.showinfo("Exportar PNG", "No hay mapa para exportar.")
            return
        path = filedialog.asksaveasfilename(
            title="Guardar PNG", defaultextension=".png",
            initialfile=self._default_name("png"),
            filetypes=[("PNG", "*.png")])
        if not path:
            return
        try:
            self.plot.save_png(path)
            self.set_status(f"PNG guardado: {path}")
        except Exception as exc:
            messagebox.showerror("Exportar PNG", f"No se pudo guardar:\n{exc}")

    def export_csv(self):
        if self.current is None or self.reader is None:
            messagebox.showinfo("Exportar CSV", "No hay datos cargados.")
            return
        path = filedialog.asksaveasfilename(
            title="Guardar CSV", defaultextension=".csv",
            initialfile=self._default_name("csv"),
            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        cur = self.current
        lats, lons = self.reader.lats, self.reader.lons

        def cell(arr, j, i):
            if arr is None:
                return ""
            val = arr[j, i]
            return "" if np.isnan(val) else f"{val:.3f}"

        try:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["# archivo", os.path.basename(self.reader.path)])
                w.writerow(["# paso", cur["step"].step_range, "validez_utc",
                            cur["step"].valid.isoformat() if cur["step"].valid else ""])
                w.writerow(["# nivel_hPa", f"{cur['info']['p']:.2f}",
                            "modo", "FL interpolado" if self.level_mode == "fl" else "nivel exacto"])
                w.writerow(["lat", "lon", "u_ms", "v_ms", "velocidad_kt", "direccion_deg", "t_c"])
                tc = (cur["t"] - KELVIN) if cur["t"] is not None else None
                for j in range(len(lats)):
                    for i in range(len(lons)):
                        w.writerow([f"{lats[j]:.3f}", f"{lons[i]:.3f}",
                                    cell(cur["u"], j, i), cell(cur["v"], j, i),
                                    cell(cur["spd"], j, i), cell(cur["dir"], j, i),
                                    cell(tc, j, i)])
            self.set_status(f"CSV guardado: {path}")
        except Exception as exc:
            messagebox.showerror("Exportar CSV", f"No se pudo guardar:\n{exc}")

    def _default_name(self, ext):
        base = os.path.splitext(os.path.basename(self.reader.path))[0] if self.reader else "grib"
        lvl = f"F{self.sel_fl:03d}" if self.level_mode == "fl" else f"{self.sel_p:g}hPa"
        return f"{base}_paso{self.step_idx}_{lvl}.{ext}"


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------
def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    path = argv[0] if argv else None
    app = App(path)
    app.mainloop()


if __name__ == "__main__":
    main()
