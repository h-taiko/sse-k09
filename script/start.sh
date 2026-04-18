#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="jupyter_env"
VENV_PATH="${SCRIPT_DIR}/${VENV_DIR}"

if [ -f "${VENV_PATH}/bin/activate" ]; then
    echo "${VENV_DIR} がすでに存在しています"
else
    echo "仮想環境${VENV_DIR}がありません"
    echo "先に setup.sh を実行してください"
    exit 1
fi

echo "仮想環境を有効化中..."
source "${VENV_PATH}/bin/activate"

echo "Jupyter をインストール中..."
pip install jupyter

echo "親ディレクトリへ移動します..."
cd "${SCRIPT_DIR}/.."
cd notebook

echo "現在のディレクトリ: $(pwd)"
echo "現在の Python: $(which python)"
echo "仮想環境: $VIRTUAL_ENV"

echo "Jupyter Notebook を起動します..."
jupyter notebook

exec bash --noprofile --norc
