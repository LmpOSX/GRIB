#!/usr/bin/env python3
"""
gfs_to_wafs.py - Convierte GRIB2 GFS en niveles de presion (lat/lon regular,
tipicamente 0.25 grados) a un GRIB2 "tipo WAFS":
   * recortado a una caja lat/lon,
   * llevado a la resolucion de salida (ej. 1 grado) por submuestreo (default)
     o por promedio de area (--metodo average, actua como filtro pasabajos),
   * en niveles de vuelo, con cuatro tablas posibles (--niveles):
       indra (14 FL), oaci (17 FL, DEFAULT), oaci56 (56 FL, etiquetas redondeadas
       unicas) y wafs (56 FL, etiqueta = presion ISA exacta, como NOAA).
     Ver el bloque TABLAS DE NIVELES DE VUELO mas abajo. En todos los casos el
     dato se interpola a la presion ISA exacta del FL; cambia solo la etiqueta.
   Con --tabla imprime la tabla del modo elegido y sale.

Uso:
  gfs_to_wafs.py ENTRADA SALIDA --bbox LAT_S LAT_N LON_W LON_E --res 1
                 [--niveles indra|oaci|oaci56|wafs] [--metodo subsample|average]
                 [--flmin 50] [--flmax 600] [--idx]
Requiere: eccodes, numpy  (pip install -r requirements.txt)
"""
import sys, math, argparse
import numpy as np
import eccodes as ec

RH_FLMAX = 180                                   # WAFS lleva humedad solo hasta FL180
NOMBRE_NCEP = {"t": "TMP", "u": "UGRD", "v": "VGRD", "gh": "HGT", "r": "RH"}

# =============================================================================
# TABLAS DE NIVELES DE VUELO  (--niveles)
#
# En todas, el DATO se interpola a la presion ISA exacta del FL (columna ISA).
# Lo que cambia es la ETIQUETA de nivel que se graba en el GRIB, porque cada
# consumidor reconoce los niveles de una manera distinta:
#   indra  : 14 FL, etiqueta = nominal OACI. Los 14 botones del FDP.
#   oaci   : 17 FL, etiqueta = nominal OACI (Anexo 3, Ap. 2, 1.2.2) = indra + F080 + F210 + F480.
#   oaci56 : 56 FL cada 1000 ft, etiqueta redondeada y UNICA (regla: los 17 OACI
#            conservan su nominal; el resto al multiplo de 25 mas cercano si esta
#            libre; si colisiona, al multiplo de 5 -no de 25- mas cercano y libre).
#   wafs   : 56 FL cada 1000 ft, etiqueta = ISA exacta, como codifica NOAA.
#
# Columnas:  FL : (ISA_Pa, OACI56_hPa)     ISA_Pa = lista oficial de NOAA
#            (scripts/exwafs_upp.sh del repo NOAA-EMC/wafs), redondeada a 10 Pa.
# =============================================================================
TABLA = {
    #  FL    ISA Pa   OACI56      regla OACI56          en INDRA  en OACI
    50:  (84310,  850),   # OACI  850                 si        si
    60:  (81200,  800),   # x25
    70:  (78190,  775),   # x25
    80:  (75260,  750),   # OACI  750                 -         si
    90:  (72430,  725),   # x25
    100: (69680,  700),   # OACI  700                 si        si
    110: (67020,  675),   # x25
    120: (64440,  650),   # x25
    130: (61940,  625),   # x25
    140: (59520,  600),   # OACI  600                 si        si
    150: (57180,  575),   # x25
    160: (54920,  550),   # x25
    170: (52720,  525),   # x25
    180: (50600,  500),   # OACI  500                 si        si
    190: (48550,  485),   # x5   (475 colisionaba con F200)
    200: (46560,  465),   # x5   (475 colisionaba con F190)
    210: (44650,  450),   # OACI  450                 -         si
    220: (42790,  425),   # x25
    230: (41000,  410),   # x5   (400 es F240)
    240: (39270,  400),   # OACI  400                 si        si
    250: (37600,  375),   # x25
    260: (35990,  360),   # x5   (350 es F270)
    270: (34430,  350),   # OACI  350                 si        si
    280: (32930,  330),   # x5   (325 colisionaba con F290)
    290: (31490,  315),   # x5   (325 colisionaba con F280)
    300: (30090,  300),   # OACI  300                 si        si
    310: (28740,  285),   # x5   (275 es F320)
    320: (27450,  275),   # OACI  275                 si        si
    330: (26200,  260),   # x5   (250 es F340)
    340: (25000,  250),   # OACI  250                 si        si
    350: (23840,  240),   # x5   (250 es F340)
    360: (22730,  225),   # OACI  225                 si        si
    370: (21660,  215),   # x5   (225 es F360)
    380: (20650,  205),   # x5   (200 es F390)
    390: (19680,  200),   # OACI  200                 si        si
    400: (18750,  190),   # x5   (200 es F390; 187.5 -> 190)
    410: (17870,  175),   # OACI  175                 si        si
    420: (17040,  170),   # x5   (175 es F410)
    430: (16240,  160),   # x5   (150 es F450)
    440: (15470,  155),   # x5   (150 es F450)
    450: (14750,  150),   # OACI  150                 si        si
    460: (14060,  140),   # x5   (150 es F450)
    470: (13400,  135),   # x5   (125 es F480)
    480: (12770,  125),   # OACI  125                 -         si
    490: (12170,  120),   # x5   (125 es F480)
    500: (11600,  115),   # x5   (125 es F480)
    510: (11050,  110),   # x5   (100 es F530)
    520: (10530,  105),   # x5   (100 es F530)
    530: (10040,  100),   # OACI  100                 si        si
    540: ( 9570,   95),   # x5   (100 es F530)
    550: ( 9120,   90),   # x5   (100 es F530)
    560: ( 8700,   85),   # x5   (75 es multiplo de 25)
    570: ( 8280,   80),   # x5
    580: ( 7900,   70),   # x5   (75 prohibido, 80 ocupado por F570)
    590: ( 7520,   65),   # x5   (75 prohibido, 70 ocupado)
    600: ( 7170,   60),   # x5   (75 prohibido, 65 ocupado)
}
OACI17_FL = (50, 80, 100, 140, 180, 210, 240, 270, 300, 320, 340, 360, 390, 410, 450, 480, 530)
INDRA14_FL = tuple(fl for fl in OACI17_FL if fl not in (80, 210, 480))

