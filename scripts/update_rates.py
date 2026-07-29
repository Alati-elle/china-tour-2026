#!/usr/bin/env python3
import html
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rates.json"
UA = {"User-Agent": "Mozilla/5.0 china-tour-2026 rates updater", "Accept": "*/*"}

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

def pbc_usd_cny():
    listing = fetch("https://www.pbc.gov.cn/zhengcehuobisi/125207/125217/125925/17105-1.html").decode("utf-8", "replace")
    match = re.search(r'href="([^"]+/index\.html)"[^>]+title="(\d{4})年(\d{1,2})月(\d{1,2})日中国外汇交易中心受权公布人民币汇率中间价公告', listing)
    if not match:
        raise RuntimeError("PBC latest parity publication not found")
    url = urllib.parse.urljoin("https://www.pbc.gov.cn", match.group(1))
    page = fetch(url).decode("utf-8", "replace")
    rate = re.search(r"1美元对人民币([0-9.]+)元", page)
    if not rate:
        raise RuntimeError("PBC USD/CNY parity not found")
    return {"rate": float(rate.group(1)), "date": f"{match.group(2)}-{int(match.group(3)):02d}-{int(match.group(4)):02d}", "url": url}

def boc_usd_cny():
    url = "https://www.bank-of-china.com/english/bocinfo/exr/index.html"
    page = fetch(url).decode("utf-8", "replace")
    row = re.search(r"<tr[^>]*>\s*<td>\s*USD\s*</td>([\s\S]*?)</tr>", page, re.I)
    if not row:
        raise RuntimeError("Bank of China USD row not found")
    cells = [html.unescape(re.sub(r"<[^>]+>", "", x)).strip() for x in re.findall(r"<td[^>]*>([\s\S]*?)</td>", row.group(1), re.I)]
    if len(cells) < 6:
        raise RuntimeError("Bank of China USD row is incomplete")
    # BOC quotes CNY per 100 units of foreign currency. Cash Buying Rate is
    # what the bank pays when a customer sells physical USD for CNY.
    return {"rate": float(cells[1]) / 100, "published_at": cells[5], "url": url}

def main():
    now = datetime.now(ZoneInfo("Europe/Moscow"))
    cbr, rshb = cbr_rates(), rshb_rates()
    pbc, boc = pbc_usd_cny(), boc_usd_cny()
    row = {
        "date": now.date().isoformat(),
        "cbr_rub_cny": round(cbr["CNY"], 6),
        "rshb_rub_cny": round(rshb["cny_sale"], 6),
        "pbc_cny_per_usd": round(pbc["rate"], 6),
        "boc_cash_cny_per_usd": round(boc["rate"], 6),
        "pbc_rate_date": pbc["date"],
        "boc_updated_at": boc["published_at"],
        "rshb_updated_at": rshb["updated_at"],
    }
    data = json.loads(DATA.read_text("utf-8")) if DATA.exists() else {"rows": []}
    data["rows"] = [x for x in data.get("rows", []) if x["date"] != row["date"]]
    data["rows"].append(row)
    data["rows"].sort(key=lambda x: x["date"])
    data["updated_at"] = now.isoformat(timespec="seconds")
    data["sources"] = {"pbc": pbc["url"], "boc": boc["url"]}
    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")

if __name__ == "__main__":
    main()
