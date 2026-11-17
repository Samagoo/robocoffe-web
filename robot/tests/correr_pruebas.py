"""Corre tests/test_fsm.py sin pytest (por si no esta instalado).

    python tests/correr_pruebas.py
Con pytest instalado, lo normal es:  python -m pytest -q tests
"""
import os
import sys
import traceback
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import pytest  # noqa: F401
except ImportError:                                   # mini sustituto: parametrize + approx
    pytest = types.ModuleType("pytest")

    class _Mark:
        @staticmethod
        def parametrize(nombres, valores):
            def deco(f):
                f._params = ([n.strip() for n in nombres.split(",")], valores)
                return f
            return deco

    class _Approx:
        def __init__(self, v, abs=1e-6):
            self.v, self.tol = v, abs

        def __eq__(self, otro):
            return abs(otro - self.v) <= self.tol

    pytest.mark = _Mark()
    pytest.approx = _Approx
    sys.modules["pytest"] = pytest

import test_fsm  # noqa: E402

fallas, total = 0, 0
for nombre in sorted(n for n in dir(test_fsm) if n.startswith("test_")):
    f = getattr(test_fsm, nombre)
    params = getattr(f, "_params", None)
    for m in getattr(f, "pytestmark", []):              # pytest real instalado
        if m.name == "parametrize":
            params = ([n.strip() for n in m.args[0].split(",")], m.args[1])
    casos = [dict(zip(params[0], v)) for v in params[1]] if params else [{}]
    for kw in casos:
        total += 1
        etiqueta = nombre + (f"[{list(kw.values())[0]}]" if kw else "")
        try:
            f(**kw)
            print(f"PASA   {etiqueta}")
        except Exception:
            fallas += 1
            print(f"FALLA  {etiqueta}")
            traceback.print_exc(limit=3)
print(f"\n{total - fallas}/{total} pruebas pasan")
sys.exit(1 if fallas else 0)
