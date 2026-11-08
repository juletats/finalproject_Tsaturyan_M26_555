.PHONY: install lint format run once build clean

## Установка зависимостей и создание окружения
install:
	uv sync

## Проверка стиля кода (ruff)
lint:
	uv run ruff check .

## Проверка стиля с автоисправлением
format:
	uv run ruff check . --fix

## Запуск интерактивного режима (REPL)
run:
	uv run valutatrade

## Запуск одной команды: make once CMD="register --username alice --password 1234"
once:
	uv run valutatrade $(CMD)

## Сборка пакета
build:
	uv build

## Удаление артефактов сборки и кэша
clean:
	rm -rf build dist
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
