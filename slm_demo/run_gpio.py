# run_gpio.py
import time
from state_machine import ToiletFeedbackEngine
from input_gpio import GPIOInput


def show(msg: str):
    print("\n" + "=" * 50, flush=True)
    print(msg, flush=True)
    print("=" * 50 + "\n", flush=True)


def apply_knobs(inp: GPIOInput, eng: ToiletFeedbackEngine, tag: str = ""):
    """
    可変抵抗2つ(CH0=temp, CH1=top_k)を読み、Engineへ反映。
    tag はログ用（任意）。
    """
    knobs = inp.read_knobs01()
    eng.set_knobs(knobs["temp01"], knobs["topk01"])
    print(
        f"[KNOBS]{' '+tag if tag else ''} temp01={knobs['temp01']:.3f} topk01={knobs['topk01']:.3f}",
        flush=True,
    )


def main():
    inp = GPIOInput(
        pir_pin=23,
        btn1_pin=16,
        btn2_pin=20,
        btn3_pin=21,
        # adc_channel は input_gpio.py 内で使っていないので指定不要（残しても害はない）
        spi_bus=0,
        spi_device=0,
    )
    eng = ToiletFeedbackEngine()

    print("=== LLM Toilet Feedback (GPIO版 / ターミナル出力) ===", flush=True)
    print("人感(PIR)で開始 → ボタン1/2/3 → ボタン1/2/3", flush=True)
    print("可変抵抗: CH0=temperature, CH1=top_k", flush=True)
    print("Ctrl+Cで終了\n", flush=True)

    try:
        while True:
            print("[WAIT] 人感センサ待ち...", flush=True)
            inp.wait_for_presence()

            # セッション開始直前のノブ値を読む（開始時点）
            apply_knobs(inp, eng, "start")

            # Q1（満足度質問）をLLM生成
            show("[Q1] 生成中（満足度質問）...")
            q1 = eng.start()
            show(f"[Q1]\n{q1}\n\n入力: 1/2/3ボタン")

            # 満足度入力
            ans1 = inp.wait_for_button_123()
            print(f"[IN] satisfaction={ans1}", flush=True)

            # Q2生成直前：ノブを回した効果を反映
            apply_knobs(inp, eng, "before Q2")

            # Q2（深掘り質問）をLLM生成
            show("[Q2] 生成中（深掘り質問）...")
            q2 = eng.handle_choice(ans1)
            show(f"[Q2]\n{q2}\n\n入力: 1/2/3ボタン")

            # 理由入力
            ans2 = inp.wait_for_button_123()
            print(f"[IN] reason={ans2}", flush=True)

            # お礼生成直前：ノブを回した効果を反映
            apply_knobs(inp, eng, "before THANKS")

            # お礼生成
            show("[THANKS] 生成中（お礼）...")
            thanks = eng.handle_choice(ans2)
            show(f"[THANKS]\n{thanks}")

            print("---- セッション終了。次の人を待ちます ----\n", flush=True)

            # PIRが連続ONだとすぐ次に進む場合があるので少し待つ（任意）
            time.sleep(1.0)

    except KeyboardInterrupt:
        print("\nbye", flush=True)
    finally:
        inp.close()


if __name__ == "__main__":
    main()
