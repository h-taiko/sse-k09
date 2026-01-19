# input_gpio.py
import time
import spidev
from gpiozero import Button, MotionSensor

def clamp(x, lo, hi):
    return max(lo, min(hi, x))

class MCP3008Reader:
    """
    MCP3008 (SPI) から 10bit値(0..1023) を読む
    bus=0, device=0 は SPI0 CE0 (/dev/spidev0.0)
    """
    def __init__(self, bus=0, device=0, max_speed_hz=1_000_000):
        self.spi = spidev.SpiDev()
        self.spi.open(bus, device)
        self.spi.max_speed_hz = max_speed_hz

    def read_channel_10bit(self, ch: int) -> int:
        if not (0 <= ch <= 7):
            raise ValueError("channel must be 0..7")
        r = self.spi.xfer2([1, (8 + ch) << 4, 0])
        return ((r[1] & 3) << 8) | r[2]

    def close(self):
        try:
            self.spi.close()
        except:
            pass

class GPIOInput:
    """
    人感(PIR) + ボタン1/2/3 + 可変抵抗(MCP3008)

    配線想定:
    - MCP3008: SPI0 CE0
    - 可変抵抗: CH0
    - ボタン: GPIO入力 + 内部pull-up（押すとGNDへ落ちる配線）
    - PIR: MotionSensor（反応で開始）
    """
    def __init__(
        self,
        pir_pin=23,
        btn1_pin=16,  
        btn2_pin=20,   
        btn3_pin=21,  
        spi_bus=0,
        spi_device=0,
        debounce_sec=0.03,
    ):
        self.pir = MotionSensor(pir_pin)

        # 押すとGNDに落ちる前提（pull_up=True）
        self.btn1 = Button(btn1_pin, pull_up=True, bounce_time=debounce_sec)
        self.btn2 = Button(btn2_pin, pull_up=True, bounce_time=debounce_sec)
        self.btn3 = Button(btn3_pin, pull_up=True, bounce_time=debounce_sec)

        self.adc = MCP3008Reader(bus=spi_bus, device=spi_device)

    def wait_for_presence(self):
        # 人が来るまで待機
        self.pir.wait_for_motion()

    def read_knobs01(self) -> dict:
        """
        CH0, CH1 を 0.0〜1.0 に正規化して返す
        """
        raw_temp = self.adc.read_channel_10bit(0)  # CH0
        raw_topk = self.adc.read_channel_10bit(1)  # CH1

        return {
            "temp01": raw_temp / 1023.0,
            "topk01": raw_topk / 1023.0,
        }

    def wait_for_button_123(self) -> str:
        """
        どれかのボタンが押されるまで待って '1'/'2'/'3' を返す
        """
        while True:
            if self.btn1.is_pressed:
                while self.btn1.is_pressed:
                    time.sleep(0.01)
                return "1"
            if self.btn2.is_pressed:
                while self.btn2.is_pressed:
                    time.sleep(0.01)
                return "2"
            if self.btn3.is_pressed:
                while self.btn3.is_pressed:
                    time.sleep(0.01)
                return "3"
            time.sleep(0.01)

    def close(self):
        self.adc.close()
