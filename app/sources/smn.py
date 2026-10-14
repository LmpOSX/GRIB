# -*- coding: utf-8 -*-
"""Fuente SMN Argentina, WRF 4 km (datos abiertos en AWS, bucket smn-ar-wrf).

Es una fuente **de superficie**: temperatura y humedad a 2 m, viento a 10 m
y precipitación, sin niveles de presión. Un archivo NetCDF por hora de
pronóstico (~38 MB, dominio completo en Lambert 4 km) que se convierte
localmente a GRIB2 en lat/lon regular recortado a la zona; el visor lo
muestra sin selector de nivel.

Archivos: https://smn-ar-wrf.s3.amazonaws.com/DATA/WRF/DET/YYYY/MM/DD/HH/
  WRFDETAR_01H_YYYYMMDD_HH_FFF.nc   (FFF = 000…072)
Documentación: https://odp-aws-smn.github.io/documentation_wrf_det/
"""
from ..netcdf_convert import smn_wrf_to_grib, SMN_VARIABLES
from .base import Source, Param, Request

SMN_BASE = "https://smn-ar-wrf.s3.amazonaws.com/DATA/WRF/DET"
SMN_DOMAIN = (-11.6, -56.9, -94.3, -35.7)     # top, bottom, left, right


class SMNSource(Source):
    key = "smn_wrf"
    name = "SMN Argentina WRF 4 km"
    model = "WRF-ARW 4 km del SMN (superficie: T/HR 2 m, viento 10 m)"
    kind = "superficie"
    flight_levels = False
    doc_url = "https://odp-aws-smn.github.io/documentation_wrf_det/"
    description = ("Pronóstico determinístico del SMN sobre Argentina y países vecinos, 4 corridas "
                   "diarias hasta +72 h, horario. Sólo variables de superficie. Cada hora es un "
                   "NetCDF de ~38 MB que se convierte a GRIB2 lat/lon recortado a la zona.")
    params = [
        Param("resolucion", "Resolución de salida", "choice", "0.04",
              choices=[("0.04", "0,04° (≈ 4 km, la del modelo)"), ("0.08", "0,08°"),
                       ("0.10", "0,10°"), ("0.25", "0,25°")]),
    ]
    variables = SMN_VARIABLES
    default_variables = ["viento10", "T2"]
    levels = []
    cycles = [0, 6, 12, 18]
    availability_lag_h = 4.0
    region_filter = "local"
    default_region = SMN_DOMAIN

    def steps(self, params=None, cycle=None):
        return list(range(0, 73))

    def default_basename(self, job):
        return f"smn_wrf_{job.run_date:%Y%m%d}_{job.cycle:02d}z"

    def build_requests(self, job, step):
        url = (f"{SMN_BASE}/{job.run_date:%Y/%m/%d}/{job.cycle:02d}/"
               f"WRFDETAR_01H_{job.run_date:%Y%m%d}_{job.cycle:02d}_{step:03d}.nc")
        return [Request(url, expect="netcdf")]

    def postprocess_step(self, data, job, step=None):
        p = self.merged_params(job.params)
        return smn_wrf_to_grib(data, region=job.region, res_deg=float(p["resolucion"]),
                               variables=tuple(job.variables))
