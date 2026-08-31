#!/usr/bin/env python
"""프로덕션 진입점. 개발용 Flask 서버 대신 waitress 로 띄운다.

server.py 를 직접 실행하면 Flask 개발 서버가 뜨는데, 그것은 한 번에 하나의
요청만 안정적으로 처리하고 보안 경고도 낸다. waitress 는 순수 파이썬이라
빌드 도구 없이 설치되고 스레드 풀을 준다.
"""
import threading

from waitress import serve

import server

# 첫 요청이 몇 초 걸리는 것을 없앤다. 백그라운드로 그래프를 미리 올린다.
threading.Thread(target=server.graph_adj, daemon=True).start()

if __name__ == "__main__":
    serve(server.app, host="127.0.0.1", port=5001, threads=8,
          channel_timeout=120, ident="Seed 42")
