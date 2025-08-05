import json
from datetime import datetime, timezone

def parse_iso8601(ts):
    # Handles timestamps like "2025-08-01T09:08:51Z"
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

def find_closest_record(jsonl_path, target_ts):
    target_dt = parse_iso8601(target_ts)
    min_diff = None
    closest_record = None

    with open(jsonl_path, "r") as f:
        for line in f:
            try:
                obj = json.loads(line)
                record_ts = parse_iso8601(obj["timestamp"])
                diff = abs((record_ts - target_dt).total_seconds())
                if (min_diff is None) or (diff < min_diff):
                    min_diff = diff
                    closest_record = obj
            except Exception as e:
                continue  # skip malformed lines

    return closest_record

# Example usage:
image_ts = "2025-08-01T09:25:48Z"  # timestamp of the image
match = find_closest_record("/home/sg/sensing-garden/sen55/env_data.jsonl", image_ts)
print(json.dumps(match, indent=2))
