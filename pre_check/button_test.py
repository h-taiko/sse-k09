from gpiozero import Button
import time

btn1 = Button(16, pull_up=True)
btn2 = Button(20, pull_up=True)
btn3 = Button(21, pull_up=True)

print("Button test (GPIO16/20/21)")

try:
    while True:
        if btn1.is_pressed:
            print("Button 1", flush=True)
            time.sleep(0.3)
        if btn2.is_pressed:
            print("Button 2", flush=True)
            time.sleep(0.3)
        if btn3.is_pressed:
            print("Button 3", flush=True)
            time.sleep(0.3)
        time.sleep(0.01)
except KeyboardInterrupt:
    print("\nbye")
