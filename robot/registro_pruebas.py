"""Registro de pruebas para el dashboard: manda las ordenes al robot y llena las hojas
«Pedidos» y «Robot» con los nombres de columna exactos que pide el dashboard.

Funciona con el robot real (main_real.py) y con Webots (oak9_entregas.wbt): ambos escuchan en
el puerto 9000. Las horas las pone ESTA computadora en el momento en que pasa cada cosa:
  automaticas   HoraPedido, HoraRegresoBase, Incidencia=Navegación (si hubo DETENIDO/ERROR),
                MinParoFalla, InicioTurno, FinTurno
  tecleadas     Producto (o del plan), HoraListo (LISTO), HoraInicioCarga + PesoCarga_g (CARGA),
                HoraEntrega + PesoEntrega_g (ENTREGA), Incidencia=Vaso (VASO), Recargas (RECARGA)

Uso (con main_real.py o Webots ya corriendo):
    python main_real.py --host 192.168.99.254 --entrega 180      (terminal 1)
    python registro_pruebas.py                                    (terminal 2)

Ciclo de cada cafe:
    PEDIDO            toma el siguiente del plan balanceado (o: PEDIDO C2 3 = latte a la mesa 3)
    LISTO             el cafe quedo listo para cargarse
    CARGA 352.4       pones el vaso en el robot (peso en g, robot detenido) -> el robot sale
    ENTREGA 351.9     el cliente toma el vaso en la mesa (peso leido ANTES de quitarlo) -> regresa
    (HoraRegresoBase se registra sola cuando el robot vuelve a la base)
Otros:  VASO / NAV        marcar incidencia del ultimo folio
        NOTA <texto>      observacion del turno          RECARGA   inicio / fin de recarga
        RESUMEN           avance contra el plan           PAUSA REANUDAR CANCELAR RESET ESTADO
        SALIR             cierra el turno y escribe el Excel
Archivos (carpeta datos_pruebas_<fecha>): Pedidos.csv, Robot.csv, eventos.log (todo lo recibido,
con hora) y Pruebas_RoboCoffe_<fecha>.xlsx (hojas Pedidos, Robot y Receta) si hay openpyxl.
Los CSV se reescriben despues de cada cambio: si algo se cae, no se pierde nada.
"""
import argparse
import csv
import datetime as dt
import os
import random
import socket
import threading
import time

# Distancia de la estacion a cada mesa [m]. MIDELA una vez con cinta y corrige aqui.
DISTANCIA_M = {1: 1.0, 2: 2.0, 3: 3.0}
PRODUCTOS = {"C1": "americano", "C2": "latte", "C3": "frappe"}

COL_PEDIDOS = ["Folio", "HoraPedido", "Producto", "Mesa", "Distancia_m", "HoraListo", "HoraInicioCarga",
               "HoraEntrega", "HoraRegresoBase", "Incidencia", "PesoCarga_g", "PesoEntrega_g"]
COL_ROBOT = ["Fecha", "InicioTurno", "FinTurno", "Recargas", "MinRecarga", "MinParoFalla", "Observaciones"]


def ahora():
    return dt.datetime.now().replace(microsecond=0)


def fmt(t):
    return t.strftime("%Y-%m-%d %H:%M:%S") if isinstance(t, dt.datetime) else ("" if t is None else t)


def plan_balanceado(semilla=12):
    """30 entregas: 10 por producto, cada producto repartido entre las 3 mesas (10 por mesa), orden aleatorio."""
    reparto = {"C1": [1, 1, 1, 2, 2, 2, 3, 3, 3, 1], "C2": [1, 1, 1, 2, 2, 2, 3, 3, 3, 2],
               "C3": [1, 1, 1, 2, 2, 2, 3, 3, 3, 3]}
    plan = [(p, m) for p, mesas in reparto.items() for m in mesas]
    random.Random(semilla).shuffle(plan)
    return plan


