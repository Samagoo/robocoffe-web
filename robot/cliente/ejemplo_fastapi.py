"""Ejemplo de backend FastAPI conectado al robot. Punto de partida para la plataforma web.

    pip install fastapi uvicorn
    python servidor_simulado.py --entrega 180          (terminal 1: robot simulado; o main_real.py)
    uvicorn ejemplo_fastapi:app --reload --port 8000   (terminal 2, dentro de la carpeta cliente/)
    abre http://127.0.0.1:8000/docs                    (prueba los endpoints desde el navegador)

Variables de entorno: ROBOT_HOST (default 127.0.0.1), ROBOT_PUERTO (default 9000).

Los pedidos viven en un dict en memoria para que el ejemplo sea corto: cambienlo por su base de
datos (SQLModel). Lo importante es DONDE se llama al robot y QUE se guarda en cada paso:

    POST /pedidos                 cliente pide       -> Folio, HoraPedido, Producto, Mesa
    POST /pedidos/{folio}/listo   barista termina    -> HoraListo
    POST /pedidos/{folio}/enviar  barista carga vaso -> HoraInicioCarga, PesoCarga_g; el robot sale
    POST /robot/retirado          cliente toma vaso  -> HoraEntrega, PesoEntrega_g; el robot regresa
    (automatico)                  robot en la base   -> HoraRegresoBase, Incidencia
    WS   /ws                      la pagina recibe estado del robot y de cada pedido en vivo
"""
import asyncio
import datetime as dt
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from robocoffe_cliente import ClienteRobot, SeguimientoPedidos

PRODUCTOS = {"C1": "americano", "C2": "latte", "C3": "frappe"}
DISTANCIA_M = {1: 1.0, 2: 2.0, 3: 3.0}            # <POR MEDIR> con cinta, igual que registro_pruebas.py

pedidos = {}                                       # folio -> dict con las columnas de la hoja «Pedidos»
sockets = set()                                    # WebSockets abiertos


def ahora():
    return dt.datetime.now().replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


async def difundir(msg):
    for ws in list(sockets):
        try:
            await ws.send_json(msg)
        except Exception:
            sockets.discard(ws)


def al_cambiar(viaje):
    """Cada cambio del viaje del robot se copia al pedido y se manda a las paginas abiertas."""
    p = pedidos.get(viaje.folio)
    if p is not None:
        v = viaje.como_dict()
        p["EstadoRobot"] = viaje.estado
        p["Detalle"] = viaje.detalle
        p["HoraLlegadaMesa"] = v["hora_llegada_mesa"]       # extra, util para el aviso al cliente
        if v["hora_entrega"] and not p.get("HoraEntrega"):
            p["HoraEntrega"] = v["hora_entrega"]
        p["HoraRegresoBase"] = v["hora_regreso_base"]
        p["Incidencia"] = v["incidencia"]
        if viaje.estado == "EN_MESA":
            p["Estado"] = "Entregado"                       # el flujo avisa al cliente al llegar (FR-05)
        elif viaje.estado == "RECHAZADO":
            p["Estado"] = "Listo"                           # no salio: se puede volver a enviar
        elif viaje.estado == "FALLA":
            p["Estado"] = "Falla"
        elif viaje.estado == "CERRADO":
            p["Estado"] = "Cancelado" if viaje.motivo_regreso == "cancelado" else \
                          "No entregado" if viaje.motivo_regreso == "sin_retirar" else "Cerrado"
    return difundir({"tipo": "PEDIDO", "pedido": p or viaje.como_dict()})


robot = ClienteRobot(os.getenv("ROBOT_HOST", "127.0.0.1"), int(os.getenv("ROBOT_PUERTO", "9000")))
seguimiento = SeguimientoPedidos(robot, al_cambiar)


async def reenviar_robot():
    """Todo lo que dice el robot llega a las paginas como {'tipo': 'ROBOT', 'robot': {...}}."""
    cola = robot.suscribir()
    while True:
        d = await cola.get()
        await difundir({"tipo": "ROBOT", "robot": robot.resumen(),
                        "linea": d.get("linea") if d.get("nombre") != "LATIDO" else None})


