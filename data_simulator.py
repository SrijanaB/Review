# Fallback only. Prefer: sudo python3 live_capture.py
# This file invents HTTP-like fields and is not real router traffic.
import requests
import random
import time
from datetime import datetime

ES_URL = "http://localhost:9200/logs/_doc"

while True:
    # Normal traffic
    data = {
        "bytes": random.randint(100, 500),
        "response_time": round(random.uniform(0.5, 2.0), 2),
        "status_code": random.choice([200, 200, 200, 404]),  # mostly normal
        "@timestamp": datetime.utcnow().isoformat() + "Z"
    }

    # Inject anomaly (10% chance)
    if random.random() < 0.5:
        data["bytes"] = random.randint(3000, 8000)
        data["response_time"] = round(random.uniform(5, 15), 2)
        data["status_code"] = random.choice([500, 503])

    requests.post(ES_URL, json=data)

    print("Sent:", data)

    time.sleep(1)  # every 1 second
