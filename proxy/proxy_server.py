import json
import time
import asyncio
import aiohttp
from aiohttp import web, ClientSession

PROXY_HOST = "127.0.0.1"
PROXY_PORT = 18080
LLAMA_BASE = "http://127.0.0.1:8080"
LOG_PATH = "llm_requests.log"

# スクリプトパスを取得
script_path = os.path.dirname(os.path.abspath(__file__))
# ログファイルのパスを設定（自身のパスからlogsフォルダに）
log_path = os.path.join(script_path, '..', 'logs', 'llm_requests.log')



def log_request(data: dict):
    rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "path": "/v1/chat/completions", "body": data}
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

def print_input_only(data: dict):
    print("\n=== LLM INPUT ===", flush=True)
    print(f"temp={data.get('temperature')} max_tokens={data.get('max_tokens')} top_p={data.get('top_p')} top_k={data.get('top_k')} stream={data.get('stream')}", flush=True)
    for i, m in enumerate(data.get("messages", [])):
        role = m.get("role")
        content = m.get("content", "")
        head = content if len(content) <= 800 else content[:800] + " ... (truncated)"
        print(f"[{i}] {role}: {head}", flush=True)
    print("=== /LLM INPUT ===\n", flush=True)

async def handle_chat(request: web.Request):
    data = await request.json()

    # 入力だけ表示・保存
    print_input_only(data)
    log_request(data)

    target_url = f"{LLAMA_BASE}/v1/chat/completions"

    async with ClientSession() as session:
        async with session.post(target_url, json=data) as resp:

            # stream=true (SSE) は「行単位」で中継すると安定
            if data.get("stream"):
                proxy_resp = web.StreamResponse(
                    status=resp.status,
                    headers={
                        "Content-Type": "text/event-stream",
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                    },
                )
                await proxy_resp.prepare(request)

                try:
                    async for line in resp.content:
                        # lineは bytes（改行含む）で来ることが多い
                        await proxy_resp.write(line)
                        # 古いaiohttpでも確実に送るために小休止（実質フラッシュ）
                        await asyncio.sleep(0)
                    try:
                        await proxy_resp.write_eof()
                    except (ConnectionResetError, aiohttp.ClientConnectionError):
                        pass
                except (asyncio.CancelledError, ConnectionResetError, aiohttp.ClientConnectionError):
                    pass

                return proxy_resp

            # stream=false は content_type 固定で返す（charset問題回避）
            text = await resp.text()
            return web.Response(status=resp.status, text=text, content_type="application/json")

app = web.Application()
app.router.add_post("/v1/chat/completions", handle_chat)

if __name__ == "__main__":
    web.run_app(app, host=PROXY_HOST, port=PROXY_PORT)
