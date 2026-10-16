# -*- coding: utf-8 -*-
"""Tabla de niveles de vuelo (FL) del generador WAFS del servidor: la única
fuente de verdad del visor para pasar de FL a presión y al revés.

Para cada FL (F050…F600 cada 1000 ft) hay dos columnas:

* ``ISA_Pa``: la presión ISA exacta en Pa (lista oficial de NOAA, repo
  NOAA-EMC/wafs). El dato de viento y temperatura de un nivel corresponde
  **siempre** a esta presión: ahí se interpola.
* ``OACI56_hPa``: la etiqueta nominal en hPa. Es lo que se graba en el GRIB
  en los modos nominales y lo que reconoce cada consumidor (el FDP, etc.).

La tabla está copiada literal; no se recalcula con la fórmula ISA.

Cuatro modos de etiquetado (``MODES``):

* ``INDRA``  : las 14 filas de ``INDRA14``, etiqueta nominal. El FDP.
* ``OACI``   : las 16 filas de ``OACI16`` (Anexo 3), etiqueta nominal.
* ``OACI56`` : las 56 filas, etiqueta nominal. Por defecto.
* ``WAFS``   : las 56 filas, etiqueta = ISA_Pa (como codifica NOAA).

Sin Qt: lo usan el formato WAFS, el lector, el panel y los tests.
"""

# FL: (ISA_Pa, OACI56_hPa) — copiar literal, no recalcular
FL_TABLE = {
    50: (84310, 850), 60: (81200, 800), 70: (78190, 775), 80: (75260, 750),
    90: (72430, 725), 100: (69680, 700), 110: (67020, 675), 120: (64440, 650),
    130: (61940, 625), 140: (59520, 600), 150: (57180, 575), 160: (54920, 550),
    170: (52720, 525), 180: (50600, 500), 190: (48550, 485), 200: (46560, 465),
    210: (44650, 450), 220: (42790, 425), 230: (41000, 410), 240: (39270, 400),
    250: (37600, 375), 260: (35990, 360), 270: (34430, 350), 280: (32930, 330),
    290: (31490, 315), 300: (30090, 300), 310: (28740, 285), 320: (27450, 275),
    330: (26200, 260), 340: (25000, 250), 350: (23840, 240), 360: (22730, 225),
    370: (21660, 215), 380: (20650, 205), 390: (19680, 200), 400: (18750, 190),
    410: (17870, 175), 420: (17040, 170), 430: (16240, 160), 440: (15470, 155),
    450: (14750, 150), 460: (14060, 140), 470: (13400, 135), 480: (12770, 125),
    490: (12170, 120), 500: (11600, 115), 510: (11050, 110), 520: (10530, 105),
    530: (10040, 100), 540: (9570, 95), 550: (9120, 90), 560: (8700, 85),
    570: (8280, 80), 580: (7900, 70), 590: (7520, 65), 600: (7170, 60),
}
FLS = sorted(FL_TABLE)
FL_STEP = 10
FL_LOWEST, FL_HIGHEST = FLS[0], FLS[-1]

OACI16 = [50, 80, 100, 140, 180, 240, 270, 300, 320, 340, 360, 390, 410, 450, 480, 530]
INDRA14 = [fl for fl in OACI16 if fl not in (80, 480)]

MODES = ["INDRA", "OACI", "OACI56", "WAFS"]
MODE_LABELS = {
    "INDRA": "INDRA (14 FL del FDP, etiqueta nominal hPa)",
    "OACI": "OACI (16 FL del Anexo 3, etiqueta nominal hPa)",
    "OACI56": "OACI56 (56 FL, etiqueta nominal hPa)",
    "WAFS": "WAFS (56 FL, etiqueta = presión ISA en Pa, como NOAA)",
}
DEFAULT_MODE = "OACI56"
ISA_TOL_PA = 10         # tolerancia al reconocer la columna ISA (Pa): NOAA redondea a 0,1 hPa

_ISA_TO_FL = {pa: fl for fl, (pa, _h) in FL_TABLE.items()}
_NOMINAL_TO_FL = {h * 100: fl for fl, (_pa, h) in FL_TABLE.items()}


def mode_fls(mode):
    """FL que abarca un modo, ascendentes."""
    mode = normalize_mode(mode)
    if mode == "INDRA":
        return list(INDRA14)
    if mode == "OACI":
        return list(OACI16)
    return list(FLS)


