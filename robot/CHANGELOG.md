# Historial de cambios

## 2026-11-13 · Entrega al equipo de la plataforma web

- **Simulador:** `servidor_simulado.py`, un robot simulado por TCP que habla el mismo protocolo, con fallas que se provocan desde la terminal.
- **Cliente:**
  - `cliente/robocoffe_cliente.py`: cliente asyncio con reconexión, ids, reintentos y seguimiento de cada pedido.
  - `cliente/ejemplo_fastapi.py`: backend de ejemplo.
  - `cliente/demo_seguimiento.py`: demostración y prueba del cliente.
- **Canal TCP:** `CanalTCP` acepta hasta 4 clientes a la vez (antes, uno); respuestas y eventos van a todos.
- **Ids:**
  - Las herramientas usan el mismo esquema, `int(time.time() * 10)`, sin módulo 10⁹. El módulo hacía que los ids se reiniciaran en enero de 2027.
  - **No mezclar con copias viejas** de `consola_ordenes.py`, `enviar_orden.py` o `registro_pruebas.py`.
- **Consola:** `consola_ordenes.py` acepta `RETIRADO`.
- **Arranque con robot real:** `main_real.py` y `probar_movimiento.py` esperan hasta 15 s la respuesta de `imu.calibrate` (antes, 1 s: se iba a ERROR al arrancar).
- **Webots:** `sincronizar_webots.py` y `tests/test_copias_sincronizadas.py` mantienen igual la copia del paquete en el controlador.
- **Documentación:** completa en `docs/`.

## 2026-11-12

- Tres mesas en fila a 1, 2 y 3 m; regreso opcional en reversa.
- `RETIRADO` por TCP.
- `registro_pruebas.py` para el dashboard.
- Webots: `oak9_entregas.wbt` y `MesaCafe.proto`.
- Manejo de cortes de WiFi y de respuestas tardías en `probar_movimiento.py`.

## 2026-11-02

- **Diagnóstico de `go2point`:** giros ~38° cortos y avances ~5 cm cortos.
- **`NavegadorPC`:** lazo cerrado sobre la pose medida, igual en Webots y en el robot real.

## Antes

Diseño de la máquina de estados (9 estados, T1–T17) y del protocolo de una línea (opción A).