# Fin de la cabecera de tablas -------------------------------------------------

def isa_pa(fl):
    """Presion ISA (Pa) de un FL de la tabla (la lista de NOAA)."""
    return float(TABLA[fl][0])


def niveles_salida(modo, flmin, flmax):
    """Lista de (FL, Pa_interpolacion, Pa_etiqueta) para el modo pedido."""
    fls = {"indra": INDRA14_FL, "oaci": OACI17_FL,
           "oaci56": tuple(TABLA), "wafs": tuple(TABLA)}[modo]
    out = []
    for fl in fls:
        if flmin <= fl <= flmax:
            pa_isa, hpa56 = TABLA[fl]
            etiqueta = pa_isa if modo == "wafs" else hpa56 * 100
            out.append((fl, float(pa_isa), float(etiqueta)))
    return out


# ----------------------------------------------------------------------------
# Lectura: devuelve {(plazo, variable): {nivel_hPa: campo2D}}, la grilla y un
# mensaje plantilla por (plazo, variable) para escribir la salida
# ----------------------------------------------------------------------------
def leer(ruta):
    campos, plantillas, grilla = {}, {}, None
    with open(ruta, "rb") as f:
        while (g := ec.codes_grib_new_from_file(f)) is not None:
            if ec.codes_get_long(g, "typeOfFirstFixedSurface") != 100:   # solo isobaricos
                ec.codes_release(g); continue
            if grilla is None:
                grilla = grilla_de(g)
            k = (ec.codes_get(g, "stepRange"), ec.codes_get(g, "shortName"))
            campos.setdefault(k, {})[ec.codes_get(g, "level")] = \
                ec.codes_get_values(g).reshape(grilla["nj"], grilla["ni"])
            if k not in plantillas:
                plantillas[k] = ec.codes_clone(g)
            ec.codes_release(g)
    return campos, plantillas, grilla


def grilla_de(g):
    """Vectores de latitud y longitud de una grilla lat/lon regular."""
    ni, nj = ec.codes_get(g, "Ni"), ec.codes_get(g, "Nj")
    lat1 = ec.codes_get(g, "latitudeOfFirstGridPointInDegrees")
    lon1 = ec.codes_get(g, "longitudeOfFirstGridPointInDegrees")
    di = ec.codes_get(g, "iDirectionIncrementInDegrees")
    dj = ec.codes_get(g, "jDirectionIncrementInDegrees")
    if not ec.codes_get(g, "jScansPositively"):
        dj = -dj                                               # filas de norte a sur
    return {"ni": ni, "nj": nj,
            "lats": lat1 + dj * np.arange(nj),
            "lons": lon1 + di * np.arange(ni)}                 # pueden estar en 0..360


