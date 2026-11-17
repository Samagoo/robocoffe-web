# Guía para el equipo de la plataforma web

**Idea central:** el robot ya sabe moverse, llegar a las mesas, detenerse ante problemas y regresar a la base. La plataforma solo tiene que **decirle a qué mesa ir**, **avisarle cuando el cliente tomó el vaso** y **escuchar lo que va pasando** para mostrarlo y guardarlo.

## 1. Qué le toca a cada quien

| Ya resuelto (este folder) | Le toca a la plataforma |
|---|---|
| Ir y volver de las mesas 1, 2 y 3 en lazo cerrado | Cola de pedidos, productos, folios y base de datos |
| Detenerse por obstáculo, WiFi, atasco o pausa, y reanudar solo | Decidir **cuándo** sale el robot: el barista confirma que cargó el vaso |
| Detectar errores y quedarse quieto en ERROR | Mandar `RETIRADO` cuando el cliente toma el vaso (botón en la app o celda de carga) |
| No duplicar órdenes si la plataforma reintenta | Mostrar el estado del robot y de cada pedido (WebSocket) |
| Rechazar órdenes que no se pueden cumplir y decir por qué | Guardar las horas para el dashboard (ver [07](07_datos_dashboard.md)) |
| Cliente de Python que maneja conexión, ids y reintentos | Pantallas: cliente, barista y operador |

## 2. Cómo se conectan

```
Navegador ──HTTP/WS──► Backend FastAPI ──TCP 9000──► main_real.py ──TCP 8080──► Robot OAK9
                         (ustedes)        (texto)      (este folder)   (oak9lib)
```

Hay **dos IP distintas**; confundirlas es el error más común:

| IP | Puerto | Quién la usa |
|---|---|---|
| La del **robot** (por ejemplo `192.168.1.173`; cambia con la red) | 8080 | Solo `main_real.py`. La plataforma **nunca** habla directo con el robot |
| La de la **computadora donde corre `main_real.py`** | 9000 | La plataforma. Si el backend corre en la misma computadora, usen `127.0.0.1` |

## 3. Cómo empezar a desarrollar hoy (sin robot)

```bash
python servidor_simulado.py --entrega 180       # robot simulado en el puerto 9000
```

- Es la **misma** máquina de estados y el **mismo** protocolo que el robot real. Lo único que cambia es que el robot es simulado.
- Se pueden provocar fallas escribiendo en esa terminal: `obstaculo`, `corte`, `atasco` o `salto`. Sirven para probar las pantallas de error.
- `--rapido 10` corre todo 10 veces más rápido.

Después:

1. Corran `python cliente/demo_seguimiento.py`. Hace tres pedidos y verifica que todo responda como describe esta guía.
2. Lean `cliente/ejemplo_fastapi.py`. Es un backend completo de unas 200 líneas; cambien el `dict` de pedidos por su base de datos (SQLModel).
3. Usen `cliente/robocoffe_cliente.py` tal cual o como referencia. Solo usa la biblioteca estándar.

## 4. Flujo de un pedido

```mermaid
sequenceDiagram
    autonumber
    actor C as Cliente
    participant W as Plataforma
    actor B as Barista
    participant R as Robot (main_real.py)
    C->>W: pide C2 a la mesa 2
    Note over W: Folio, HoraPedido, estado "Preparando"
    B->>W: café listo
    Note over W: HoraListo
    B->>W: puse el vaso en el robot (peso)
    W->>R: ORDEN id=17631234567 destino=MESA2
    R-->>W: OK ORDEN id=17631234567 estado=RECORRIDO_MESA_2
    Note over W: HoraInicioCarga, "En camino"
    R-->>W: EVT TRANSICION ... a=RECORRIDO_MESA_2
    R-->>W: EVT LLEGO mesa=2 orden=17631234567
    Note over W: avisar al cliente: "tu café llegó"
    C->>W: tomé mi vaso (o la celda de carga marca menos de 50 g)
    W->>R: RETIRADO id=17631234890
    R-->>W: OK RETIRADO ... estado=REGRESO_BASE
    Note over W: HoraEntrega
    R-->>W: EVT TRANSICION a=REGRESO_BASE causa=vaso_retirado
    R-->>W: EVT TRANSICION a=ESPERANDO_ORDEN causa=en_base
    Note over W: HoraRegresoBase, Incidencia; el robot queda libre
```

**Si nadie toma el vaso:** después de `t_entrega` segundos el robot regresa solo, con el vaso; `causa=t_entrega`. En operación real usen `--entrega 180` (NFR-01). Eso cuenta como incidencia `Vaso`.

## 5. Reglas que la plataforma debe respetar

