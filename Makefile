.PHONY: install lint format run once logs parser-logs build clean

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

## Запуск одной команды: make once CMD="register --username me --password 1234"
once:
	uv run valutatrade $(CMD)

## Последние строки журнала операций: make logs LOG_LINES=50
logs:
	@if [ -f logs/actions.log ]; then \
		tail -n $(or $(LOG_LINES),20) logs/actions.log; \
	else \
		echo "Журнал ещё не создан: logs/actions.log - выполните пару команд приложения"; \
	fi

## Последние строки журнала парсера: make parser-logs LOG_LINES=50
parser-logs:
	@if [ -f logs/parser.log ]; then \
		tail -n $(or $(LOG_LINES),20) logs/parser.log; \
	else \
		echo "Журнал парсера ещё не создан: logs/parser.log - выполните update-rates"; \
	fi

## Сборка пакета
build:
	uv build

## Удаление артефактов сборки и кэша
clean:
	rm -rf build dist
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
