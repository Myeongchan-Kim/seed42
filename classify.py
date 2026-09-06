#!/usr/bin/env python
"""단어 목록을 받아 ok 값을 계산한다. 결과만 서버로 보낸다.

서버에서 직접 돌리면 spaCy 모델 5개 + 80만 단어 판정이 2 vCPU 를 다 먹어
사이트가 죽고 SSH 까지 거부된다. 판정은 개발 기기에서 한다.

  python classify.py words.tsv.gz ok.tsv.gz
"""
from __future__ import annotations

import gzip
import sys
import time
import warnings

warnings.filterwarnings("ignore")

from number import tokens

src, dst = sys.argv[1], sys.argv[2]
rows = [l.rstrip("\n").split("\t", 1) for l in gzip.open(src, "rt") if "\t" in l]
print(f"  {len(rows):,}개 판정 시작", flush=True)

t0 = time.time()
ok = 0
with gzip.open(dst, "wt") as f:
    for i, (key, word) in enumerate(rows, 1):
        v = 1 if tokens.is_word(word) else 0
        ok += v
        f.write(f"{key}\t{v}\n")
        if i % 50_000 == 0:
            el = time.time() - t0
            print(f"  {i:,}/{len(rows):,}  {i/el:.0f}개/s  "
                  f"남은 {(len(rows)-i)/(i/el)/60:.0f}분", flush=True)
print(f"  완료 {time.time()-t0:.0f}s — 인정 {ok:,} / 제외 {len(rows)-ok:,} "
      f"({(len(rows)-ok)/len(rows):.0%})")
