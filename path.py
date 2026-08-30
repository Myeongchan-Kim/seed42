#!/usr/bin/env python
"""쌓인 그래프에서 두 단어 사이 최단경로를 찾는다. LLM 호출 없음.

온라인 탐색은 예산 안에서 한 방향으로만 뻗어 실패했지만, 관측이 쌓인 뒤에는
저장된 엣지 위에서 BFS 로 바로 잰다. 이것이 MC number 의 진짜 값에 가깝다
(여전히 상한이다 - 그래프에 없는 엣지는 세지 못한다).

  python path.py "TCA cycle" "베르세르크"
  python path.py "TCA cycle" "베르세르크" --undirected --config 3
"""
from __future__ import annotations

import argparse
from collections import deque

from number import db


def load(conn, cfg: int, undirected: bool):
    adj: dict[int, list[int]] = {}
    q = "SELECT src_id, dst_id FROM edge WHERE config_id=?"
    for s, d in conn.execute(q, (cfg,)):
        adj.setdefault(s, []).append(d)
        if undirected:
            adj.setdefault(d, []).append(s)
    return adj


def bfs(adj, start: int, goal: int, cap: int = 4_000_000):
    prev = {start: None}
    q = deque([start])
    seen = 0
    while q:
        cur = q.popleft()
        if cur == goal:
            path, k = [], cur
            while k is not None:
                path.append(k)
                k = prev[k]
            return path[::-1], seen
        for nxt in adj.get(cur, ()):
            if nxt not in prev:
                prev[nxt] = cur
                q.append(nxt)
        seen += 1
        if seen > cap:
            break
    return None, seen


def ids(conn, word: str) -> list[tuple[int, str]]:
    return [(r["id"], r["word"]) for r in conn.execute(
        "SELECT id, word FROM node WHERE lower(word)=lower(?)", (word,))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("start")
    ap.add_argument("target")
    ap.add_argument("--config", type=int)
    ap.add_argument("--undirected", action="store_true")
    a = ap.parse_args()

    conn = db.connect()
    if a.config:
        cfg = a.config
    else:  # 엣지가 가장 많은 설정
        cfg = conn.execute("SELECT config_id FROM edge GROUP BY config_id"
                           " ORDER BY COUNT(*) DESC LIMIT 1").fetchone()[0]
    info = dict(conn.execute("SELECT * FROM graph_config WHERE id=?", (cfg,)).fetchone())
    n_edge = conn.execute("SELECT COUNT(*) c FROM edge WHERE config_id=?",
                          (cfg,)).fetchone()["c"]
    print(f"\n  config #{cfg}  {info['gen_model']} k={info['k']} "
          f"{info['prompt_version']} seed={info['seed']}  엣지 {n_edge:,}")
    print(f"  방향 {'무시(무방향)' if a.undirected else '유지(방향 그래프)'}\n")

    src = ids(conn, a.start)
    dst = ids(conn, a.target)
    if not src or not dst:
        print(f"  그래프에 없다: {a.start if not src else a.target}")
        return

    adj = load(conn, cfg, a.undirected)
    name = {r["id"]: r["word"] for r in conn.execute("SELECT id, word FROM node")}

    best = None
    for sid, sw in src:
        for did, dw in dst:
            p, seen = bfs(adj, sid, did)
            if p and (best is None or len(p) < len(best)):
                best = p
    if not best:
        print(f"  경로 없음  ({a.start} -> {a.target})")
        print(f"  탐색한 노드 {len(adj):,}개 중 도달 불가")
        return
    print(f"  {len(best)-1}홉")
    print("  " + "  →  ".join(name[i] for i in best))
    print()


if __name__ == "__main__":
    main()
