#!/usr/bin/env python
"""프로덕션 진입점. 개발용 Flask 서버 대신 waitress 로 띄운다.

server.py 를 직접 실행하면 Flask 개발 서버가 뜨는데, 그것은 한 번에 하나의
요청만 안정적으로 처리하고 보안 경고도 낸다. waitress 는 순수 파이썬이라
빌드 도구 없이 설치되고 스레드 풀을 준다.
"""
import threading

from waitress import serve

import server

# 그래프 적재와 통계 계산을 백그라운드로 돌린다. 요청 중에 하면 그 한 번이
# 전부를 뒤집어쓴다 (대시보드 20초, 심하면 Cloudflare 524).
threading.Thread(target=server.stats_loop, daemon=True).start()

if __name__ == "__main__":
    serve(server.app, host="127.0.0.1", port=5001, threads=8,
          channel_timeout=120, ident="Seed 42")
