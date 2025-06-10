import json
import datetime
from google.cloud import storage

def test_gcs_save():
    """
    GCSへの保存機能をテストする
    python test_gcs_save.py
    """
    GCS_BUCKET_NAME = "shift-optimization-result-storage"
    GCS_OBJECT_PREFIX = "result-folder/"
    run_id_test = f"test_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S%f')}"

    # テスト用データの作成
    test_data = {
        "test_id": run_id_test,
        "timestamp": datetime.datetime.now().isoformat(),
        "sample_data": {
            "schedule_result": {
                "status": "TEST",
                "assignments": []
            }
        }
    }

    try:
        # 1. GCSクライアントの初期化
        print("GCSクライアントの初期化中...")
        storage_client = storage.Client()
        
        # 2. バケットの取得
        print(f"バケット '{GCS_BUCKET_NAME}' の取得中...")
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        
        # 3. 保存するファイル名の生成
        object_name = f"{GCS_OBJECT_PREFIX}test_{run_id_test}.json"
        print(f"保存先: gs://{GCS_BUCKET_NAME}/{object_name}")

        # 4. JSONデータの準備
        json_string = json.dumps(test_data, indent=2, ensure_ascii=False)
        
        # 5. GCSへの保存
        print("データをGCSに保存中...")
        blob = bucket.blob(object_name)
        blob.upload_from_string(
            json_string,
            content_type='application/json'
        )
        
        # 6. 保存確認
        print("保存したデータの確認中...")
        stored_blob = bucket.get_blob(object_name)
        if stored_blob:
            stored_data = json.loads(stored_blob.download_as_string())
            print("保存成功！")
            print(f"保存されたデータのtest_id: {stored_data.get('test_id')}")
            return True
        else:
            print("エラー: 保存したデータが見つかりません")
            return False

    except Exception as e:
        print(f"エラーが発生しました: {str(e)}")
        return False

if __name__ == "__main__":
    print("GCS保存機能のテストを開始します...")
    success = test_gcs_save()
    print(f"テスト結果: {'成功' if success else '失敗'}")