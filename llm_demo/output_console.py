# output_console.py

def show_text(text: str):
    print("\n--- OUTPUT ---")
    print(text)
    print("--------------\n")

def led_thinking(on: bool):
    # 実験中は視覚的な区切りとして残す
    print("[LED] thinking=" + ("ON" if on else "OFF"))
