"""Demostracion y prueba del cliente SIN FastAPI: tres pedidos contra el robot (real o simulado).

    python servidor_simulado.py --rapido 10 --entrega 60   (terminal 1, en la carpeta principal)
    python cliente/demo_seguimiento.py                (terminal 2)

Pedido 1 -> mesa 1, el cliente toma el vaso (RETIRADO)   -> CERRADO, entregado, Incidencia Ninguna
Pedido 2 -> mesa 2, nadie toma el vaso                   -> CERRADO, sin_retirar, Incidencia Vaso
Pedido 3 -> mesa 3, se cancela a medio camino            -> CERRADO, cancelado
Ademas: un pedido mandado con el robot ocupado se RECHAZA sin tocar el robot.
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from robocoffe_cliente import ClienteRobot, SeguimientoPedidos  # noqa: E402


async def esperar(cond, limite=180.0):
    t = 0.0
    while not cond() and t < limite:
        await asyncio.sleep(0.1)
        t += 0.1
    if not cond():
        raise TimeoutError("no se cumplio a tiempo")


async def main(host, puerto):
    cambios = []

    def al_cambiar(v):
        cambios.append(v.como_dict())
        print(f"  [{v.folio}] {v.estado:<10} {v.detalle}")

    robot = ClienteRobot(host, puerto)
    seg = SeguimientoPedidos(robot, al_cambiar)
    await seg.iniciar()
    await esperar(lambda: robot.libre, 20)
    print(f"Robot conectado y libre: {robot.resumen()}")

    print("\nPedido 1: mesa 1, el cliente toma el vaso")
    v1 = await seg.enviar("P-0001", 1)
    otro = await seg.enviar("P-0099", 3)                       # robot ocupado
    assert otro.estado == "RECHAZADO", otro
    await esperar(lambda: v1.estado == "EN_MESA")
    await asyncio.sleep(1.0)
    r = await seg.marcar_retirado()
    assert r.ok, r
    await esperar(lambda: v1.estado == "CERRADO")

    print("\nPedido 2: mesa 2, nadie toma el vaso")
    v2 = await seg.enviar("P-0002", 2)
    await esperar(lambda: v2.estado == "CERRADO", 300)

    print("\nPedido 3: mesa 3, se cancela a medio camino")
    v3 = await seg.enviar("P-0003", 3)
    await esperar(lambda: robot.pose is not None and v3.estado == "EN_CAMINO")
    await asyncio.sleep(3.0)
    r = await seg.cancelar()
    assert r.ok, r
    await esperar(lambda: v3.estado == "CERRADO", 300)

    print("\nResultado:")
    for v in (v1, v2, v3):
        d = v.como_dict()
        print(f"  {d['folio']}  mesa {d['mesa']}  salida {d['hora_salida']}  llegada {d['hora_llegada_mesa']}  "
              f"entrega {d['hora_entrega']}  regreso {d['hora_regreso_base']}  {d['motivo_regreso']}  "
              f"incidencia={d['incidencia']}")
    assert (v1.motivo_regreso, v1.incidencia) == ("entregado", "Ninguna") and v1.hora_entrega
    assert (v2.motivo_regreso, v2.incidencia) == ("sin_retirar", "Vaso") and v2.hora_entrega is None
    assert v3.motivo_regreso == "cancelado" and v3.hora_llegada_mesa is None
    print("\nOK: los tres casos se comportaron como dice docs/01_guia_equipo_web.md")
    await seg.cerrar()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--puerto", type=int, default=9000)
    a = ap.parse_args()
    asyncio.run(main(a.host, a.puerto))