1. **Un pedido a la vez.** El robot lleva un vaso. Solo acepta `ORDEN` en `ESPERANDO_ORDEN`; en cualquier otro estado responde `ERROR ORDEN ... OCUPADO`. La cola de pedidos es de ustedes. Habiliten el botón «Enviar» solo si `robot.libre`.
2. **El robot sale cuando el barista lo dice**, no cuando se crea el pedido, porque el vaso tiene que estar físicamente encima.
3. **Ids siempre crecientes** en cada mensaje (no son los folios). Usen el generador del cliente: décimas de segundo desde 1970. Las demás herramientas usan el mismo esquema, así que pueden convivir. Un id menor o igual al último se rechaza con `ID_REPETIDO`.
4. **Reintentar con el mismo id.** Si no llega respuesta en 2 s, reenvíen el mismo mensaje con el **mismo** id, hasta 3 veces. El robot no repite la acción: contesta lo mismo que la primera vez.
5. **Usen la hora de su computadora.** El campo `t=` de los eventos son segundos desde que arrancó `main_real.py`, no una hora del día.
6. **Si se cae la conexión, el robot sigue.** Termina lo que estaba haciendo. Al reconectarse manden `ESTADO` para ponerse al día; el cliente ya lo hace. Los eventos que pasaron mientras estaban desconectados **no se reenvían**.
7. **`RETIRADO` solo vale en `EN_MESA`.** En otro estado responde `NO_PERMITIDO`.
8. **`CANCELAR` solo vale de ida** (`RECORRIDO_MESA_n`) y requiere el id de la orden: `CANCELAR id=... orden=<id de la ORDEN>`.
9. **`RESET` solo vale en `ERROR`**, y solo **después** de que una persona lleve el robot a mano a la base, mirando al frente. Pongan esa instrucción en la pantalla del operador.
10. **Pueden conectarse hasta 4 clientes a la vez.** Por ejemplo, el backend más `consola_ordenes.py` para depurar. Todos reciben todas las respuestas y todos los eventos; el cliente ignora las respuestas que no son suyas. En producción, solo el backend debe mandar órdenes.

## 6. Qué mostrar en pantalla

Estados de **un pedido** según `SeguimientoPedidos`. Los nombres de la columna «Pantalla» son una propuesta tomada del diagrama de flujo del servicio (19 oct): `<RELLENAR>` con los nombres de su base de datos.

| Viaje (`Viaje.estado`) | Cuándo | Pantalla sugerida |
|---|---|---|
| — | pedido creado, café en preparación | Preparando |
| — | barista marcó listo | Listo |
| `EN_CAMINO` | `OK ORDEN` | En camino |
| `DETENIDO` | obstáculo, WiFi, pausa o atasco; `detalle` trae la causa | En camino (detenido) |
| `EN_MESA` | `EVT LLEGO` | Entregado: avisar al cliente (FR-05) |
| `REGRESANDO` | regresa; `motivo_regreso` = `entregado`, `sin_retirar` o `cancelado` | Entregado / No entregado / Cancelado |
| `CERRADO` | robot en la base; el viaje terminó | (igual) y el robot queda libre |
| `RECHAZADO` | el robot no salió; `detalle` = `OCUPADO`, `FUERA_DE_BASE`… | Listo (volver a intentar) |
| `FALLA` | `EVT ERROR`; el robot queda quieto | Falla: llamar al operador |

Estados del **robot** para el panel del operador:

| Estado | Mensaje sugerido |
|---|---|
| `INICIALIZANDO` | Calibrando, no mover el robot (tarda unos segundos) |
| `ESPERANDO_ORDEN` | Libre en la base |
| `RECORRIDO_MESA_n` | Yendo a la mesa n |
| `EN_MESA` | Esperando que tomen el vaso |
| `REGRESO_BASE` | Regresando |
| `DETENIDO` | Detenido (causa); reanuda solo |
| `ERROR` | Error (código): llevarlo a la base a mano y presionar RESET |

## 7. Checklist de integración

- [ ] El backend se conecta al simulador y muestra `ESPERANDO_ORDEN`.
- [ ] Crear pedido → listo → enviar → el simulador va a la mesa → aparece «Entregado».
- [ ] El botón «Tomé mi café» manda `RETIRADO` y el robot regresa de inmediato.
- [ ] Si nadie lo toma, el pedido termina con incidencia `Vaso`.
- [ ] Mandar con el robot ocupado muestra el motivo y no rompe nada.
- [ ] `obstaculo` y `corte` en el simulador → la pantalla muestra «detenido» y luego sigue.
- [ ] `salto` en el simulador → «Falla» → RESET desde el panel → vuelve a `ESPERANDO_ORDEN`.
- [ ] Apagar el backend a medio viaje y prenderlo → el pedido se cierra con la hora aproximada.
- [ ] Los pedidos exportan las columnas de la hoja «Pedidos» ([07](07_datos_dashboard.md)).
- [ ] Prueba con el robot real: `main_real.py` en lugar del simulador; el backend no cambia.

## 8. Lo que todavía no está decidido y les afecta

- **Quién manda `RETIRADO`:** el botón en la app, la celda de carga (que llega a la computadora por Bluetooth) o ambos. Sugerencia: ambos, y el primero que llegue gana. `<RELLENAR>`
- **Si el robot sale solo** cuando la celda de carga marca más de 150 g en la base, o solo con el botón del barista. `<RELLENAR>`
- **La confirmación de llegada con cámara** que aparece en el diagrama de flujo **no existe** en este código. La llegada se decide con la odometría (`EVT LLEGO`). `<RELLENAR>`

Más detalles en [09](09_pendientes_y_contradicciones.md).
