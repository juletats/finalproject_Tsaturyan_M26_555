"""Конфигурация приложения: Singleton SettingsLoader."""

import json
import os
import tomllib
from pathlib import Path

from valutatrade_hub.infra import Singleton

# Корень проекта: infra -> valutatrade_hub -> финальный проект
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT_FILE = PROJECT_ROOT / "pyproject.toml"
CONFIG_FILE = PROJECT_ROOT / "config.json"
# Секция с настройками приложения в pyproject.toml
TOOL_SECTION = ("tool", "valutatrade")

# Переменные окружения: дом приложения (в нём data/ и logs/) и уровень логов
ENV_HOME = "VALUTATRADE_HOME"
ENV_LOG_LEVEL = "VALUTATRADE_LOG_LEVEL"
ENV_PARSER_INTERVAL = "VALUTATRADE_PARSER_INTERVAL"
# Ключ ExchangeRate-API читается только из окружения (parser_service/config.py)
ENV_EXCHANGERATE_KEY = "EXCHANGERATE_API_KEY"

# Минимальный набор ключей: пути к JSON, TTL курсов, параметры логов и парсера
DEFAULT_SETTINGS = {
    "data_dir": os.path.join(os.getcwd(), "data"),
    "users_file": "users.json",
    "portfolios_file": "portfolios.json",
    "rates_file": "rates.json",
    "exchange_rates_file": "exchange_rates.json",
    "rates_ttl_seconds": 300,
    "base_currency": "USD",
    "min_password_length": 4,
    "log_dir": os.path.join(os.getcwd(), "logs"),
    "log_file": "actions.log",
    "parser_log_file": "parser.log",
    "log_level": "INFO",
    "log_format": "text",
    "log_max_bytes": 1000000,
    "log_backup_count": 3,
    "parser_request_timeout": 10,
    "parser_update_interval_seconds": 900,
    "parser_history_limit": 5000,
}

# Ключи, значения которых трактуются как пути: приводятся к абсолютному виду
PATH_SETTINGS = ("data_dir", "log_dir")

_MISSING = object()


def resolve_path(value):
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = Path(os.getcwd()) / path
    return str(path)


class SettingsLoader(metaclass=Singleton):

    def __init__(self):
        self._values = dict(DEFAULT_SETTINGS)
        self.reload()

    def reload(self):
        values = dict(DEFAULT_SETTINGS)
        values.update(self._read_pyproject())
        values.update(self._read_config_file())
        values.update(self._read_environment())
        for key in PATH_SETTINGS:
            if key in values:
                values[key] = resolve_path(values[key])
        self._values = values
        return dict(values)

    def get(self, key, default=_MISSING):
        if key in self._values:
            return self._values[key]
        if default is _MISSING:
            raise KeyError(f"Нет такой настройки: '{key}'")
        return default

    def as_dict(self):
        """ Копия всех значений - удобно для логов и отладки."""
        return dict(self._values)

    @staticmethod
    def _read_pyproject(path=None):
        filename = str(path or PYPROJECT_FILE)
        try:
            with open(filename, "rb") as file:
                data = tomllib.load(file)
        except (OSError, tomllib.TOMLDecodeError):
            return {}
        section = data
        for part in TOOL_SECTION:
            section = section.get(part, {}) if isinstance(section, dict) else {}
        return dict(section) if isinstance(section, dict) else {}

    @staticmethod
    def _read_config_file(path=None):
        filename = str(path or CONFIG_FILE)
        try:
            with open(filename, "r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _read_environment():
        values = {}
        home = os.environ.get(ENV_HOME)
        if home:
            root = Path(str(home)).expanduser()
            values["data_dir"] = str(root / "data")
            values["log_dir"] = str(root / "logs")
        log_level = os.environ.get(ENV_LOG_LEVEL)
        if log_level:
            values["log_level"] = log_level
        interval = os.environ.get(ENV_PARSER_INTERVAL)
        if interval:
            values["parser_update_interval_seconds"] = interval
        return values

    def __repr__(self):
        return (
            f"SettingsLoader(data_dir={self._values.get('data_dir')!r}, "
            f"rates_ttl_seconds={self._values.get('rates_ttl_seconds')!r}, "
            f"log_level={self._values.get('log_level')!r})"
        )
