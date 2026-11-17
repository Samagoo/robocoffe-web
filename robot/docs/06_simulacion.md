# Simulación

Hay tres formas de correr la máquina sin el robot. Las tres usan **la misma** máquina de estados.

| Opción | Robot | Protocolo TCP 9000 | Para qué |
|---|---|---|---|
| `servidor_simulado.py` | Cinemático, en memoria | Sí | **Desarrollar la plataforma web.** Arranca en 1 s y no necesita nada instalado |
| Webots, `oak9_entregas.wbt` | Físico, en 3D | Sí | Ver el recorrido, comparar sim contra real, presentaciones |
| `main_sim.py` y `tests/` | Cinemático, con reloj simulado | No | Probar la lógica en segundos |

## `servidor_simulado.py`

```bash
python servidor_simulado.py                         # tiempo real; espera 10 s en la mesa
python servidor_simulado.py --entrega 180           # espera como en operación (NFR-01)
python servidor_simulado.py --rapido 10             # 10 veces más rápido
python servidor_simulado.py --reversa               # regresa de espaldas
python servidor_simulado.py --puerto 9001           # otro puerto
```

Fallas que se pueden provocar escribiendo en su terminal:

| Escribe | Pasa | Lo que debe ver la plataforma |
|---|---|---|
| `obstaculo` | Algo frente al robot durante 4 s | `DETENIDO causa=OBSTACULO`; sigue solo |
| `corte` | Se cae el WiFi del robot durante 3 s | `DETENIDO causa=ENLACE`; sigue solo |
| `atasco` | Las ruedas no avanzan durante 5 s | `DETENIDO causa=ATASCO`, incidencia Navegación |
| `salto` | La pose salta 0.5 m | `ERROR E_SALTO_POSE`; se sale con `RESET` |
| `estado` | Imprime estado, pose y clientes conectados | — |

Las fallas solo tienen efecto mientras el robot va en camino. Un obstáculo con el robot en la base no hace nada.

**Lo que no simula:** aceleraciones, derrape, zona muerta, batería real (siempre 7.8 V) ni la celda de carga. El `RETIRADO` lo manda la plataforma.

## Webots

El proyecto está en `webots/`. Probado en Webots **R2025a**.

**Mundos:**

- `worlds/oak9_entregas.wbt`: modo interactivo; escucha en el puerto 9000.
- `worlds/oak9_entregas_demo.wbt`: hace MESA1, MESA2 y MESA3 seguidas, sin TCP.

**Disposición:** base en (0, 0); puntos de entrega en x = 1, 2 y 3 m; mesas `MesaCafe` a la derecha, con centro en y = −0.50.

**`MesaCafe`:** es la `RoundTable` de Webots con diámetro y altura como campos (0.70 m y 0.76 m por defecto). Hizo falta porque `RoundTable` mide 2 m y un Solid no se puede escalar. Medidas de la mesa real: `<POR MEDIR>`.

**Cómo darle órdenes:**

- **Teclado** (primero haz clic en la vista 3D):
  - `1`, `2`, `3`: ORDEN a esa mesa.
  - `R`: el cliente retiró el vaso.
  - `P`: pausa o reanudar.
  - `C`: cancelar.
  - `X`: RESET.
  - `E`: ESTADO.
- **Terminal o plataforma:** igual que con el robot real, al puerto 9000. Por ejemplo, `python consola_ordenes.py`.

**`controllerArgs`** (en el `.wbt`):

| Argumento | Qué hace | Por defecto |
|---|---|---|
| `modo` | `interactivo` o `demo` | `interactivo` |
| `puerto` | Puerto TCP; `0` = sin TCP | 9000 |
| `reversa` | `1` = regresa de espaldas | 0 |
| `entrega` | Segundos de espera en la mesa | 10 |
| `zona_muerta` | Grados/s de rueda que no mueven el motor; emula el OAK9 | 0 |
| `v` | Velocidad de avance, m/s | 0.10 |

**Registros:** `controllers/oak9_entregas/log_entregas.csv` guarda la pose estimada y la real cada 40 ms. `transiciones_webots.csv` guarda una línea por transición.

**Copia del paquete.** `webots/controllers/oak9_entregas/robocoffe_fsm/` es una **copia** de `robocoffe_fsm/`, porque Webots necesita el código junto al controlador. Después de cambiar el paquete:

```bash
python sincronizar_webots.py
```

La prueba `tests/test_copias_sincronizadas.py` falla si las copias difieren.

**Proyecto completo.** CAD, URDF, herramientas de inercias y comparaciones sin café contra con café: `robocoffe_webots_v3.zip` (proyecto de simulación del equipo). Aquí solo va lo necesario para correr las entregas.
