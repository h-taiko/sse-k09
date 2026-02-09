# config.py
LLAMA_URL = "http://127.0.0.1:18080/v1/chat/completions"

# 会話履歴（今回のフローは2ターンなので最小でOK）
HISTORY_TURNS = 2

# 生成長は短めがUX良い
MAX_TOKENS_STAGE1 = 60
MAX_TOKENS_STAGE2 = 80


# 推論の安定（必要なら固定）
TOP_P = 0.9
TOP_K = 40

# Temperatureのレンジ（可変抵抗→0..1→この範囲）
TEMP_MIN = 0.2
TEMP_MAX = 1.0

# “LCDっぽく”短くするための最大文字数（コンソール代替用）
LCD_LINE_LEN = 20
LCD_LINES = 4
