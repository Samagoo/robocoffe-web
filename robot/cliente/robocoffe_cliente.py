"""Cliente del robot RoboCoffe para la plataforma web. Solo biblioteca estandar (asyncio).

Pensado para FastAPI (que ya corre en asyncio), pero sirve en cualquier programa asyncio.
Hace por ti lo dificil del protocolo (ver docs/02_protocolo.md):
  * mantiene UNA conexion TCP abierta al puerto 9000 y se reconecta sola cada 2 s si se cae;
  * al (re)conectarse pregunta ESTADO para no quedarse con informacion vieja;
  * genera ids crecientes (decimas de segundo desde 1970), compatibles con las demas herramientas;
  * reintenta con el MISMO id si no hay respuesta en 2 s (hasta 3 veces): el robot no duplica ordenes;
  * convierte cada linea en un dict y la reparte a quien se suscriba (WebSocket, base de datos...).

Capas:
  ClienteRobot         habla el protocolo (ordenar, cancelar, pausa, reanudar, reset, retirado, estado)
  SeguimientoPedidos   convierte los eventos del robot en el estado y las horas de CADA pedido
                       (misma logica que registro_pruebas.py, que ya genero los datos del dashboard)

Uso minimo:
    robot = ClienteRobot("127.0.0.1")           # IP de la computadora donde corre main_real.py
    await robot.iniciar()
    r = await robot.ordenar(2)                  # Respuesta(ok=True, ...) o ok=False con motivo
"""
import asyncio
import datetime as dt
import time
from dataclasses import dataclass, field

# Estados de la maquina del robot (docs/03_maquina_estados.md)
ESPERANDO_ORDEN = "ESPERANDO_ORDEN"
EN_MESA = "EN_MESA"
REGRESO_BASE = "REGRESO_BASE"
DETENIDO = "DETENIDO"
ERROR = "ERROR"


def parsear_linea(linea):
    """'EVT LLEGO t=12.3 mesa=2 orden=17' -> {'tipo': 'EVT', 'nombre': 'LLEGO', 'campos': {...}, ...}.

    tipo: OK | ERROR | EVT.  En ERROR, 'motivo' trae el codigo (OCUPADO, FUERA_DE_BASE, ...).
    Todos los valores de 'campos' son texto; '-' significa "sin valor".
    """
    tokens = linea.strip().split()
    if len(tokens) < 2 or tokens[0] not in ("OK", "ERROR", "EVT"):
        return None
    campos, libres = {}, []
    for tok in tokens[2:]:
        if "=" in tok:
            k, _, v = tok.partition("=")
            campos[k] = v
        else:
            libres.append(tok)
    d = {"tipo": tokens[0], "nombre": tokens[1], "campos": campos, "linea": linea.strip()}
    if tokens[0] == "ERROR":
        d["motivo"] = " ".join(libres)
    return d


@dataclass
class Respuesta:
    ok: bool
    cmd: str
    id: int
    campos: dict = field(default_factory=dict)
    motivo: str = ""          # si ok=False: OCUPADO, FUERA_DE_BASE, ... o SIN_RESPUESTA


