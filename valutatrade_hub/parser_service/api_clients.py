"""Клиенты внешних API курсов: единый интерфейс поверх разных форматов ответов.

Клиент ничего не пишет на диск: он превращает ответ сервиса в список замеров
RateSample - пара, курс, время наблюдения, источник и метаданные запроса.
Сетевые сбои, ошибки статуса и неверный JSON превращаются здесь же в
ApiRequestError с понятным текстом (ТЗ 3.2), а детали вроде etag и длительности
запроса в meta для истории.
"""

import abc
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

from valutatrade_hub.core import utils
from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.infra.settings import ENV_EXCHANGERATE_KEY
from valutatrade_hub.parser_service import config as parser_config

# Формат времени ответа ExchangeRate-API: "Fri, 10 Oct 2025 12:00:00 +0000"
PROVIDER_TIME_FORMAT = "%a, %d %b %Y %H:%M:%S %z"
# Разделы ответа с курсами от базы: фактический (v6) и документированный в ТЗ
RATES_SECTIONS = ("conversion_rates", "rates")


@dataclass
class RateSample:
    """ Один замер курса: значение, время наблюдения и метаданные запроса."""

    pair: str
    rate: float
    timestamp: str
    source: str
    meta: dict = field(default_factory=dict)
    fetched_at: str = ""

    def __post_init__(self):
        """ Ключ пары и курс проходят проверку: данные с сети не доверяем."""
        self.pair = utils.pair_key(*self.codes)
        try:
            self.rate = float(self.rate)
        except (TypeError, ValueError):
            raise ApiRequestError(
                f"{self.source}: некорректный курс для {self.pair}"
            ) from None
        if self.rate <= 0:
            raise ApiRequestError(
                f"{self.source}: некорректный курс для {self.pair}"
            )
        self.timestamp = self.timestamp or utils.utc_timestamp()
        self.fetched_at = self.fetched_at or self.timestamp

    @property
    def codes(self):
        """ Пара (FROM, TO): коды проходят общую валидацию формата."""
        currency_from, _, currency_to = str(self.pair).partition("_")
        return (
            utils.validate_currency_code(currency_from),
            utils.validate_currency_code(currency_to),
        )


