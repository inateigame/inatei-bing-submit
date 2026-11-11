"""inatei.com の新着記事を Bing URL Submission API に自動送信する。

ブログの RSS から直近 LOOKBACK_HOURS 時間以内に公開された記事の URL を取り出し、
Bing Webmaster Tools の SubmitUrlBatch API でまとめて送信する。
外部ライブラリ不要(Python 標準ライブラリのみ)。

環境変数:
  BING_API_KEY    必須。Bing Webmaster Tools の「設定 > API アクセス」で発行したキー
  SITE_URL        任意。既定 https://www.inatei.com/
  FEED_URL        任意。既定 https://www.inatei.com/rss
  LOOKBACK_HOURS  任意。既定 3(1時間ごとに実行し、取りこぼしを防ぐため少し重ねる)
"""

import json
import os
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

SITE_URL = os.environ.get("SITE_URL", "https://www.inatei.com/")
FEED_URL = os.environ.get("FEED_URL", "https://www.inatei.com/rss")
LOOKBACK_HOURS = float(os.environ.get("LOOKBACK_HOURS", "3"))
API_ENDPOINT = "https://ssl.bing.com/webmaster/api.svc/json/SubmitUrlbatch?apikey={key}"
UA = "inatei-bing-submit/1.0"
ATOM = "{http://www.w3.org/2005/Atom}"


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read()


def parse_date(text: str) -> datetime | None:
    if not text:
        return None
    text = text.strip()
    try:
        return parsedate_to_datetime(text)  # RSS (RFC 822)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))  # Atom (ISO 8601)
    except ValueError:
        return None


def recent_entries(feed_xml: bytes, since: datetime) -> list[str]:
    root = ET.fromstring(feed_xml)
    entries: list[tuple[str, datetime | None]] = []

    for item in root.iter("item"):  # RSS 2.0
        link = (item.findtext("link") or "").strip()
        date = parse_date(item.findtext("pubDate") or "")
        entries.append((link, date))

    for entry in root.iter(f"{ATOM}entry"):  # Atom
        link = ""
        for l in entry.findall(f"{ATOM}link"):
            if l.get("rel", "alternate") == "alternate":
                link = l.get("href", "")
                break
        date = parse_date(entry.findtext(f"{ATOM}published") or entry.findtext(f"{ATOM}updated") or "")
        entries.append((link, date))

    urls = []
    for link, date in entries:
        if not link or date is None:
            continue
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        if date >= since and link not in urls:
            urls.append(link)
    return urls


def submit(api_key: str, urls: list[str]) -> None:
    body = json.dumps({"siteUrl": SITE_URL, "urlList": urls}).encode("utf-8")
    req = urllib.request.Request(
        API_ENDPOINT.format(key=api_key),
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": UA},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            print(f"Bing API: HTTP {res.status} {res.read().decode('utf-8', 'replace')}")
    except urllib.error.HTTPError as e:
        print(f"Bing API エラー: HTTP {e.code} {e.read().decode('utf-8', 'replace')}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    api_key = os.environ.get("BING_API_KEY", "").strip()
    if not api_key:
        print("BING_API_KEY が設定されていません", file=sys.stderr)
        sys.exit(1)

    since = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    urls = recent_entries(fetch(FEED_URL), since)

    if not urls:
        print(f"直近 {LOOKBACK_HOURS:g} 時間の新着記事はありません")
        return

    print(f"{len(urls)} 件を送信します:")
    for u in urls:
        print("  " + u)
    # API の1回あたりの上限に余裕を持たせて 100 件ずつ送る
    for i in range(0, len(urls), 100):
        submit(api_key, urls[i : i + 100])


if __name__ == "__main__":
    main()
