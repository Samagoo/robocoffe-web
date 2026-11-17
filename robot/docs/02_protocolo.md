# Protocolo TCP entre la plataforma y el robot

**Este documento es el contrato entre los dos equipos.** Si algo aquí cambia, cambia el código de ambos lados.

Fuente de verdad en el código: `robocoffe_fsm/protocolo.py` (formato), `robocoffe_fsm/fsm.py` (qué se acepta en cada estado) y `robocoffe_fsm/canales.py` (TCP).

## 1. Transporte

- **Conexión:** TCP. `main_real.py`, `servidor_simulado.py` y la simulación de Webots son el **servidor**, en el puerto **9000**. La plataforma es el cliente.
- **Mensajes:** una línea de texto UTF-8 por mensaje, terminada en `\n`. Formato `PALABRA clave=valor clave=valor ...`, separado por espacios. Los valores no llevan espacios.
- **Varios clientes:** hasta 4 a la vez. Todo lo que el robot manda (respuestas y eventos) llega a **todos** los clientes conectados.
- **Líneas incompletas:** un fragmento sin `\n` se descarta después de 1 s.
- **Ritmo:** el robot lee 20 veces por segundo y procesa **un** comando que cambia el estado por ciclo; los demás esperan su turno. Las consultas (`ESTADO`, `PING`) se responden en el mismo ciclo.
- **Seguridad:** no hay autenticación. Cualquiera en la misma red puede mandar órdenes; úsenlo solo en la red del laboratorio.

## 2. Comandos (plataforma → robot)

El comando no distingue mayúsculas de minúsculas. **Todos llevan `id=<entero>`.**

| Comando | Campos | Se acepta en | Respuesta si se acepta |
|---|---|---|---|
| `ORDEN` | `destino=MESA1` · `MESA2` · `MESA3` | `ESPERANDO_ORDEN` | `OK ORDEN id=N estado=RECORRIDO_MESA_n` |
| `RETIRADO` | — | `EN_MESA` | `OK RETIRADO id=N estado=REGRESO_BASE` |
| `CANCELAR` | `orden=<id de la ORDEN>` | `RECORRIDO_MESA_n` (solo de ida) | `OK CANCELAR id=N estado=REGRESO_BASE` |
| `PAUSA` | — | `RECORRIDO_MESA_n`, `REGRESO_BASE` | `OK PAUSA id=N estado=DETENIDO` |
| `REANUDAR` | — | `DETENIDO`, solo si la causa fue `PAUSA` | `OK REANUDAR id=N estado=<estado al que vuelve>` |
| `RESET` | — | `ERROR` | `OK RESET id=N estado=INICIALIZANDO` |
| `ESTADO` | — | siempre | `OK ESTADO id=N estado=… orden=… tramo=k/n x=… y=… th=… error=…` |
| `PING` | — | siempre | `OK PING id=N estado=…` |

Ejemplos:

```
ORDEN id=17631234567 destino=MESA2
CANCELAR id=17631234601 orden=17631234567
ESTADO id=17631234700
```

### Reglas de los ids

1. **Crecientes.** Si un id que cambia el estado es menor o igual al último recibido y no es un reintento, se responde `ERROR … ID_REPETIDO`. El contador se reinicia cuando se reinicia `main_real.py`.
2. **Esquema común:** `max(último + 1, int(time.time() * 10))`, en décimas de segundo desde 1970. Lo usan `cliente/robocoffe_cliente.py`, `consola_ordenes.py`, `enviar_orden.py`, `registro_pruebas.py` y Webots, así que se pueden mezclar.
3. **Reintento = mismo id.** Si llega un id que ya se respondió, el robot **repite la misma respuesta** y no vuelve a ejecutar nada. Así un reintento nunca duplica una orden.
4. **Consecuencia:** un rechazo también queda guardado. Si `ORDEN id=5` respondió `OCUPADO`, mandar `id=5` otra vez devuelve `OCUPADO` aunque el robot ya esté libre. **Para volver a intentar, usen un id nuevo.**
5. **Consultas:** `ESTADO` y `PING` no tocan la memoria de ids.

### Respuestas de error

Formato: `ERROR <COMANDO> id=N <MOTIVO>`.

