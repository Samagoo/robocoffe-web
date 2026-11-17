"""
OAK9 -- odometry & IMU diagnostic / calibration (run BEFORE trusting oak9_linea_recta_real.py).

  Test 0  reset check     : do encoder.reset()/pose.set() really reset the pose? (no motion)
  Test 1  IMU still       : gyro bias calibration + yaw drift with the robot standing still
  Test 2  straight line   : open-loop forward run, you measure the REAL distance with a tape
                            -> effective wheel radius per wheel, suggested CPR, left/right asymmetry
  Test 3  rotation        : in-place rotation, you count the REAL turns
                            -> effective track width L, IMU yaw scale

  Test 4  CPR by hand      : turn each wheel exactly 1 turn by hand -> encoder must read 360 deg

Usage:  python calib_odometria.py            (tests 0-3)
        python calib_odometria.py 4 2 3      (only the tests you list, in that order)
        Ctrl+C at any time stops the motors
Results are appended to calib_resultados.txt
"""
import math
import time

from oak9 import Robot

HOST = "192.168.137.134"    # IP of YOUR robot (from calib_resultados.txt)
RHO_NOM = 0.034             # [m] nominal wheel radius
STRAIGHT_DEG_S = 90.0       # wheel speed for test 2 (~0.053 m/s)
STRAIGHT_TIME = 8.0         # [s] -> ~0.43 m
ROT_DEG_S = 60.0            # wheel speed for test 3 (opposite signs)
DRIFT_TIME = 30.0           # [s] test 1

OUT = "calib_resultados.txt"


def call(r, fn, *args, retries=2, **kw):
    """Run one oak9lib call; on a TCP timeout/drop, reconnect (this also clears any
    late reply left in the buffer) and retry. Only for commands that are safe to repeat."""
    for attempt in range(retries + 1):
        try:
            return fn(*args, **kw)
        except (TimeoutError, ConnectionError, OSError) as ex:
            if attempt == retries:
                raise
            print(f"  [red] {type(ex).__name__} -> reconectando y reintentando ({attempt + 1}/{retries})...")
            time.sleep(0.5)
            r._transport.connect()


def safe_stop(r):
    """Stop the wheels even if the connection just dropped."""
    try:
        call(r, r.wheel_velocity.stop)
    except Exception as ex:
        print(f"  [!] NO se pudo mandar stop ({ex}). Apaga el robot con el interruptor.")


def log(msg):
    print(msg)
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def snap(r):
    e = call(r, r.encoder.read)
    p = call(r, r.pose.get)
    y = call(r, r.imu.attitude_get)
    return {"l": e["left_deg"], "r": e["right_deg"], "x": p["x_mm"], "y": p["y_mm"],
            "th": p["theta_deg"], "yaw": y.get("yaw", float("nan"))}


def ask_float(prompt, default=None):
    """Repeat until the user types a valid number (Enter alone -> default, if any)."""
    while True:
        txt = input(prompt + (f" [Enter = {default}]: " if default is not None else ": ")).strip()
        if not txt and default is not None:
            return float(default)
        try:
            return float(txt.replace(",", "."))
        except ValueError:
            print("  -> escribe solo un numero (ej. 38.5)")


def wrap180(a):
    return (a + 180.0) % 360.0 - 180.0


def test0(r):
    log("\n=== TEST 0: reset check (robot still) ===")
    log(f"before : pose={r.pose.get()['raw_line']}  enc={r.encoder.read()['raw_line']}")
    r.encoder.reset(); time.sleep(0.2)
    log(f"after encoder.reset : pose={r.pose.get()['raw_line']}")
    r.pose.set(x_mm=0, y_mm=0, theta_deg=0); time.sleep(0.2)
    p = r.pose.get()
    log(f"after pose.set(0,0,0): pose={p['raw_line']}")
    ok = abs(p["x_mm"]) < 5 and abs(p["y_mm"]) < 5 and abs(p["theta_deg"]) < 1
    log("RESULT: " + ("OK, pose resets correctly" if ok else
                      "FAIL -> the pose does NOT reset: errors accumulate between runs"))


def test1(r):
    log("\n=== TEST 1: IMU still (do NOT touch the robot) ===")
    input("Robot on the floor, completely still. Press Enter to calibrate the IMU...")
    log(f"imu.calibrate -> {r.imu.calibrate()['raw_line']}")
    time.sleep(1.0)
    y0 = r.imu.attitude_get()["yaw"]; t0 = time.monotonic()
    time.sleep(DRIFT_TIME)
    y1 = r.imu.attitude_get()["yaw"]
    drift = wrap180(y1 - y0) / (time.monotonic() - t0) * 60.0
    log(f"yaw drift = {drift:.2f} deg/min  (still robot; a 1 m run at 0.1 m/s takes ~10 s)")
    log("RESULT: " + ("OK" if abs(drift) < 1.0 else "HIGH drift -> recalibrate, check MPU6050 mounting/vibration"))


