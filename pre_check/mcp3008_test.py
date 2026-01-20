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

print("MCP3008 test: CH0 / CH1 を読みます（Ctrl+Cで終了）")
print("同じ可変抵抗を CH0 と CH1 に接続してください\n")

try:
    while True:
        v0 = read_ch(0)  # CH0
        v1 = read_ch(1)  # CH1

        n0 = v0 / 1023.0
        n1 = v1 / 1023.0

        print(
            f"CH0 raw={v0:4d} norm={n0:.3f} | "
            f"CH1 raw={v1:4d} norm={n1:.3f}",
            end="\r"
        )

        time.sleep(0.1)

except KeyboardInterrupt:
    print("\n終了")

finally:
    spi.close()
