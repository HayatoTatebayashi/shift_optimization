# python cloud_run_trigger.py
from google.auth.transport.requests import Request
from google.oauth2 import service_account
import requests, json, os


INPUT_JSON  = "generated_combined_input_data.json"
SERVICE_URL = "https://shift-optimazation-935486185986.asia-northeast1.run.app"
OUTPUT_JSON = "solution_from_cloud_run.json"

creds = service_account.IDTokenCredentials.from_service_account_file(
    "shifthub-462108-1d597be5e5d6.json",
    target_audience=SERVICE_URL)                         # ★audience は URL
creds.refresh(Request())                                 # ID トークンを取得
token = creds.token

resp = requests.post(f"{SERVICE_URL}?time_limit_sec=120",
     headers={"Authorization": f"Bearer {token}",
              "Content-Type": "application/json"},
     json=json.load(open(INPUT_JSON, encoding="utf-8")),
     timeout=3600)

resp.raise_for_status()
json.dump(resp.json(), open(OUTPUT_JSON, "w", encoding="utf-8"),
            ensure_ascii=False, indent=2)

print(resp.json()["schedule_result"]["status"])
