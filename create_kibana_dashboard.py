"""Create the SHIELD Kibana Analytics dashboard (classic visualizations).

Run while Kibana is up:
    python create_kibana_dashboard.py
"""

import json
import sys

import requests

KIBANA = "http://127.0.0.1:5601"
HEADERS = {"kbn-xsrf": "true", "Content-Type": "application/json"}

LOGS_VIEW = "75ce9249-fc92-48f3-87a9-29e4f25787d0"
ML_VIEW = "cabb1875-67ae-4343-ad04-bac763cfecb0"

DASHBOARD_ID = "shield-live-traffic"
DASHBOARD_TITLE = "SHIELD live traffic"
VIZ_DASHBOARD_ID = "shield-data-visualizer"
VIZ_DASHBOARD_TITLE = "SHIELD data visualizer"


def _upsert_data_view(view_id, title, name):
    payload = {
        "data_view": {
            "id": view_id,
            "title": title,
            "name": name,
            "timeFieldName": "@timestamp",
            "allowNoIndex": True,
        },
        "override": True,
    }
    created = requests.post(
        f"{KIBANA}/api/data_views/data_view",
        headers=HEADERS,
        json=payload,
        timeout=20,
    )
    if created.status_code not in (200, 409):
        # Already exists — fetch it.
        existing = requests.get(
            f"{KIBANA}/api/data_views/data_view/{view_id}",
            headers=HEADERS,
            timeout=15,
        )
        if existing.status_code == 200:
            return existing.json()["data_view"]["id"]
        created.raise_for_status()
    return created.json().get("data_view", {}).get("id") or view_id


def ensure_data_views():
    logs_id = _upsert_data_view(LOGS_VIEW, "logs*", "Live packets")
    ml_id = _upsert_data_view(ML_VIEW, "ml-results*", "Anomaly results")
    requests.post(
        f"{KIBANA}/api/data_views/default",
        headers=HEADERS,
        json={"data_view_id": logs_id, "force": True},
        timeout=15,
    )
    return logs_id, ml_id


def vis_state(title, vis_type, aggs, params=None):
    return {
        "title": title,
        "type": vis_type,
        "aggs": aggs,
        "params": params
        or {
            "type": vis_type,
            "grid": {"categoryLines": False},
            "categoryAxes": [
                {
                    "id": "CategoryAxis-1",
                    "type": "category",
                    "position": "bottom",
                    "show": True,
                    "style": {},
                    "scale": {"type": "linear"},
                    "labels": {"show": True, "truncate": 100},
                    "title": {},
                }
            ],
            "valueAxes": [
                {
                    "id": "ValueAxis-1",
                    "name": "LeftAxis-1",
                    "type": "value",
                    "position": "left",
                    "show": True,
                    "style": {},
                    "scale": {"type": "linear", "mode": "normal"},
                    "labels": {"show": True, "rotate": 0, "filter": False, "truncate": 100},
                    "title": {"text": "Count"},
                }
            ],
            "seriesParams": [
                {
                    "show": True,
                    "type": vis_type,
                    "mode": "normal",
                    "data": {"label": "Count", "id": "1"},
                    "valueAxis": "ValueAxis-1",
                    "drawLinesBetweenPoints": True,
                    "lineWidth": 2,
                    "showCircles": True,
                }
            ],
            "addTooltip": True,
            "addLegend": True,
            "legendPosition": "right",
            "times": [],
            "addTimeMarker": False,
        },
    }


def search_source(index_id, query=""):
    return {
        "index": index_id,
        "query": {"query": query, "language": "kuery"},
        "filter": [],
    }


def upsert_visualization(vis_id, title, index_id, vis_type, aggs, query="", params=None):
    body = {
        "attributes": {
            "title": title,
            "visState": json.dumps(vis_state(title, vis_type, aggs, params)),
            "uiStateJSON": "{}",
            "description": "",
            "kibanaSavedObjectMeta": {
                "searchSourceJSON": json.dumps(search_source(index_id, query))
            },
        },
        "references": [
            {"name": "kibanaSavedObjectMeta.searchSourceJSON.index", "type": "index-pattern", "id": index_id}
        ],
    }
    response = requests.put(
        f"{KIBANA}/api/saved_objects/visualization/{vis_id}",
        headers=HEADERS,
        json=body,
        timeout=20,
    )
    if response.status_code == 404:
        response = requests.post(
            f"{KIBANA}/api/saved_objects/visualization/{vis_id}",
            headers=HEADERS,
            json=body,
            timeout=20,
        )
    response.raise_for_status()
    return vis_id


