#!/bin/sh
# Khởi động API trong container dev: chạy migration rồi chạy uvicorn.
# DEBUGPY=1: chạy dưới debugpy (cổng 5678) để VS Code attach. DEBUGPY_WAIT=1: chờ attach rồi mới chạy.
set -e

alembic upgrade head

if [ "${DEBUGPY:-0}" = "1" ]; then
    # Không dùng --reload: reload tạo process con mới, breakpoint đã đặt sẽ không còn tác dụng.
    set -- python -m debugpy --listen 0.0.0.0:5678
    if [ "${DEBUGPY_WAIT:-0}" = "1" ]; then
        set -- "$@" --wait-for-client
    fi
    exec "$@" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir src --no-access-log
