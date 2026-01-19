from gpiozero import MotionSensor
from signal import pause
import time

PIR_PIN = 23  # BCM番号

pir = MotionSensor(PIR_PIN)

print("PIR test started")
print("人が動くと 'MOTION!'、止まると 'IDLE' が表示されます")
print("Ctrl+C で終了\n")

def on_motion():
    print(f"[{time.strftime('%H:%M:%S')}] MOTION!", flush=True)

def on_no_motion():
    print(f"[{time.strftime('%H:%M:%S')}] IDLE", flush=True)

pir.when_motion = on_motion
pir.when_no_motion = on_no_motion

pause()  # 無限待機
