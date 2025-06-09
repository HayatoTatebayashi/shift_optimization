# ---- base layer ----
    FROM python:3.12-slim

    # 基本設定
    WORKDIR /app
    
    # 依存ライブラリだけ先にコピー→インストール
    COPY requirements.txt .
    RUN pip install --no-cache-dir -r requirements.txt
    
    # アプリ本体を最後にコピー
    COPY . .
    
    # エントリポイント（Batch で上書き可）
    ENTRYPOINT ["python", "solve_new.py"]
    