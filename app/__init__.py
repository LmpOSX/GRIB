__version__ = "0.5.4"

# Ver main.py: pyproj antes que PyQt6 y ecCodes (orden de carga en Linux).
# Cubre a quien importe `app` primero (CLI de wafs_format, fir_aip, tests).
try:
    import pyproj  # noqa: F401
except ImportError:
    pass
