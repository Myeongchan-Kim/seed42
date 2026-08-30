#!/usr/bin/env python
"""response 테이블의 본문으로 respond 캐시를 새 키에 맞춰 다시 채운다.
캐시 키에서 temperature 를 뺀 뒤 옛 항목이 히트하지 않는 것을 고친다."""
from number import db, llm

conn = llm.conn()
rows = conn.execute(
    "SELECT n.word AS w, r.text, r.gen_model FROM response r"
    " JOIN node n ON n.id=r.node_id").fetchall()
added = 0
for r in rows:
    key = {"model": r["gen_model"], "word": r["w"], "seed": llm.SEED}
    h = llm._key_hash(key)
    if db.cache_get(conn, "respond", h) is None:
        db.cache_put(conn, "respond", h, r["text"], model=r["gen_model"],
                     params={"seed": llm.SEED}, inp={"word": r["w"]})
        added += 1
print(f"response {len(rows)}행 중 {added}개를 새 키로 재등록")
