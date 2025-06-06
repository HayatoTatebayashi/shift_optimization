import json
import subprocess
import os
import requests # HTTPリクエスト用

# --- 設定 ---
CLOUD_RUN_SERVICE_NAME = "solve-shift-service"  # あなたのCloud Runサービス名に合わせてください
CLOUD_RUN_REGION = "asia-northeast1"         # あなたのCloud Runリージョンに合わせてください
INPUT_JSON_FILE = "generated_combined_input_data.json"
OUTPUT_JSON_FILE = "solution_from_cloud_run.json"
# Cloud Runへのリクエスト時のタイムアウト (秒)
REQUEST_TIMEOUT_SEC = 300 # Cloud Run側のタイムアウトより少し短く設定すると良い
# solve_schedule関数に渡す time_limit_sec (Cloud Run上のソルバー実行時間制限)
SOLVER_TIME_LIMIT_SEC = 120 # 必要に応じて調整

def get_cloud_run_url(service_name, region):
    """gcloudコマンドを使ってCloud RunサービスのURLを取得する"""
    try:
        command = [
            "gcloud", "run", "services", "describe", service_name,
            "--region", region,
            "--format", "value(status.url)"
        ]
        process = subprocess.run(command, capture_output=True, text=True, check=True)
        url = process.stdout.strip()
        if not url:
            print(f"エラー: {service_name} のURLを取得できませんでした。gcloudコマンドの出力を確認してください。")
            return None
        print(f"取得したCloud RunサービスURL: {url}")
        return url
    except subprocess.CalledProcessError as e:
        print(f"エラー: gcloudコマンドの実行に失敗しました: {e}")
        print(f"エラー出力:\n{e.stderr}")
        return None
    except FileNotFoundError:
        print("エラー: gcloudコマンドが見つかりません。パスが通っているか確認してください。")
        return None

def send_request_to_cloud_run(url, data, solver_time_limit):
    """Cloud RunサービスにPOSTリクエストを送信する"""
    headers = {"Content-Type": "application/json"}
    # time_limit_sec をクエリパラメータとしてURLに追加
    request_url = f"{url}?time_limit_sec={solver_time_limit}"
    print(f"リクエストURL: {request_url}")
    print(f"送信データサイズ: 約 {len(json.dumps(data))/1024:.2f} KB")

    try:
        response = requests.post(request_url, json=data, headers=headers, timeout=REQUEST_TIMEOUT_SEC)
        response.raise_for_status()  # HTTPエラーがあれば例外を発生させる (4xx, 5xx)
        print(f"レスポンスステータスコード: {response.status_code}")
        return response.json()
    except requests.exceptions.HTTPError as e:
        print(f"HTTPエラーが発生しました: {e}")
        print(f"レスポンスボディ: {response.text}") # エラー詳細の確認
        return None
    except requests.exceptions.ConnectionError as e:
        print(f"接続エラーが発生しました: {e}")
        return None
    except requests.exceptions.Timeout as e:
        print(f"リクエストがタイムアウトしました ({REQUEST_TIMEOUT_SEC}秒): {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"リクエスト中に予期せぬエラーが発生しました: {e}")
        return None
    except json.JSONDecodeError:
        print("エラー: レスポンスのJSONデコードに失敗しました。")
        print(f"レスポンスボディ: {response.text}")
        return None


if __name__ == "__main__":
    print("--- Cloud Run サービスURL取得開始 ---")
    service_url = get_cloud_run_url(CLOUD_RUN_SERVICE_NAME, CLOUD_RUN_REGION)

    if not service_url:
        print("Cloud RunのURL取得に失敗したため、処理を終了します。")
        exit(1)
    print("--- Cloud Run サービスURL取得完了 ---")

    print(f"--- 入力ファイル '{INPUT_JSON_FILE}' 読み込み開始 ---")
    if not os.path.exists(INPUT_JSON_FILE):
        print(f"エラー: 入力ファイル '{INPUT_JSON_FILE}' が見つかりません。")
        print("先に demo_input_generator.py を実行してファイルを生成してください。")
        exit(1)

    try:
        with open(INPUT_JSON_FILE, 'r', encoding='utf-8') as f:
            input_data = json.load(f)
        print(f"--- 入力ファイル '{INPUT_JSON_FILE}' 読み込み完了 ---")
    except json.JSONDecodeError:
        print(f"エラー: 入力ファイル '{INPUT_JSON_FILE}' のJSON形式が正しくありません。")
        exit(1)
    except Exception as e:
        print(f"エラー: 入力ファイル '{INPUT_JSON_FILE}' の読み込み中にエラーが発生しました: {e}")
        exit(1)

    print("--- Cloud Runへのリクエスト送信開始 ---")
    solution_data = send_request_to_cloud_run(service_url, input_data, SOLVER_TIME_LIMIT_SEC)
    print("--- Cloud Runへのリクエスト送信完了 ---")

    if solution_data:
        print(f"--- 結果を '{OUTPUT_JSON_FILE}' に保存中 ---")
        try:
            with open(OUTPUT_JSON_FILE, 'w', encoding='utf-8') as f:
                json.dump(solution_data, f, indent=2, ensure_ascii=False)
            print(f"結果を '{OUTPUT_JSON_FILE}' に保存しました。")
            print("\n--- 受信したレスポンス (一部表示) ---")
            # レスポンスが大きい場合があるので、主要な部分だけ表示する例
            if isinstance(solution_data, dict):
                print(f"  Schedule Status: {solution_data.get('schedule_result', {}).get('status')}")
                print(f"  Overtime Status: {solution_data.get('overtime_result', {}).get('status')}")
                if 'logs' in solution_data and 'errors' in solution_data['logs'] and solution_data['logs']['errors']:
                    print(f"  エラーログあり ({len(solution_data['logs']['errors'])}件)")
            else:
                print(json.dumps(solution_data, indent=2, ensure_ascii=False)[:1000] + "...") # 最初の1000文字
            print("-----------------------------------")

        except Exception as e:
            print(f"エラー: 結果の保存中にエラーが発生しました: {e}")
    else:
        print("Cloud Runからのレスポンス取得に失敗しました。")