import json
import requests  # pip install requests

def load_all_records(jsonl_path):
    records = []
    with open(jsonl_path, "r") as f:
        for line in f:
            try:
                obj = json.loads(line)
                records.append(obj)
            except Exception:
                continue
    return records

def upload_records(api_url, records, auth_token=None):
    headers = {"Content-Type": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    resp = requests.post(api_url, data=json.dumps(records), headers=headers)
    resp.raise_for_status()
    return resp.status_code

# Usage:
api_url = "https://your_api_endpoint.example/upload"
jsonl_path = "/home/sg/sensing-garden/sen55/env_data.jsonl"
records = load_all_records(jsonl_path)
if records:
    status = upload_records(api_url, records)
    print(f"Upload successful: {status}")
    # If successful, clear file
    open(jsonl_path, "w").close()
else:
    print("No records to upload.")