class ClienteRobot:
    def __init__(self, host="127.0.0.1", puerto=9000, espera_respuesta=2.0, intentos=3):
        self.host, self.puerto = host, puerto
        self.espera_respuesta, self.intentos = espera_respuesta, intentos
        # lo ultimo que se sabe del robot
        self.estado = None            # ESPERANDO_ORDEN, RECORRIDO_MESA_2, EN_MESA, ...
        self.orden = None             # id de la orden en curso (texto) o None
        self.pose = None              # (x [m], y [m], th [deg])
        self.bateria = None           # [V] o None
        self.error = None             # codigo de error si estado == ERROR
        self.t_ultimo_mensaje = None  # time.monotonic() del ultimo mensaje recibido
        self._writer = None
        self._tarea = None
        self._pendientes = {}         # id -> Future con la respuesta
        self._colas = set()
        self._ultimo_id = 0

    # ------------------------------------------------------------ ciclo de vida
    async def iniciar(self):
        """Arranca la conexion en segundo plano (no espera a que conecte)."""
        if self._tarea is None:
            self._tarea = asyncio.create_task(self._mantener_conexion())

    async def cerrar(self):
        if self._tarea:
            self._tarea.cancel()
            try:
                await self._tarea
            except asyncio.CancelledError:
                pass
            self._tarea = None
        if self._writer:
            self._writer.close()
            self._writer = None

    @property
    def conectado(self):
        return self._writer is not None

    @property
    def libre(self):
        """True si se le puede mandar una orden ahora (esta en la base esperando)."""
        return self.conectado and self.estado == ESPERANDO_ORDEN

    def resumen(self):
        """Estado del robot listo para mandarse como JSON a la pagina."""
        return {"conectado": self.conectado, "estado": self.estado, "orden": self.orden,
                "pose": self.pose, "bateria": self.bateria, "error": self.error}

    # ------------------------------------------------------------ suscripciones
    def suscribir(self, maximo=200):
        """Cola con cada mensaje del robot (dict de parsear_linea) y avisos {'tipo': 'CONEXION', ...}."""
        q = asyncio.Queue(maximo)
        self._colas.add(q)
        return q

    def desuscribir(self, q):
        self._colas.discard(q)

    def _publicar(self, d):
        for q in list(self._colas):
            if q.full():                         # un suscriptor lento no frena a los demas
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(d)

    # ------------------------------------------------------------ conexion
    async def _mantener_conexion(self):
        while True:
            try:
                reader, writer = await asyncio.wait_for(asyncio.open_connection(self.host, self.puerto), 3.0)
            except (OSError, asyncio.TimeoutError):
                await asyncio.sleep(2.0)
                continue
            self._writer = writer
            self._publicar({"tipo": "CONEXION", "conectado": True})
            asyncio.create_task(self.consultar_estado())        # ponerse al dia
            try:
                while True:
                    linea = await reader.readline()
                    if not linea:
                        break                                    # el servidor cerro
                    self._procesar(linea.decode("utf-8", errors="replace"))
            except (OSError, asyncio.IncompleteReadError):
                pass
            finally:
                self._writer = None
                writer.close()
                self._publicar({"tipo": "CONEXION", "conectado": False})
            await asyncio.sleep(2.0)

    def _procesar(self, linea):
        d = parsear_linea(linea)
        if d is None:
            return
        self.t_ultimo_mensaje = time.monotonic()
        c = d["campos"]
        if d["tipo"] == "EVT" and d["nombre"] == "TRANSICION":
            self.estado = c.get("a")
            self.orden = None if c.get("orden") in (None, "-") or self.estado == ESPERANDO_ORDEN else c.get("orden")
            self._pose(c)
            if self.estado != ERROR:
                self.error = None
        elif d["tipo"] == "EVT" and d["nombre"] == "LATIDO":
            self.estado = c.get("estado", self.estado)
            self.bateria = None if c.get("bat") in (None, "-") else float(c["bat"])
        elif d["tipo"] == "EVT" and d["nombre"] == "ERROR":
            self.error = c.get("codigo")
        elif d["tipo"] == "OK" and d["nombre"] == "ESTADO":
            self.estado = c.get("estado")
            self.orden = None if c.get("orden") in (None, "-") else c.get("orden")
            self.error = None if c.get("error") in (None, "-") else c.get("error")
            self._pose(c)
        # respuesta a un comando nuestro
        if d["tipo"] in ("OK", "ERROR") and c.get("id", "-").isdigit():
            fut = self._pendientes.get(int(c["id"]))
            if fut is not None and not fut.done():
                fut.set_result(d)
        self._publicar(d)

    def _pose(self, c):
        try:
            self.pose = (float(c["x"]), float(c["y"]), float(c["th"]))
        except (KeyError, ValueError):
            pass

    # ------------------------------------------------------------ comandos
    def nuevo_id(self):
        self._ultimo_id = max(self._ultimo_id + 1, int(time.time() * 10))
        return self._ultimo_id

    async def enviar(self, cmd, id_=None, **campos):
        """Manda 'CMD id=N k=v ...' y espera su OK/ERROR. Reintenta con el MISMO id."""
        mid = id_ if id_ is not None else self.nuevo_id()
        linea = " ".join([f"{cmd} id={mid}"] + [f"{k}={v}" for k, v in campos.items()]) + "\n"
        fut = asyncio.get_running_loop().create_future()
        self._pendientes[mid] = fut
        try:
            for _ in range(self.intentos):
                if self._writer is not None:
                    try:
                        self._writer.write(linea.encode("utf-8"))
                        await self._writer.drain()
                    except OSError:
                        pass
                try:
                    d = await asyncio.wait_for(asyncio.shield(fut), self.espera_respuesta)
                    return Respuesta(d["tipo"] == "OK", cmd, mid, d["campos"], d.get("motivo", ""))
                except asyncio.TimeoutError:
                    continue
            return Respuesta(False, cmd, mid, {}, "SIN_RESPUESTA")
        finally:
            self._pendientes.pop(mid, None)

    async def ordenar(self, mesa, id_=None):
        """Manda el robot a la mesa 1, 2 o 3. Solo se acepta si esta en la base (ESPERANDO_ORDEN)."""
        return await self.enviar("ORDEN", id_=id_, destino=f"MESA{int(mesa)}")

    async def cancelar(self, orden_id):
        """Solo durante la ida (RECORRIDO_MESA_n): el robot vuelve a la base por donde vino."""
        return await self.enviar("CANCELAR", orden=orden_id)

    async def retirado(self):
        """El cliente tomo el vaso (celda de carga < 50 g o boton en la app): el robot regresa ya."""
        return await self.enviar("RETIRADO")

    async def pausa(self):
        return await self.enviar("PAUSA")

    async def reanudar(self):
        return await self.enviar("REANUDAR")

    async def reset(self):
        """Solo en ERROR, y DESPUES de regresar el robot a mano a la base, mirando al frente."""
        return await self.enviar("RESET")

    async def consultar_estado(self):
        return await self.enviar("ESTADO")

    async def ping(self):
        return await self.enviar("PING")


