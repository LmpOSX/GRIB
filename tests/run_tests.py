# -*- coding: utf-8 -*-
"""Corre toda la suite, equivalente a
`python -m unittest discover -s tests -p "test_*.py"`, cargando antes pyproj.

En Linux, si pyproj (PROJ con sus propias libcurl, libtiff y libsqlite3) se
carga después de PyQt6 o de ecCodes, la finalización del intérprete aborta
con un error de glibc («corrupted size vs. prev_size») *después* de que la
suite terminó en OK, y el código de salida 134 tiraba abajo la CI. Con
`python -m unittest` el orden lo decide el primer test que importe cada cosa.

    QT_QPA_PLATFORM=offscreen python tests/run_tests.py [patrón]
"""
import os
import sys
import unittest

try:
    import pyproj  # noqa: F401
except ImportError:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))


def main():
    pattern = sys.argv[1] if len(sys.argv) > 1 else "test_*.py"
    suite = unittest.defaultTestLoader.discover(HERE, pattern=pattern)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
