from elasticsearch import Elasticsearch
import pandas as pd
from sklearn.ensemble import IsolationForest
import time

es = Elasticsearch("http://localhost:9200")

while True:

    # Fetch logs
    response = es.search(
        index="logs",
        query={"match_all": {}},
        size=1000
    )

    data = []
    for hit in response['hits']['hits']:
        src = hit['_source']
        data.append({
            "bytes": src.get("bytes", 0),
            "response_time": src.get("response_time", 0),
            "status_code": src.get("status_code", 0),
            "@timestamp": src.get("@timestamp")
        })
        

    df = pd.DataFrame(data)
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler()

    scaled_features = scaler.fit_transform(
    df[["bytes", "response_time", "status_code"]]
    )

    # ML model
    model = IsolationForest(contamination=0.05, random_state=42)
    df['anomaly'] = model.fit_predict(scaled_features)

    # Push results
    for _, row in df.iterrows():
        es.index(
            index="ml-results",
            document={
                "bytes": float(row["bytes"]),
                "response_time": float(row["response_time"]),
                "status_code": int(row["status_code"]),
                "anomaly": int(row["anomaly"]),
                "@timestamp": row["@timestamp"]
            }
        )

    print("Processed batch")

    time.sleep(10)