| Motivo | Comando | Significa | Qué hacer |
|---|---|---|---|
| `OCUPADO` | ORDEN | El robot no está en `ESPERANDO_ORDEN` (va, viene o está iniciando) | Esperar a que esté libre |
| `FUERA_DE_BASE` | ORDEN | La pose está a más de 5 cm o 5° de la base | Revisar el robot. Si se movió a mano, reiniciar `main_real.py` con el robot en la base |
| `SIN_ENLACE_ROBOT` | ORDEN | `main_real.py` no recibe respuesta del OAK9 | Revisar el WiFi y la batería del robot |
| `BATERIA_BAJA` | ORDEN | La batería está por debajo de `bat_min` (hoy no se revisa: `None`) | Cargar |
| `DESTINO_INVALIDO` | ORDEN | El destino no es `MESA1`, `MESA2` ni `MESA3` | — |
| `EN_ERROR` | cualquiera excepto RESET | El robot está en `ERROR` | Llevarlo a la base a mano y mandar `RESET` |
| `NO_PERMITIDO` | los demás | El comando no aplica en este estado (ver la tabla) | — |
| `ORDEN_NO_COINCIDE` | CANCELAR | `orden=` no es la orden en curso | Usar el id de la `ORDEN` |
| `ID_REPETIDO` | cualquiera | Id viejo (regla 1) | Usar un id nuevo |

Si el formato está mal (comando desconocido, falta `id` o falta `destino`), la respuesta es `ERROR ? id=- FORMATO <motivo_con_guiones_bajos>`.

## 3. Eventos (robot → plataforma)

Llegan sin que nadie los pida. Todos empiezan con `EVT`. `t=` son segundos desde que arrancó la máquina; para las horas del día usen su propio reloj.

| Evento | Campos | Cuándo |
|---|---|---|
| `EVT TRANSICION` | `t de a causa orden x y th` | Cada cambio de estado. Es el más importante |
| `EVT LLEGO` | `t mesa orden` | El robot llegó a la mesa (justo después de la transición a `EN_MESA`) |
| `EVT TRAMO` | `t orden tramo=k/n tipo=IR\|GIRAR ex ey eth reintentos ok` | Al terminar cada tramo, con el error de llegada en m y grados |
| `EVT ERROR` | `t codigo orden tramo` | Al entrar a `ERROR` |
| `EVT LATIDO` | `t estado bat` | Cada 1 s: "sigo vivo". `bat` en V, o `-` si no se lee |

Ejemplo de una entrega completa a la mesa 1, con el cliente tomando el vaso. Es la salida real de `servidor_simulado.py` el 13 nov 2026, sin los `EVT LATIDO`. Por eso los errores salen en cero; con el robot real son de milímetros.

```
OK ORDEN id=17945497071 estado=RECORRIDO_MESA_1
EVT TRANSICION t=3.88 de=ESPERANDO_ORDEN a=RECORRIDO_MESA_1 causa=orden_MESA1 orden=17945497071 x=0.000 y=0.000 th=0.0
EVT TRAMO t=14.41 orden=17945497071 tramo=1/1 tipo=IR ex=0.000 ey=0.000 eth=0.0 reintentos=0 ok=True
EVT TRANSICION t=14.41 de=RECORRIDO_MESA_1 a=EN_MESA causa=ultimo_tramo orden=17945497071 x=1.000 y=0.000 th=0.0
EVT LLEGO t=14.41 mesa=1 orden=17945497071
OK RETIRADO id=17945497101 estado=REGRESO_BASE
EVT TRANSICION t=16.43 de=EN_MESA a=REGRESO_BASE causa=vaso_retirado orden=17945497071 x=1.000 y=0.000 th=0.0
EVT TRAMO t=28.98 orden=17945497071 tramo=1/2 tipo=IR ex=0.000 ey=0.000 eth=0.0 reintentos=0 ok=True
EVT TRAMO t=31.50 orden=17945497071 tramo=2/2 tipo=GIRAR ex=0.000 ey=0.000 eth=0.0 reintentos=0 ok=True
EVT TRANSICION t=31.50 de=REGRESO_BASE a=ESPERANDO_ORDEN causa=en_base orden=17945497071 x=0.000 y=0.000 th=0.0
OK ESTADO id=17945497131 estado=ESPERANDO_ORDEN orden=- tramo=- x=0.000 y=0.000 th=0.0 error=-
```

