"""La copia del paquete en el controlador de Webots debe ser identica al original."""
import filecmp
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
import sincronizar_webots as S  # noqa: E402


def test_copia_de_webots_igual_al_original():
    if not os.path.isdir(S.DESTINO):
        return                                   # repositorio sin la carpeta webots/
    distintos = [os.path.relpath(d, RAIZ) for o, d in S.pares() if not filecmp.cmp(o, d, shallow=False)]
    assert not distintos, f"Copias desactualizadas: {distintos}. Corre: python sincronizar_webots.py"