def pie_params():
    return {
        "type": "pie",
        "addTooltip": True,
        "addLegend": True,
        "legendPosition": "right",
        "isDonut": True,
        "labels": {"show": False},
    }


def metric_params(sub_text=""):
    return {
        "addTooltip": True,
        "addLegend": False,
        "type": "metric",
        "metric": {
            "percentageMode": False,
            "useRanges": False,
            "colorSchema": "Green to Red",
            "metricColorMode": "None",
            "colorsRange": [{"from": 0, "to": 10000}],
            "labels": {"show": True},
            "invertColors": False,
            "style": {
                "bgFill": "#000",
                "bgColor": False,
                "labelColor": False,
                "subText": sub_text,
                "fontSize": 36,
            },
        },
    }


def table_params():
    return {
        "perPage": 10,
        "showPartialRows": False,
        "showMetricsAtAllLevels": False,
        "sort": {"columnIndex": None, "direction": None},
        "showTotal": False,
        "showToolbar": True,
        "totalFunc": "sum",
        "percentageCol": "",
    }


def upsert_dashboard(dashboard_id, title, description, layouts):
    panels = []
    refs = []
    for i, (panel_id, vis_id, x, y, w, h) in enumerate(layouts):
        panels.append(
            {
                "version": "8.12.0",
                "type": "visualization",
                "gridData": {"x": x, "y": y, "w": w, "h": h, "i": panel_id},
                "panelIndex": panel_id,
                "embeddableConfig": {"enhancements": {}},
                "panelRefName": f"panel_{i}",
            }
        )
        refs.append({"name": f"panel_{i}", "type": "visualization", "id": vis_id})

    body = {
        "attributes": {
            "title": title,
            "hits": 0,
            "description": description,
            "panelsJSON": json.dumps(panels),
            "optionsJSON": json.dumps(
                {"useMargins": True, "syncColors": False, "hidePanelTitles": False}
            ),
            "version": 1,
            "timeRestore": True,
            "timeTo": "now",
            "timeFrom": "now-24h",
            "refreshInterval": {"pause": False, "value": 10000},
            "kibanaSavedObjectMeta": {
                "searchSourceJSON": json.dumps(
                    {"query": {"query": "", "language": "kuery"}, "filter": []}
                )
            },
        },
        "references": refs,
    }
    response = requests.put(
        f"{KIBANA}/api/saved_objects/dashboard/{dashboard_id}",
        headers=HEADERS,
        json=body,
        timeout=20,
    )
    if response.status_code == 404:
        response = requests.post(
            f"{KIBANA}/api/saved_objects/dashboard/{dashboard_id}",
            headers=HEADERS,
            json=body,
            timeout=20,
        )
    response.raise_for_status()
    return dashboard_id


