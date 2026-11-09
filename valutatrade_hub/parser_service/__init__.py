"""Сервис парсинга курсов: внешние API, хранилище, обновление, планировщик.

Parser Service - сервис, который ходит в CoinGecko и ExchangeRate-API.
Пишет историю замеров в data/exchange_rates.json, актуальный снимок в
data/rates.json.
Core Service (core/usecases.py) к этим API не обращается и
читает только снимок, поэтому сеть нужна лишь здесь.
"""

from valutatrade_hub.parser_service.api_clients import (
    BaseApiClient,
    CoinGeckoClient,
    ExchangeRateApiClient,
    RateSample,
)
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.scheduler import RateScheduler
from valutatrade_hub.parser_service.storage import RatesStorage
from valutatrade_hub.parser_service.updater import RatesUpdater, build_updater

__all__ = [
    "BaseApiClient",
    "CoinGeckoClient",
    "ExchangeRateApiClient",
    "ParserConfig",
    "RateSample",
    "RateScheduler",
    "RatesStorage",
    "RatesUpdater",
    "build_updater",
]
