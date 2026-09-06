#!/usr/bin/env python
"""classify.py 가 만든 ok 값을 DB 에 적용한다. 토크나이저를 쓰지 않는다.

판정은 개발 기기에서 하고 결과만 옮긴다 - 서버에서 spaCy 를 돌리면 2 vCPU 를
다 먹어 사이트가 죽는다.

  python apply_ok.py number.db ok.tsv.gz
"""
from __future__ import annotations

import gzip
import sqlite3
import sys
import time

path, tsv = sys.argv[1], sys.argv[2]
rows = []
with gzip.open(tsv, "rt") as f:
    for line in f:
        k, v = line.rstrip("\n").split("\t")
        rows.append((int(v), k))

conn = sqlite3.connect(path, timeout=600, isolation_level=None)
conn.execute("PRAGMA busy_timeout=600000")
t0 = time.time()
conn.execute("BEGIN")
conn.executemany("UPDATE node SET ok=? WHERE key=?", rows)
conn.execute("COMMIT")
conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
d = dict(conn.execute("SELECT ok, COUNT(1) FROM node GROUP BY ok"))
print(f"  {len(rows):,}행 적용 {time.time()-t0:.0f}s -> {d}")
