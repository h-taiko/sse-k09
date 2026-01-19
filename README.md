# LLM Toilet Feedback Sandbox
Raspberry Pi × LLM × GPIO 実験プロジェクト

---

## 1. プロジェクト概要

本プロジェクトは、**Raspberry Pi 上でローカルLLM（llama.cpp）を動かし、物理入力（人感センサ・ボタン・可変抵抗）によって LLM の対話と生成特性をリアルタイムに制御する実験**です。

目的は以下です。

- 固定アンケートではなく、**LLMがその場で質問を生成する対話型アンケート**を実現する
- **Temperature / TOP-k を物理ノブで直接操作**し、生成文の性格（揺らぎ、語彙の幅）がどう変化するかを観察する
- LLMをブラックボックスにしないため、**Proxy を挟んで入力（messages / sampling params）を可視化**する

---

## 2. システム全体構成（論理図）

```text
[ 人感センサ / ボタン / 可変抵抗(2ノブ) ]
                    │
                    ▼
             input_gpio.py
                    │
                    ▼
              run_gpio.py
          (制御ループ / UI)
                    │
                    ▼
           state_machine.py
 (状態遷移 / サンプリング制御)
                    │
                    ▼
             llm_client.py
           (HTTP + SSE)
                    │
                    ▼
           proxy_server.py
     (入力ログ表示 / 中継)
                    │
                    ▼
             llama-server
          (llama.cpp / GGUF)
```

## 3. ハードウェア構成
### 3.1 Raspberry Pi

Raspberry Pi 4 / 5（8GB推奨）

### 3.2 入力デバイス

- 人感センサ（PIR）
  - セッション開始トリガー
- 押しボタン × 3
  - 選択肢入力 1 / 2 / 3
- 可変抵抗 × 2（MCP3008経由）
  - CH0：Temperature（揺らぎ）
  - CH1：TOP-k（発想の広さ）

### 3.3 ADC

MCP3008（SPI接続）

## 4. ソフトウェア構成
### 4.1 使用技術

- llama.cpp（llama-server）
- Python 3
- gpiozero
- spidev
- aiohttp（Proxy用）
- OpenAI互換 Chat Completions API

## 5. ファイル構成と目的

- run_gpio.py
  - メイン制御ループ
  - 人感センサ待機 → LLMで質問生成 → ボタン入力 → 次の質問生成 → お礼生成
  - 各生成直前にノブ値を読み直し、LLMのサンプリングパラメータに反映する

- input_gpio.py
  - GPIO入力をまとめる層（ハード依存をここに閉じ込める）
  - PIR（人感）、ボタン（1/2/3）、MCP3008（CH0/CH1）を扱う
  - CH0/CH1 を 0.0〜1.0 に正規化して返す
    - CH0 → temp01（temperature用）
    - CH1 → topk01（top_k用）

- state_machine.py
  - 対話の状態遷移とLLM制御の中核
  - フェーズ管理：idle → await_sat → await_reason → done
  - 入力（満足度/理由）を保持して、次の質問・お礼生成のためのプロンプトを構成
  - ノブ値（temp01/topk01）を サンプリングパラメータに変換し、LLMへ渡す

```text
状態遷移
idle
 ↓ /start（またはPIR）
await_sat（満足度質問）
 ↓ 1/2/3
await_reason（理由質問）
 ↓ 1/2/3
done（お礼）
```

  - 2ノブの役割

| ノブ | 例（内部名） | 役割 | 代表パラメータ |
|-----|-----|-----|-----|
|CH0	|temp01|揺らぎの強さ|temperature, top_p, repeat_penalty|
|CH1|topk01|発想の広さ|top_k|

- llm_client.py
  - llama-server（またはProxy）へのHTTPクライアント
  - /v1/chat/completions に POST
  - stream=true（SSE）を受け取り、逐次表示（UX改善）
  - Proxy経由でSSEが分割されても破綻しないよう、イベント区切り（\\n\\n）でバッファ処理

- proxy_server.py
  - llama-server の前段に置く HTTP Proxy
  - 目的は「ブラックボックス化の解消」：
  - 入力（messages / temperature / top_k など）だけ表示・ログ
  - 応答はそのまま中継（streamも維持）
  - 教材・デバッグ・実験観察用

- prompts.py
  - LLMに与える固定ルールと、フェーズごとの指示テンプレ

- 重要方針：
  - TemperatureやTOP-kの説明をプロンプトに含めない
  - 生成の性格は サンプリングパラメータで直接制御する

## 6. 実験フロー（GPIO版）

PIRが人を検知

ノブ（CH0/CH1）を読み取り、サンプリングパラメータに反映

Q1（満足度質問）を LLM が生成

ボタン 1/2/3 で回答

ノブを読み取り直して反映

Q2（深掘り質問）を LLM が生成

ボタン 1/2/3 で理由を回答

ノブを読み取り直して反映

お礼文を LLM が生成

セッション終了 → 次の人を待機


## 7. 実行方法（例）
### 7.1 llama-server 起動（例）
./llama-server -m model.gguf --host 127.0.0.1 --port 8080

### 7.2 Proxy 起動（任意だが推奨）
python3 proxy_server.py


Pythonアプリ側の送信先URLを Proxy に向ける（例：http://127.0.0.1:18080/v1/chat/completions）

### 7.3 GPIO版 実行
python3 run_gpio.py

## 8. 推奨パラメータ設計（例）

可変抵抗（0.0〜1.0）を以下にマッピング

temperature = 0.1 + 1.1 * temp01     # 0.1 .. 1.2
top_k       = 20  + 80  * topk01     # 20  .. 100
top_p       = 0.70 + 0.25 * temp01
repeat_penalty = 1.15 - 0.10 * temp01

## 9. トラブルシューティング（よくある）
GPIO busy

既に別プロセスがGPIOを掴んでいる

対策：

既存テストを停止（Ctrl+C）

/dev/gpiochip0 を掴むプロセスを確認して kill

最終手段：再起動

Proxy経由でストリーム表示が止まる

SSEが分割されると readline() 方式が壊れることがある

対策：

llm_client.py を バッファ処理（\\n\\n区切り）版にする

<img width="1295" height="970" alt="image" src="https://github.com/user-attachments/assets/0d1de733-cc83-489a-a566-e83234581e09" />
