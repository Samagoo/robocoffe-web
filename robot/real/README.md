# Calibración del robot real

Herramientas de calibración de bajo nivel. Antes de correrlas, editen `HOST` con la IP del robot.

| Script | Qué mide | Cuándo usarlo |
|---|---|---|
| `calib_odometria.py` | Reinicio de pose, deriva del giroscopio, radio efectivo de rueda, separación L y CPR | Si el robot se queda corto o se pasa **siempre** por la misma cantidad (problema de odometría, no de control) |
| `prueba_zona_muerta.py` | La velocidad mínima de rueda que realmente mueve el robot en línea recta | Para ajustar `W_MIN_RECTA` en `robocoffe_fsm/movimiento.py` y `probar_movimiento.py` |

Los resultados se agregan a `calib_resultados.txt`. Si cambian ρ, L o el CPR, actualicen `docs/04_movimiento.md` y los valores en `movimiento.py`.
