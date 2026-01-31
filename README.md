# LLM Toilet Feedback Sandbox
Raspberry Pi × LLM × GPIO 実験プロジェクト

---

## 概要

本プロジェクトは、**LLM が対話を生成し、利用者の選択（1/2/3）によって質問を分岐させていく「対話型フィードバック実験」**です。

同一の対話ロジック（`state_machine.py`）を用いて、

- **GPIO 実機入力（人感センサ・ボタン・可変抵抗）**
- **Terminal 入力（キーボード）**

の **2つの実行環境を完全に同一挙動で再現**できることを目的としています。

---

## このプロジェクトでやっていること

- 固定アンケートではなく、**LLM がその場で質問文を生成**
- ユーザーは **3択（1/2/3）だけを入力**
- 回答内容に応じて **次の質問やお礼文が動的に変化**
- **Temperature / Top-k を「セッション途中でも変更可能」**にし、生成結果への影響を観察

---

## 全体構成

```
llm_demo/
├── run_gpio.py        # GPIO実機用エントリポイント
├── run_terminal.py    # Terminal用エントリポイント（GPIO互換挙動）
├── state_machine.py  # 対話状態管理（中核ロジック）
├── llm_client.py     # LLM呼び出し（SSEストリーム対応）
├── prompts.py        # プロンプト定義
├── input_gpio.py     # GPIO入力（PIR / ボタン / 可変抵抗）
├── input_terminal.py # Terminal入力（GPIOの代替実装）
├── output_console.py # コンソール出力補助
└── config.py         # 各種設定
```

---

## 対話フロー（GPIO版 / Terminal版 共通）

両者は **完全に同一の順序・タイミング**で動作します。

```
[PIR検知 or /start]
   ↓
(開始時点のノブ値を反映)
   ↓
Q1: 満足度質問をLLM生成
   ↓
[1/2/3 選択]
   ↓
(Q2生成直前にノブ値を再反映)
   ↓
Q2: 深掘り質問をLLM生成
   ↓
[1/2/3 選択]
   ↓
(THANKS生成直前にノブ値を再反映)
   ↓
THANKS: お礼文をLLM生成
   ↓
次のセッション待ち
```

---

## 重要な設計方針

### 1. run_gpio と run_terminal は「構造を揃える」

- `run_terminal.py` は **REPLではなく GPIO版の完全代替**
- ロジック差分は **入力層（input_*）のみ**
- `state_machine.py` は **一切分岐しない**

👉 実機で確認した挙動を、そのまま Terminal で再現できます。

---

### 2. ノブ（Temperature / Top-k）は「生成直前」に必ず反映

以下の **3箇所で必ずノブ値を再読込**します。

- セッション開始時
- Q2生成直前
- THANKS生成直前

これは「途中でノブを回した効果を即座に観察する」ための仕様です。

---

## 実行方法

### Terminal 版（開発・デバッグ用）

```bash
python run_terminal.py
```

#### 主なコマンド

```
/start        : セッション開始（PIR相当）
/temp 0.7     : Temperature設定 (0.0〜1.0)
/topk 0.4     : Top-k設定 (0.0〜1.0)
1 / 2 / 3     : 回答入力
/status       : 状態表示
/reset        : セッションリセット
/quit         : 終了
```

---

### GPIO 版（Raspberry Pi 実機）

```bash
python run_gpio.py
```

#### 入力デバイス

- PIR（人感センサ）: セッション開始
- ボタン 1 / 2 / 3 : 回答入力
- 可変抵抗 CH0     : Temperature
- 可変抵抗 CH1     : Top-k



<img width="1295" height="970" alt="image" src="https://github.com/user-attachments/assets/0d1de733-cc83-489a-a566-e83234581e09" />
