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

    return system_instruction, contents


def openai_params_to_gemini_generation_config(data: Dict[str, Any]) -> Dict[str, Any]:
    cfg: Dict[str, Any] = {}
    if data.get("temperature") is not None:
        cfg["temperature"] = float(data["temperature"])
    if data.get("top_p") is not None:
        cfg["topP"] = float(data["top_p"])
    if data.get("top_k") is not None:
        try:
            cfg["topK"] = int(data["top_k"])
        except Exception:
            pass
    if data.get("max_tokens") is not None:
        try:
            cfg["maxOutputTokens"] = int(data["max_tokens"])
        except Exception:
            pass
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
    # alt=sse が必須
    url = f"{GEMINI_BASE}/models/{model}:streamGenerateContent?alt=sse"
    system_instruction, contents = openai_messages_to_gemini(data.get("messages", []))
    gen_cfg = openai_params_to_gemini_generation_config(data)

    req: Dict[str, Any] = {"contents": contents}
    if system_instruction is not None:
        req["system_instruction"] = system_instruction
    if gen_cfg:
        req["generationConfig"] = gen_cfg

    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }

    session = ClientSession(timeout=aiohttp.ClientTimeout(total=timeout_s))
    resp = await session.post(url, headers=headers, json=req)
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
    """
    Gemini SSE(streamGenerateContent?alt=sse) を OpenAI互換SSEへ変換。
    取りこぼし防止のため、chunk分割ではなく「行ベース」でSSEを処理する。
    """
    proxy_resp = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream; charset=utf-8",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
    await proxy_resp.prepare(request)

    async def _open_upstream():
        return await gemini_stream_generate_content(data=data, api_key=api_key, model=model)

    # 429対応：retryDelayに従って最大2回待って再試行
    max_retries = 2
    attempt = 0
    session: Optional[aiohttp.ClientSession] = None
    resp: Optional[aiohttp.ClientResponse] = None

    while True:
        attempt += 1
        session, resp = await _open_upstream()
        ct = resp.headers.get("Content-Type")
        print(f"[proxy] gemini upstream status={resp.status} ct={ct} attempt={attempt}", flush=True)

        if resp.status != 429:
            break

        body = await resp.text()
        wait_s = 60.0
        try:
            obj = json.loads(body)
            # details の retryDelay を拾う（"46s" など）
            details = (obj.get("error") or {}).get("details") or []
            for d in details:
                if isinstance(d, dict) and "retryDelay" in d:
                    rd = d["retryDelay"]
                    if isinstance(rd, str) and rd.endswith("s"):
                        wait_s = float(rd[:-1])
                        break
        except Exception:
            pass

        # close before waiting
        try:
            resp.release()
        finally:
            await session.close()

        await proxy_resp.write(
            make_openai_stream_chunk(
                model=model,
                content_delta=f"[proxy] upstream 429 rate limited. retry in {wait_s:.1f}s (attempt {attempt}/{max_retries+1})",
            )
        )
        await asyncio.sleep(wait_s)

        if attempt >= (max_retries + 1):
            # give up after retries
            await proxy_resp.write(
                make_openai_stream_chunk(model=model, content_delta=f"[proxy] giving up after {attempt} attempts.")
            )
            await proxy_resp.write(make_openai_stream_done())
            await proxy_resp.write_eof()
            return proxy_resp

    try:
        assert resp is not None and session is not None

        if resp.status >= 400:
            err_text = await resp.text()
            await proxy_resp.write(
                make_openai_stream_chunk(
                    model=model,
                    content_delta=f"[proxy upstream error {resp.status}] {err_text}",
                )
            )
            await proxy_resp.write(make_openai_stream_done())
            await proxy_resp.write_eof()
            return proxy_resp

        created = int(time.time())
        last_text = ""

        # SSEを仕様通り「行単位」で読む
        # 1イベントは空行で区切られ、data: 行が複数ある場合は結合する
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
                # Geminiは普通送らないが防御
                raise StopAsyncIteration

            try:
                ev = json.loads(payload_str)
            except Exception:
                # JSONでなければ捨てる
                return

            cur_text = _extract_text_from_gemini_event(ev)
            if not cur_text:
                return

            # Geminiが「累積」を返す場合と「増分」を返す場合があるので両対応
            # - curが last をprefixに含む：差分= suffix
            # - curが短い/無関係：増分扱いで全量
            if last_text and cur_text.startswith(last_text):
                delta = cur_text[len(last_text):]
            else:
                delta = cur_text

            # last_text 更新：累積ならcur、増分なら連結
            if last_text and cur_text.startswith(last_text):
                last_text = cur_text
            else:
                last_text = last_text + cur_text if last_text else cur_text

            if delta:
                await proxy_resp.write(make_openai_stream_chunk(model=model, content_delta=delta, created=created))
                await asyncio.sleep(0)

        while True:
            line_bytes = await resp.content.readline()
            if not line_bytes:
                # upstream closed
                break

            line = line_bytes.decode("utf-8", errors="ignore").rstrip("\r\n")

            # 空行 = イベント終端
            if line == "":
                await _flush_event()
                continue

            # コメント行は無視
            if line.startswith(":"):
                continue

            # data行を集める（複数行可）
            if line.startswith("data:"):
                data_lines.append(line[len("data:"):].lstrip())
                continue

            # event: / id: などは今は無視
            continue

        # 末尾に未flushがあれば処理
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

    except (asyncio.CancelledError, ConnectionResetError, aiohttp.ClientConnectionError):
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
