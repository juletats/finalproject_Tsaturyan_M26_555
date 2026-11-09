"""Конфигурация сервиса парсинга: эндпоинты, списки валют, пути и ключ API.

Ключ ExchangeRate-API читается только из переменной окружения
EXCHANGERATE_API_KEY, это позволяет спокойно коммитить.
Числа и пути берутся из Singleton SettingsLoader, чтобы у парсера и Core были
один каталог данных, один TTL курсов и одна база расчётов.
"""

import os
from dataclasses import dataclass, field

from valutatrade_hub.core import utils
from valutatrade_hub.infra.settings import ENV_EXCHANGERATE_KEY, SettingsLoader

COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"
EXCHANGERATE_API_URL = "https://v6.exchangerate-api.com/v6"

SOURCE_COINGECKO = "CoinGecko"
SOURCE_EXCHANGERATE = "ExchangeRate-API"
SOURCE_ALIASES = {
    "coingecko": SOURCE_COINGECKO,
    "exchangerate": SOURCE_EXCHANGERATE,
}

BASE_FIAT_CURRENCY = "USD"
FIAT_CURRENCIES = ("EUR", "GBP", "RUB", "TRY")
CRYPTO_CURRENCIES = ("BTC", "ETH", "SOL")
CRYPTO_ID_MAP = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana"}

DEFAULT_REQUEST_TIMEOUT = 10
DEFAULT_UPDATE_INTERVAL = 15 * 60
DEFAULT_HISTORY_LIMIT = 5000


def read_api_key():
    """ Ключ ExchangeRate-API из окружения; пустая строка, если не задан."""
    return str(os.environ.get(ENV_EXCHANGERATE_KEY, "")).strip()


def _as_int(value, default):
    """ Целое из значения конфигурации: строки из TOML и ENV тоже годятся."""
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError, AttributeError):
        return int(default)


@dataclass
class ParserConfig:
    """Изменяемые параметры парсера в одном структурированном месте."""

    api_key: str = ""
    base_currency: str = BASE_FIAT_CURRENCY
    coingecko_url: str = COINGECKO_URL
    exchangerate_url: str = EXCHANGERATE_API_URL
    fiat_currencies: tuple = FIAT_CURRENCIES
    crypto_currencies: tuple = CRYPTO_CURRENCIES
    crypto_id_map: dict = field(default_factory=lambda: dict(CRYPTO_ID_MAP))
    request_timeout: int = DEFAULT_REQUEST_TIMEOUT
    update_interval_seconds: int = DEFAULT_UPDATE_INTERVAL
    history_limit: int = DEFAULT_HISTORY_LIMIT
    rates_path: str = ""
    history_path: str = ""

    def __post_init__(self):
        """ Коды валют проходят общую валидацию формата (2-5 знака, верхний
        регистр), пути достраиваются из конфигурации хранилища."""
        self.base_currency = utils.validate_currency_code(self.base_currency)
        self.fiat_currencies = tuple(
            utils.validate_currency_code(code)
            for code in self.fiat_currencies
        )
        self.crypto_currencies = tuple(
            utils.validate_currency_code(code)
            for code in self.crypto_currencies
        )
        self.crypto_id_map = {
            utils.validate_currency_code(code): str(raw_id)
            for code, raw_id in dict(self.crypto_id_map).items()
        }
        self.request_timeout = _as_int(
            self.request_timeout, DEFAULT_REQUEST_TIMEOUT
        )
        self.update_interval_seconds = _as_int(
            self.update_interval_seconds, DEFAULT_UPDATE_INTERVAL
        )
        self.history_limit = _as_int(self.history_limit, DEFAULT_HISTORY_LIMIT)
        if not self.rates_path:
            self.rates_path = utils.storage_path("rates")
        if not self.history_path:
            self.history_path = utils.storage_path("exchange_rates")

    @classmethod
    def from_settings(cls, settings=None):
        """ Собирает конфигурацию из SettingsLoader и переменной окружения."""
        values = settings or SettingsLoader()
        return cls(
            api_key=read_api_key(),
            base_currency=values.get(
                "base_currency", BASE_FIAT_CURRENCY
            ),
            request_timeout=_as_int(
                values.get("parser_request_timeout"), DEFAULT_REQUEST_TIMEOUT
            ),
            update_interval_seconds=_as_int(
                values.get("parser_update_interval_seconds"),
                DEFAULT_UPDATE_INTERVAL,
            ),
            history_limit=_as_int(
                values.get("parser_history_limit"), DEFAULT_HISTORY_LIMIT
            ),
        )

    def has_api_key(self):
        """ Задан ли ключ ExchangeRate-API (без него фиатный источник молчит)."""
        return bool(self.api_key)

    def masked_key(self):
        """ Ключ для логов и сообщений: первые 4 и последние 4 символа."""
        if not self.has_api_key():
            return "не задан"
        key = self.api_key
        if len(key) <= 8:
            return key[:2] + "*" * max(len(key) - 2, 1)
        return f"{key[:4]}****{key[-4:]}"

    def crypto_ids(self):
        """ Пара (код, ID CoinGecko) только по криптовалют из конфигурации."""
        return [
            (code, self.crypto_id_map[code])
            for code in self.crypto_currencies
            if code in self.crypto_id_map
        ]

    def tracked_codes(self):
        """ Все коды, которые парсер держит в кеше."""
        return (*self.fiat_currencies, *self.crypto_currencies)

    def source_name(self, alias):
        """ Приводит --source к имени источника; подсказка при ошибке."""
        name = str(alias or "").strip().lower()
        if name not in SOURCE_ALIASES:
            allowed = ", ".join(sorted(SOURCE_ALIASES))
            raise ValueError(
                f"Неизвестный источник '{alias}'. Доступные: {allowed}"
            )
        return SOURCE_ALIASES[name]

    def __repr__(self):
        return (
            f"ParserConfig(base={self.base_currency!r}, "
            f"fiat={self.fiat_currencies!r}, "
            f"crypto={self.crypto_currencies!r}, "
            f"timeout={self.request_timeout!r}, "
            f"interval={self.update_interval_seconds!r}, "
            f"api_key={self.masked_key()!r})"
        )
