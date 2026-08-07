#!/usr/bin/env python3
import html
import json
import re
import socket
import ssl
import urllib.parse
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rates.json"
UA = {"User-Agent": "Mozilla/5.0 china-tour-2026 rates updater", "Accept": "*/*", "Connection": "close"}
TIMEOUT = 12
INSECURE_TLS_HOSTS = {"www.rshb.ru"}
socket.setdefaulttimeout(TIMEOUT)

def fetch(url, headers=None, allow_insecure_tls=False):
    req = urllib.request.Request(url, headers=headers or UA)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            return response.read()
    except urllib.error.URLError as error:
        reason = getattr(error, "reason", None)
        host = urllib.parse.urlparse(url).hostname
        is_cert_error = isinstance(reason, ssl.SSLCertVerificationError)
        if allow_insecure_tls and is_cert_error and host in INSECURE_TLS_HOSTS:
            context = ssl._create_unverified_context()
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=context) as response:
                return response.read()
        raise RuntimeError(f"Failed to fetch {url}: {error}") from error

def cbr_rates():
    root = ET.fromstring(fetch("https://www.cbr.ru/scripts/XML_daily.asp"))
    result = {"rate_date": datetime.strptime(root.attrib["Date"], "%d.%m.%Y").date().isoformat()}
    for item in root.findall("Valute"):
        code = item.findtext("CharCode")
        if code in {"USD", "CNY"}:
            nominal = float(item.findtext("Nominal").replace(",", "."))
            value = float(item.findtext("Value").replace(",", "."))
            result[code] = value / nominal
    if "CNY" not in result:
        raise RuntimeError("CBR response has no CNY")
    return result

def rshb_rates():
    payload = json.loads(fetch("https://www.rshb.ru/api/v1/exchangerates?regionCode=039", allow_insecure_tls=True).decode("utf-8"))
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
    urls = [
        "https://www.bankofchina.com/english/bocinfo/exr/index.html",
        "https://www.bankofchina.com/english/bocinfo/",
        "https://www.bank-of-china.com/english/bocinfo/exr/index.html",
    ]
    last_error = None
    for url in urls:
        try:
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
        except Exception as error:
            last_error = error
    raise RuntimeError(f"Bank of China USD/CNY unavailable: {last_error}")

def previous_row(data):
    rows = data.get("rows", [])
    return max(rows, key=lambda x: x.get("date", "")) if rows else {}

def source_or_previous(name, getter, previous, mapping, warnings):
    try:
        return getter()
    except Exception as error:
        missing = [target for target in mapping.values() if target not in previous]
        if missing:
            raise RuntimeError(f"{name} failed and no previous values exist for {', '.join(missing)}") from error
        warnings[name] = str(error)
        return {source: previous[target] for source, target in mapping.items()}

def main():
    now = datetime.now(ZoneInfo("Europe/Moscow"))
    data = json.loads(DATA.read_text("utf-8")) if DATA.exists() else {"rows": []}
    previous = previous_row(data)
    warnings = {}
    cbr = source_or_previous("cbr", cbr_rates, previous, {"CNY": "cbr_rub_cny", "rate_date": "date"}, warnings)
    rshb = source_or_previous("rshb", rshb_rates, previous, {"cny_sale": "rshb_rub_cny", "updated_at": "rshb_updated_at"}, warnings)
    pbc = source_or_previous("pbc", pbc_usd_cny, previous, {"rate": "pbc_cny_per_usd", "date": "pbc_rate_date"}, warnings)
    boc = source_or_previous("boc", boc_usd_cny, previous, {"rate": "boc_cash_cny_per_usd", "published_at": "boc_updated_at"}, warnings)
    row = {
        "date": cbr["rate_date"],
        "cbr_rub_cny": round(cbr["CNY"], 6),
        "rshb_rub_cny": round(float(rshb["cny_sale"]), 6),
        "pbc_cny_per_usd": round(float(pbc["rate"]), 6),
        "boc_cash_cny_per_usd": round(float(boc["rate"]), 6),
        "pbc_rate_date": pbc["date"],
        "boc_updated_at": boc["published_at"],
        "rshb_updated_at": rshb["updated_at"],
    }
    if warnings:
        row["warnings"] = warnings
    data["rows"] = [x for x in data.get("rows", []) if x["date"] != row["date"]]
    data["rows"].append(row)
    data["rows"].sort(key=lambda x: x["date"])
    data["updated_at"] = now.isoformat(timespec="seconds")
    data["sources"] = {"pbc": pbc.get("url") or data.get("sources", {}).get("pbc"), "boc": boc.get("url") or data.get("sources", {}).get("boc")}
    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")

if __name__ == "__main__":
    main()
