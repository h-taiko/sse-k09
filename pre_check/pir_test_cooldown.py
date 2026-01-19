from gpiozero import MotionSensor
from signal import pause
import time

PIR_PIN = 23
COOLDOWN_SEC = 5

pir = MotionSensor(PIR_PIN)

print("PIR test (cooldown)")
print("動いた瞬間だけ表示します。Ctrl+Cで終了")
print(f"トリガ後 {COOLDOWN_SEC}s は無視\n")

last = 0.0

def on_motion():
    global last
    now = time.time()
    if now - last < COOLDOWN_SEC:
        return
    last = now
    print(f"[{time.strftime('%H:%M:%S')}] MOTION TRIGGER", flush=True)

pir.when_motion = on_motion
pause()
