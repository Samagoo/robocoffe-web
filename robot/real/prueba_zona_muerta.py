"""
Measures the wheel dead band of the OAK9: the smallest commanded speed that actually turns
each wheel, with the robot ON THE FLOOR (the friction that matters is the real one).

The command ramps from 4 to 60 deg/s in 2 deg/s steps (both wheels, forward); each step lasts
STEP_S seconds and the encoder advance is measured. The robot moves forward at most ~25 cm.
Result -> put a value a little above it in W_MIN (oak9_ida_vuelta_real.py).

Usage:  python prueba_zona_muerta.py
"""
import time

from oak9 import Robot

HOST = "192.168.137.134"
STEP_S = 0.8          # [s] per speed step
MOVE_DEG = 3.0        # [deg] encoder advance within one step that counts as "moving"


def main():
    r = Robot(HOST, timeout=3.0)
    found = {"left": None, "right": None}
    try:
        r.wheel_velocity.stop()
        time.sleep(0.5)
        for v in range(4, 62, 2):
            e0 = r.encoder.read()
            r.wheel_velocity.set(left=v, right=v)
            time.sleep(STEP_S)
            e1 = r.encoder.read()
            dl, dr = e1["left_deg"] - e0["left_deg"], e1["right_deg"] - e0["right_deg"]
            print(f"cmd {v:3d} deg/s  ->  left {dl:6.1f} deg   right {dr:6.1f} deg")
            for side, d in (("left", dl), ("right", dr)):
                if found[side] is None and d > MOVE_DEG:
                    found[side] = v
            if found["left"] and found["right"]:
                break
    finally:
        r.wheel_velocity.stop()
        r.close()
    print(f"\nDead band: left starts at {found['left']} deg/s, right at {found['right']} deg/s")
    if found["left"] and found["right"]:
        print(f"Suggested W_MIN = math.radians({max(found.values()) + 5}.0)")


if __name__ == "__main__":
    main()