@asynccontextmanager
async def ciclo_de_vida(app):
    await seguimiento.iniciar()
    tarea = asyncio.create_task(reenviar_robot())
    yield
    tarea.cancel()
    await seguimiento.cerrar()


app = FastAPI(title="RoboCoffe - ejemplo de backend", lifespan=ciclo_de_vida)


class NuevoPedido(BaseModel):
    producto: str          # C1 | C2 | C3
    mesa: int              # 1 | 2 | 3


class Peso(BaseModel):
    peso_g: float | None = None


def pedido_o_404(folio):
    p = pedidos.get(folio)
    if p is None:
        raise HTTPException(404, f"no existe {folio}")
    return p


@app.post("/pedidos")
async def crear_pedido(d: NuevoPedido):
    if d.producto not in PRODUCTOS or d.mesa not in DISTANCIA_M:
        raise HTTPException(422, "producto C1|C2|C3 y mesa 1|2|3")
    folio = f"P-{len(pedidos) + 1:04d}"
    pedidos[folio] = {"Folio": folio, "HoraPedido": ahora(), "Producto": d.producto, "Mesa": d.mesa,
                      "Distancia_m": DISTANCIA_M[d.mesa], "Estado": "Preparando"}
    await difundir({"tipo": "PEDIDO", "pedido": pedidos[folio]})
    return pedidos[folio]


@app.get("/pedidos")
async def listar_pedidos():
    return list(pedidos.values())


@app.post("/pedidos/{folio}/listo")
async def marcar_listo(folio: str):
    p = pedido_o_404(folio)
    p["HoraListo"], p["Estado"] = ahora(), "Listo"
    await difundir({"tipo": "PEDIDO", "pedido": p})
    return p


@app.post("/pedidos/{folio}/enviar")
async def enviar(folio: str, d: Peso):
    """El barista puso el vaso en el robot. Responde 409 si el robot no puede salir (y por que)."""
    p = pedido_o_404(folio)
    if not robot.libre:
        raise HTTPException(409, f"robot no disponible: conectado={robot.conectado} estado={robot.estado}")
    p["HoraInicioCarga"], p["PesoCarga_g"] = ahora(), d.peso_g
    viaje = await seguimiento.enviar(folio, p["Mesa"])
    if viaje.estado == "RECHAZADO":
        raise HTTPException(409, f"el robot rechazo la orden: {viaje.detalle}")
    p["Estado"] = "En camino"
    return p


@app.post("/robot/retirado")
async def retirado(d: Peso):
    """El cliente tomo el vaso (boton en la app o celda de carga < 50 g)."""
    v = seguimiento.activo
    r = await seguimiento.marcar_retirado()
    if not r.ok:
        raise HTTPException(409, f"RETIRADO rechazado: {r.motivo} (solo vale con el robot EN_MESA)")
    if v is not None and v.folio in pedidos:
        pedidos[v.folio]["PesoEntrega_g"] = d.peso_g
        pedidos[v.folio]["HoraEntrega"] = ahora()
    return {"ok": True}


@app.get("/robot")
async def estado_robot():
    return robot.resumen() | {"viaje": seguimiento.activo.como_dict() if seguimiento.activo else None}


@app.post("/robot/{accion}")
async def accion_robot(accion: str):
    """pausa | reanudar | cancelar | reset"""
    fn = {"pausa": robot.pausa, "reanudar": robot.reanudar, "reset": robot.reset,
          "cancelar": seguimiento.cancelar}.get(accion)
    if fn is None:
        raise HTTPException(404, "accion: pausa | reanudar | cancelar | reset")
    r = await fn()
    if not r.ok:
        raise HTTPException(409, f"{accion} rechazado: {r.motivo}")
    return {"ok": True, "respuesta": r.campos}


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    sockets.add(websocket)
    await websocket.send_json({"tipo": "ROBOT", "robot": robot.resumen(), "linea": None})
    try:
        while True:
            await websocket.receive_text()            # la pagina no necesita mandar nada
    except WebSocketDisconnect:
        sockets.discard(websocket)
