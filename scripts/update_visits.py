import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUT = Path("data/visits.json")
API_BASE = os.environ.get("PLAUSIBLE_API_BASE", "https://plausible.io").rstrip("/")
API_KEY = os.environ.get("PLAUSIBLE_API_KEY", "").strip()
SITE_ID = os.environ.get("PLAUSIBLE_SITE_ID", "").strip()
PERIOD = os.environ.get("PLAUSIBLE_PERIOD", "30d").strip() or "30d"
PATH_PREFIX = os.environ.get("PLAUSIBLE_PATH_PREFIX", "/china-tour-2026").strip()


def write_payload(payload):
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def empty(status, message):
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "plausible",
        "status": status,
        "period": PERIOD,
        "site_id": SITE_ID,
        "path_prefix": PATH_PREFIX,
        "totals": {"visitors": 0, "visits": 0, "pageviews": 0},
        "locations": [],
        "message": message,
    }


def plausible_query(metrics, dimensions=None):
    filters = [["is_not", "visit:country_name", [""]]]
    if PATH_PREFIX:
        filters.append(["contains", "event:page", [PATH_PREFIX]])
    query = {
        "site_id": SITE_ID,
        "metrics": metrics,
        "date_range": PERIOD,
        "filters": filters,
    }
    if dimensions:
        query["dimensions"] = dimensions
        query["order_by"] = [["visitors", "desc"]]
        query["pagination"] = {"limit": 50, "offset": 0}
    req = urllib.request.Request(
        API_BASE + "/api/v2/query",
        data=json.dumps(query).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + API_KEY,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main():
    if not API_KEY or not SITE_ID:
        write_payload(empty("not_configured", "Добавьте PLAUSIBLE_API_KEY и PLAUSIBLE_SITE_ID в GitHub Secrets."))
        return 0
    metrics = ["visitors", "visits", "pageviews"]
    try:
        totals_response = plausible_query(metrics)
        locations_response = plausible_query(metrics, ["visit:country_name", "visit:city_name"])
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        write_payload(empty("error", f"Plausible API вернул {exc.code}: {detail}"))
        return 1
    except Exception as exc:
        write_payload(empty("error", f"Не удалось обновить Plausible: {exc}"))
        return 1

    total_metrics = (totals_response.get("results") or [{}])[0].get("metrics", [0, 0, 0])
    locations = []
    for row in locations_response.get("results", []):
        country, city = (row.get("dimensions") or ["", ""])[:2]
        visitors, visits, pageviews = (row.get("metrics") or [0, 0, 0])[:3]
        locations.append({
            "country": country or "Не определено",
            "city": city or "Не определено",
            "visitors": int(visitors or 0),
            "visits": int(visits or 0),
            "pageviews": int(pageviews or 0),
        })
    write_payload({
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "plausible",
        "status": "ok",
        "period": PERIOD,
        "site_id": SITE_ID,
        "path_prefix": PATH_PREFIX,
        "totals": {
            "visitors": int((total_metrics + [0, 0, 0])[0] or 0),
            "visits": int((total_metrics + [0, 0, 0])[1] or 0),
            "pageviews": int((total_metrics + [0, 0, 0])[2] or 0),
        },
        "locations": locations,
        "message": "",
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
