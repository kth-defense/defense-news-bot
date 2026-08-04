#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
국내 방산 뉴스 자동 알림 텔레그램 봇 (네이버 검색 API 버전 · 제목만)
- 네이버 뉴스 검색 API에서 키워드별 '최신순' 기사 수집  → 적시성 확보
- 제목 + 발행 시각 + 링크를 전송 (요약 없음)
- originallink(언론사 원본 URL) 기준으로 중복 제거
- pubDate(발행 시각)로 너무 오래된 기사는 걸러냄
- seen.json 파일로 중복 전송 방지

사전 준비:
  1) 네이버 개발자센터(developers.naver.com)에서 '검색' API 애플리케이션 등록
     → Client ID / Client Secret 발급
  2) 텔레그램 BotFather로 봇 토큰 발급, chat_id 확인
  3) pip install requests

GitHub Actions에서 돌릴 때는 아래 4개 값을 파일에 넣지 말고
저장소 Secrets(NAVER_CLIENT_ID / NAVER_CLIENT_SECRET / TELEGRAM_TOKEN /
TELEGRAM_CHAT_ID)로 등록하면 됨. (placeholder는 그대로 둬도 됨)
"""

import os
import re
import json
import time
import html
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

import requests

# ─────────────────────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────────────────────
NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "여기에_네이버_Client_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "여기에_네이버_Client_Secret")

TOKEN = os.environ.get("TELEGRAM_TOKEN", "여기에_봇토큰")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "여기에_chat_id")

KEYWORDS = [
    "K9 자주포",
    "K2 전차",
    "천무",
    "천궁",
    "방산 수출",
    "한화에어로스페이스",
    "현대로템",
    "KAI",
]

DISPLAY = 20            # 키워드당 네이버에서 받아올 기사 수 (최대 100)
MAX_PER_RUN = 5         # 키워드당 한 번에 보낼 최대 새 기사 수 (도배 방지)
MAX_AGE_HOURS = 48      # 이 시간보다 오래된 기사는 무시 (0 이면 시간 제한 없음)
SEEN_FILE = "seen.json"
REQUEST_TIMEOUT = 20    # 초

NAVER_NEWS_URL = "https://openapi.naver.com/v1/search/news.json"


# ─────────────────────────────────────────────────────────────
# 내부 함수
# ─────────────────────────────────────────────────────────────
def load_seen():
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, OSError):
            return set()
    return set()


def save_seen(seen):
    trimmed = list(seen)[-3000:]
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, ensure_ascii=False, indent=0)


def clean_html(raw):
    """네이버가 주는 <b> 태그와 HTML 엔티티(&quot; 등)를 제거."""
    no_tags = re.sub(r"<[^>]+>", "", raw)
    return html.unescape(no_tags).strip()


def parse_pubdate(pubdate_str):
    try:
        return parsedate_to_datetime(pubdate_str)
    except (TypeError, ValueError):
        return None


def is_recent(pubdate_str):
    if MAX_AGE_HOURS <= 0:
        return True
    dt = parse_pubdate(pubdate_str)
    if dt is None:
        return True
    now = datetime.now(timezone.utc)
    return (now - dt) <= timedelta(hours=MAX_AGE_HOURS)


def fetch_news(keyword):
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    params = {
        "query": keyword,
        "display": DISPLAY,
        "start": 1,
        "sort": "date",   # 최신순 정렬 = 적시성 핵심
    }
    try:
        resp = requests.get(
            NAVER_NEWS_URL, headers=headers, params=params, timeout=REQUEST_TIMEOUT
        )
        if resp.status_code != 200:
            print(f"[네이버 오류] '{keyword}' {resp.status_code}: {resp.text}")
            return []
        return resp.json().get("items", [])
    except requests.RequestException as e:
        print(f"[네이버 요청 오류] '{keyword}': {e}")
        return []


def article_url(item):
    return item.get("originallink") or item.get("link")


def send_telegram(text):
    api = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        resp = requests.post(
            api,
            data={
                "chat_id": CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            print(f"[전송 실패] {resp.status_code}: {resp.text}")
            return False
        return True
    except requests.RequestException as e:
        print(f"[전송 오류] {e}")
        return False


def format_message(keyword, item):
    title = html.escape(clean_html(item.get("title", "")))
    url = article_url(item)

    # 발행 시각(한국시간)
    dt = parse_pubdate(item.get("pubDate", ""))
    when = ""
    if dt:
        kst = dt.astimezone(timezone(timedelta(hours=9)))
        when = f"\n🕒 {kst.strftime('%Y-%m-%d %H:%M')}"

    return f"🛡 <b>[{html.escape(keyword)}]</b>\n{title}{when}\n{url}"


# ─────────────────────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────────────────────
def main():
    for name, val in [
        ("NAVER_CLIENT_ID", NAVER_CLIENT_ID),
        ("NAVER_CLIENT_SECRET", NAVER_CLIENT_SECRET),
        ("TELEGRAM_TOKEN", TOKEN),
        ("TELEGRAM_CHAT_ID", CHAT_ID),
    ]:
        if "여기에" in str(val):
            print(f"⚠️  {name} 를 먼저 설정하세요.")
            return

    seen = load_seen()
    first_run = len(seen) == 0
    total_sent = 0

    for keyword in KEYWORDS:
        items = fetch_news(keyword)

        fresh = [
            it for it in items
            if article_url(it) not in seen and is_recent(it.get("pubDate", ""))
        ]

        to_send = fresh[:MAX_PER_RUN]
        rest = fresh[MAX_PER_RUN:]

        for item in to_send:
            if send_telegram(format_message(keyword, item)):
                seen.add(article_url(item))
                total_sent += 1
                time.sleep(1)

        if first_run:
            for item in rest:
                seen.add(article_url(item))
        time.sleep(0.3)

    save_seen(seen)
    print(f"완료: {total_sent}건 전송.")


if __name__ == "__main__":
    main()
