# Datos para el dashboard

El dashboard de Ingeniería Industrial lee dos hojas, «Pedidos» y «Robot», con los nombres de columna exactos de abajo. Hay dos formas de llenarlas:

- **Hoy, en pruebas:** con `registro_pruebas.py`, que usa un operador en la terminal.
- **Después:** con la plataforma web, de forma automática. `cliente/ejemplo_fastapi.py` ya llena las columnas con la misma lógica.

**Formato:** horas como `2026-11-12 10:41:20` (hora de la computadora), decimales con punto y CSV en UTF-8 con BOM, para que Excel respete los acentos.

## Hoja «Pedidos»: una fila por pedido

| Columna | Obligatoria | Quién la pone | Momento exacto |
|---|---|---|---|
| `Folio` | sí | Plataforma | Al crear el pedido (`P-0001`, …) |
| `HoraPedido` | sí | Plataforma | El cliente confirma el pedido |
| `Producto` | sí | Plataforma | `C1` americano, `C2` latte, `C3` frappé |
| `Mesa` | — | Plataforma | 1, 2 o 3 |
| `Distancia_m` | — | Plataforma | De la tabla de distancias: 1.0, 2.0 y 3.0 m hoy; `<POR MEDIR>` con cinta |
| `HoraListo` | sí | Barista | Termina de preparar |
| `HoraInicioCarga` | sí | Barista | Pone el vaso en el robot y presiona «Enviar» (en ese momento se manda `ORDEN`) |
| `HoraEntrega` | sí | Cliente o celda de carga | El cliente toma el vaso: se manda `RETIRADO` |
| `HoraRegresoBase` | sí | **Robot** | `EVT TRANSICION a=ESPERANDO_ORDEN causa=en_base` |
| `Incidencia` | — | Robot y operador | `Ninguna`, `Navegación` o `Vaso` (reglas abajo) |
| `PesoCarga_g` | — | Báscula o celda de carga | Con el vaso en el robot, antes de salir |
| `PesoEntrega_g` | — | Báscula o celda de carga | En la mesa, **antes** de que lo retiren |

**Reglas de `Incidencia`,** iguales en `registro_pruebas.py` y en `robocoffe_cliente.py`:

| Valor | Cuándo |
|---|---|
| `Navegación` | Hubo `ERROR`, o `DETENIDO` por `ATASCO`, durante el viaje. También si el pedido se cancela (`<RELLENAR>`: confirmar que un pedido cancelado cuenta así) |
| `Vaso` | Nadie tomó el vaso a tiempo (`causa=t_entrega`), o el operador lo marca (derrame, vaso caído) |
| `Ninguna` | El viaje cerró en la base sin nada de lo anterior |

Un `DETENIDO` por `OBSTACULO`, `ENLACE` (WiFi) o `PAUSA` **no** es incidencia.

**Columna extra útil:** `HoraLlegadaMesa`, que viene de `EVT LLEGO`. El dashboard no la pide, pero separa el tiempo de traslado del tiempo de espera del cliente. La plataforma la tiene gratis.

## Hoja «Robot»: una fila por turno

| Columna | Cómo se obtiene |
|---|---|
| `Fecha` | Día del turno |
| `InicioTurno` | Primera vez que el robot queda en `ESPERANDO_ORDEN` |
| `FinTurno` | El operador cierra el turno |
| `Recargas` | Número de veces que se cargó la batería en el turno |
| `MinRecarga` | Minutos totales de recarga |
| `MinParoFalla` | Minutos en `DETENIDO` o `ERROR`, **sin contar** `PAUSA` ni `OBSTACULO` |
| `Observaciones` | Notas del operador |

## Hoy: `registro_pruebas.py`

```bash
python main_real.py --host <ip del robot> --entrega 180      # terminal 1
python registro_pruebas.py                                   # terminal 2
```

**Ciclo de cada café:**

1. `PEDIDO`: toma el siguiente del plan balanceado de 30 (10 por producto y 10 por mesa).
2. `LISTO`
3. `CARGA 352.4`: peso en gramos. El robot sale.
4. `ENTREGA 351.9`: el peso se lee **antes** de que el cliente quite el vaso. El robot regresa.

`HoraRegresoBase` se registra sola. Otros comandos:

| Comando | Para qué |
|---|---|
| `VASO`, `NAV` | Marcar una incidencia |
| `NOTA <texto>` | Agregar una observación |
| `RECARGA` | Inicio y fin de una recarga |
| `RESUMEN` | Avance contra el plan |
| `SALIR` | Cierra el turno y escribe el Excel |

**Archivos** (carpeta `datos_pruebas_<fecha>/`):

- `Pedidos.csv` y `Robot.csv`: se reescriben después de cada cambio, así que si algo se cae no se pierde nada.
- `eventos.log`: todo lo que dijo el robot, con hora.
- `plan_30_entregas.csv`
- `Pruebas_RoboCoffe_<fecha>.xlsx`: hojas Pedidos, Robot y Receta. Necesita `openpyxl`.

**Si se cierra el programa,** al volver a abrirlo el mismo día continúa los folios y el plan.

## Después: la plataforma

- `SeguimientoPedidos` de `cliente/robocoffe_cliente.py` regresa por cada viaje:
  - `hora_salida`, `hora_llegada_mesa`, `hora_entrega` y `hora_regreso_base`;
  - `incidencia` y `motivo_regreso` (`entregado`, `sin_retirar` o `cancelado`).
- `ejemplo_fastapi.py` copia esos campos a las columnas de arriba. La plataforma solo agrega lo que ya es suyo: `Folio`, `HoraPedido`, `Producto`, `Mesa`, `HoraListo`, `HoraInicioCarga` y los pesos.
- **Exportar:** un endpoint que escriba `Pedidos.csv` con `COL_PEDIDOS` en ese orden. La lista está en `registro_pruebas.py`; conviene importarla de ahí para que nunca diverja.
