.DEFAULT_GOAL := help
COMPOSE := docker compose

.PHONY: help install dev debug down logs services run admin seed migrate migration lint format typecheck test check

help: ## Liệt kê các lệnh
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-11s %s\n", $$1, $$2}'

install: ## Cài dependency và git hook
	uv sync
	uv run pre-commit install

dev: ## Chạy toàn bộ stack bằng Docker (Swagger: http://localhost:8001/docs)
	$(COMPOSE) up -d --build

debug: ## Chạy stack với API dưới debugpy (cổng 5678), rồi attach bằng VS Code
	DEBUGPY=1 $(COMPOSE) up -d --build

down: ## Dừng stack
	$(COMPOSE) down

logs: ## Xem log API
	$(COMPOSE) logs -f api

services: ## Chỉ chạy PostgreSQL, Redis, Mailpit (để chạy API hoặc test trên máy host)
	$(COMPOSE) up -d --wait postgres redis mailpit

run: ## Chạy API trên máy host, tự reload khi sửa code (cần make services, dừng container api trước)
	uv run alembic upgrade head
	uv run uvicorn app.main:app --reload --port 8001 --no-access-log

admin: ## Tạo tài khoản admin (hỏi email, họ tên, mật khẩu)
	uv run daily-report create-admin

seed: ## Tạo dữ liệu mẫu (bộ phận, user, báo cáo). Chạy lại không tạo trùng
	uv run daily-report seed

migrate: ## Chạy migration tới bản mới nhất
	uv run alembic upgrade head

migration: ## Tạo migration mới từ model: make migration m="add users table"
	uv run alembic revision --autogenerate -m "$(m)"

lint: ## Kiểm tra lint và format
	uv run ruff check .
	uv run ruff format --check .

format: ## Tự sửa lint và format
	uv run ruff check --fix .
	uv run ruff format .

typecheck: ## Kiểm tra kiểu (mypy strict)
	uv run mypy

test: ## Chạy test kèm coverage (cần make services)
	uv run pytest --cov --cov-report=term-missing

check: lint typecheck test ## Chạy toàn bộ kiểm tra như CI