# ====================================================================== pedidos
def ahora():
    return dt.datetime.now().replace(microsecond=0)


@dataclass
class Viaje:
    """Lo que el robot hizo con UN pedido. Las horas las pone ESTA computadora al recibir el evento."""
    folio: str
    mesa: int
    orden_id: int = None
    estado: str = "ENVIANDO"            # ver ESTADOS_VIAJE
    hora_salida: dt.datetime = None     # el robot acepto la orden (OK ORDEN)
    hora_llegada_mesa: dt.datetime = None   # EVT LLEGO
    hora_entrega: dt.datetime = None    # se mando RETIRADO (el cliente tomo el vaso)
    hora_regreso_base: dt.datetime = None   # volvio a ESPERANDO_ORDEN
    incidencia: str = None              # Ninguna | Navegación | Vaso   (columnas del dashboard)
    motivo_regreso: str = None          # entregado | sin_retirar | cancelado
    detalle: str = ""                   # texto para el operador

    def como_dict(self):
        d = dict(self.__dict__)
        for k, v in d.items():
            if isinstance(v, dt.datetime):
                d[k] = v.strftime("%Y-%m-%d %H:%M:%S")
        return d


ESTADOS_VIAJE = {
    "ENVIANDO": "se esta mandando la orden",
    "RECHAZADO": "el robot no salio (ver detalle: OCUPADO, FUERA_DE_BASE, SIN_RESPUESTA...)",
    "EN_CAMINO": "va hacia la mesa",
    "DETENIDO": "detenido en el camino (obstaculo, WiFi, pausa o atasco); sigue solo al despejarse",
    "EN_MESA": "llego a la mesa; esperando a que tomen el vaso",
    "REGRESANDO": "vuelve a la base (entregado, sin retirar o cancelado: ver incidencia)",
    "CERRADO": "el robot volvio a la base; el viaje termino",
    "FALLA": "el robot entro en ERROR: hay que llevarlo a mano a la base y mandar RESET",
}


