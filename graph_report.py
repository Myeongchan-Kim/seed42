#!/usr/bin/env python
"""쌓인 그래프의 현재 상태."""
from number import db, graph

conn = db.connect()
print()
for c in graph.configs(conn):
    if not c["edges"]:
        continue
    g = graph.build(conn, c["id"])
    s = graph.stats(g)
    print(f"config #{c['id']}  {c['gen_model']} T={c['temperature']} k={c['k']} "
          f"({c['prompt_version']})")
    print(f"  노드 {s['nodes']}  엣지 {s['edges']}  "
          f"던져본 단어 {s['expanded_nodes']}  이웃으로만 {s['frontier_nodes']}")
    print(f"  최대약연결성분 {s['largest_wcc']} ({s['wcc_ratio']:.0%})")
    cs = graph.core_stats(g)
    if cs.get("clustering") is not None and cs["nodes"] >= 2:
        print(f"  [확장된 노드만] {cs['nodes']}노드 {cs['edges']}엣지  "
              f"군집계수 {cs['clustering']:.3f}  상호성 {cs['reciprocity']:.3f}  "
              f"밀도 {cs['density']:.4f}  최대강연결성분 {cs['largest_scc']}")
    print(f"  평균 진입차수 {s['mean_in_degree']:.2f}  최대 {s['max_in_degree']}")
    print(f"  허브: {', '.join(r['word'] + '(' + str(r['indeg']) + ')' for r in graph.hubs(conn, c['id'], 10))}")
    print(f"  반증된 관계: {graph.introspection_accuracy(conn, c['id'])['refuted']}건")
    print()
runs = graph.mc_numbers(conn)
if runs:
    print("측정된 MC number:")
    for r in runs[:10]:
        v = f"≤ {r['hops']}" if r["found"] else "미확정"
        print(f"  MC_{r['k']}({r['start_word']}, {r['target_word']}) {v}"
              f"   [{r['mode']}/{r['policy']}, budget {r['budget']}]")
    print()
