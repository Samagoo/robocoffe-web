# Problemas comunes

Todos los casos de esta tabla ya pasaron en pruebas y ya se corrigieron en el código.

| Síntoma | Causa | Qué hacer |
|---|---|---|
| `TimeoutError` al conectar (`probar_movimiento.py` o `main_real.py`) | La computadora no llega al robot | 1) La IP correcta del robot (cambia con la red). 2) Misma red WiFi. 3) Robot encendido y con batería. 4) Probar con `ping <ip>` |
| `TimeoutError` en `imu.calibrate` | La calibración del giroscopio tarda más de 1 s en responder | **Ya corregido:** espera hasta 15 s, y si no responde sigue sin recalibrar. Si sale el aviso, todo sigue normal |
| `TimeoutError` a medio movimiento; el robot "se traba" | Corte de WiFi | **Ya corregido:** pausa las ruedas, se reconecta y continúa el mismo tramo. Si pasa seguido, quitar el ahorro de energía del WiFi en Windows ([05](05_robot_real_paso_a_paso.md)), acercar el router o usar otro con menos tráfico |
| `KeyError: 'x_mm'` | Una respuesta tardía desfasó la conexión | **Ya corregido:** después de cualquier timeout se reconecta y valida cada respuesta |
| `AttributeError: … go2point` | Versión vieja de oak9lib | Ya no se usa `go2point`; el modo por defecto es el navegador de la computadora |
| Gira y no termina el giro, o oscila | Zona muerta de la rueda | Subir `W_MIN_GIRO` ([04](04_movimiento.md)) |
| `ERROR ORDEN … FUERA_DE_BASE` | La pose está a más de 5 cm o 5° de (0, 0, 0) | Si alguien movió el robot, regresarlo a la base y reiniciar `main_real.py` |
| `ERROR ORDEN … OCUPADO` | El robot no está en `ESPERANDO_ORDEN` | Esperar; habilitar el botón solo con `robot.libre` |
| `ERROR … ID_REPETIDO` | Id menor o igual al último | Usar el generador común de ids ([02](02_protocolo.md)). Pasa si se mezcla una herramienta **vieja** (ids con módulo 10⁹) con las de este folder |
| `ERROR ORDEN … OCUPADO` aunque el robot ya está libre, al reintentar | Se reintentó con el **mismo** id, y el robot repite la respuesta guardada | Para un intento nuevo, usar un id nuevo |
| `consola_ordenes.py`: "No me pude conectar a 127.0.0.1:9000" | `main_real.py`, el simulador o Webots no están corriendo (o Webots está en pausa) | Abrir uno primero; en Webots, presionar **Play** |
| El backend en otra computadora no se conecta al 9000 | Firewall de Windows en la computadora de `main_real.py` | Permitir Python en redes privadas, o una regla de entrada para el TCP 9000 |
| `OSError: [Errno 98/10048] Address already in use` | Ya hay algo escuchando en el 9000: otro `main_real.py`, el simulador o Webots | Cerrar el otro, o usar `--puerto 9001` |
| `Test-NetConnection` "no se reconoce" | Se escribió en `cmd`; solo existe en PowerShell | Abrir PowerShell, o usar `ping` |
| `enviar_orden.py: error: the following arguments are required: destino` | Faltó la mesa | `python enviar_orden.py MESA1` |
| `ERROR E_INIT:pose_no_reinicia` | El firmware no aceptó la pose en cero | Revisar la conexión; reiniciar el robot |
| `ERROR E_INIT:cpr=…` | El CPR del encoder no es 905 | Revisar la configuración del firmware |
| `DETENIDO causa=ENLACE` frecuente | WiFi inestable | Ver la fila de `TimeoutError` a medio movimiento |
| No se detiene ante una persona | Ultrasónicos sin configurar (`FRONTALES` es `<RELLENAR>`) | Configurar `FRONTALES` en `robot_oak9.py`; mientras tanto, vigilar el robot |
