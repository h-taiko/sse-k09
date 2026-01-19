import spidev
import time

# SPI設定（SPI0 CE0）
spi = spidev.SpiDev()
spi.open(0, 0)              # bus=0, device=0 (CE0)
spi.max_speed_hz = 1_000_000

def read_ch(ch):
    """
    MCP3008の指定チャネル(0-7)を読む
    戻り値: 0..1023
    """
    if not (0 <= ch <= 7):
        return -1
    r = spi.xfer2([1, (8 + ch) << 4, 0])
    value = ((r[1] & 3) << 8) | r[2]
    return value

print("MCP3008 test: CH0 を読みます（Ctrl+Cで終了）")
print("つまみを回して数値が変われば成功です\n")

try:
    while True:
        v = read_ch(0)   # CH0
        temp01 = v / 1023.0
        print(f"raw={v:4d}  temp01={temp01:.3f}", end="\r")
        time.sleep(0.1)
except KeyboardInterrupt:
    print("\n終了")
finally:
    spi.close()
