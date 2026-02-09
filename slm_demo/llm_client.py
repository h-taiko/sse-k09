# llm_client.py
import json
import urllib.request
import urllib.error

from config import LLAMA_URL


def _extract_stream_delta(obj: dict) -> str:
    """
    llama-server(OpenAI互換)の返却形式の差分を抽出
    - stream時: choices[0].delta.content
    - 非stream時: choices[0].message.content
    - 互換: choices[0].text
    """
    try:
        choice = obj["choices"][0]
    except Exception:
        return ""

    delta = choice.get("delta") or {}
    if isinstance(delta, dict):
        c = delta.get("content")
        if isinstance(c, str) and c:
            return c

    msg = choice.get("message") or {}
    if isinstance(msg, dict):
        c = msg.get("content")
        if isinstance(c, str) and c:
            return c

    t = choice.get("text")
    if isinstance(t, str) and t:
        return t

    return ""


def chat_completion(
    messages,
    *,
    temperature: float,
    max_tokens: int,
    top_p: float = 0.9,
    top_k: int = 40,
    repeat_penalty: float = 1.1,
    stream: bool = True,
    print_stream: bool = True,
) -> str:
    """
    llama-server(OpenAI互換 /v1/chat/completions)へリクエストし、
    stream=Trueなら逐次表示しつつ最終文字列も返す。

    Proxyを挟むとSSEの行が分割される場合があるため、
    readline()ではなくバッファリングして「イベント区切り(\\n\\n)」で処理する。
    """
    payload = {
        "model": "local",
        "messages": messages,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
        "top_p": float(top_p),
        "top_k": int(top_k),
        "repeat_penalty": float(repeat_penalty),
    }
    if stream:
        payload["stream"] = True

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        LLAMA_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            # 非ストリームは普通にJSONを読んで返す
            if not stream:
                body = resp.read().decode("utf-8", errors="replace")
                obj = json.loads(body)
                return obj["choices"][0]["message"]["content"].strip()

            # ここからストリーム(SSE)処理
            full = []
            buf = ""

            while True:
                chunk = resp.read(1024)
                if not chunk:
                    break

                buf += chunk.decode("utf-8", errors="replace")

                # SSEは空行(\n\n)でイベント区切り
                while "\n\n" in buf:
                    event, buf = buf.split("\n\n", 1)

                    # event内には複数行あり得る。data: 行だけ拾う
                    for line in event.splitlines():
                        line = line.strip()
                        if not line.startswith("data:"):
                            continue

                        payload_str = line[len("data:"):].strip()

                        if payload_str == "[DONE]":
                            return "".join(full).strip()

                        try:
                            obj = json.loads(payload_str)
                        except json.JSONDecodeError:
                            continue

                        delta = _extract_stream_delta(obj)
                        if delta:
                            full.append(delta)
                            if print_stream:
                                print(delta, end="", flush=True)

            return "".join(full).strip()

    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTPError {e.code}: {err}") from e
    except Exception as e:
        raise RuntimeError(f"Request failed: {e}") from e
