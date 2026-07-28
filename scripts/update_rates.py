#!/usr/bin/env python3
import json
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rates.json"
UA = {"User-Agent": "Mozilla/5.0 china-tour-2026 rates updater", "Accept": "application/json"}

def fetch(url, headers=None):
    req = urllib.request.Request(url, headers=headers or UA)
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read()

def cbr_rates():
    root = ET.fromstring(fetch("https://www.cbr.ru/scripts/XML_daily.asp"))
    result = {}
    for item in root.findall("Valute"):
        code = item.findtext("CharCode")
        if code in {"USD", "CNY"}:
            nominal = float(item.findtext("Nominal").replace(",", "."))
            value = float(item.findtext("Value").replace(",", "."))
            result[code] = value / nominal
    if result.keys() != {"USD", "CNY"}:
        raise RuntimeError("CBR response has no USD/CNY")
    return result

def rshb_rates():
    payload = json.loads(fetch("https://www.rshb.ru/api/v1/exchangerates?regionCode=039").decode("utf-8"))
    currencies = {x["currency"]["currency"]: x for x in payload["exchangeRate"]["currencies"]}
    cny, usd = currencies["CNY"], currencies["USD"]
    return {
        "cny_sale": float(cny["saleExchangeRate"]),
        "usd_buy": float(usd["buyExchangeRate"]),
        "updated_at": payload["exchangeRate"]["lastUpdate"],
    }

def main():
    now = datetime.now(ZoneInfo("Europe/Moscow"))
    cbr, rshb = cbr_rates(), rshb_rates()
    row = {
        "date": now.date().isoformat(),
        "cbr_rub_cny": round(cbr["CNY"], 6),
        "rshb_rub_cny": round(rshb["cny_sale"], 6),
        "cbr_usd_cny": round(cbr["USD"] / cbr["CNY"], 6),
        "rshb_usd_cny": round(rshb["usd_buy"] / rshb["cny_sale"], 6),
        "rshb_updated_at": rshb["updated_at"],
    }
    data = json.loads(DATA.read_text("utf-8")) if DATA.exists() else {"rows": []}
    data["rows"] = [x for x in data.get("rows", []) if x["date"] != row["date"]]
    data["rows"].append(row)
    data["rows"].sort(key=lambda x: x["date"])
    data["updated_at"] = now.isoformat(timespec="seconds")
    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")

if __name__ == "__main__":
    main()
