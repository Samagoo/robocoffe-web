# Robot real paso a paso

## Una sola vez: instalar

1. Instalar Python 3.10 o más reciente.
2. Instalar la librería del robot:
   ```bash
   git clone https://github.com/DrLizarraga/oak9lib
   pip install -e oak9lib
   ```
3. Opcional, para el Excel del registro de pruebas: `pip install openpyxl`.
4. **Windows: quitar el ahorro de energía del adaptador WiFi.** Ir a *Administrador de dispositivos → Adaptadores de red → (WiFi) → Propiedades → Administración de energía* y quitar la casilla *Permitir que el equipo apague este dispositivo*. Con el ahorro activado se cortaba la comunicación a medio movimiento.

## Cada sesión

1. **Red:** la computadora y el robot deben estar en la **misma** red WiFi. Usen un router fijo, de preferencia sin otros equipos pesados conectados. Anoten la **IP del robot** (la que usan con oak9lib); cambia según la red.
2. **Robot:**
   - Batería cargada. El 12 nov arrancó con 8.18 V; el umbral mínimo está `<POR MEDIR>`.
   - Colocado en la base, con o1 sobre la marca y mirando al frente (+x).
   - Ruta despejada.
3. **Revisar el movimiento** (1 min):
   ```bash
   python probar_movimiento.py 192.168.1.173
   oak9> IR 0.5 0
   oak9> BASE
   oak9> SALIR
   ```
   - **Mientras dice "Calibrando giroscopio":** no muevan el robot. Tarda unos segundos.
   - **Si no se conecta:** ver [08](08_problemas_comunes.md).
4. **Arrancar la máquina de estados:**
   ```bash
   python main_real.py --host 192.168.1.173 --entrega 180
   ```
   Debe verse:
   ```
   [RoboCoffe] ordenes por tcp puerto=9000  robot=192.168.1.173:8080  registro=transiciones_<fecha>.csv
   EVT TRANSICION ... a=INICIALIZANDO causa=arranque ...
   EVT TRANSICION ... a=ESPERANDO_ORDEN causa=verificaciones_ok ...
   ```
   - **Si se va a `ERROR E_INIT:…`:** lean el detalle (ver [08](08_problemas_comunes.md)), acomoden el robot y manden `RESET` o reinicien.
   - **Windows:** la primera vez puede preguntar si permite el acceso a la red. Acepten, porque si no el backend no se puede conectar al puerto 9000 desde otra computadora.
5. **Mandar órdenes.** Usen una de estas opciones:
   - Consola, en otra terminal de la misma computadora: `python consola_ordenes.py`
   - Registro de pruebas para el dashboard: `python registro_pruebas.py` (ver [07](07_datos_dashboard.md))
   - La plataforma web: `ROBOT_HOST` = la IP de **esta computadora**, o `127.0.0.1` si el backend corre aquí mismo.
6. **Terminar:** Ctrl+C en `main_real.py`. Manda el paro a las ruedas antes de salir.

## Orden recomendado para la primera vez con la máquina completa

1. `MESA1` y dejar que regrese solo por tiempo.
2. `MESA1` y, ya en la mesa, `RETIRADO`: el robot regresa de inmediato.
3. `MESA2`, después `MESA3`.
4. Durante un viaje: `PAUSA`, `REANUDAR`. Luego `CANCELAR` de ida.
5. Una persona se cruza frente al robot: debe detenerse **solo si** están configurados los ultrasónicos (`FRONTALES` en `robot_oak9.py`, hoy `<RELLENAR>`). Mientras no estén, **el robot no detecta obstáculos**: vigílenlo.

## Seguridad

- El paro de emergencia real es el **interruptor del robot**. Ctrl+C manda el paro por WiFi, pero si el WiFi está caído no llega.
- Si `main_real.py` imprime `NO SE PUDO MANDAR STOP`, apaguen el robot con el interruptor.
- Si el robot se mueve a mano, su pose ya no es válida: reinicien `main_real.py` con el robot en la base.

## Archivos que genera

| Archivo | Quién lo genera | Contenido |
|---|---|---|
| `transiciones_<fecha>.csv` | `main_real.py` | Una línea por transición: t, de, a, causa, orden, x, y, th |
| `movimiento_<fecha>.csv` | `probar_movimiento.py` | Pose y error de cada tramo |
| `datos_pruebas_<fecha>/` | `registro_pruebas.py` | Hojas del dashboard (ver [07](07_datos_dashboard.md)) |
