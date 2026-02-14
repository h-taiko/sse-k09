# slm_demo/llm_client.py
import json
import urllib.request
import urllib.error

from config import LLAMA_URL


def _extract_stream_delta(obj: dict) -> str:
    # OpenAI互換: choices[0].delta.content
    try:
        ch0 = (obj.get("choices") or [])[0]
        delta = ch0.get("delta") or {}
        if isinstance(delta, dict) and isinstance(delta.get("content"), str):
            return delta["content"]
        # 非ストリーム形式の保険
        msg = ch0.get("message") or {}
        if isinstance(msg, dict) and isinstance(msg.get("content"), str):
            return msg["content"]
    except Exception:
        pass
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
    OpenAI互換 /v1/chat/completions へPOST。
    stream=True の場合は SSE(data: ...) を行単位(readline)で処理する。
    """
    payload = {
        "model": "local",
        "messages": messages,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
        "top_p": float(top_p),
        "top_k": int(top_k),
        "repeat_penalty": float(repeat_penalty),
        "stream": bool(stream),
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
            if not stream:
                body = resp.read().decode("utf-8", errors="replace")
                obj = json.loads(body)
                return obj["choices"][0]["message"]["content"].strip()

            full = []
            while True:
                raw = resp.readline()
                if not raw:
                    break

                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                if not line.startswith("data:"):
                    continue

                payload_str = line[len("data:"):].strip()

                if payload_str == "[DONE]":
                    break

                try:
                    obj = json.loads(payload_str)
                except Exception:
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
