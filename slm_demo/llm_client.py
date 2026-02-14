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
    stream=True の場合は SSE(data: ...) を chunk読みしてイベント単位で処理する。
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
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )

    def _iter_sse_payload_strings(resp):
        """
        SSEを raw bytes から復元して、イベントごとの payload(data: の結合結果) をyieldする
        """
        buf = b""
        data_lines = []

        while True:
            chunk = resp.read(8192)
            if not chunk:
                break
            buf += chunk

            while b"\n" in buf:
                raw_line, buf = buf.split(b"\n", 1)
                if raw_line.endswith(b"\r"):
                    raw_line = raw_line[:-1]
                line = raw_line.decode("utf-8", errors="replace")

                # 空行 = event 終端
                if line == "":
                    if data_lines:
                        yield "\n".join(data_lines).strip()
                        data_lines = []
                    continue

                if line.startswith(":"):
                    continue
                if line.startswith("data:"):
                    data_lines.append(line[len("data:"):].lstrip())
                    continue
                # event: / id: は無視

        # EOFで残っていたらflush
        if data_lines:
            yield "\n".join(data_lines).strip()

    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            if not stream:
                body = resp.read().decode("utf-8", errors="replace")
                obj = json.loads(body)
                return obj["choices"][0]["message"]["content"].strip()

            full = []
            for payload_str in _iter_sse_payload_strings(resp):
                if not payload_str:
                    continue
                if payload_str == "[DONE]":
                    break

                try:
                    obj = json.loads(payload_str)
                except Exception:
                    # proxy がエラーメッセージを文字列で流した等に備える
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