# ----------------------------------------------------------------------------
# Matriz de remuestreo 1D (destino x origen). Se aplica como W_lat @ campo @ W_lon.T
#   "subsample": para cada punto destino toma el punto origen mas cercano
#                (con grillas alineadas, 0.25 -> 1, es exactamente el mismo punto;
#                 se descartan los demas; es lo que hace wgrib2 por defecto)
#   "average"  : promedio de los puntos origen dentro de +-res/2 (peso 0.5 en el
#                borde = regla trapezoidal); equivale al "budget" de wgrib2 y
#                actua como filtro pasabajos antes de decimar
# Si el origen ya tiene la resolucion destino, ambas dan la identidad.
# ----------------------------------------------------------------------------
def matriz_remuestreo(origen, destino, res, metodo):
    W = np.zeros((len(destino), len(origen)))
    for i, c in enumerate(destino):
        d = np.abs(origen - c)
        if metodo == "subsample":
            j = int(np.argmin(d))
            if d[j] > res / 2 + 1e-6:
                raise SystemExit("ERROR: la caja pedida no esta cubierta por los datos de entrada")
            W[i, j] = 1.0
        else:
            W[i] = np.where(d < res / 2 - 1e-6, 1.0, np.where(d < res / 2 + 1e-6, 0.5, 0.0))
    suma = W.sum(axis=1, keepdims=True)
    if (suma == 0).any():
        raise SystemExit("ERROR: la caja pedida no esta cubierta por los datos de entrada")
    return W / suma


# ----------------------------------------------------------------------------
# Escritura de un mensaje con la nueva grilla y nivel
# ----------------------------------------------------------------------------
def escribir(plantilla, valores, pa, lats_out, lons_out, res, out):
    g = ec.codes_clone(plantilla)
    ec.codes_set(g, "packingType", "grid_simple")
    ec.codes_set(g, "Ni", len(lons_out)); ec.codes_set(g, "Nj", len(lats_out))
    ec.codes_set(g, "latitudeOfFirstGridPointInDegrees", float(lats_out[0]))
    ec.codes_set(g, "latitudeOfLastGridPointInDegrees", float(lats_out[-1]))
    ec.codes_set(g, "longitudeOfFirstGridPointInDegrees", float(lons_out[0] % 360))
    ec.codes_set(g, "longitudeOfLastGridPointInDegrees", float(lons_out[-1] % 360))
    ec.codes_set(g, "iDirectionIncrementInDegrees", float(res))
    ec.codes_set(g, "jDirectionIncrementInDegrees", float(res))
    ec.codes_set(g, "jScansPositively", 0); ec.codes_set(g, "iScansNegatively", 0)
    ec.codes_set(g, "typeOfFirstFixedSurface", 100)            # isobarico
    ec.codes_set(g, "scaleFactorOfFirstFixedSurface", 0)
    ec.codes_set(g, "scaledValueOfFirstFixedSurface", int(round(pa / 10.0) * 10))  # Pa a 0.1 hPa
    try:
        ec.codes_set(g, "tablesVersion", 25)                   # como el WAFS de NCEP
    except Exception:
        pass
    ec.codes_set(g, "bitsPerValue", 16)
    ec.codes_set_values(g, valores.ravel())
    ec.codes_write(g, out)
    ec.codes_release(g)