**`th` puede no estar normalizado.** `th` es el ángulo tal como lo reporta la odometría, y puede salir fuera de ±180°. En la prueba contra un firmware falso salió `th=-358.2`, que es lo mismo que `+1.8°`; falta revisar si el firmware real también acumula el ángulo: `<POR MEDIR>`. Si lo muestran en pantalla, normalícenlo con `((th + 180) % 360) - 180`.

### Valores de `causa` en `EVT TRANSICION`

| `causa` | Transición | Para la plataforma |
|---|---|---|
| `arranque`, `verificaciones_ok` | → `INICIALIZANDO` → `ESPERANDO_ORDEN` | Robot listo |
| `E_INIT:<detalle>` | `INICIALIZANDO` → `ERROR` | Falló el arranque. El detalle puede ser `sin_conexion_TimeoutError`, `pose_no_reinicia`, `cpr=…`, `bateria=…` o `timeout` |
| `orden_MESAn` | → `RECORRIDO_MESA_n` | Salió |
| `ultimo_tramo` | → `EN_MESA` | Llegó |
| `vaso_retirado` | `EN_MESA` → `REGRESO_BASE` | Entregado |
| `t_entrega` | `EN_MESA` → `REGRESO_BASE` | Nadie tomó el vaso: incidencia `Vaso` |
| `cancelada` | `RECORRIDO_MESA_n` → `REGRESO_BASE` | Cancelado |
| `en_base` | `REGRESO_BASE` → `ESPERANDO_ORDEN` | Viaje cerrado: `HoraRegresoBase` |
| `PAUSA`, `OBSTACULO`, `ENLACE`, `ATASCO` | → `DETENIDO` | Detenido; sigue solo al despejarse (`PAUSA` necesita `REANUDAR`) |
| `reanuda` | `DETENIDO` → el estado anterior | Siguió |
| `E_…` (ver abajo) | → `ERROR` | Falla |
| `reset` | `ERROR` → `INICIALIZANDO` | Reiniciando |

### Códigos de error

| Código | Causa | Qué revisar |
|---|---|---|
| `E_INIT` | El arranque no pasó las verificaciones | Conexión con el robot, encoders, batería |
| `E_POSICION` | No llegó dentro de la tolerancia después de 2 reintentos | Ruedas, piso, calibración |
| `E_TRAMO_TIMEOUT` | El tramo tardó más que su tiempo máximo | Robot bloqueado o demasiado lento |
| `E_ATASCO` | Segundo atasco en el mismo tramo | Algo traba las ruedas |
| `E_DETENIDO_TIMEOUT` | Más de 30 s detenido (excepto por PAUSA) | Obstáculo permanente, WiFi caído |
| `E_SALTO_POSE` | La pose brincó más de lo físicamente posible | Alguien movió el robot o la odometría falló |
| `E_TRAMO_RECHAZADO` | El adaptador rechazó el tramo | — |
| `E_BATERIA` | Batería por debajo de `bat_crit` (hoy desactivado) | Cargar |

**Salir de `ERROR`:** llevar el robot a mano a la base, mirando al frente, y mandar `RESET`. Vuelve a calibrar y a poner la pose en cero.

## 4. Desconexiones

- **Si la plataforma se desconecta**, el robot **no** se detiene: termina lo que estaba haciendo. Es a propósito, para que una caída del backend no deje un café a medio pasillo.
- **Al reconectarse**, manden `ESTADO`. `cliente/robocoffe_cliente.py` lo hace solo y, si el robot ya está en la base, cierra el pedido con la hora aproximada.
- **Si `main_real.py` pierde el WiFi del robot** por más de 1 s, el robot entra a `DETENIDO causa=ENLACE` y las ruedas se paran. Sigue solo cuando vuelve el enlace. Si dura más de 30 s, entra a `ERROR E_DETENIDO_TIMEOUT`.

## 5. Probar el protocolo a mano

```bash
python servidor_simulado.py          # o main_real.py --host <ip del robot>
python consola_ordenes.py            # escribe MESA1, PAUSA, REANUDAR, CANCELAR, RESET, ESTADO
```

Con netcat: `nc 127.0.0.1 9000` y teclear `PING id=1`.
