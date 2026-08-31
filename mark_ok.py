#!/usr/bin/env python
"""현 토크나이저가 명사로 인정하지 않는 노드에 ok=0 을 매긴다.

지우지 않는다. 7,883 개는 돈 들여 받은 관측이고, 토크나이저가 또 바뀌면 판정도
바뀐다. 표시·경로에서만 빼고 데이터는 남긴다 - 이 스크립트를 다시 돌리면 갱신된다.

실측: 잔재를 경로에서 빼도 무작위 300쌍 중 끊긴 것은 1개, 평균 홉은 +0.22 뿐이다.
엣지의 30% 가 잔재에서 출발하지만 대체로 중복 경로였다.
"""
from __future__ import annotations

import warnings

warnings.filterwarnings("ignore")

from number import db, tokens

conn = db.connect()
rows = conn.execute("SELECT id, word FROM node").fetchall()
good = [(r["id"],) for r in rows if tokens.is_word(r["word"])]
bad = [(r["id"],) for r in rows if not tokens.is_word(r["word"])]
with db.WRITE:
    conn.execute("UPDATE node SET ok=1")
    conn.executemany("UPDATE node SET ok=0 WHERE id=?", bad)
    conn.commit()
print(f"  노드 {len(rows):,}  인정 {len(good):,}  제외 {len(bad):,} "
      f"({len(bad)/len(rows):.0%})")
