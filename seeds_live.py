#!/usr/bin/env python
"""실제로 유통되는 키워드를 모아 시드로 만든다.

손으로 고른 시드는 고르는 사람의 편향이 그대로 들어간다. "AI 가 사람들을
연결하는가 단절하는가" 를 물으려면 출발점이 실제 관심사여야 한다.

구(phrase)를 그대로 노드로 쓰지 않는다. 'real madrid vs atl. madrid' 같은
검색어는 진입차수가 0 인 채로 남아 그래프를 오염시킨다. 명사만 뽑아낸다.

  python seeds_live.py            -> seeds_live.txt
  python seeds_live.py --show     -> 출처별로 보여주기만
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import ssl
import urllib.request
from collections import Counter
from datetime import date, timedelta

from number import tokens

UA = {"User-Agent": "number-experiment/0.1 (research; contact via github)"}

# urllib 은 시스템 인증서 번들을 안 쓴다 (curl 은 되는데 여기서만 CERTIFICATE_VERIFY_FAILED).
# truststore 로 OS 신뢰 저장소를 붙인다. 없으면 certifi 로 떨어진다.
try:
    import truststore
    truststore.inject_into_ssl()
    CTX = None
except ImportError:                                    # pragma: no cover
    try:
        import certifi
        CTX = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        CTX = None

NEWS = [
    "https://feeds.npr.org/1001/rss.xml",
    "https://feeds.npr.org/1004/rss.xml",          # world
    "https://feeds.npr.org/1019/rss.xml",          # science
    "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
    "https://www.theguardian.com/world/rss",
    "https://feeds.arstechnica.com/arstechnica/index",
]

# 피드 자체의 이름. 기사 제목이 아니라 매체 브랜드라 시드로 쓸 수 없다.
FEED_BRAND = {"npr", "topics", "news", "guardian", "ars", "technica", "bbc",
              "reuters", "nytimes", "times", "headlines", "latest", "rss",
              "feed", "homepage", "world", "video", "audio", "podcast"}

# 위키 시스템 문서·목록류는 주제어가 아니다
WIKI_SKIP = re.compile(r"^(Main_Page|Special:|Wikipedia:|Portal:|Help:|File:|"
                       r"Category:|Template:|List_of_|Talk:)")


def fetch(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return r.read().decode("utf-8", "replace")


def rss_titles(url: str) -> list[str]:
    try:
        body = fetch(url)
    except Exception as e:
        print(f"  [건너뜀] {url}: {str(e)[:60]}", file=sys.stderr)
        return []
    return [html.unescape(re.sub(r"<[^>]+>", "", t))
            for t in re.findall(r"<title>(.*?)</title>", body, re.S)][1:]


def google_trends(geo: str = "US") -> list[str]:
    return rss_titles(f"https://trends.google.com/trending/rss?geo={geo}")


def wiki_top(lang: str = "en", days_ago: int = 1) -> list[str]:
    d = date.today() - timedelta(days=days_ago)
    url = (f"https://wikimedia.org/api/rest_v1/metrics/pageviews/top/"
           f"{lang}.wikipedia/all-access/{d:%Y/%m/%d}")
    try:
        items = json.loads(fetch(url))["items"][0]["articles"]
    except Exception as e:
        print(f"  [건너뜀] wiki {lang}: {str(e)[:60]}", file=sys.stderr)
        return []
    out = []
    for a in items:
        t = a["article"]
        if WIKI_SKIP.match(t):
            continue
        t = re.sub(r"_\(.*?\)$", "", t).replace("_", " ").strip()   # 괄호 구분자 제거
        if t and len(t.split()) <= 3:
            out.append(t)                    # 문서 제목은 통째로 - 조각내지 않는다
    return out


def words_from(phrases: list[str]) -> list[str]:
    """구에서 명사만 뽑는다. 불용어·활용형은 tokens 가 거른다."""
    out = []
    for p in phrases:
        for m in tokens.TOKEN.finditer(p):
            w = tokens.clean(m.group(0))
            if (tokens.is_word(m.group(0)) and len(w) >= 3
                    and w.lower() not in FEED_BRAND):
                out.append(w)
    return out


def entities(phrases: list[str]) -> list[str]:
    """여러 단어로 된 고유명사는 통째로 시드가 된다.

    노드를 한 단어로 제한한 것은 조합어 폭발을 막기 위해서인데, 시드는 수백 개로
    고정이라 그 위험이 없다. 조각내면 'Dolly'/'Parton', 'United'/'States' 처럼
    아무 뜻도 없는 단어가 남는다."""
    out = []
    for p in phrases:
        p = p.strip()
        if not p or len(p) > 40:
            continue
        ws = p.split()
        if len(ws) > 3:
            continue
        if len(p) < 3 or p.isdigit():
            continue
        if not any(c.isalpha() for c in p) or len(set(p.lower())) < 3:
            continue                         # 'XXX', '1win', 'A' 같은 것
        if all(tokens.is_word(w) or w[0].isupper() for w in ws):
            out.append(p)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--out", default="seeds_live.txt")
    ap.add_argument("--limit", type=int, default=400)
    a = ap.parse_args()

    wiki = wiki_top("en")
    news_titles = [t for u in NEWS for t in rss_titles(u)]
    sources = {
        "wiki-entity": entities(wiki),          # 문서 제목 통째로
        "trends": words_from(google_trends("US")),
        "news": words_from(news_titles),
    }

    counts: Counter[str] = Counter()
    origin: dict[str, set[str]] = {}
    rank: dict[str, int] = {}
    for name, ws in sources.items():
        print(f"  {name:<14} {len(set(ws)):>4}개")
        for i, w in enumerate(ws):           # 출처 안의 순서를 유지한다
            counts[w] += 1                   # (위키는 조회수 순, 뉴스는 등장 순)
            origin.setdefault(w, set()).add(name)
            rank[w] = min(rank.get(w, 10**9), i)

    # 여러 출처에 나온 것 우선, 그 다음 출처 안 순위. 알파벳순으로 두면
    # 위키의 조회수 순서를 버리게 되어 'A', 'Aaliyah' 가 앞에 온다.
    ranked = sorted(counts, key=lambda w: (-len(origin[w]), rank[w], -counts[w]))
    ranked = ranked[: a.limit]

    if a.show:
        for name in sources:
            got = [w for w in ranked if origin[w] == {name} or
                   (len(origin[w]) > 1 and name in origin[w])][:22]
            print(f"\n  [{name}] {', '.join(got)}")
        print()
        return

    with open(a.out, "w") as f:
        f.write("\n".join(ranked) + "\n")
    multi = sum(1 for w in ranked if len(origin[w]) > 1)
    print(f"\n  {a.out}: {len(ranked)}단어 (2개 이상 출처에 등장: {multi}개)")
    print(f"  상위 20: {', '.join(ranked[:20])}")


if __name__ == "__main__":
    main()
