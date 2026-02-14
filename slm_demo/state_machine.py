# state_machine.py
from dataclasses import dataclass
from typing import Optional
import random

from config import MAX_TOKENS_STAGE1, MAX_TOKENS_STAGE2
from prompts import (
    SYSTEM_PROMPT,
    build_stage0_user_prompt,
    build_stage1_user_prompt,
    build_stage2_user_prompt,
)
from llm_client import chat_completion


FOCUS_LIST = [
    "清潔さ",
    "におい",
    "設備",
    "混雑",
    "快適さ",
]

def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def norm_choice_123(s: str) -> Optional[str]:
    s = s.strip()
    if s in ("1", "2", "3"):
        return s
    if s.startswith("/"):
        s2 = s[1:].strip()
        if s2 in ("1", "2", "3"):
            return s2
    return None


def sampling_from_knobs(temp01: float, topk01: float) -> dict:
    """
    可変抵抗2つ:
      - temp01: 0..1  → temperature（揺らぎ）
      - topk01: 0..1  → top_k（発想の広さ）
    """
    t = clamp(temp01, 0.0, 1.0)
    k = clamp(topk01, 0.0, 1.0)

    #temperature = 0.1 + 1.1 * t         # 0.1 .. 1.2
    #top_k = int(20 + 80 * k)            # 20 .. 100

    # 補助（必要なら）
    top_p = 0.70 + 0.25 * t             # 0.70 .. 0.95
    repeat_penalty = 1.15 - 0.10 * t    # 1.15 .. 1.05

    return {
        "temperature": t,
        "top_p": top_p,
        "top_k": int(20 + 80 * k),
        "repeat_penalty": repeat_penalty,
    }


@dataclass
class Session:
    # 2ノブ
    temp01: float = 0.5     # CH0
    topk01: float = 0.5     # CH1

    satisfaction: Optional[str] = None  # "1"|"2"|"3"
    reason: Optional[str] = None        # "1"|"2"|"3"
    last_question: Optional[str] = None
    phase: str = "idle"                 # idle|await_sat|await_reason|done


class ToiletFeedbackEngine:
    def __init__(self):
        self.session = Session()

    # 互換のため残す（CH0だけ更新したい場合）
    def set_temp01(self, temp01: float):
        self.session.temp01 = clamp(temp01, 0.0, 1.0)

    # 互換のため残す（CH1だけ更新したい場合）
    def set_topk01(self, topk01: float):
        self.session.topk01 = clamp(topk01, 0.0, 1.0)

    # 2ノブをまとめて更新（run_gpio からはこれを呼ぶ）
    def set_knobs(self, temp01: float, topk01: float):
        self.session.temp01 = clamp(temp01, 0.0, 1.0)
        self.session.topk01 = clamp(topk01, 0.0, 1.0)

    def reset(self):
        # ノブ値は引き継ぐ（これが便利）
        self.session = Session(
            temp01=self.session.temp01,
            topk01=self.session.topk01,
        )

    def _params(self) -> dict:
        return sampling_from_knobs(self.session.temp01, self.session.topk01)

    def start(self) -> str:
        """
        セッション開始：最初の満足度質問をLLMに生成させる
        """
        self.session.satisfaction = None
        self.session.reason = None
        self.session.phase = "await_sat"

        #今回のセッションの論点を固定
        focus = random.choice(FOCUS_LIST)
        self.session.focus = focus

        params = self._params()
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            # ※ prompts.py を直すまでは temp01 を渡してOK
            {"role": "user", "content": build_stage0_user_prompt(self.session.focus, self.session.temp01)},
            # {"role": "user", "content": build_stage0_user_prompt(self.session.temp01)},
        ]

        print("LLM: ", end="", flush=True)
        text = chat_completion(
            messages,
            temperature=params["temperature"],
            top_p=params["top_p"],
            top_k=params["top_k"],
            repeat_penalty=params["repeat_penalty"],
            max_tokens=MAX_TOKENS_STAGE1,
            stream=True,
            print_stream=True,
        )
        print("")
        self.session.last_question = text
        return text

    def handle_choice(self, choice_123: str) -> str:
        """
        現在フェーズに応じて、満足度 or 理由として処理
        """
        ch = norm_choice_123(choice_123)
        if ch is None:
            return "入力エラー。1/2/3 を入力してください。"

        if self.session.phase == "await_sat":
            return self._handle_satisfaction(ch)
        elif self.session.phase == "await_reason":
            return self._handle_reason(ch)
        elif self.session.phase == "idle":
            return "まだ開始していません。/start を実行してください。"
        else:
            return "このセッションは完了しています。/start で新しく開始できます。"

    def _handle_satisfaction(self, ch: str) -> str:
        self.session.satisfaction = ch
        self.session.phase = "await_reason"

        params = self._params()
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            # ※ prompts.py を直すまでは temp01 を渡してOK
            #{"role": "user", "content": build_stage1_user_prompt(ch, self.session.temp01)},
            {"role": "user", "content": build_stage1_user_prompt(ch, self.session.last_question or "", self.session.temp01)},

        ]

        print("LLM: ", end="", flush=True)
        text = chat_completion(
            messages,
            temperature=params["temperature"],
            top_p=params["top_p"],
            top_k=params["top_k"],
            repeat_penalty=params["repeat_penalty"],
            max_tokens=MAX_TOKENS_STAGE1,
            stream=True,
            print_stream=True,
        )
        print("")
        self.session.last_question = text
        return text

    def _handle_reason(self, ch: str) -> str:
        self.session.reason = ch
        self.session.phase = "done"

        params = self._params()
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            # ※ prompts.py を直すまでは temp01 を渡してOK
            {"role": "user", "content": build_stage2_user_prompt(self.session.satisfaction or "2", ch, self.session.temp01)},
        ]

        print("LLM: ", end="", flush=True)
        text = chat_completion(
            messages,
            temperature=params["temperature"],
            top_p=params["top_p"],
            top_k=params["top_k"],
            repeat_penalty=params["repeat_penalty"],
            max_tokens=MAX_TOKENS_STAGE2,
            stream=True,
            print_stream=True,
        )
        print("")
        return text
