"""Исключения предметной области и тексты сообщений для пользователя"""

from valutatrade_hub.core import utils


class ValutaTradeError(ValueError):
    """ Базовая ошибка платформы."""


class ValidationError(ValutaTradeError):
    """ Данные не проходят проверку валидатора или модели."""


class DuplicateUsernameError(ValutaTradeError):
    def __init__(self, username):
        self.username = username
        super().__init__(f"Имя пользователя '{username}' уже занято")


class UserNotFoundError(ValutaTradeError):
    def __init__(self, username):
        self.username = username
        super().__init__(f"Пользователь '{username}' не найден")


class WrongPasswordError(ValutaTradeError):
    def __init__(self):
        super().__init__("Неверный пароль")


class NoSessionError(ValutaTradeError):
    def __init__(self):
        super().__init__("Сначала выполните login")


class WalletExistsError(ValutaTradeError):
    def __init__(self, currency_code):
        self.currency_code = currency_code
        super().__init__(f"Кошелёк '{currency_code}' уже существует")


class WalletNotFoundError(ValutaTradeError):
    def __init__(self, currency_code):
        self.currency_code = currency_code
        super().__init__(
            f"У вас нет кошелька '{currency_code}'. Добавьте валюту: она "
            "создаётся автоматически при первой покупке."
        )


class InsufficientFundsError(ValutaTradeError):
    def __init__(self, currency_code, available, required):
        self.currency_code = currency_code
        self.available = available
        self.required = required
        available_text = utils.format_amount(available, currency_code)
        required_text = utils.format_amount(required, currency_code)
        super().__init__(
            f"Недостаточно средств: доступно {available_text} {currency_code}"
            f", требуется {required_text} {currency_code}"
        )


class CurrencyNotFoundError(ValutaTradeError):
    def __init__(self, currency_code):
        self.currency_code = currency_code
        super().__init__(f"Неизвестная валюта '{currency_code}'")


class UnknownCurrencyError(ValutaTradeError):
    def __init__(self, currency_code):
        self.currency_code = currency_code
        super().__init__(f"Неизвестная базовая валюта '{currency_code}'")


class RateLookupError(ValutaTradeError):
    """ В таблице курсов нет записи для запрашиваемого"""
    def __init__(self, currency_from, currency_to):
        self.currency_from = currency_from
        self.currency_to = currency_to
        super().__init__(
            f"Не удалось получить курс для {currency_from}"
            f"→{currency_to}"
        )


class ApiRequestError(ValutaTradeError):
    """ Сбой внешнего сервиса курсов"""
    def __init__(self, reason):
        self.reason = reason
        super().__init__(f"Ошибка при обращении к внешнему API: {reason}")
