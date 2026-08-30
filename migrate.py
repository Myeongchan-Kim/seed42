#!/usr/bin/env python
"""파일 캐시(cache/)를 DB(number.db)로 옮긴다. 여러 번 돌려도 안전하다."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from number import db

ROOT = Path(__file__).parent
CACHE = ROOT / "cache"

# 캐시 키에서 모델·temperature·나머지 파라미터를 갈라낸다
def split(key: dict) -> tuple[str | None, float | None, dict, dict]:
    k = dict(key)
    model = k.pop("model", None) or k.pop("m", None)
    temp = k.pop("temperature", None)
    params = {x: k.pop(x) for x in ("k", "v") if x in k}
    return model, temp, params, k


def main() -> None:
    conn = db.connect()
    counts: dict[str, int] = {}

    for d in sorted(CACHE.iterdir()):
        if not d.is_dir():
            continue
        kind = d.name
        for f in d.iterdir():
            if f.suffix != ".json":
                continue
            rec = json.loads(f.read_text())
            key, value = rec.get("key", {}), rec.get("value")

            if kind == "embed":
                vec = np.array(value, dtype=np.float32)
                db.embed_put(conn, key.get("m", "?"), key.get("w", ""),
                             vec.tobytes(), len(vec))
            else:
                model, temp, params, rest = split(key)
                db.cache_put(conn, kind, f.stem, value, model=model,
                             temperature=temp, params=params, inp=rest)
            counts[kind] = counts.get(kind, 0) + 1
        conn.commit()

    for kind, n in sorted(counts.items()):
        print(f"  {kind}: {n}")
    total = conn.execute("SELECT COUNT(*) c FROM llm_call").fetchone()["c"]
    emb = conn.execute("SELECT COUNT(*) c FROM embedding").fetchone()["c"]
    print(f"\nllm_call {total}행, embedding {emb}행")


if __name__ == "__main__":
    main()
