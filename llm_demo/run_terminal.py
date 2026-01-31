# run_terminal.py
import time
from state_machine import ToiletFeedbackEngine

HELP = """\
Commands:
  /start                 : PIRの代替。セッション開始トリガ（人感検知相当）
  /temp 0.73             : temp01(0..1) を設定（CH0の代替）
  /topk 0.40             : topk01(0..1) を設定（CH1の代替）
  /knobs                 : ノブ値表示
  /status                : 現在状態の表示
  /reset                 : セッション状態をリセット（ノブは維持）
  /quit                  : 終了
Input:
  1 / 2 / 3              : ボタン入力の代替（満足度→理由の順）
"""

def show(msg: str):
    print("\n" + "=" * 50, flush=True)
    print(msg, flush=True)
    print("=" * 50 + "\n", flush=True)

def clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))

def apply_knobs(eng: ToiletFeedbackEngine, temp01: float, topk01: float, tag: str = ""):
    # GPIO版と同じ：2つのノブをEngineへ反映
    # state_machine側が set_knobs を持っている前提（run_gpioと同じ）
    eng.set_knobs(temp01, topk01)
    print(
        f"[KNOBS]{' '+tag if tag else ''} temp01={temp01:.3f} topk01={topk01:.3f}",
        flush=True,
    )

def read_choice_blocking(prompt="> ") -> str:
    while True:
        s = input(prompt).strip()
        if s in ("1", "2", "3"):
            return s
        if s in ("/1", "/2", "/3"):
            return s[1:]  # "1" "2" "3"
        print("input 1/2/3", flush=True)

def main():
    eng = ToiletFeedbackEngine()

    # terminal側のノブ状態（GPIOの可変抵抗2chの代替）
    temp01 = 0.5
    topk01 = 0.5

    print("=== LLM Toilet Feedback (Terminal / run_gpio互換) ===", flush=True)
    print("PIR代替: /start → 1/2/3 → 1/2/3", flush=True)
    print("可変抵抗代替: /temp (CH0), /topk (CH1)", flush=True)
    print("Ctrl+C or /quit で終了\n", flush=True)
    print(HELP, flush=True)

    try:
        while True:
            # PIR待ち相当（/start を待つ）
            print("[WAIT] /start を入力（人感センサ相当）...", flush=True)
            while True:
                s = input("> ").strip()
                if not s:
                    continue
                if s.startswith("/quit"):
                    print("bye", flush=True)
                    return
                if s.startswith("/help"):
                    print(HELP, flush=True)
                    continue
                if s.startswith("/temp"):
                    parts = s.split()
                    if len(parts) < 2:
                        print("usage: /temp 0.73  (0..1)", flush=True); continue
                    try:
                        temp01 = clamp01(float(parts[1]))
                        print(f"[ok] temp01={temp01:.2f}", flush=True)
                    except:
                        print("usage: /temp 0.73  (0..1)", flush=True)
                    continue
                if s.startswith("/topk"):
                    parts = s.split()
                    if len(parts) < 2:
                        print("usage: /topk 0.40  (0..1)", flush=True); continue
                    try:
                        topk01 = clamp01(float(parts[1]))
                        print(f"[ok] topk01={topk01:.2f}", flush=True)
                    except:
                        print("usage: /topk 0.40  (0..1)", flush=True)
                    continue
                if s.startswith("/knobs"):
                    print(f"[knobs] temp01={temp01:.2f} topk01={topk01:.2f}", flush=True)
                    continue
                if s.startswith("/status"):
                    sess = eng.session
                    print(f"[status] phase={sess.phase} temp01={sess.temp01:.2f} sat={sess.satisfaction} reason={sess.reason}", flush=True)
                    if getattr(sess, "last_question", None):
                        print(f"[last_question] {sess.last_question}", flush=True)
                    continue
                if s.startswith("/reset"):
                    eng.reset()
                    print("[ok] reset (knobs kept)", flush=True)
                    continue
                if s.startswith("/start"):
                    break

                print("unknown command. type /help", flush=True)

            # セッション開始直前のノブ値を読む（開始時点）
            apply_knobs(eng, temp01, topk01, "start")

            # Q1生成
            show("[Q1] 生成中（満足度質問）...")
            q1 = eng.start()
            show(f"[Q1]\n{q1}\n\n入力: 1/2/3")

            # 満足度入力（ブロック）
            ans1 = read_choice_blocking("> ")
            print(f"[IN] satisfaction={ans1}", flush=True)

            # Q2生成直前：ノブ反映
            apply_knobs(eng, temp01, topk01, "before Q2")

            # Q2生成
            show("[Q2] 生成中（深掘り質問）...")
            q2 = eng.handle_choice(ans1)
            show(f"[Q2]\n{q2}\n\n入力: 1/2/3")

            # 理由入力（ブロック）
            ans2 = read_choice_blocking("> ")
            print(f"[IN] reason={ans2}", flush=True)

            # THANKS生成直前：ノブ反映
            apply_knobs(eng, temp01, topk01, "before THANKS")

            # THANKS生成
            show("[THANKS] 生成中（お礼）...")
            thanks = eng.handle_choice(ans2)
            show(f"[THANKS]\n{thanks}")

            print("---- セッション終了。次の人を待ちます ----\n", flush=True)
            time.sleep(0.2)

    except KeyboardInterrupt:
        print("\nbye", flush=True)

if __name__ == "__main__":
    main()
