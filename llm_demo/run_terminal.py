# run_terminal.py
from state_machine import ToiletFeedbackEngine

HELP = """\
Commands:
  /start           : セッション開始（最初の質問をLLM生成）
  /lvl 0.73        : Temperature(0..1) を設定（可変抵抗の代替）
  /status          : 現在状態の表示
  /reset           : セッション状態をリセット（温度は維持）
  /quit            : 終了
Input:
  1 / 2 / 3        : 選択肢の入力（ボタンの代替）  ※ /1 /2 /3 でも可
"""

def main():
    eng = ToiletFeedbackEngine()
    print("=== LLM Toilet Feedback (Terminal REPL) ===")
    print(HELP)

    while True:
        try:
            s = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            return

        if not s:
            continue

        if s.startswith("/quit"):
            print("bye")
            return

        if s.startswith("/help"):
            print(HELP)
            continue

        if s.startswith("/lvl"):
            parts = s.split()
            if len(parts) < 2:
                print("usage: /lvl 0.73  (0..1)")
                continue
            try:
                v = float(parts[1])
            except:
                print("usage: /lvl 0.73  (0..1)")
                continue
            eng.set_temp01(v)
            print(f"[ok] temp01 set to {max(0.0, min(1.0, v)):.2f}")
            continue

        if s.startswith("/status"):
            sess = eng.session
            print(f"[status] phase={sess.phase} temp01={sess.temp01:.2f} sat={sess.satisfaction} reason={sess.reason}")
            if sess.last_question:
                print(f"[last_question] {sess.last_question}")
            continue

        if s.startswith("/reset"):
            eng.reset()
            print("[ok] reset (temp kept)")
            continue

        if s.startswith("/start"):
            print("--- SESSION START ---")
            q = eng.start()
            print(f"Q: {q}")
            continue

        # 1/2/3（または /1 /2 /3）
        if s in ("1", "2", "3") or s in ("/1", "/2", "/3"):
            out = eng.handle_choice(s)
            print(f"OUT: {out}")
            if eng.session.phase == "done":
                print("--- SESSION DONE ---")
            continue

        print("unknown command. type /help")

if __name__ == "__main__":
    main()
