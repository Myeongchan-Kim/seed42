#!/usr/bin/env python
"""LLM 은 자기 연상 구조를 아는가?

'어떤 단어를 던지면 X 가 나오나?' 라고 물어 얻은 선행어를 실제로 던져,
정말 X 가 나오는지 센다. 맞힌 비율이 곧 자기 연상에 대한 내성 정확도다.

이 값이 낮으면 LLM 에게 길을 물어 검색 전략을 짜게 하는 설계가 듣지 않는다.
"""
from __future__ import annotations

import sys
import warnings

warnings.filterwarnings("ignore")

from number import llm, tokens

WORDS = sys.argv[1:] or ["베르세르크", "재즈", "미토콘드리아", "숙신산", "커피"]


def main() -> None:
    tot_hit = tot = 0
    print("\n  선행어 제안 -> 실제 응답으로 검증\n")
    for w in WORDS:
        hits = []
        for p in llm.predecessors(w, 8):
            nb = {x.lower() for x in tokens.neighbors(llm.respond(p))}
            hits.append((p, w.lower() in nb))
        n = sum(ok for _, ok in hits)
        tot_hit += n
        tot += len(hits)
        print(f"  {w}  ->  {n}/{len(hits)} 성립")
        for p, ok in hits:
            print(f"      {'O' if ok else 'X'}  {p} → {w}")
        print()
    if tot:
        print(f"  전체 내성 정확도: {tot_hit}/{tot} = {tot_hit/tot:.0%}\n")


if __name__ == "__main__":
    main()