class BaseApiClient(abc.ABC):
    """ Единый интерфейс источника курсов."""

    source = ""

    def __init__(self, settings=None, session=None):
        self._settings = settings or parser_config.ParserConfig.from_settings()
        self._session = session

    @abc.abstractmethod
    def fetch_samples(self):
        """ Список RateSample, приведённый из ответа источника."""

    def fetch_rates(self):
        """ Стандартизированный словарь пар: {"BTC_USD": 59337.21}."""
        return {sample.pair: sample.rate for sample in self.fetch_samples()}

    @property
    def available(self):
        """ Можно ли опросить источник сейчас (фиату нужен ключ API)."""
        return True

    def request_json(self, url, params=None):
        """ GET-запрос с разбором JSON; возвращает (ответ, метаданные).
        """
        if self._session is None:
            self._session = requests.Session()
        started = time.monotonic()
        try:
            response = self._session.get(
                url, params=params, timeout=self._settings.request_timeout
            )
        except requests.exceptions.RequestException as error:
            raise ApiRequestError(
                f"{self.source}: сетевая ошибка - {error}"
            ) from error
        elapsed_ms = int((time.monotonic() - started) * 1000)
        self.check_status(response)
        try:
            payload = response.json()
        except ValueError as error:
            raise ApiRequestError(
                f"{self.source}: ответ не является JSON"
            ) from error
        if not isinstance(payload, dict):
            raise ApiRequestError(
                f"{self.source}: неожиданный формат ответа"
            )
        meta = {
            "request_ms": elapsed_ms,
            "status_code": int(response.status_code),
            "etag": response.headers.get("ETag"),
        }
        return payload, meta

    def check_status(self, response):
        status = int(response.status_code)
        if 200 <= status < 300:
            return
        if status == 429:
            raise ApiRequestError(
                f"{self.source}: превышен лимит запросов (429) - "
                "повторите позже или уменьшите частоту обновления"
            )
        if status in (401, 403):
            raise ApiRequestError(
                f"{self.source}: недоступен ключ API ({status}) - "
                f"проверьте переменную {ENV_EXCHANGERATE_KEY}"
            )
        if status == 404:
            raise ApiRequestError(
                f"{self.source}: эндпоинт не найден (404)"
            )
        raise ApiRequestError(
            f"{self.source}: сервер ответил кодом {status}"
        )

    def numbers(self, value):
        """ Положительное число из ответа API либо None (bool не считается)."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if float(value) <= 0:
            return None
        return float(value)

    def __repr__(self):
        return f"{type(self).__name__}(source={self.source!r})"


class CoinGeckoClient(BaseApiClient):
    source = parser_config.SOURCE_COINGECKO

    def fetch_samples(self):
        pairs = self._settings.crypto_ids()
        if not pairs:
            raise ApiRequestError(f"{self.source}: не заданы ID криптовалют")
        base = self._settings.base_currency
        quote = base.lower()
        payload, meta = self.request_json(
            self._settings.coingecko_url,
            params={
                "ids": ",".join(raw_id for _, raw_id in pairs),
                "vs_currencies": quote,
            },
        )
        timestamp = utils.utc_timestamp()
        samples = []
        for code, raw_id in pairs:
            entry = payload.get(raw_id)
            rate = (
                self.numbers(entry.get(quote))
                if isinstance(entry, dict) else None
            )
            if rate is None:
                continue
            samples.append(RateSample(
                pair=utils.pair_key(code, base),
                rate=rate,
                timestamp=timestamp,
                source=self.source,
                meta=dict(meta, raw_id=raw_id),
            ))
        if not samples:
            raise ApiRequestError(
                f"{self.source}: нет данных ни по одной криптовалюте"
            )
        return samples


class ExchangeRateApiClient(BaseApiClient):
    """ Фиатные валюты: курсы от базовой валюты (1 USD = N EUR)."""
    source = parser_config.SOURCE_EXCHANGERATE

    @property
    def available(self):
        return self._settings.has_api_key()

    def fetch_samples(self):
        if not self.available:
            raise ApiRequestError(
                f"{self.source}: не задана переменная {ENV_EXCHANGERATE_KEY}"
            )
        base = self._settings.base_currency
        url = (
            f"{self._settings.exchangerate_url}/"
            f"{self._settings.api_key}/latest/{base}"
        )
        payload, meta = self.request_json(url)
        self.check_result(payload)
        rates = self.rates_mapping(payload)
        timestamp = self.provider_timestamp(payload)
        observed = utils.utc_timestamp()
        samples = []
        for code in self._settings.fiat_currencies:
            provider_rate = self.numbers(rates.get(code))
            if provider_rate is None:
                continue
            # Провайдер считает от базы: 1 USD = provider_rate EUR, а в кеше
            # EUR_USD означает «сколько USD стоит 1 EUR», поэтому значение
            # переворачивается; сырой курс остаётся в meta истории
            samples.append(RateSample(
                pair=utils.pair_key(code, base),
                rate=1 / provider_rate,
                timestamp=timestamp,
                source=self.source,
                fetched_at=observed,
                meta=dict(
                    meta,
                    provider_pair=utils.pair_key(base, code),
                    provider_rate=provider_rate,
                ),
            ))
        if not samples:
            raise ApiRequestError(
                f"{self.source}: нет данных ни по одной фиатной валюте"
            )
        return samples

    def rates_mapping(self, payload):
        """ Словарь «код валюты -> курс от базы» из ответа провайдера.

        API v6 отдаёт раздел conversion_rates; в ТЗ приведён пример с разделом
        rates, поэтому поддерживаются оба, а отсутствие обоих - это явная
        ошибка с перечислением увиденного, а не молчаливый пустой список.
        """
        for key in RATES_SECTIONS:
            mapping = payload.get(key)
            if isinstance(mapping, dict) and mapping:
                return mapping
        raise ApiRequestError(
            f"{self.source}: в ответе нет курсов (ожидаемые разделы: "
            f"{', '.join(RATES_SECTIONS)})"
        )

    def check_result(self, payload):
        """ Поля result и base_code: неверный ключ и смену базы видно сразу."""
        result = str(payload.get("result", "")).strip().lower()
        if result and result != "success":
            raise ApiRequestError(
                f"{self.source}: ответ со статусом '{result}' "
                f"(ключ {self._settings.masked_key()})"
            )
        provider_base = payload.get("base_code")
        if provider_base and provider_base != self._settings.base_currency:
            raise ApiRequestError(
                f"{self.source}: базовая валюта ответа '{provider_base}' "
                f"не совпадает с {self._settings.base_currency}"
            )

    def provider_timestamp(self, payload):
        """ Время последнего обновления провайдера в ISO UTC с суффиксом Z."""
        moment = payload.get("time_last_update_utc")
        try:
            parsed = datetime.strptime(str(moment), PROVIDER_TIME_FORMAT)
        except ValueError:
            return self.provider_unix_timestamp(payload)
        return parsed.astimezone(timezone.utc).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z")

    @staticmethod
    def provider_unix_timestamp(payload):
        """ Запасной вариант времени: time_last_update_unix (epoch секунд)."""
        seconds = payload.get("time_last_update_unix")
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
            return utils.utc_timestamp()
        if seconds <= 0:
            return utils.utc_timestamp()
        moment = datetime.fromtimestamp(int(seconds), timezone.utc)
        return moment.isoformat(timespec="seconds").replace("+00:00", "Z")