class Registro:
    def __init__(self, carpeta):
        os.makedirs(carpeta, exist_ok=True)
        self.carpeta = carpeta
        self.fecha = dt.date.today().isoformat()
        self.lock = threading.RLock()
        self.pedidos = []                 # dicts con COL_PEDIDOS + campos internos (_id, _estado)
        self.plan = plan_balanceado()
        self.i_plan = 0
        self.estado_robot = None
        self.folio_activo = None          # pedido que va en el robot
        self.id_a_folio = {}
        self.inicio_turno = None
        self.fin_turno = None
        self.recargas, self.min_recarga, self.t_recarga = 0, 0.0, None
        self.min_paro, self.t_paro = 0.0, None
        self.obs = []
        self.log = open(os.path.join(carpeta, "eventos.log"), "a", encoding="utf-8")
        with open(os.path.join(carpeta, "plan_30_entregas.csv"), "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["Orden", "Producto", "Descripcion", "Mesa"])
            for i, (prod, mesa) in enumerate(self.plan, start=1):
                w.writerow([i, prod, PRODUCTOS[prod], mesa])
        self._cargar_previo()

    # ------------------------------------------------------------ persistencia
    def _cargar_previo(self):
        """Si ya habia registro de hoy (se cerro el programa), sigue los folios."""
        p = os.path.join(self.carpeta, "Pedidos.csv")
        if os.path.exists(p):
            with open(p, encoding="utf-8-sig") as f:
                for r in csv.DictReader(f):
                    r["_id"], r["_estado"] = None, "cerrado" if r.get("HoraRegresoBase") else "previo"
                    self.pedidos.append(r)
            hechos = [(r["Producto"], int(r["Mesa"])) for r in self.pedidos if r.get("Mesa")]
            while self.i_plan < len(self.plan) and self.plan[self.i_plan] in hechos:
                hechos.remove(self.plan[self.i_plan])
                self.i_plan += 1
            print(f"Continuo el registro de hoy: {len(self.pedidos)} pedidos previos.")
        r = os.path.join(self.carpeta, "Robot.csv")
        if os.path.exists(r):
            with open(r, encoding="utf-8-sig") as f:
                fila = next(csv.DictReader(f), None)
            if fila:
                self.inicio_turno = fila.get("InicioTurno") or None
                self.recargas = int(fila.get("Recargas") or 0)
                self.min_recarga = float(fila.get("MinRecarga") or 0)
                self.min_paro = float(fila.get("MinParoFalla") or 0)
                self.obs = [o for o in (fila.get("Observaciones") or "").split(" | ") if o]

    def guardar(self):
        with self.lock:
            with open(os.path.join(self.carpeta, "Pedidos.csv"), "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(COL_PEDIDOS)
                for p in self.pedidos:
                    w.writerow([fmt(p.get(c)) for c in COL_PEDIDOS])
            with open(os.path.join(self.carpeta, "Robot.csv"), "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(COL_ROBOT)
                w.writerow(self.fila_robot())

    def fila_robot(self):
        paro = self.min_paro + ((time.monotonic() - self.t_paro) / 60 if self.t_paro else 0)
        return [self.fecha, fmt(self.inicio_turno), fmt(self.fin_turno), self.recargas,
                f"{self.min_recarga:.1f}", f"{paro:.1f}", " | ".join(self.obs)]

    def excel(self):
        try:
            from openpyxl import Workbook
        except ImportError:
            print("Sin openpyxl: quedan los CSV (para el Excel: pip install openpyxl y vuelve a SALIR).")
            return None
        wb = Workbook()
        ws = wb.active
        ws.title = "Pedidos"
        ws.append(COL_PEDIDOS)
        for p in self.pedidos:
            fila = []
            for c in COL_PEDIDOS:
                v = p.get(c)
                if c in ("Mesa",) and v not in (None, ""):
                    v = int(v)
                elif c in ("Distancia_m", "PesoCarga_g", "PesoEntrega_g") and v not in (None, ""):
                    v = float(v)
                fila.append(fmt(v) if isinstance(v, dt.datetime) else v)
            ws.append(fila)
        wr = wb.create_sheet("Robot")
        wr.append(COL_ROBOT)
        fr = self.fila_robot()
        wr.append([fr[0], fr[1], fr[2], fr[3], float(fr[4]), float(fr[5]), fr[6]])
        rc = wb.create_sheet("Receta")
        rc.append(["Producto", "Descripcion", "Vaso1_g", "Vaso2_g", "Vaso3_g", "Vaso4_g", "Vaso5_g",
                   "Promedio_g", "Tolerancia_g", "CostoPorGramo"])
        for i, (k, v) in enumerate(PRODUCTOS.items(), start=2):
            rc.append([k, v, None, None, None, None, None, f"=AVERAGE(C{i}:G{i})", None, None])
        ruta = os.path.join(self.carpeta, f"Pruebas_RoboCoffe_{self.fecha}.xlsx")
        wb.save(ruta)
        return ruta

    # ------------------------------------------------------------ eventos del robot
    def evento(self, linea):
        t = ahora()
        self.log.write(f"{fmt(t)}  {linea}\n")
        self.log.flush()
        if linea.startswith("EVT LATIDO"):
            return None
        kv = dict(x.split("=", 1) for x in linea.split() if "=" in x)
        msg = None
        with self.lock:
            if linea.startswith("OK ESTADO"):
                self.estado_robot = kv.get("estado")
                if self.estado_robot == "ESPERANDO_ORDEN" and self.inicio_turno is None:
                    self.inicio_turno = t
            elif linea.startswith("ERROR ORDEN"):
                p = self.id_a_folio.get(kv.get("id"))
                if p is not None:
                    p["_estado"] = "listo"                     # no salio: se puede volver a CARGA
                    msg = f"El robot RECHAZO {p['Folio']}: {linea.split()[-1]}. Corrige y repite CARGA."
            elif linea.startswith("EVT TRANSICION"):
                de, a, causa = kv.get("de"), kv.get("a"), kv.get("causa", "")
                self.estado_robot = a
                p = self.id_a_folio.get(kv.get("orden"))
                if a == "ESPERANDO_ORDEN" and self.inicio_turno is None:
                    self.inicio_turno = t
                if a in ("DETENIDO", "ERROR") and not causa.startswith(("PAUSA", "OBSTACULO")):
                    # MinParoFalla: atasco, WiFi (ENLACE) y errores; una pausa o un obstaculo no son falla
                    if self.t_paro is None:
                        self.t_paro = time.monotonic()
                    # Incidencia de navegacion: atasco o ERROR (no un corte de WiFi)
                    if p is not None and (a == "ERROR" or causa.startswith("ATASCO")) and p.get("Incidencia") != "Vaso":
                        p["Incidencia"] = "Navegación"
                    msg = f"ATENCION: robot en {a} ({causa}). Si se salio de la linea o lo moviste a mano: NAV"
                elif a == "DETENIDO":
                    msg = f"Robot detenido ({causa}); sigue solo cuando se despeje."
                elif de in ("DETENIDO", "ERROR") and self.t_paro is not None:
                    self.min_paro += (time.monotonic() - self.t_paro) / 60
                    self.t_paro = None
                if a == "EN_MESA" and p is not None:
                    msg = f"{p['Folio']} llego a la mesa {p['Mesa']}: lee el peso y escribe ENTREGA <g> cuando tomen el vaso."
                if a == "REGRESO_BASE" and causa == "t_entrega" and p is not None:
                    msg = f"OJO: {p['Folio']} regreso por tiempo (nadie escribio ENTREGA)."
                    if not p.get("Incidencia"):
                        p["Incidencia"] = "Vaso"
                if a == "ESPERANDO_ORDEN" and de == "REGRESO_BASE" and p is not None:
                    p["HoraRegresoBase"] = t
                    if not p.get("Incidencia"):
                        p["Incidencia"] = "Ninguna"
                    p["_estado"] = "cerrado"
                    if self.folio_activo is p:
                        self.folio_activo = None
                    msg = f"{p['Folio']} cerrado: el robot esta en la base."
        self.guardar()
        return msg

    # ------------------------------------------------------------ comandos del operador
    def siguiente(self, estado):
        return next((p for p in self.pedidos if p["_estado"] == estado), None)

    def nuevo_pedido(self, producto=None, mesa=None):
        with self.lock:
            if producto is None:
                if self.i_plan >= len(self.plan):
                    return "El plan de 30 ya se completo; usa PEDIDO C1 2 para agregar."
                producto, mesa = self.plan[self.i_plan]
                self.i_plan += 1
            n = len(self.pedidos) + 1
            p = {"Folio": f"P-{n:04d}", "HoraPedido": ahora(), "Producto": producto, "Mesa": mesa,
                 "Distancia_m": f"{DISTANCIA_M[mesa]:.2f}", "_estado": "pedido", "_id": None}
            self.pedidos.append(p)
        self.guardar()
        return f"{p['Folio']}: {producto} ({PRODUCTOS[producto]}) a la mesa {mesa}. Cuando este listo: LISTO"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--puerto", type=int, default=9000)
    ap.add_argument("--carpeta", default=None)
    a = ap.parse_args()
    reg = Registro(a.carpeta or f"datos_pruebas_{dt.date.today().isoformat()}")
    try:
        s = socket.create_connection((a.host, a.puerto), timeout=3)
    except OSError:
        print(f"No me pude conectar a {a.host}:{a.puerto}. Abre primero main_real.py (o Webots con Play).")
        return
    s.settimeout(None)
    ids = {"ultimo": 0}

    def nuevo_id():
        ids["ultimo"] = max(ids["ultimo"] + 1, int(time.time() * 10))
        return ids["ultimo"]

    def enviar(linea):
        s.sendall((linea + "\n").encode())

    def escuchar():
        buf = ""
        while True:
            try:
                d = s.recv(4096)
            except OSError:
                break
            if not d:
                break
            buf += d.decode(errors="replace")
            while "\n" in buf:
                linea, _, buf = buf.partition("\n")
                linea = linea.strip()
                if not linea:
                    continue
                msg = reg.evento(linea)
                if linea.startswith(("EVT TRANSICION", "OK ", "ERROR ")):
                    kv = dict(x.split("=", 1) for x in linea.split() if "=" in x)
                    corto = f"{kv.get('de')} -> {kv.get('a')} ({kv.get('causa')})" if "TRANSICION" in linea else linea
                    print(f"\r  [robot] {corto}")
                if msg:
                    print(f"  >>> {msg}")
                print("registro> ", end="", flush=True)
        print("\nSe cerro la conexion con el robot (los datos ya estan guardados).")

    threading.Thread(target=escuchar, daemon=True).start()
    enviar(f"ESTADO id={nuevo_id()}")
    print(f"Conectado. Datos en: {os.path.abspath(reg.carpeta)}")
    print("Ciclo: PEDIDO -> LISTO -> CARGA <g> -> ENTREGA <g>   |  RESUMEN  NOTA  RECARGA  VASO  NAV  SALIR")

    while True:
        try:
            entrada = input("registro> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not entrada:
            continue
        partes = entrada.split()
        cmd = partes[0].upper()
        try:
            if cmd == "PEDIDO":
                if len(partes) == 3:
                    prod, mesa = partes[1].upper(), int(partes[2].upper().replace("MESA", ""))
                    if prod not in PRODUCTOS or mesa not in DISTANCIA_M:
                        print("Uso: PEDIDO C1|C2|C3 1|2|3   (o solo PEDIDO para el siguiente del plan)")
                        continue
                    print(reg.nuevo_pedido(prod, mesa))
                else:
                    print(reg.nuevo_pedido())
            elif cmd == "LISTO":
                with reg.lock:
                    p = reg.siguiente("pedido")
                    if p is None:
                        print("No hay pedidos esperando cafe. Usa PEDIDO.")
                        continue
                    p["HoraListo"], p["_estado"] = ahora(), "listo"
                reg.guardar()
                print(f"{p['Folio']} listo. Pon el vaso en el robot y escribe CARGA <peso en g>.")
            elif cmd == "CARGA":
                with reg.lock:
                    if reg.folio_activo is not None:
                        print(f"El robot todavia lleva {reg.folio_activo['Folio']}; espera a que vuelva a la base.")
                        continue
                    if reg.estado_robot not in (None, "ESPERANDO_ORDEN"):
                        print(f"El robot esta en {reg.estado_robot}; espera ESPERANDO_ORDEN.")
                        continue
                    p = reg.siguiente("listo")
                    if p is None:
                        print("No hay cafe listo. Usa LISTO primero.")
                        continue
                    p["HoraInicioCarga"] = ahora()
                    p["PesoCarga_g"] = f"{float(partes[1]):.1f}" if len(partes) > 1 else ""
                    oid = str(nuevo_id())
                    p["_id"], p["_estado"] = oid, "en_ruta"
                    reg.id_a_folio[oid] = p
                    reg.folio_activo = p
                enviar(f"ORDEN id={oid} destino=MESA{p['Mesa']}")
                reg.guardar()
                print(f"{p['Folio']} cargado ({p['PesoCarga_g'] or 'sin peso'} g): el robot sale a la mesa {p['Mesa']}.")
            elif cmd == "ENTREGA":
                with reg.lock:
                    p = reg.folio_activo
                    if p is None or reg.estado_robot != "EN_MESA":
                        print("El robot no esta esperando en una mesa.")
                        continue
                    p["PesoEntrega_g"] = f"{float(partes[1]):.1f}" if len(partes) > 1 else ""
                    p["HoraEntrega"] = ahora()
                enviar(f"RETIRADO id={nuevo_id()}")
                reg.guardar()
                print(f"{p['Folio']} entregado: el robot regresa a la base.")
            elif cmd in ("VASO", "NAV"):
                with reg.lock:
                    p = reg.folio_activo or (reg.pedidos[-1] if reg.pedidos else None)
                    if p is None:
                        continue
                    p["Incidencia"] = "Vaso" if cmd == "VASO" else "Navegación"
                reg.guardar()
                print(f"{p['Folio']}: Incidencia = {p['Incidencia']}")
            elif cmd == "NOTA":
                reg.obs.append(f"{ahora().strftime('%H:%M')} {entrada[5:].strip()}")
                reg.guardar()
                print("Nota guardada.")
            elif cmd == "RECARGA":
                if reg.t_recarga is None:
                    reg.t_recarga = time.monotonic()
                    reg.recargas += 1
                    print("Recarga iniciada. Escribe RECARGA otra vez cuando termine.")
                else:
                    reg.min_recarga += (time.monotonic() - reg.t_recarga) / 60
                    reg.t_recarga = None
                    print(f"Recarga terminada. Total: {reg.min_recarga:.1f} min.")
                reg.guardar()
            elif cmd == "RESUMEN":
                cerr = [p for p in reg.pedidos if p.get("HoraRegresoBase")]
                print(f"Cerrados {len(cerr)} de 30 (plan: {reg.i_plan}/30 pedidos tomados).")
                for k in PRODUCTOS:
                    por_mesa = [sum(1 for p in cerr if p["Producto"] == k and int(p["Mesa"]) == m) for m in (1, 2, 3)]
                    print(f"  {k}: {sum(por_mesa)}  (mesa1 {por_mesa[0]}, mesa2 {por_mesa[1]}, mesa3 {por_mesa[2]})")
                inc = [p["Folio"] + ":" + p["Incidencia"] for p in cerr if p.get("Incidencia") not in (None, "", "Ninguna")]
                print(f"  Incidencias: {', '.join(inc) or 'ninguna'}")
            elif cmd in ("PAUSA", "REANUDAR", "RESET", "ESTADO"):
                enviar(f"{cmd} id={nuevo_id()}")
            elif cmd == "CANCELAR":
                p = reg.folio_activo
                enviar(f"CANCELAR id={nuevo_id()} orden={p['_id'] if p else '-'}")
                if p:
                    p["Incidencia"] = p.get("Incidencia") or "Navegación"
            elif cmd == "SALIR":
                break
            else:
                print("No entendi. PEDIDO  LISTO  CARGA <g>  ENTREGA <g>  VASO  NAV  NOTA <texto>  RECARGA  RESUMEN  SALIR")
        except (ValueError, IndexError):
            print("Revisa el numero (usa punto decimal, ej. CARGA 352.4).")
    with reg.lock:
        reg.fin_turno = ahora()
        if reg.t_paro is not None:
            reg.min_paro += (time.monotonic() - reg.t_paro) / 60
            reg.t_paro = None
    reg.guardar()
    ruta = reg.excel()
    print(f"Turno cerrado. Archivos en {os.path.abspath(reg.carpeta)}" + (f"\nExcel: {ruta}" if ruta else ""))
    s.close()


if __name__ == "__main__":
    main()
