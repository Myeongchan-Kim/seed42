#!/usr/bin/env python
"""비영어 시드를 던지면 응답이 얼마나 영어로 끌려가는가.

한국어 시드만으로 크롤했는데 엣지의 71.8% 가 en->en 이 되었다. ko->en 이
29,619 인데 en->ko 는 27 - 1,097 대 1 의 일방통행이었다. 다른 언어도 같은지 본다.

측정: 응답의 라틴 문자 비율과, 고유명사가 아닌 영어 용어 토큰 수.
한국어·중국어·일본어는 고유 문자가 있어 신호가 깨끗하다. 스페인어는 라틴 문자를
공유하므로 이 지표로는 잴 수 없다 - 대신 영어 기능어 출현으로 문장 단위 전환만 본다.
"""
from __future__ import annotations

import re
from collections import Counter

from number import llm

CONCEPTS = ["mitochondria", "jazz", "democracy", "coffee",
            "war", "poetry", "algorithm", "glacier"]

SEEDS = {
    "ko": ["미토콘드리아", "재즈", "민주주의", "커피", "전쟁", "시", "알고리즘", "빙하"],
    "zh": ["线粒体", "爵士乐", "民主", "咖啡", "战争", "诗歌", "算法", "冰川"],
    "ja": ["ミトコンドリア", "ジャズ", "民主主義", "コーヒー", "戦争", "詩", "アルゴリズム", "氷河"],
    "es": ["mitocondria", "jazz", "democracia", "café", "guerra", "poesía",
           "algoritmo", "glaciar"],
}

SCRIPT = {
    "ko": re.compile(r"[가-힣]"),
    "zh": re.compile(r"[一-鿿]"),
    "ja": re.compile(r"[぀-ヿ一-鿿]"),
    "es": None,
}
LATIN = re.compile(r"[A-Za-z]")
LATIN_TOKEN = re.compile(r"\b[A-Za-z][A-Za-z\-]{2,}\b")

# 영어로 문장이 넘어갔는지 보는 표지 (스페인어용)
EN_MARKERS = {"the", "and", "of", "is", "are", "with", "that", "this", "for",
              "which", "these", "from", "have", "has", "was", "were"}


def measure(lang: str, word: str) -> dict:
    text = llm.respond(word)
    native = SCRIPT[lang]
    n_native = len(native.findall(text)) if native else 0
    n_latin = len(LATIN.findall(text))
    toks = [t.lower() for t in LATIN_TOKEN.findall(text)]
    return {
        "word": word,
        "chars": len(text),
        "native": n_native,
        "latin": n_latin,
        "latin_ratio": n_latin / max(n_native + n_latin, 1),
        "en_tokens": len(set(toks)),
        "en_markers": sum(1 for t in toks if t in EN_MARKERS),
        "top": Counter(t for t in toks if t not in EN_MARKERS).most_common(5),
    }


def main() -> None:
    print()
    for lang, words in SEEDS.items():
        rows = [measure(lang, w) for w in words]
        if lang == "es":
            mk = sum(r["en_markers"] for r in rows)
            print(f"  [{lang}] 라틴 문자 공유 - 비율로는 못 잼. "
                  f"영어 기능어 출현 {mk}회 (문장 단위 전환 지표)")
        else:
            ratio = sum(r["latin"] for r in rows) / max(
                sum(r["native"] + r["latin"] for r in rows), 1)
            print(f"  [{lang}] 라틴 문자 비율 {ratio:6.1%}   "
                  f"응답당 영어 토큰 {sum(r['en_tokens'] for r in rows)/len(rows):5.1f}종")
        for r in rows[:3]:
            top = ", ".join(t for t, _ in r["top"])
            print(f"      {r['word']:<12} 라틴 {r['latin_ratio']:5.1%}  {top}")
        print()


if __name__ == "__main__":
    main()