def test2(r):
    log("\n=== TEST 2: straight line, open loop ===")
    input(f"Mark the floor at the centre between the wheels. {STRAIGHT_DEG_S} deg/s for "
          f"{STRAIGHT_TIME} s (~{math.radians(STRAIGHT_DEG_S)*RHO_NOM*STRAIGHT_TIME*100:.0f} cm). Enter to start...")
    call(r, r.encoder.reset); time.sleep(0.2)
    call(r, r.pose.set, x_mm=0, y_mm=0, theta_deg=0); time.sleep(0.2)
    a = snap(r)
    call(r, r.wheel_velocity.set, left=STRAIGHT_DEG_S, right=STRAIGHT_DEG_S)
    time.sleep(STRAIGHT_TIME)
    safe_stop(r); time.sleep(0.5)
    b = snap(r)
    d_real = 10.0 * ask_float("Distancia REAL recorrida, en CENTIMETROS (ej. 38.5)")
    lat = 10.0 * ask_float("Desviacion lateral REAL en CENTIMETROS (izq +, der -)", 0)
    dl, dr = b["l"] - a["l"], b["r"] - a["r"]
    rho_l = d_real / 1000.0 / math.radians(dl) if dl else float("nan")
    rho_r = d_real / 1000.0 / math.radians(dr) if dr else float("nan")
    rho_eff = 0.5 * (rho_l + rho_r)
    d_odo = math.hypot(b["x"] - a["x"], b["y"] - a["y"])
    log(f"encoders: left={dl:.1f} deg  right={dr:.1f} deg  (expected each ~{math.degrees(d_real/1000/RHO_NOM):.1f})")
    log(f"pose: travelled {d_odo:.1f} mm  (real {d_real:.1f})  ratio real/odo = {d_real/d_odo if d_odo else float('nan'):.3f}")
    log(f"pose: dtheta={wrap180(b['th']-a['th']):.2f} deg   imu: dyaw={wrap180(b['yaw']-a['yaw']):.2f} deg   real lateral={lat:.1f} mm")
    log(f"effective radius: left={rho_l*1000:.2f} mm  right={rho_r*1000:.2f} mm  mean={rho_eff*1000:.2f} mm")
    if dl * dr <= 0:
        log("RESULT: FAIL -> one encoder counts BACKWARDS (or not at all). Fix encoder.invert_set first.")
        return
    asym = abs(rho_l - rho_r) / rho_eff * 100
    cpr = r.encoder.cpr_get()
    log(f"current CPR: {cpr['raw_line']}")
    if "cpr" in cpr:
        log(f"suggested CPR (keeping rho={RHO_NOM*1000:.0f} mm): {cpr['cpr'] * RHO_NOM / rho_eff:.0f}")
    log(f"left/right asymmetry = {asym:.1f} %  " + ("OK" if asym < 2 else "-> HIGH: robot will curve while odometry believes it goes straight"))


def test3(r):
    log("\n=== TEST 3: in-place rotation ===")
    input("Put a tape mark on the floor aligned with the robot's front. Enter to start rotating (CCW)...")
    call(r, r.encoder.reset); time.sleep(0.2)
    call(r, r.pose.set, x_mm=0, y_mm=0, theta_deg=0); time.sleep(0.2)
    a = snap(r)
    call(r, r.wheel_velocity.set, left=-ROT_DEG_S, right=ROT_DEG_S)
    input("Press Enter EXACTLY when the robot is aligned with the mark again after 1 full turn...")
    safe_stop(r); time.sleep(0.5)
    b = snap(r)
    turns = ask_float("Numero REAL de vueltas completas", 1)
    th_real = 2 * math.pi * turns
    dl, dr = math.radians(b["l"] - a["l"]), math.radians(b["r"] - a["r"])
    g = call(r, r.geometry.get)
    rho = g.get("wheel_radius_mm", RHO_NOM * 1000) / 1000.0
    L_eff = rho * (dr - dl) / th_real
    log(f"encoders: left={math.degrees(dl):.1f} deg  right={math.degrees(dr):.1f} deg")
    log(f"pose theta (unwrapped not available, check by eye) final={b['th']:.1f} deg  imu yaw final={b['yaw']:.1f} deg")
    log(f"geometry in firmware: {g['raw_line']}")
    log(f"effective track width L = {L_eff*1000:.1f} mm  (use it in geometry.set and in Webots)")


def test4(r):
    log("\n=== TEST 4: CPR check, wheel turned BY HAND (robot lifted, motors stopped) ===")
    r.wheel_velocity.stop()
    for side in ("left", "right"):
        input(f"Marca la llanta {side.upper()} con cinta. Enter, luego gira esa rueda a mano "
              f"EXACTAMENTE 1 vuelta HACIA ADELANTE...")
        r.encoder.reset(); time.sleep(0.2)
        input("Cuando termines la vuelta, presiona Enter...")
        e = r.encoder.read()
        deg = e[f"{side}_deg"]
        log(f"{side}: encoder = {deg:.1f} deg (expected 360)  raw={e['raw_line']}")
        if abs(deg) > 1:
            log(f"  -> CPR real aprox = {r.encoder.cpr_get().get('cpr', 1336) * abs(deg) / 360.0:.0f}")


def main():
    r = Robot(HOST, timeout=3.0)
    try:
        log(f"\n######## {time.strftime('%Y-%m-%d %H:%M:%S')}  host={HOST}")
        log(f"geometry={r.geometry.get()['raw_line']}  cpr={r.encoder.cpr_get()['raw_line']}")
        log(f"invert motor={r.motor.invert_get()['raw_line']}  encoder={r.encoder.invert_get()['raw_line']}")
        import sys
        tests = sys.argv[1:] or ["0", "1", "2", "3"]        # e.g.  python calib_odometria.py 4 2
        for t in tests:
            {"0": test0, "1": test1, "2": test2, "3": test3, "4": test4}[t](r)
        log("\nDone. Send calib_resultados.txt for analysis.")
    finally:
        try:
            safe_stop(r)
        finally:
            r.close()


if __name__ == "__main__":
    main()
