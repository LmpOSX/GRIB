# grib_viewer – Visor de viento y temperatura GRIB2 (GFS)

Programa de escritorio en Python (tkinter + matplotlib + cartopy opcional) para
visualizar archivos GRIB2 con componentes de viento (UGRD/VGRD) y temperatura
(TMP) en niveles de presión, con un panel de controles al estilo de un sistema
ATC: selección de paso (Current / Next / Advanced), nivel de vuelo (F050…F530
convertido a presión ISA e interpolado en ln(p)), barbas coloreadas por
velocidad, contornos de temperatura, "Extra Info", grilla, zoom/pan y
exportación a PNG/CSV.

Todo el código está en un único archivo: `grib_viewer.py`.

## Requisitos

* Python 3.9 o superior con **tkinter**.
* `numpy`, `matplotlib`, `eccodes` (bindings Python de ecCodes).
* `cartopy` (opcional: costas y fronteras a 50 m; sin él el mapa se dibuja
  sin costas y se avisa).
* `certifi` (opcional: evita errores de certificado SSL cuando cartopy
  descarga las costas de Natural Earth por primera vez).

## Instalación en macOS

```bash
# 1) Python con tkinter (el de python.org o el de Homebrew con python-tk)
brew install python@3.12 python-tk@3.12

# 2) Entorno virtual
python3.12 -m venv venv
source venv/bin/activate
pip install --upgrade pip

# 3) Dependencias
pip install -r requirements.txt
```

Si `pip install eccodes` no encuentra la biblioteca nativa (error
"Cannot find the ecCodes library"), instalarla con Homebrew o conda:

```bash
# Opción A: Homebrew
brew install eccodes
pip install eccodes          # o: pip install --no-binary eccodes eccodes
# Si aún no la encuentra, indicar la ruta:
export ECCODES_DIR=$(brew --prefix eccodes)

# Opción B: conda / mamba (incluye cartopy, que a veces es difícil con pip)
conda create -n grib python=3.12 -c conda-forge eccodes python-eccodes \
    cartopy matplotlib numpy tk certifi
conda activate grib
```

Si al dibujar aparece un error `CERTIFICATE_VERIFY_FAILED` (Python de
python.org en macOS), instalar `certifi` (`pip install certifi`) o ejecutar
una vez `/Applications/Python 3.x/Install Certificates.command`.

## Instalación en Linux (Debian / Ubuntu)

```bash
# 1) tkinter y, opcionalmente, la biblioteca ecCodes del sistema
sudo apt update
sudo apt install python3-tk python3-venv libeccodes0 libeccodes-dev

# 2) Entorno virtual
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip

# 3) Dependencias
pip install -r requirements.txt
```

Si pip no alcanza para `eccodes` o `cartopy` (faltan ruedas para la
arquitectura o la versión de Python), usar conda:

```bash
conda create -n grib python=3.12 -c conda-forge eccodes python-eccodes \
    cartopy matplotlib numpy tk certifi
conda activate grib
```

En Fedora / RHEL: `sudo dnf install python3-tkinter eccodes eccodes-devel`.

## Uso

```bash
python grib_viewer.py                      # abre la ventana vacía
python grib_viewer.py FDP_MULTI.grib2      # abre directamente un archivo
```

Panel de la derecha:

* **Abrir GRIB...**: selecciona un archivo `*.grib2 *.grb2 *.grib *.grb`.
  Al abrirlo se muestra el inventario (corrida, pasos y validez, variables,
  niveles, grilla) en el panel INVENTARIO.
* **STATUS**: corrida, paso seleccionado, ventana de validez en UTC y en la
  hora local del sistema, nivel elegido y si fue interpolado o extrapolado
  (nivel más cercano).
* **TIME**: `Current (+0)`, `Next (+1)`, `Advanced (+2)` eligen el 1.°, 2.° y
  3.° paso del archivo. Si hay más de tres pasos aparece un combo con todos.
* **LEVEL**: botones F050…F530. El FL se convierte a presión con la atmósfera
  estándar ISA y U, V y T se interpolan linealmente en ln(p) entre los niveles
  del archivo. Si el FL cae fuera del rango de niveles se usa el nivel más
  cercano y STATUS lo indica como "extrapolado". El combo "Nivel de presión"
  permite elegir un nivel del archivo sin interpolar.
* **VARIABLE**: Viento (barbas), Temperatura (contornos cada 2 °C) o ambas.
* **CONFIG**: `Extra Info` escribe la velocidad en kt (y la temperatura en °C
  si corresponde) junto a cada barba; `Grilla` dibuja la grilla lat/lon del
  archivo; `Fondo de velocidad` rellena el mapa con la misma escala de
  colores; `Densidad` submuestrea las barbas cada N puntos; `Update` redibuja
  y `Disable`/`Enable` oculta o muestra la capa de datos. Cambiar un radio,
  un botón de nivel o un checkbox redibuja automáticamente.
* **RECUADRO**: lat/lon mín/máx para fijar la vista; `Todo el dominio`
  vuelve a la grilla completa. También funcionan el zoom y el pan de la
  barra de matplotlib.
* **Exportar PNG / CSV**: guarda la vista actual o una tabla con lat, lon,
  u, v, velocidad (kt), dirección (°) y T (°C) del nivel y paso actuales.
* Barra inferior: lat/lon, velocidad, dirección y temperatura bajo el cursor.

Escala de colores de las barbas: 0–9 kt cian, 10–19 azul, 20–29 verde,
30–39 amarillo, 40–49 naranja, ≥50 rojo.

Conversiones usadas: 1 m/s = 1.943844 kt; dirección meteorológica
= (270 − atan2(v, u)) mod 360; T(°C) = T(K) − 273.15. Las longitudes 0–360
se normalizan a −180…180 y las latitudes se reordenan de sur a norte si el
archivo viene de norte a sur.

## Verificación con wgrib2

1. Abrir el archivo: `python grib_viewer.py FDP_MULTI.grib2`.
2. Elegir **Next (+1)** (segundo paso, por ejemplo +9 h) y el nivel **F100**.
   STATUS mostrará `F100 = 696.8 hPa (ISA)` interpolado entre 700 y 600 hPa;
   al estar a sólo 3 hPa de 700, los valores son prácticamente los del nivel
   de 700 mb. Para comparar exactamente, elegir `700 hPa` en el combo
   "Nivel de presión".
3. Listar los mensajes de 700 mb del archivo con wgrib2:

   ```bash
   wgrib2 -s FDP_MULTI.grib2 | grep ":700 mb:"
   ```

   Debe aparecer, para cada paso, una línea de `UGRD`, `VGRD` y `TMP`, por
   ejemplo `...:UGRD:700 mb:9 hour fcst:`; la hora de validez y el paso
   coinciden con los que muestra STATUS.
4. Extraer el valor en un punto (por ejemplo 34°S 58°W; wgrib2 usa
   longitudes 0–360, 58°W = 302°E) y compararlo con el que muestra la barra
   de estado al pasar el cursor por ese punto o con la fila correspondiente
   del CSV exportado:

   ```bash
   wgrib2 FDP_MULTI.grib2 -match ":(UGRD|VGRD|TMP):700 mb:9 hour fcst:" -lon 302 -34
   ```

   Con u y v en m/s: velocidad (kt) = √(u²+v²) × 1.943844 y dirección
   = (270 − atan2(v,u)·180/π) mod 360; T (°C) = TMP − 273.15.
