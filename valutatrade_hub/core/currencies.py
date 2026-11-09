"""Реестр валют: абстрактный Currency и его наследники Fiat/Crypto """

from abc import ABC, abstractmethod
from dataclasses import dataclass

from valutatrade_hub.core import utils
from valutatrade_hub.core.exceptions import (
    CurrencyNotFoundError,
    ValidationError,
)

NAME_EMPTY_ERROR = "Название валюты не может быть пустым"


@dataclass
class Currency(ABC):
    """ Базовый класс валюты: атрибуты и требования, без реализации."""

    name: str
    code: str

    def __post_init__(self):
        """ Проверяет инварианты: корректный код и непустое имя."""
        self.code = validate_currency_name_code(self.code)
        self.name = validate_currency_name(self.name)

    @abstractmethod
    def get_display_info(self):
        """ Строковое представление валюты для UI и логов."""

    @property
    def kind(self):
        """ Метка типа: FIAT или CRYPTO - по имени класса."""
        return self.__class__.__name__.removesuffix("Currency").upper()

    def __str__(self):
        return self.get_display_info()


def validate_currency_name_code(code):
    """ Проверка и нормализация кода валюты через валидатор utils."""
    try:
        return utils.validate_currency_code(code)
    except ValueError as error:
        raise ValidationError(str(error)) from None


def validate_currency_name(name):
    """ Проверка читаемого имени валюты: не пустая строка."""
    cleaned = str(name).strip() if name is not None else ""
    if not cleaned:
        raise ValidationError(NAME_EMPTY_ERROR)
    return cleaned


def validate_required(value, message):
    """ Общая проверка непустой строки для доп. атрибутов наследников."""
    cleaned = str(value).strip() if value is not None else ""
    if not cleaned:
        raise ValidationError(message)
    return cleaned


@dataclass
class FiatCurrency(Currency):
    issuing_country: str = ""

    def __post_init__(self):
        super().__post_init__()
        self.issuing_country = validate_required(
            self.issuing_country, "Не указана страна или зона эмиссии"
        )

    def get_display_info(self):
        """ Пример: [FIAT] USD - US Dollar (Issuing: United States)."""
        return (
            f"[{self.kind}] {self.code} - {self.name} "
            f"(Issuing: {self.issuing_country})"
        )


@dataclass
class CryptoCurrency(Currency):
    algorithm: str = ""
    market_cap: float = 0.0

    def __post_init__(self):
        super().__post_init__()
        self.algorithm = validate_required(
            self.algorithm, "Не указан алгоритм криптовалюты"
        )
        self.market_cap = self.validate_market_cap(self.market_cap)

    @staticmethod
    def validate_market_cap(market_cap):
        try:
            value = float(market_cap)
        except (TypeError, ValueError):
            raise ValidationError(
                "Капитализация должна быть числом"
            ) from None
        if value < 0:
            raise ValidationError("Капитализация не может быть отрицательной")
        return value

    @staticmethod
    def format_market_cap(market_cap):
        mantissa, exponent = f"{market_cap:.2e}".split("e")
        return f"{mantissa}e{int(exponent)}"

    def get_display_info(self):
        """ Пример: [CRYPTO] BTC - Bitcoin (Algo: SHA-256, MCAP: 1.12e12)."""
        cap = self.format_market_cap(self.market_cap)
        return (
            f"[{self.kind}] {self.code} - {self.name} "
            f"(Algo: {self.algorithm}, MCAP: {cap})"
        )


FIAT_CURRENCIES = (
    FiatCurrency(
        name="US Dollar", code="USD", issuing_country="United States"
    ),
    FiatCurrency(name="Euro", code="EUR", issuing_country="Eurozone"),
    FiatCurrency(name="Pound Sterling", code="GBP",
                 issuing_country="United Kingdom"),
    FiatCurrency(name="Russian Ruble", code="RUB", issuing_country="Russia"),
    FiatCurrency(name="Turkish Lira", code="TRY", issuing_country="Turkey"),
)

CRYPTO_CURRENCIES = (
    CryptoCurrency(
        name="Bitcoin", code="BTC", algorithm="SHA-256", market_cap=1.12e12
    ),
    CryptoCurrency(
        name="Ethereum", code="ETH", algorithm="Ethash", market_cap=2.14e11
    ),
    CryptoCurrency(name="Solana", code="SOL",
                   algorithm="Proof of Stake", market_cap=6.60e10),
)

CURRENCY_REGISTRY = {
    currency.code: currency
    for currency in (*FIAT_CURRENCIES, *CRYPTO_CURRENCIES)
}


def find_currency(code):
    """ Возвращает объект валюты по коду либо None, если кода нет в реестре."""
    try:
        normalized = utils.validate_currency_code(code)
    except ValueError:
        return None
    return CURRENCY_REGISTRY.get(normalized)


def get_currency(code):
    """ Фабрика валюты по коду: CurrencyNotFoundError для неизвестных кодов."""
    currency = find_currency(code)
    if currency is None:
        raise CurrencyNotFoundError(normalize_for_message(code))
    return currency


def supported_codes():
    return sorted(CURRENCY_REGISTRY)


def normalize_for_message(code):
    cleaned = str(code).strip() if code is not None else ""
    return cleaned.upper()
