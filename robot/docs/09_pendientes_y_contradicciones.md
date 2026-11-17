# Pendientes, contradicciones y límites conocidos

Estado al 13 nov 2026.

## Qué está probado y qué no

| Qué | Estado |
|---|---|
| Máquina de estados: T1–T17 y reglas del protocolo | 27 pruebas automáticas pasan |
| La copia de Webots es igual al paquete | 1 prueba automática pasa |
| `servidor_simulado.py` con 2 clientes a la vez | Probado |
| `cliente/robocoffe_cliente.py`: los tres casos de pedido, rechazo por robot ocupado y reconexión a medio viaje | Probado contra el simulador (`demo_seguimiento.py`) |
| `cliente/ejemplo_fastapi.py` | Lógica de los endpoints probada contra el simulador, pero **sin FastAPI real**, porque no se pudo instalar en el entorno donde se armó. Falta correrlo con `uvicorn` |
| `main_real.py` con firmware falso (calibración de 3 s y cortes de WiFi) | Probado: orden a MESA1 completa, error de 9 mm |
| `probar_movimiento.py` con el robot real | Probado el 12 nov: llegó a MESA2 con buen seguimiento; hubo cortes de WiFi, ya manejados |
| `main_real.py` completo con el robot real | **Pendiente.** Siguiente paso de la prueba física |
| Webots, tres mesas seguidas | Probado: −9 mm en mesas y +9 a +10 mm en la base |
| Error de llegada real en el piso (medición externa) | `<POR MEDIR>` |

## Datos por medir (`<POR MEDIR>`)

| Dato | Dónde se pone | Cómo |
|---|---|---|
| Distancia real de la base a cada mesa | `rutas.py` (`D_MESAS`) y `registro_pruebas.py` (`DISTANCIA_M`) | Cinta, de o1 en la base a o1 en el punto de entrega |
| `bat_min` y `bat_crit` | `config.py` | `battery.read` con la batería llena y cuando el robot empieza a fallar. El 12 nov arrancó con 8.18 V |
| `d_obst` (0.25 m) | `config.py` | Distancia a la que el robot alcanza a frenar a 0.10 m/s |
| `W_MIN_GIRO` (45 °/s) y `W_MIN_RECTA` (30 °/s) | `movimiento.py` y `probar_movimiento.py` | Giro: `GIRAR 90` subiendo de 5 en 5. Recta: `real/prueba_zona_muerta.py` |
| Error de llegada en el piso | Informe y artículo | Visión (OpenCV) o cinta, contra el punto pedido |
| Si el firmware real acumula θ fuera de ±180° | Plataforma (normalizar al mostrar) | Ver `th` en `ESTADO` después de varios viajes |
| Medidas de la mesa real | `MesaCafe` en el `.wbt` | Cinta |

## Decisiones del equipo (`<RELLENAR>`)

| Decisión | Opciones | Afecta a |
|---|---|---|
| `FRONTALES`: qué ultrasónicos miran al frente | Ver las claves que regresa `ultrasonic.read()` | **Seguridad:** sin esto no hay detección de obstáculos |
| Quién manda `RETIRADO` | Botón en la app, celda de carga (< 50 g) o ambos | Plataforma |
| Si el robot sale solo con la celda (> 150 g) o con el botón del barista | — | Plataforma |
| `t_entrega` en operación | 180 s según NFR-01 | `--entrega` |
| `regreso_en_reversa` | Ahorra ~24 s en tres entregas (Webots) a cambio de manejar de espaldas | `config.py` |
| `tol_pos` final (hoy 3 cm) | Después de medir el error real | `config.py` |
| Nombres de los estados del pedido en la app | Ver la contradicción 1 | Plataforma |
| ¿Un pedido cancelado cuenta como incidencia de navegación? | Hoy sí, igual que en `registro_pruebas.py` | Dashboard |

## Contradicciones entre documentos

1. **Nombres de los estados del pedido.**
   - Las instrucciones del proyecto dicen *Pendiente → En tránsito → Entregado*.
   - El diagrama de flujo del servicio (19 oct) dice *Preparando → En camino → Entregado*.
   - El ejemplo de FastAPI usa los del diagrama.
   - Hay que elegir uno.
2. **Confirmación de llegada.** El diagrama de flujo (paso 11) dice que la **cámara** confirma la llegada a B. Este código decide la llegada con la **odometría** (`EVT LLEGO`) y no usa ninguna cámara. Si se quiere la cámara, es un módulo aparte que tendría que mandar su confirmación a la plataforma.
3. **"Entregado".** En el diagrama de flujo, el pedido es *Entregado* cuando el robot **llega** (paso 12). En el dashboard, `HoraEntrega` es cuando el cliente **toma** el vaso. Aquí se guardan las dos: `HoraLlegadaMesa` y `HoraEntrega`.
4. **Tiempo en la mesa.** NFR-01 pide 180 s; `config.py` trae 10 s por defecto, porque es cómodo para pruebas. En operación usen `--entrega 180`.
5. **Documentos viejos.**
   - Estos documentos describían rutas con giros (*Mesa 2: 1 m a la derecha y 1 m más*, *Mesa 3: 1 m a la izquierda y 2 m al frente*) y el uso de `go2point` y `orientation.set`:
     - el README anterior de `robocoffe_fsm`;
     - la sección 5 del documento *Máquina de estados de entrega · OAK9 RoboCoffe* (Claude Docs).
   - **Vale lo de este folder:** tres mesas en línea recta a 1, 2 y 3 m (12 nov) y navegador de lazo cerrado.
   - La sección 5 de ese documento sigue pendiente de actualizar.
6. **IP de ejemplo.**
   - Los archivos traían `192.168.99.254` y `192.168.137.134`.
   - En la prueba del 12 nov el robot estaba en `192.168.1.173`.
   - Siempre pasen la IP como argumento.

## Límites conocidos

- **Un robot por proceso.** Para una flotilla habría que correr un `main_real.py` por robot, cada uno en otro puerto (`--puerto 9001`, …). La plataforma tendría que asignar los pedidos.
- **Sin autenticación** en el puerto 9000.
- **Sin repetición de eventos perdidos.** Si la plataforma se desconecta, los eventos de ese rato se pierden. `ESTADO` da el estado actual, no la historia; la historia completa queda en `transiciones_<fecha>.csv`.
- **La pose es odométrica.** No hay una referencia externa durante la operación: el error crece con los viajes. Si el robot se mueve a mano, hay que reiniciar con el robot en la base.
- **El simulador no modela** la dinámica, el derrape, la zona muerta ni la celda de carga.
