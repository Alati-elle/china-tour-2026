import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUT = Path("data/visits.json")
ANALYTICS = Path("data/analytics.json")
PROPERTY_ID = os.environ.get("GA_PROPERTY_ID", "").strip()
SERVICE_ACCOUNT_JSON = os.environ.get("GA_SERVICE_ACCOUNT_JSON", "").strip()
MEASUREMENT_ID = os.environ.get("GA_MEASUREMENT_ID", "").strip()
PERIOD = os.environ.get("GA_PERIOD", "30daysAgo").strip() or "30daysAgo"
API_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def b64url(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def empty(status, message):
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "google_analytics",
        "status": status,
        "period": PERIOD,
        "property_id": PROPERTY_ID,
        "totals": {"visitors": 0, "visits": 0, "pageviews": 0},
        "locations": [],
        "message": message,
    }


def update_public_config():
    current = {}
    if ANALYTICS.exists():
        try:
            current = json.loads(ANALYTICS.read_text())
        except Exception:
            current = {}
    if MEASUREMENT_ID:
        current["measurement_id"] = MEASUREMENT_ID
    current.setdefault("measurement_id", "")
    write_json(ANALYTICS, current)


def sign_rs256(data, private_key):
    with tempfile.NamedTemporaryFile("w", delete=False) as key_file:
        key_file.write(private_key)
        key_path = key_file.name
    try:
        proc = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", key_path],
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        return proc.stdout
    finally:
        Path(key_path).unlink(missing_ok=True)


def access_token():
    account = json.loads(SERVICE_ACCOUNT_JSON)
    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {
        "iss": account["client_email"],
        "scope": API_SCOPE,
        "aud": TOKEN_URL,
        "iat": now,
        "exp": now + 3600,
    }
    unsigned = b64url(json.dumps(header, separators=(",", ":")).encode()) + "." + b64url(json.dumps(claims, separators=(",", ":")).encode())
    signature = b64url(sign_rs256(unsigned.encode("ascii"), account["private_key"]))
    body = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": unsigned + "." + signature,
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST")
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode())["access_token"]


def run_report(token, dimensions=None, limit=100):
    payload = {
        "dateRanges": [{"startDate": PERIOD, "endDate": "today"}],
        "metrics": [{"name": "activeUsers"}, {"name": "sessions"}, {"name": "screenPageViews"}],
        "limit": str(limit),
    }
    if dimensions:
        payload["dimensions"] = [{"name": name} for name in dimensions]
        payload["orderBys"] = [{"metric": {"metricName": "activeUsers"}, "desc": True}]
    req = urllib.request.Request(
        f"https://analyticsdata.googleapis.com/v1beta/properties/{PROPERTY_ID}:runReport",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def metric_values(row):
    values = [int(x.get("value", 0) or 0) for x in row.get("metricValues", [])]
    return (values + [0, 0, 0])[:3]


def main():
    update_public_config()
    if not PROPERTY_ID or not SERVICE_ACCOUNT_JSON:
        write_json(OUT, empty("not_configured", "Добавьте GA_PROPERTY_ID, GA_SERVICE_ACCOUNT_JSON и GA_MEASUREMENT_ID в GitHub Secrets."))
        return 0
    try:
        token = access_token()
        totals_response = run_report(token)
        locations_response = run_report(token, ["country", "region", "city"], 50)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        write_json(OUT, empty("error", f"Google Analytics API вернул {exc.code}: {detail}"))
        return 1
    except Exception as exc:
        write_json(OUT, empty("error", f"Не удалось обновить Google Analytics: {exc}"))
        return 1

    total_row = (totals_response.get("rows") or [{}])[0]
    visitors, visits, pageviews = metric_values(total_row)
    locations = []
    for row in locations_response.get("rows", []):
        dims = [x.get("value", "") for x in row.get("dimensionValues", [])]
        country, region, city = (dims + ["", "", ""])[:3]
        row_visitors, row_visits, row_pageviews = metric_values(row)
        locations.append({
            "country": country or "Не определено",
            "region": region or "",
            "city": city or "Не определено",
            "visitors": row_visitors,
            "visits": row_visits,
            "pageviews": row_pageviews,
        })
    write_json(OUT, {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "google_analytics",
        "status": "ok",
        "period": PERIOD,
        "property_id": PROPERTY_ID,
        "totals": {"visitors": visitors, "visits": visits, "pageviews": pageviews},
        "locations": locations,
        "message": "",
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