# ----------------------------------------------------------------------------
# Inventario .idx (formato NOMADS: n:offset:d=YYYYMMDDHH:VAR:NIVEL:plazo:) de un
# GRIB2 ya escrito. Se usa para el archivo unico, que es una concatenacion.
# ----------------------------------------------------------------------------
def escribir_idx(ruta):
    lineas, n = [], 0
    with open(ruta, "rb") as f:
        while True:
            offset = f.tell()
            g = ec.codes_grib_new_from_file(f)
            if g is None:
                break
            n += 1
            var = ec.codes_get(g, "shortName")
            lineas.append(f"{n}:{offset}:d={ec.codes_get(g,'dataDate')}{ec.codes_get(g,'dataTime')//100:02d}:"
                          f"{NOMBRE_NCEP.get(var, var.upper())}:{ec.codes_get(g,'scaledValueOfFirstFixedSurface')/100:g} mb:"
                          f"{ec.codes_get(g,'stepRange')} hour fcst:")
            ec.codes_release(g)
    with open(ruta + ".idx", "w") as f:
        f.write("\n".join(lineas) + "\n")


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--solo-idx":      # modo: solo generar el .idx
        escribir_idx(sys.argv[2]); return 0
    ap = argparse.ArgumentParser()
    ap.add_argument("entrada", nargs="?"); ap.add_argument("salida", nargs="?")
    ap.add_argument("--bbox", nargs=4, type=float, metavar=("LAT_S", "LAT_N", "LON_W", "LON_E"))
    ap.add_argument("--res", type=float, default=1.0, help="resolucion de salida en grados")
    ap.add_argument("--metodo", choices=["subsample", "average"], default="subsample",
                    help="como pasar de la resolucion de entrada a la de salida (default subsample)")
    ap.add_argument("--flmin", type=int, default=50); ap.add_argument("--flmax", type=int, default=600)
    ap.add_argument("--niveles", choices=["indra", "oaci", "oaci56", "wafs"], default="oaci",
                    help="tabla de niveles de vuelo y forma de etiquetarlos (ver cabecera del archivo)")
    ap.add_argument("--tabla", action="store_true", help="imprimir la tabla del modo elegido y salir")
    ap.add_argument("--idx", action="store_true", help="escribir inventario .idx junto a la salida")
    a = ap.parse_args()
    if a.tabla:
        print(f"{'FL':>4} {'ISA hPa':>8} {'etiqueta':>9}")
        for fl, pa, pe in niveles_salida(a.niveles, a.flmin, a.flmax):
            print(f"{fl:04d} {pa/100:8.1f} {pe/100:9.1f}")
        return 0
    if not (a.entrada and a.salida and a.bbox):
        ap.error("se requieren ENTRADA, SALIDA y --bbox")
    lat_s, lat_n, lon_w, lon_e = a.bbox

    campos, plantillas, grilla = leer(a.entrada)
    if not campos:
        raise SystemExit("ERROR: la entrada no tiene mensajes en niveles de presion")

    # --- grilla de salida y matrices de promedio ------------------------------
    lats_out = np.arange(lat_n, lat_s - 1e-6, -a.res)          # de norte a sur
    lons_out = np.arange(lon_w, lon_e + 1e-6, a.res)           # de oeste a este
    # longitudes de entrada (pueden venir en 0..360) llevadas a +-180 alrededor de la caja
    lons_in = (grilla["lons"] - (lon_w - 180)) % 360 + (lon_w - 180)
    W_lat = matriz_remuestreo(grilla["lats"], lats_out, a.res, a.metodo)
    W_lon = matriz_remuestreo(lons_in, lons_out, a.res, a.metodo)

    # --- niveles de vuelo: lista de (FL, Pa para interpolar, Pa para etiquetar) ---
    niveles_fl = niveles_salida(a.niveles, a.flmin, a.flmax)
    fls = [fl for fl, _, _ in niveles_fl]
    n = 0
    with open(a.salida, "wb") as out:
        for (plazo, var), niveles in campos.items():
            p = np.array(sorted(niveles), dtype=float)          # hPa ascendente
            lnp = np.log(p)
            # recortar + remuestrear cada nivel una sola vez: (nlev, nlat_out, nlon_out)
            datos = np.stack([W_lat @ niveles[x] @ W_lon.T for x in p])
            for fl, pa, pa_etiqueta in niveles_fl:
                if var in ("r", "rh") and fl > RH_FLMAX:
                    continue
                lp = math.log(pa / 100.0)
                if lp < lnp[0] or lp > lnp[-1]:
                    continue                                   # FL fuera de los niveles disponibles
                j = int(np.clip(np.searchsorted(lnp, lp), 1, len(p) - 1))
                w = (lp - lnp[j - 1]) / (lnp[j] - lnp[j - 1])  # interpolacion lineal en ln(p)
                valores = (1.0 - w) * datos[j - 1] + w * datos[j]
                escribir(plantillas[(plazo, var)], valores, pa_etiqueta, lats_out, lons_out, a.res, out)
                n += 1
    if a.idx:
        escribir_idx(a.salida)
    print(f"{a.salida}: {n} mensajes, {len(lats_out)}x{len(lons_out)} puntos a {a.res:g} grados ({a.metodo}), "
          f"{len(fls)} niveles FL{fls[0]:03d}-FL{fls[-1]:03d} ({a.niveles})")
    return 0 if n else 1


if __name__ == "__main__":
    sys.exit(main())