def main():
    try:
        requests.get(f"{KIBANA}/api/status", timeout=8).raise_for_status()
    except requests.RequestException as exc:
        print(f"Kibana is not reachable at {KIBANA}: {exc}")
        print("Start it with: docker compose up -d")
        sys.exit(1)

    logs_id, ml_id = ensure_data_views()
    count = {
        "id": "1",
        "enabled": True,
        "type": "count",
        "params": {},
        "schema": "metric",
    }

    vis_ids = [
        upsert_visualization(
            "shield-packets-over-time",
            "Packet count over time",
            logs_id,
            "line",
            [
                count,
                {
                    "id": "2",
                    "enabled": True,
                    "type": "date_histogram",
                    "schema": "segment",
                    "params": {
                        "field": "@timestamp",
                        "interval": "auto",
                        "min_doc_count": 1,
                    },
                },
            ],
        ),
        upsert_visualization(
            "shield-top-dst-ports",
            "Top destination ports",
            logs_id,
            "histogram",
            [
                count,
                {
                    "id": "2",
                    "enabled": True,
                    "type": "terms",
                    "schema": "segment",
                    "params": {
                        "field": "dst_port",
                        "size": 10,
                        "order": "desc",
                        "orderBy": "1",
                    },
                },
            ],
        ),
        upsert_visualization(
            "shield-top-dst-ips",
            "Top destination IPs",
            logs_id,
            "histogram",
            [
                count,
                {
                    "id": "2",
                    "enabled": True,
                    "type": "terms",
                    "schema": "segment",
                    "params": {
                        "field": "dst_ip.keyword",
                        "size": 10,
                        "order": "desc",
                        "orderBy": "1",
                    },
                },
            ],
        ),
        upsert_visualization(
            "shield-protocol-breakdown",
            "Protocol breakdown",
            logs_id,
            "pie",
            [
                count,
                {
                    "id": "2",
                    "enabled": True,
                    "type": "terms",
                    "schema": "segment",
                    "params": {
                        "field": "protocol.keyword",
                        "size": 5,
                        "order": "desc",
                        "orderBy": "1",
                    },
                },
            ],
            params=pie_params(),
        ),
        upsert_visualization(
            "shield-anomalies-over-time",
            "Anomaly count over time",
            ml_id,
            "line",
            [
                count,
                {
                    "id": "2",
                    "enabled": True,
                    "type": "date_histogram",
                    "schema": "segment",
                    "params": {
                        "field": "@timestamp",
                        "interval": "auto",
                        "min_doc_count": 1,
                    },
                },
            ],
            query="status: ANOMALY",
        ),
        upsert_visualization(
            "shield-if-normal-vs-anomaly",
            "Isolation Forest: normal vs anomaly",
            ml_id,
            "pie",
            [
                count,
                {
                    "id": "2",
                    "enabled": True,
                    "type": "terms",
                    "schema": "segment",
                    "params": {
                        "field": "anomaly",
                        "size": 2,
                        "order": "desc",
                        "orderBy": "1",
                    },
                },
            ],
            params=pie_params(),
        ),
        upsert_visualization(
            "shield-window-ports-over-time",
            "Unique destination ports per window",
            ml_id,
            "line",
            [
                {
                    "id": "1",
                    "enabled": True,
                    "type": "avg",
                    "schema": "metric",
                    "params": {"field": "unique_dst_ports"},
                },
                {
                    "id": "2",
                    "enabled": True,
                    "type": "date_histogram",
                    "schema": "segment",
                    "params": {
                        "field": "@timestamp",
                        "interval": "auto",
                        "min_doc_count": 1,
                    },
                },
            ],
        ),
        upsert_visualization(
            "shield-anomaly-windows",
            "Anomalous windows (investigate)",
            ml_id,
            "table",
            [
                count,
                {
                    "id": "2",
                    "enabled": True,
                    "type": "terms",
                    "schema": "bucket",
                    "params": {
                        "field": "event_id.keyword",
                        "size": 15,
                        "order": "desc",
                        "orderBy": "1",
                    },
                },
            ],
            query="status: ANOMALY AND NOT event_id: current-status",
            params=table_params(),
        ),
        upsert_visualization(
            "shield-if-by-time",
            "Isolation Forest labels over time",
            ml_id,
            "histogram",
            [
                count,
                {
                    "id": "2",
                    "enabled": True,
                    "type": "date_histogram",
                    "schema": "segment",
                    "params": {
                        "field": "@timestamp",
                        "interval": "auto",
                        "min_doc_count": 1,
                    },
                },
                {
                    "id": "3",
                    "enabled": True,
                    "type": "terms",
                    "schema": "group",
                    "params": {
                        "field": "anomaly",
                        "size": 2,
                        "order": "desc",
                        "orderBy": "1",
                    },
                },
            ],
        ),
    ]

    upsert_dashboard(
        DASHBOARD_ID,
        DASHBOARD_TITLE,
        "Live laptop packets and Isolation Forest anomalies",
        [
            ("1", vis_ids[4], 0, 0, 48, 14),
            ("2", vis_ids[7], 0, 14, 24, 12),
            ("3", vis_ids[8], 24, 14, 24, 12),
            ("4", vis_ids[5], 0, 26, 16, 12),
            ("5", vis_ids[6], 16, 26, 32, 12),
            ("6", vis_ids[0], 0, 38, 24, 12),
            ("7", vis_ids[3], 24, 38, 24, 12),
        ],
    )

    viz_ids = [
        upsert_visualization(
            "shield-metric-packets",
            "Total packets",
            logs_id,
            "metric",
            [count],
            params=metric_params("logs index"),
        ),
        upsert_visualization(
            "shield-metric-unique-dst",
            "Unique destination IPs",
            logs_id,
            "metric",
            [
                {
                    "id": "1",
                    "enabled": True,
                    "type": "cardinality",
                    "schema": "metric",
                    "params": {"field": "dst_ip.keyword"},
                }
            ],
            params=metric_params("dst_ip"),
        ),
        upsert_visualization(
            "shield-metric-avg-bytes",
            "Average packet size",
            logs_id,
            "metric",
            [
                {
                    "id": "1",
                    "enabled": True,
                    "type": "avg",
                    "schema": "metric",
                    "params": {"field": "bytes"},
                }
            ],
            params=metric_params("bytes"),
        ),
        upsert_visualization(
            "shield-metric-anomalies",
            "Anomaly count",
            ml_id,
            "metric",
            [count],
            query="status: ANOMALY",
            params=metric_params("anomaly = -1"),
        ),
        upsert_visualization(
            "shield-table-src-ip",
            "Field: src_ip",
            logs_id,
            "table",
            [
                count,
                {
                    "id": "2",
                    "enabled": True,
                    "type": "terms",
                    "schema": "bucket",
                    "params": {
                        "field": "src_ip.keyword",
                        "size": 10,
                        "order": "desc",
                        "orderBy": "1",
                    },
                },
            ],
            params=table_params(),
        ),
        upsert_visualization(
            "shield-table-dst-port",
            "Field: dst_port",
            logs_id,
            "table",
            [
                count,
                {
                    "id": "2",
                    "enabled": True,
                    "type": "terms",
                    "schema": "bucket",
                    "params": {
                        "field": "dst_port",
                        "size": 10,
                        "order": "desc",
                        "orderBy": "1",
                    },
                },
            ],
            params=table_params(),
        ),
        upsert_visualization(
            "shield-table-protocol",
            "Field: protocol",
            logs_id,
            "table",
            [
                count,
                {
                    "id": "2",
                    "enabled": True,
                    "type": "terms",
                    "schema": "bucket",
                    "params": {
                        "field": "protocol.keyword",
                        "size": 10,
                        "order": "desc",
                        "orderBy": "1",
                    },
                },
            ],
            params=table_params(),
        ),
        upsert_visualization(
            "shield-table-anomaly",
            "Field: anomaly",
            ml_id,
            "table",
            [
                count,
                {
                    "id": "2",
                    "enabled": True,
                    "type": "terms",
                    "schema": "bucket",
                    "params": {
                        "field": "anomaly",
                        "size": 5,
                        "order": "desc",
                        "orderBy": "1",
                    },
                },
            ],
            params=table_params(),
        ),
    ]

    upsert_dashboard(
        VIZ_DASHBOARD_ID,
        VIZ_DASHBOARD_TITLE,
        "Field stats for live packets and ML results (Analytics data visualizer)",
        [
            ("1", viz_ids[0], 0, 0, 12, 10),
            ("2", viz_ids[1], 12, 0, 12, 10),
            ("3", viz_ids[2], 24, 0, 12, 10),
            ("4", viz_ids[3], 36, 0, 12, 10),
            ("5", viz_ids[4], 0, 10, 24, 16),
            ("6", viz_ids[5], 24, 10, 24, 16),
            ("7", viz_ids[6], 0, 26, 24, 16),
            ("8", viz_ids[7], 24, 26, 24, 16),
        ],
    )

    print(f"Dashboard: {KIBANA}/app/dashboards#/view/{DASHBOARD_ID}")
    print(f"Data visualizer: {KIBANA}/app/dashboards#/view/{VIZ_DASHBOARD_ID}")
    print(
        f"ML Data Visualizer (logs): "
        f"{KIBANA}/app/ml/datavisualizer_index_view?index={logs_id}"
    )
    print(
        f"ML Data Visualizer (ml-results): "
        f"{KIBANA}/app/ml/datavisualizer_index_view?index={ml_id}"
    )


if __name__ == "__main__":
    main()
