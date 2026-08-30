#!/usr/bin/env python
"""캐시된 응답을 새 토크나이저로 다시 훑어 그래프를 채운다. API 호출 없음.

응답은 (모델, 단어, seed) 로 캐싱되므로 토크나이저를 바꿔도 다시 부를 필요가 없다.
파이프라인 버전(PROMPT_VERSION)만 다른 config 로 쌓이므로 옛 그래프는 그대로 남는다.

  python retokenize.py            -> 현재 PROMPT_VERSION 으로 채운다
  python retokenize.py --limit 500
"""
from __future__ import annotations

import argparse
import time
import warnings

warnings.filterwarnings("ignore")

from number import db, llm, tokens
from number.tokens import norm

llm.OFFLINE = True          # 실수로라도 API 를 부르지 않게


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()

    conn = db.connect()
    cfg = db.config_id(conn, llm.GEN_MODEL, 0.0, llm.PICK_MODEL, 0,
                       llm.PROMPT_VERSION, llm.SEED)
    rows = conn.execute(
        "SELECT n.word AS w, r.text FROM response r JOIN node n ON n.id=r.node_id"
        " WHERE r.gen_model=? ORDER BY r.id" + (f" LIMIT {a.limit}" if a.limit else ""),
        (llm.GEN_MODEL,)).fetchall()

    print(f"\n  응답 {len(rows):,}개를 {llm.PROMPT_VERSION} 로 다시 훑는다 "
          f"(API 호출 없음)\n")
    t0 = time.time()
    langs: dict[str, int] = {}
    edges = 0
    for i, r in enumerate(rows, 1):
        lang = tokens.detect(r["text"])
        langs[lang] = langs.get(lang, 0) + 1
        nbrs = tokens.neighbors(r["text"], exclude=r["w"], lang=lang)
        src = db.node_id(conn, norm(r["w"]), r["w"], r["w"])
        dsts = [db.node_id(conn, norm(w), w, w) for w in nbrs]
        db.record_edges(conn, cfg, src, dsts, None)
        edges += len(dsts)
        if i % 500 == 0:
            el = time.time() - t0
            print(f"  {i:,}/{len(rows):,}  엣지 {edges:,}  "
                  f"{i/el:.0f}개/s  남은 {(len(rows)-i)/(i/el)/60:.0f}분", flush=True)

    el = time.time() - t0
    print(f"\n  완료: {len(rows):,}개 {el/60:.1f}분  엣지 {edges:,}")
    print(f"  응답 언어: {dict(sorted(langs.items(), key=lambda x: -x[1]))}")
    n = conn.execute("SELECT COUNT(DISTINCT id) c FROM node WHERE id IN"
                     " (SELECT src_id FROM edge WHERE config_id=?"
                     "  UNION SELECT dst_id FROM edge WHERE config_id=?)",
                     (cfg, cfg)).fetchone()["c"]
    print(f"  v4 그래프: 노드 {n:,}  엣지 "
          f"{conn.execute('SELECT COUNT(*) c FROM edge WHERE config_id=?', (cfg,)).fetchone()['c']:,}\n")


if __name__ == "__main__":
    main()