class SeguimientoPedidos:
    """Sigue el viaje del pedido que lleva el robot y avisa cada cambio con al_cambiar(viaje).

    El robot lleva UN vaso a la vez: solo hay un viaje activo. La cola de pedidos, el producto y
    las horas de pedido/listo/carga son de la plataforma (su base de datos), no de este modulo.
    """

    def __init__(self, robot, al_cambiar=None):
        self.robot = robot
        self.al_cambiar = al_cambiar or (lambda viaje: None)
        self.activo = None             # Viaje en curso
        self.historial = []
        self._tarea = None
        self._ultimo = {}

    async def iniciar(self):
        await self.robot.iniciar()
        self._cola = self.robot.suscribir()
        self._tarea = asyncio.create_task(self._escuchar())

    async def cerrar(self):
        if self._tarea:
            self._tarea.cancel()
        await self.robot.cerrar()

    def _avisar(self, v):
        foto = v.como_dict()
        if self._ultimo.get(v.folio) == foto:     # sin cambios: no molestar a la plataforma
            return
        self._ultimo[v.folio] = foto
        try:
            r = self.al_cambiar(v)
            if asyncio.iscoroutine(r):
                asyncio.create_task(r)
        except Exception as ex:                  # un error de la plataforma no tumba el seguimiento
            print(f"[SeguimientoPedidos] al_cambiar fallo: {ex!r}")

    async def enviar(self, folio, mesa):
        """El barista ya puso el vaso: manda el robot. Regresa el Viaje (estado EN_CAMINO o RECHAZADO)."""
        if self.activo is not None:
            v = Viaje(folio, int(mesa), estado="RECHAZADO", detalle=f"el robot lleva {self.activo.folio}")
            self._avisar(v)
            return v
        v = Viaje(folio, int(mesa), orden_id=self.robot.nuevo_id())
        self.activo = v                          # antes de mandar: los eventos pueden llegar antes que el OK
        r = await self.robot.ordenar(mesa, id_=v.orden_id)
        if r.ok:
            v.estado, v.hora_salida = "EN_CAMINO", ahora()
        else:
            v.estado, v.detalle = "RECHAZADO", r.motivo
            self.activo = None
        self.historial.append(v)
        self._avisar(v)
        return v

    async def marcar_retirado(self):
        """El cliente tomo su vaso (celda de carga o boton). Solo vale con el robot EN_MESA."""
        v = self.activo
        r = await self.robot.retirado()
        if r.ok and v is not None:
            v.hora_entrega = ahora()
            self._avisar(v)
        return r

    async def cancelar(self):
        v = self.activo
        if v is None:
            return Respuesta(False, "CANCELAR", 0, {}, "SIN_VIAJE")
        r = await self.robot.cancelar(v.orden_id)
        if r.ok:
            v.incidencia = v.incidencia or "Navegación"
            v.detalle = "cancelado por el operador"
            self._avisar(v)
        return r

    async def _escuchar(self):
        while True:
            d = await self._cola.get()
            v = self.activo
            if d.get("tipo") == "CONEXION" or v is None:
                continue
            c = d.get("campos", {})
            # al reconectarse: si el robot ya esta en la base, el viaje termino mientras no veiamos
            if d["tipo"] == "OK" and d["nombre"] == "ESTADO" and c.get("estado") == ESPERANDO_ORDEN \
                    and v.estado not in ("ENVIANDO",):
                self._cerrar(v, "hora de regreso aproximada: se perdio la conexion durante el viaje")
                continue
            if d["tipo"] != "EVT" or c.get("orden") != str(v.orden_id):
                continue
            if d["nombre"] == "LLEGO":
                v.estado, v.hora_llegada_mesa = "EN_MESA", ahora()
            elif d["nombre"] == "ERROR":
                v.estado, v.incidencia = "FALLA", "Navegación"
                v.detalle = f"ERROR {c.get('codigo')}: llevar el robot a mano a la base y mandar RESET"
                self.activo = None                       # el viaje no se puede completar
            elif d["nombre"] == "TRANSICION":
                a, causa = c.get("a"), c.get("causa", "")
                if a == DETENIDO:
                    v.estado, v.detalle = "DETENIDO", causa
                    if causa.startswith("ATASCO"):
                        v.incidencia = "Navegación"
                elif a == REGRESO_BASE:
                    v.estado = "REGRESANDO"
                    if causa == "vaso_retirado":
                        v.motivo_regreso, v.detalle = "entregado", ""
                        v.hora_entrega = v.hora_entrega or ahora()
                    elif causa == "t_entrega":
                        v.motivo_regreso = "sin_retirar"
                        v.incidencia = v.incidencia or "Vaso"
                        v.detalle = "nadie tomo el vaso a tiempo: regresa con el"
                    elif causa == "cancelada":
                        v.motivo_regreso, v.detalle = "cancelado", "cancelado: regresa a la base"
                    elif causa == "reanuda":
                        v.detalle = ""
                elif a.startswith("RECORRIDO_MESA"):
                    v.estado, v.detalle = "EN_CAMINO", ""
                elif a == ESPERANDO_ORDEN:
                    self._cerrar(v, v.detalle)
                    continue
            else:
                continue
            self._avisar(v)

    def _cerrar(self, v, detalle):
        v.estado, v.hora_regreso_base, v.detalle = "CERRADO", ahora(), detalle
        v.incidencia = v.incidencia or "Ninguna"
        self.activo = None
        self._avisar(v)
