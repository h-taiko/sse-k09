# input_terminal.py
from typing import Optional

def read_trigger() -> None:
    input("\n[人感センサ模擬] Enterで開始 > ")

def read_button_abc(prompt: str) -> str:
    while True:
        s = input(prompt).strip().upper()
        if s in ("A", "B", "C"):
            return s
        print("A/B/C を入力してください。")

def read_temp_cmd() -> Optional[float]:
    """
    /t 0.73 で温度(0..1)変更。何もなければNone。
    """
    s = input("[任意] 温度変更なら '/t 0.73'、なければEnter > ").strip()
    if not s:
        return None
    if s.startswith("/t"):
        parts = s.split()
        if len(parts) >= 2:
            try:
                v = float(parts[1])
                return v
            except:
                return None
    return None
