import json
import sys
import urllib.request
import urllib.error

LLAMA_URL = "http://127.0.0.1:8080/v1/chat/completions"

# ---- ここを必要に応じて調整 ----
SYSTEM_PROMPT = (
    "あなたは親切で自然な日本語アシスタントです。"
    "雑談を楽しく続けます。"
    "ユーザの発言に答えたあと、会話が続く質問を1つ返してください。"
    "長文になりすぎないように。"
)
HISTORY_TURNS = 4  # 直近の往復数（Piでは小さく）
TEMP_FIXED = 0.55  # 固定推奨（暴れ防止）
STREAM = True      # ★ストリーム表示ON
# --------------------------------


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def level_to_params(level_0_to_1: float) -> dict:
    """
    可変抵抗レベル(0..1) -> サンプリング/生成パラメータ（毎ターン変更）
    """
    l = clamp(level_0_to_1, 0.0, 1.0)

    # 応答の長さ：体感に一番効く（短い→長い）
    max_tokens = int(40 + l * 80)          # 80..260

    # 広がり：保守→自由
    top_p = 0.82 + l * 0.13                 # 0.82..0.95
    top_k = int(25 + l * 55)                # 25..80

    # 話題の回転：雑談がループしにくい
    presence_penalty = 0.0 + l * 0.55       # 0..0.55
    frequency_penalty = 0.05 + l * 0.25     # 0.05..0.30

    # くどさ抑制（強すぎると詰まるので控えめ）
    repeat_penalty = 1.10 + l * 0.06        # 1.10..1.16

    return {
        "temperature": TEMP_FIXED,
        "max_tokens": max_tokens,
        "top_p": top_p,
        "top_k": top_k,
        "presence_penalty": presence_penalty,
        "frequency_penalty": frequency_penalty,
        "repeat_penalty": repeat_penalty,
    }


def fun_meter(text: str) -> int:
    score = 0
    if "?" in text or "？" in text:
        score += 1
    if any(ch in text for ch in ["！", "!", "笑", "w", "ｗ"]):
        score += 1
    if any(k in text for k in ["たとえば", "まるで", "みたい", "例"]):
        score += 1
    if len(text) > 180:
        score += 1

    if score <= 1:
        return 1
    elif score == 2:
        return 2
    else:
        return 3


def trim_history(messages):
    """
    system + 直近HISTORY_TURNS往復だけ残す
    messages: [system, user, assistant, user, assistant, ...]
    """
    if len(messages) <= 1:
        return messages
    keep = 1 + 2 * HISTORY_TURNS + 1
    if len(messages) > keep:
        return [messages[0]] + messages[-(keep - 1):]
    return messages


def _extract_stream_delta(obj: dict) -> str:
    """
    OpenAI互換のstream chunkから、追加されたテキスト部分を取り出す。
    実装差を吸収するために複数パターンを試す。
    """
    try:
        choice = obj["choices"][0]
    except Exception:
        return ""

    # OpenAI互換: choices[0].delta.content
    delta = choice.get("delta") or {}
    if isinstance(delta, dict):
        c = delta.get("content")
        if isinstance(c, str) and c:
            return c

    # 実装によっては message/content で来ることもある
    msg = choice.get("message") or {}
    if isinstance(msg, dict):
        c = msg.get("content")
        if isinstance(c, str) and c:
            return c

    # さらに別形式（text）
    t = choice.get("text")
    if isinstance(t, str) and t:
        return t

    return ""


def call_llama_stream(messages, params) -> str:
    """
    stream=true で llama-server を呼び、生成を逐次表示しつつ全文を返す。
    """
    payload = {
        "model": "local",
        "messages": messages,
        "stream": True,
        **params,
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        LLAMA_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    full = []
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            # サーバはSSE形式で「data: {...}\n\n」を返す
            while True:
                line = resp.readline()
                if not line:
                    break  # 切断など
                line = line.decode("utf-8", errors="replace").strip()

                if not line:
                    continue
                if not line.startswith("data:"):
                    continue

                chunk = line[len("data:"):].strip()
                if chunk == "[DONE]":
                    break

                try:
                    obj = json.loads(chunk)
                except json.JSONDecodeError:
                    continue

                delta = _extract_stream_delta(obj)
                if delta:
                    full.append(delta)
                    # 逐次表示
                    print(delta, end="", flush=True)

    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTPError {e.code}: {err}") from e
    except Exception as e:
        raise RuntimeError(f"Request failed: {e}") from e

    return "".join(full).strip()


def call_llama_nonstream(messages, params) -> str:
    payload = {
        "model": "local",
        "messages": messages,
        **params,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        LLAMA_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            obj = json.loads(body)
            return obj["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTPError {e.code}: {err}") from e
    except Exception as e:
        raise RuntimeError(f"Request failed: {e}") from e


def parse_level_cmd(s: str):
    parts = s.strip().split()
    if len(parts) < 2:
        return None
    try:
        return float(parts[1])
    except:
        return None


def level_any_to_0_1(v: float) -> float:
    if 0.0 <= v <= 1.0:
        return v
    if 0.0 <= v <= 10.0:
        return v / 10.0
    return clamp(v, 0.0, 10.0) / 10.0


def print_status(level01, params):
    lvl10 = level01 * 10.0
    print(f"[status] level={lvl10:.2f}/10")
    print(f"         temp={params['temperature']:.2f} top_p={params['top_p']:.3f} top_k={params['top_k']}")
    print(f"         max_tokens={params['max_tokens']} presence={params['presence_penalty']:.2f} freq={params['frequency_penalty']:.2f}")
    print(f"         repeat_penalty={params['repeat_penalty']:.2f} stream={STREAM}")


def main():
    level01 = 0.5
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    print("=== Smart LLM Demo (Phase1 Console / llama-server) ===")
    print("Commands:")
    print("  /lvl 7.3     : set level (0..10 or 0..1)")
    print("  /status      : show current params")
    print("  /reset       : clear chat history")
    print("  /quit        : exit")
    print("--------------------------------------")

    while True:
        try:
            user_in = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            return

        if not user_in:
            continue

        if user_in.startswith("/quit"):
            print("bye")
            return

        if user_in.startswith("/reset"):
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            print("[reset] history cleared")
            continue

        if user_in.startswith("/status"):
            params = level_to_params(level01)
            print_status(level01, params)
            continue

        if user_in.startswith("/lvl"):
            v = parse_level_cmd(user_in)
            if v is None:
                print("[lvl] usage: /lvl 7.3  (or /lvl 0.73)")
                continue
            level01 = level_any_to_0_1(v)
            params = level_to_params(level01)
            print_status(level01, params)
            continue

        params = level_to_params(level01)

        # 連続制御が伝わるようにレベルを明示（UX向上）
        level_tag = f"（現在の会話レベル: {level01*10:.1f}/10）"
        messages.append({"role": "user", "content": user_in + "\n" + level_tag})
        messages = trim_history(messages)

        try:
            print("assistant: ", end="", flush=True)
            if STREAM:
                reply = call_llama_stream(messages, params)
                print("")  # ストリーム表示の後で改行
            else:
                reply = call_llama_nonstream(messages, params)
                print(reply)
        except Exception as e:
            print(f"\n[error] {e}")
            messages.pop()
            continue

        messages.append({"role": "assistant", "content": reply})
        messages = trim_history(messages)

        fun = fun_meter(reply)
        led = "●○○" if fun == 1 else ("●●○" if fun == 2 else "●●●")
        print(f"[fun:{fun}] LED:{led}")

if __name__ == "__main__":
    main()
