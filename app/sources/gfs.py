# -*- coding: utf-8 -*-
"""Fuente NOAA GFS (NOMADS grib filter), integrada al esquema de fuentes.

Parámetros propios: resolución objetivo (0,25 / 0,50 / 1,00°), bajar
siempre 0,25° y regrillar localmente, suavizado (promedio de área) y
niveles intermedios cada 25 hPa (pgrb2b). El recorte por zona lo hace el
servidor.
"""
from .. import gfs_download as gfs
from ..regrid import SMOOTHING, regrid_grib
from .base import Source, Param, Request

RES_DEG = {"0p25": 0.25, "0p50": 0.5, "1p00": 1.0}


class GFSSource(Source):
    key = "gfs"
    name = "NOAA GFS"
    model = "GFS (NCEP) vía NOMADS grib filter"
    kind = "altura"
    flight_levels = False
    doc_url = "https://nomads.ncep.noaa.gov/"
    description = ("Modelo global de NOAA, 4 corridas diarias, plazos cada hora hasta +120 h y "
                   "cada 3 h hasta +384 h. El servidor recorta por variable, nivel y zona.")
    params = [
        Param("resolucion", "Resolución de la grilla", "choice", "0p25",
              choices=[(k, n) for k, n, *_ in gfs.RESOLUTIONS],
              help="0,50° y 1,00° son muestras puntuales del campo de 0,25°."),
        Param("solo_0p25", "Bajar siempre 0,25° y regrillar localmente", "bool", False,
              help="Para suavizar hace falta el campo fino; con suavizado se activa solo."),
        Param("suavizado", "Suavizado al regrillar", "choice", "ninguno", choices=SMOOTHING,
              help="Promedio ponderado por área de las celdas de 0,25° que cubre cada celda "
                   "gruesa. Sólo actúa al regrillar a 0,50° o 1,00°."),
        Param("niveles_intermedios", "Incluir niveles intermedios cada 25 hPa (pgrb2b)", "bool",
              False, help="A 0,25° se piden al producto pgrb2b; a 0,50° vienen en pgrb2full; "
                          "a 1,00° NOMADS no los filtra."),
    ]
    variables = gfs.VARIABLES
    default_variables = ["UGRD", "VGRD", "TMP"]
    levels = gfs.ALL_LEVELS
    viewer_levels = gfs.VIEWER_LEVELS
    extra_levels_param = "niveles_intermedios"
    cycles = gfs.CYCLES
    availability_lag_h = gfs.AVAILABILITY_LAG_H
    region_filter = "servidor"

    def steps(self, params=None, cycle=None):
        return list(range(0, 121, 1)) + list(range(123, gfs.MAX_HOUR + 1, 3))

    def viewer_levels_for(self, params):
        p = self.merged_params(params)
        lv = list(gfs.VIEWER_LEVELS)
        if p["niveles_intermedios"] and gfs.extra_levels_available(self.download_resolution(p)):
            lv += gfs.VIEWER_EXTRA_LEVELS
        return lv

    def level_enabled(self, level, params):
        if level not in gfs.EXTRA_LEVELS:
            return True
        p = self.merged_params(params)
        return bool(p["niveles_intermedios"]) and gfs.extra_levels_available(self.download_resolution(p))

    def grid_resolution(self, params=None):
        return RES_DEG[self.merged_params(params)["resolucion"]]

    def download_resolution(self, params):
        """Resolución que realmente se pide al servidor."""
        p = self.merged_params(params)
        if p["solo_0p25"] or p["suavizado"] == "promedio":
            return "0p25"
        return p["resolucion"]

    def default_basename(self, job):
        p = self.merged_params(job.params)
        suf = ""
        if self.download_resolution(p) != p["resolucion"]:
            suf = "_desde_0p25" + ("_suav" if p["suavizado"] == "promedio" else "")
        return f"gfs_{job.run_date:%Y%m%d}_{job.cycle:02d}z_{p['resolucion']}{suf}"

    def _spec(self, job):
        p = self.merged_params(job.params)
        levels = list(job.levels)
        if not p["niveles_intermedios"]:
            levels = [lv for lv in levels if lv not in gfs.EXTRA_LEVELS]
        return gfs.DownloadSpec(job.run_date, job.cycle, job.steps, job.variables, levels,
                                resolution=self.download_resolution(p), region=self.server_region(job),
                                dest_dir=job.dest_dir, basename=job.basename or "x", merge=job.merge)

    def validate(self, job):
        err = super().validate(job)
        if err:
            return err
        p = self.merged_params(job.params)
        spec = self._spec(job)
        err = spec.validate()
        if err:
            return err
        if (p["niveles_intermedios"] and not gfs.extra_levels_available(self.download_resolution(p))):
            return ("A 1,00° NOMADS no filtra los niveles intermedios; marcá «Bajar siempre "
                    "0,25°» o elegí otra resolución.")
        return None

    def build_requests(self, job, step):
        spec = self._spec(job)
        return [Request(url, tag) for url, tag in gfs.build_urls(spec, step)]

    def postprocess_step(self, data, job, step=None):
        p = self.merged_params(job.params)
        src = self.download_resolution(p)
        if src == p["resolucion"]:
            return data, {"resolucion_descargada": src, "resolucion_final": src}
        factor = int(round(RES_DEG[p["resolucion"]] / RES_DEG[src]))
        out = regrid_grib(data, factor, p["suavizado"])
        return out, {"resolucion_descargada": src, "resolucion_final": p["resolucion"],
                     "regrillado": p["suavizado"], "factor": factor}
