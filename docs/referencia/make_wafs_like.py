"""Genera un GRIB2 'tipo WAFS' (niveles de vuelo codificados como presión ISA en Pa,
cada 1000 ft) a partir de un GRIB2 GFS en niveles de presión. Uso:
   python make_wafs_like.py entrada.grib2 salida.grib2 [FLmin FLmax]
"""
import sys, math, numpy as np, eccodes as ec

def isa_pa(fl):
    h = fl*100*0.3048  # m
    if h <= 11000: return 101325*(1-2.25577e-5*h)**5.25588
    return 22632.06*math.exp(-(h-11000)/6341.62)

src, dst = sys.argv[1], sys.argv[2]
flmin, flmax = (int(sys.argv[3]), int(sys.argv[4])) if len(sys.argv) > 4 else (50, 530)

# 1) leer todo, agrupado por (step, var)
fields, tmpl = {}, {}
with open(src,'rb') as f:
    while (g := ec.codes_grib_new_from_file(f)) is not None:
        k = (ec.codes_get(g,'stepRange'), ec.codes_get(g,'shortName'))
        lev = ec.codes_get(g,'level')  # hPa
        fields.setdefault(k, {})[lev] = ec.codes_get_values(g)
        if k not in tmpl: tmpl[k] = ec.codes_clone(g)
        ec.codes_release(g)

# 2) interpolar en ln(p) a cada FL y escribir
fls = list(range(flmin, flmax+1, 10))
n = 0
with open(dst,'wb') as out:
    for (step, var), levs in fields.items():
        p = np.array(sorted(levs))              # hPa ascendente
        lnp = np.log(p)
        data = np.stack([levs[x] for x in p])   # (nlev, npts)
        for fl in fls:
            pa = isa_pa(fl); lp = math.log(pa/100.0)
            if lp < lnp[0] or lp > lnp[-1]: continue   # fuera del rango disponible
            j = np.searchsorted(lnp, lp); j = min(max(j,1), len(p)-1)
            w = (lp - lnp[j-1])/(lnp[j]-lnp[j-1])
            vals = (1-w)*data[j-1] + w*data[j]
            g = ec.codes_clone(tmpl[(step,var)])
            ec.codes_set(g,'typeOfFirstFixedSurface',100)
            ec.codes_set(g,'scaleFactorOfFirstFixedSurface',0)
            ec.codes_set(g,'scaledValueOfFirstFixedSurface',int(round(pa/10)*10))  # Pa redondeado a 0.1 hPa, como NCEP (ej. 10040=FL530)
            ec.codes_set_values(g, vals)
            ec.codes_write(g, out); ec.codes_release(g); n += 1
print(f"{n} mensajes escritos en {dst}; FL{fls[0]:03d}-FL{fls[-1]:03d}")