def normalize_mode(mode):
    m = str(mode or DEFAULT_MODE).strip().upper()
    if m not in MODES:
        raise ValueError(f"modo de etiquetado desconocido: {mode!r} (válidos: {', '.join(MODES)})")
    return m


def isa_pa(fl):
    """Presión ISA exacta (Pa, entero) del FL según la tabla."""
    return FL_TABLE[int(fl)][0]


def nominal_hpa(fl):
    """Etiqueta nominal OACI56 (hPa, entero) del FL."""
    return FL_TABLE[int(fl)][1]


def label_pa(fl, mode=DEFAULT_MODE):
    """Presión (Pa) que se graba en el GRIB para el FL en el modo dado."""
    return isa_pa(fl) if normalize_mode(mode) == "WAFS" else nominal_hpa(fl) * 100


def label_text(fl, mode=DEFAULT_MODE):
    """'850 hPa' en los modos nominales, '84310 Pa' en WAFS."""
    return f"{isa_pa(fl)} Pa" if normalize_mode(mode) == "WAFS" else f"{nominal_hpa(fl)} hPa"


def fl_from_pa(pa, tol=ISA_TOL_PA):
    """(FL, columna) para una presión de nivel en Pa: primero la columna
    ISA_Pa ('isa'), después OACI56_hPa×100 ('nominal'); (None, None) si no
    está en ninguna. 25000 Pa es F340 por las dos columnas."""
    if pa is None:
        return None, None
    p = int(round(float(pa)))
    for cand in range(p - tol, p + tol + 1):
        fl = _ISA_TO_FL.get(cand)
        if fl is not None:
            return fl, "isa"
    for cand in range(p - tol, p + tol + 1):
        fl = _NOMINAL_TO_FL.get(cand)
        if fl is not None:
            return fl, "nominal"
    return None, None


def classify(pas):
    """Qué modo explica todos los niveles de un archivo.

    `pas`: presiones de nivel en Pa (una por nivel distinto). Devuelve un dict:
      mode          'WAFS' | 'INDRA' | 'OACI' | 'OACI56' | None (ninguno los explica)
      labeled       True si el archivo cuenta como etiquetado por FL: todos
                    los niveles explicados y, en los modos nominales, al
                    menos los 14 FL de INDRA presentes (un GFS crudo con
                    850/700/500/250/100 hPa coincide con nominales y no
                    debe tomarse por FL)
      fls           {pa: fl} de los niveles reconocidos
      unrecognized  [pa] de los que no están en ninguna columna
    """
    pas = sorted({int(round(float(p))) for p in pas if p is not None})
    out = {"mode": None, "labeled": False, "fls": {}, "unrecognized": [], "column": None}
    if not pas:
        return out
    isa = {}
    nominal = {}
    for p in pas:
        fl, col = fl_from_pa(p)
        if fl is None:
            out["unrecognized"].append(p)
        elif col == "isa":
            isa[p] = fl
        else:
            nominal[p] = fl
    if out["unrecognized"]:
        out["fls"] = {**isa, **nominal}
        return out
    if len(isa) == len(pas):
        out.update({"mode": "WAFS", "column": "isa", "fls": isa,
                    "labeled": set(isa.values()) != {340}})
        return out
    # Mezcla o todo nominal: por la columna nominal (25000 Pa es F340 en ambas)
    fls = {}
    for p in pas:
        fl, col = fl_from_pa(p)
        if col == "isa" and p in _NOMINAL_TO_FL:
            fl = _NOMINAL_TO_FL[p]
        elif col == "isa":
            # ISA pura mezclada con nominales: no la explica un solo modo
            out["fls"] = {**isa, **nominal}
            return out
        fls[p] = fl
    s = set(fls.values())
    if s <= set(INDRA14):
        mode = "INDRA"
    elif s <= set(OACI16):
        mode = "OACI"
    else:
        mode = "OACI56"
    out.update({"mode": mode, "column": "nominal", "fls": fls,
                "labeled": set(INDRA14) <= s})
    return out


def table_rows(mode=DEFAULT_MODE):
    """[(fl, ISA_Pa, etiqueta_Pa, texto)] del modo, para «Ver tabla»."""
    mode = normalize_mode(mode)
    return [(fl, isa_pa(fl), label_pa(fl, mode), label_text(fl, mode)) for fl in mode_fls(mode)]


def fl_label(fl):
    return f"FL{int(fl):03d}"
