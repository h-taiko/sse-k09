# proxy/proxy_server.py
import argparse
import asyncio
import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
from aiohttp import web, ClientSession


# -----------------------------
# Defaults
# -----------------------------
PROXY_HOST = "127.0.0.1"
PROXY_PORT = 18080

LLAMA_BASE_DEFAULT = "http://127.0.0.1:8080"  # llama.cpp server base
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_MODEL_DEFAULT = "gemini-2.5-flash"


# -----------------------------
# Logging (optional)
# -----------------------------
def print_input_only(data: dict, backend: str):
    print("\n=== LLM INPUT ===", flush=True)
    print(
        f"backend={backend} temp={data.get('temperature')} max_tokens={data.get('max_tokens')} "
        f"top_p={data.get('top_p')} top_k={data.get('top_k')} stream={data.get('stream')}",
        flush=True,
    )
    msgs = data.get("messages") or []
    for i, m in enumerate(msgs):
        role = m.get("role")
        content = m.get("content", "")
        head = content if len(content) <= 300 else content[:300] + " ...(truncated)"
        print(f"[{i}] {role}: {head}", flush=True)
    print("=== /LLM INPUT ===\n", flush=True)


# -----------------------------
# OpenAI <-> Gemini mapping
# -----------------------------
def openai_messages_to_gemini(messages: List[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    system_texts: List[str] = []
    contents: List[Dict[str, Any]] = []

    for m in messages or []:
        role = (m.get("role") or "").strip()
        content = m.get("content", "")
        if content is None:
            content = ""

        if role == "system":
            if str(content).strip():
                system_texts.append(str(content))
            continue

        gem_role = "model" if role == "assistant" else "user"
        contents.append({"role": gem_role, "parts": [{"text": str(content)}]})

    system_instruction = None
    if system_texts:
        system_instruction = {"parts": [{"text": "\n\n".join(system_texts)}]}

    if not contents:
        contents = [{"role": "user", "parts": [{"text": "Hello"}]}]
    
    system_instruction = None
    if system_texts:
        system_instruction = {
            "role": "user",
            "parts": [{"text": "\n\n".join(system_texts)}],
        }
    return system_instruction, contents


def openai_params_to_gemini_generation_config(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    OpenAI互換パラメータ → Gemini generationConfig 変換。
    重要: max_tokens が小さすぎると finishReason=MAX_TOKENS で即打ち切られる。
    """
    cfg: Dict[str, Any] = {}

    # temperature/top_p はそのまま寄せる
    if "temperature" in data and data["temperature"] is not None:
        cfg["temperature"] = float(data["temperature"])
    if "top_p" in data and data["top_p"] is not None:
        cfg["topP"] = float(data["top_p"])

    # max_tokens → maxOutputTokens
    # OpenAI互換では未指定の場合があり得る。その場合はデフォルトを十分大きくする。
    mt = data.get("max_tokens", None)

    # run_terminal等が 0 / 極小 を入れてくるケースも防御
    if mt is None:
        max_out = 512
    else:
        try:
            max_out = int(mt)
        except Exception:
            max_out = 512

    # あまりに小さい値は実用にならないので底上げ（必要なら下げてOK）
    if max_out < 64:
        max_out = 2048

    # 念のため過大値をクリップ（モデル上限はモデルによる）
    if max_out > 8192:
        max_out = 8192

    cfg["maxOutputTokens"] = max_out

    # あるなら stop を変換（OpenAIの stop は文字列 or 配列）
    stop = data.get("stop")
    if stop:
        if isinstance(stop, str):
            cfg["stopSequences"] = [stop]
        elif isinstance(stop, list):
            cfg["stopSequences"] = [s for s in stop if isinstance(s, str)]

    return cfg



# -----------------------------
# OpenAI-like SSE helpers
# -----------------------------
def make_openai_stream_chunk(model: str, content_delta: str, created: Optional[int] = None) -> bytes:
    if created is None:
        created = int(time.time())
    payload = {
        "id": "chatcmpl-proxy",
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {"content": content_delta}, "finish_reason": None}],
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


def make_openai_stream_done() -> bytes:
    return b"data: [DONE]\n\n"


def make_openai_nonstream_response(model: str, full_text: str) -> Dict[str, Any]:
    return {
        "id": "chatcmpl-proxy",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": full_text}, "finish_reason": "stop"}],
    }


# -----------------------------
# Gemini callers
# -----------------------------
async def gemini_generate_content(
    data: Dict[str, Any],
    api_key: str,
    model: str,
    timeout_s: int = 120,
) -> Dict[str, Any]:
    url = f"{GEMINI_BASE}/models/{model}:generateContent"
    system_instruction, contents = openai_messages_to_gemini(data.get("messages", []))
    gen_cfg = openai_params_to_gemini_generation_config(data)

    req: Dict[str, Any] = {"contents": contents}
    if system_instruction is not None:
        req["system_instruction"] = system_instruction
    if gen_cfg:
        req["generationConfig"] = gen_cfg

    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}

    async with ClientSession(timeout=aiohttp.ClientTimeout(total=timeout_s)) as session:
        async with session.post(url, headers=headers, json=req) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise web.HTTPBadRequest(text=text, content_type="application/json")
            return json.loads(text)


async def gemini_stream_generate_content(
    data: Dict[str, Any],
    api_key: str,
    model: str,
    timeout_s: int = 120,
) -> Tuple[ClientSession, aiohttp.ClientResponse]:

    url = f"{GEMINI_BASE}/models/{model}:streamGenerateContent"

    system_instruction, contents = openai_messages_to_gemini(data.get("messages", []))
    gen_cfg = openai_params_to_gemini_generation_config(data)

    req: Dict[str, Any] = {
        "contents": contents,
    }

    if system_instruction is not None:
        req["systemInstruction"] = system_instruction

    if gen_cfg:
        req["generationConfig"] = gen_cfg

    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        # ★ API Key を Header に載せる（Queryでは出さない）
        "x-goog-api-key": api_key,
    }

    timeout = aiohttp.ClientTimeout(
        total=None,
        sock_connect=30,
        sock_read=None,  # SSEなので無制限寄り
    )

    session = ClientSession(timeout=timeout)

    resp = await session.post(
        url,
        headers=headers,
        params={"alt": "sse"},  # ← key は入れない
        json=req,
    )

    return session, resp




def _extract_text_from_gemini_event(ev: Dict[str, Any]) -> str:
    try:
        cands = ev.get("candidates") or []
        if not cands:
            return ""
        content = (cands[0].get("content") or {})
        parts = content.get("parts") or []
        out = []
        for p in parts:
            t = p.get("text")
            if isinstance(t, str):
                out.append(t)
        return "".join(out)
    except Exception:
        return ""


async def proxy_gemini_stream_as_openai_sse(
    request: web.Request,
    data: Dict[str, Any],
    api_key: str,
    model: str,
) -> web.StreamResponse:
    proxy_resp = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream; charset=utf-8",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
    await proxy_resp.prepare(request)

    created = int(time.time())
    session: Optional[ClientSession] = None
    resp: Optional[aiohttp.ClientResponse] = None

    try:
        session, resp = await gemini_stream_generate_content(data=data, api_key=api_key, model=model)

        if resp.status >= 400:
            err_text = await resp.text()
            await proxy_resp.write(
                make_openai_stream_chunk(
                    model=model,
                    content_delta=f"[upstream error {resp.status}]",
                    created=created,
                )
            )
            await proxy_resp.write(make_openai_stream_done())
            await proxy_resp.write_eof()
            return proxy_resp

        last_text = ""
        buf = b""
        data_lines: List[str] = []

        async def _flush_event():
            nonlocal last_text, data_lines

            if not data_lines:
                return

            payload_str = "\n".join(data_lines).strip()
            data_lines = []

            if not payload_str:
                return
            if payload_str == "[DONE]":
                raise StopAsyncIteration

            try:
                ev = json.loads(payload_str)
            except Exception:
                return

            # まずテキストを抽出して流す（←順番が重要）
            cur_text = _extract_text_from_gemini_event(ev if isinstance(ev, dict) else {})
            if cur_text:
                if last_text and cur_text.startswith(last_text):
                    delta = cur_text[len(last_text):]
                    last_text = cur_text
                else:
                    delta = cur_text
                    last_text = (last_text + cur_text) if last_text else cur_text

                if delta:
                    await proxy_resp.write(
                        make_openai_stream_chunk(
                            model=model,
                            content_delta=delta,
                            created=created,
                        )
                    )
                    await asyncio.sleep(0)

            # その後で終了理由を見る（本文を捨てない）
            cands = ev.get("candidates") if isinstance(ev, dict) else None
            if isinstance(cands, list) and cands:
                fr = (cands[0] or {}).get("finishReason")
                # STOP以外（MAX_TOKENS等）は「終了」扱いで抜ける
                if fr and fr != "STOP":
                    raise StopAsyncIteration


        # SSE読取
        async for chunk in resp.content.iter_chunked(8192):
            if not chunk:
                continue
            buf += chunk

            while b"\n" in buf:
                raw_line, buf = buf.split(b"\n", 1)
                if raw_line.endswith(b"\r"):
                    raw_line = raw_line[:-1]
                line = raw_line.decode("utf-8", errors="ignore")

                if line == "":
                    await _flush_event()
                    continue

                if line.startswith(":"):
                    continue

                if line.startswith("data:"):
                    data_lines.append(line[len("data:"):].lstrip())
                    continue

        # EOF残り
        if buf:
            raw_line = buf[:-1] if buf.endswith(b"\r") else buf
            line = raw_line.decode("utf-8", errors="ignore")
            if line.startswith("data:"):
                data_lines.append(line[len("data:"):].lstrip())

        await _flush_event()

        await proxy_resp.write(make_openai_stream_done())
        await proxy_resp.write_eof()
        return proxy_resp

    except StopAsyncIteration:
        await proxy_resp.write(make_openai_stream_done())
        try:
            await proxy_resp.write_eof()
        except Exception:
            pass
        return proxy_resp

    except Exception:
        # 本番では詳細エラーは出さず静かに終了
        try:
            await proxy_resp.write(make_openai_stream_done())
            await proxy_resp.write_eof()
        except Exception:
            pass
        return proxy_resp

    finally:
        try:
            if resp is not None:
                resp.release()
        finally:
            if session is not None:
                await session.close()



# -----------------------------
# Main handler
# -----------------------------
class ProxyConfig:
    def __init__(self, backend: str, llama_base: str, gemini_api_key: Optional[str], gemini_model: str):
        self.backend = backend
        self.llama_base = llama_base
        self.gemini_api_key = gemini_api_key
        self.gemini_model = gemini_model


async def handle_chat(request: web.Request) -> web.StreamResponse:
    cfg: ProxyConfig = request.app["cfg"]
    data = await request.json()
    print_input_only(data, backend=cfg.backend)

    backend = (cfg.backend or "local").lower().strip()

    # local passthrough (llama.cpp OpenAI-compatible)
    if backend in ("local", "llama", "llamacpp"):
        target_url = f"{cfg.llama_base}/v1/chat/completions"
        async with ClientSession() as session:
            async with session.post(target_url, json=data) as resp:
                if data.get("stream"):
                    proxy_resp = web.StreamResponse(
                        status=resp.status,
                        headers={
                            "Content-Type": "text/event-stream; charset=utf-8",
                            "Cache-Control": "no-cache",
                            "Connection": "keep-alive",
                        },
                    )
                    await proxy_resp.prepare(request)
                    async for chunk in resp.content.iter_chunked(4096):
                        await proxy_resp.write(chunk)
                        await asyncio.sleep(0)
                    try:
                        await proxy_resp.write_eof()
                    except Exception:
                        pass
                    return proxy_resp

                text = await resp.text()
                return web.Response(status=resp.status, text=text, content_type="application/json")

    # gemini
    if backend in ("gemini", "google", "ai_studio", "aistudio"):
        if not cfg.gemini_api_key:
            raise web.HTTPBadRequest(
                text=json.dumps({"error": "GEMINI_API_KEY not set"}, ensure_ascii=False),
                content_type="application/json",
            )

        model = cfg.gemini_model or GEMINI_MODEL_DEFAULT

        if data.get("stream"):
            return await proxy_gemini_stream_as_openai_sse(request, data, cfg.gemini_api_key, model)

        obj = await gemini_generate_content(data=data, api_key=cfg.gemini_api_key, model=model)

        # extract full text
        full_text = ""
        try:
            cand0 = (obj.get("candidates") or [])[0]
            content = cand0.get("content") or {}
            parts = content.get("parts") or []
            full_text = "".join([p.get("text", "") for p in parts if isinstance(p.get("text"), str)])
        except Exception:
            full_text = ""

        out = make_openai_nonstream_response(model=model, full_text=full_text)
        return web.Response(status=200, text=json.dumps(out, ensure_ascii=False), content_type="application/json")

    raise web.HTTPBadRequest(
        text=json.dumps({"error": f"Unknown backend: {backend}"}, ensure_ascii=False),
        content_type="application/json",
    )


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Proxy: local llama.cpp or Gemini (AI Studio)")
    p.add_argument("--host", default=os.getenv("PROXY_HOST", PROXY_HOST))
    p.add_argument("--port", type=int, default=int(os.getenv("PROXY_PORT", str(PROXY_PORT))))
    p.add_argument("--backend", default=os.getenv("LLM_BACKEND", "local"), help="local (default) or gemini")
    p.add_argument("--llama-base", default=os.getenv("LLAMA_BASE", LLAMA_BASE_DEFAULT))
    p.add_argument("--gemini-model", default=os.getenv("GEMINI_MODEL", GEMINI_MODEL_DEFAULT))
    return p


def main():
    args = build_arg_parser().parse_args()
    backend = (args.backend or "local").lower().strip()

    cfg = ProxyConfig(
        backend=backend,
        llama_base=args.llama_base,
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        gemini_model=args.gemini_model,
    )

    app = web.Application()
    app["cfg"] = cfg
    app.router.add_post("/v1/chat/completions", handle_chat)

    print(
        f"[proxy] host={args.host} port={args.port} backend={cfg.backend} llama_base={cfg.llama_base} gemini_model={cfg.gemini_model}",
        flush=True,
    )

    web.run_app(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
