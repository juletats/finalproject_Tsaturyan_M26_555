"""Классы предметной области и доменные исключения платформы.

Иерархия исключений намеренно наследуется от ValueError: тексты ошибок уже
готовы к показу пользователю, поэтому CLI перехватывает их одним блоком
try...except и не дублирует сообщения.
"""

from datetime import datetime

from valutatrade_hub.core import utils


class ValutaTradeError(ValueError):
    """ Базовое доменное исключение приложения с текстом для пользователя."""


class ValidationError(ValutaTradeError):
    """ Некорректные вводимые данные (тип, формат, диапазон)."""


class DuplicateUsernameError(ValutaTradeError):
    """ Имя пользователя уже занято."""

    def __init__(self, username):
        super().__init__(f"Имя пользователя '{username}' уже занято")
        self.username = username


class UserNotFoundError(ValutaTradeError):
    """ Пользователя с таким именем нет в системе."""

    def __init__(self, username):
        super().__init__(f"Пользователь '{username}' не найден")
        self.username = username


class WrongPasswordError(ValutaTradeError):
    """ Пароль не совпадает с сохранённым хешем."""

    def __init__(self):
        super().__init__("Неверный пароль")


class NoSessionError(ValutaTradeError):
    """ Команда требует залогиненного пользователя."""

    def __init__(self):
        super().__init__("Сначала выполните login")


class WalletExistsError(ValutaTradeError):
    """ Кошелёк с таким кодом валюты уже есть в портфеле."""

    def __init__(self, currency_code):
        super().__init__(f"Кошелёк '{currency_code}' уже существует")
        self.currency_code = currency_code


class WalletNotFoundError(ValutaTradeError):
    """ В портфеле нет кошелька указанной валюты."""

    def __init__(self, currency_code):
        super().__init__(
            f"У вас нет кошелька '{currency_code}'. Добавьте валюту: "
            "она создаётся автоматически при первой покупке."
        )
        self.currency_code = currency_code


class InsufficientFundsError(ValutaTradeError):
    """ На кошельке меньше средств, чем требуется для операции."""

    def __init__(self, currency_code, available, required):
        super().__init__(
            "Недостаточно средств: доступно "
            f"{utils.format_amount(available, currency_code)} {currency_code}, "
            f"требуется {utils.format_amount(required, currency_code)}"
            f" {currency_code}"
        )
        self.currency_code = currency_code
        self.available = available
        self.required = required


class UnknownCurrencyError(ValutaTradeError):
    """ Валюту нельзя ни найти в курсах, ни использовать как базовую."""

    def __init__(self, currency_code):
        super().__init__(f"Неизвестная базовая валюта '{currency_code}'")
        self.currency_code = currency_code


class RateLookupError(ValutaTradeError):
    """ Не удалось получить курс для расчёта сделки."""

    def __init__(self, currency_from, currency_to):
        super().__init__(
            f"Не удалось получить курс для {currency_from}"
            f"→{currency_to}"
        )
        self.currency_from = currency_from
        self.currency_to = currency_to


class RateServiceError(ValutaTradeError):
    """ Курс недоступен пользователю: нет данных и нет источника обновления."""

    def __init__(self, currency_from, currency_to):
        super().__init__(
            f"Курс {currency_from}→{currency_to} недоступен. "
            "Повторите попытку позже."
        )
        self.currency_from = currency_from
        self.currency_to = currency_to


def _validate_identifier(value, name):
    """ Проверяет, что идентификатор - положительное целое число."""
    if isinstance(value, bool):
        raise ValidationError(f"{name} должно быть положительным числом")
    try:
        identifier = int(value)
    except (TypeError, ValueError):
        raise ValidationError(
            f"{name} должно быть положительным числом"
        ) from None
    if identifier <= 0:
        raise ValidationError(f"{name} должно быть положительным числом")
    return identifier


class User:
    """  Пользователь системы
         Атрибуты:
        _user_id: int - уникальный идентификатор пользователя.
        _username: str - имя пользователя.
        _hashed_password: str - пароль в зашифрованном виде.
        _salt: str - уникальная соль для пользователя.
        _registration_date: datetime - дата регистрации пользователя.

        Методы класса:
        get_user_info() - выводит информацию о пользователе (без пароля).
        change_password(new_password: str) - изменяет пароль пользователя,
        с хешированием нового пароля.
        verify_password(password: str) - проверяет введённый пароль на совпадение.
    """

    def __init__(self, _user_id, _username, _hashed_password="", _salt="",
                 _registration_date=None):
        self._user_id = _validate_identifier(_user_id, "user_id")
        self._username = utils.validate_username(_username)
        self._hashed_password = str(_hashed_password)
        self._salt = str(_salt)
        self._registration_date = _registration_date or datetime.now()

    @property
    def user_id(self):
        """ Уникальный идентификатор пользователя (только чтение)."""
        return self._user_id

    @property
    def username(self):
        """ Имя пользователя."""
        return self._username

    @username.setter
    def username(self, value):
        """ Устанавливает имя пользователя: оно не может быть пустым."""
        self._username = utils.validate_username(value)

    @property
    def registration_date(self):
        """ Дата регистрации (только чтение)."""
        return self._registration_date

    @property
    def hashed_password(self):
        """ Пароль в зашифрованном виде (только чтение)."""
        return self._hashed_password

    @property
    def salt(self):
        """ Соль, использованная при хешировании пароля (только чтение)."""
        return self._salt

    def get_user_info(self):
        """ Выводит информацию о пользователе (без пароля)."""
        return (
            f"id: {self._user_id}, имя: '{self._username}', "
            "зарегистрирован: "
            f"{utils.format_datetime(self._registration_date)}"
        )

    def change_password(self, new_password):
        """ Изменяет пароль пользователя, с хешированием нового пароля."""
        validated = utils.validate_password(new_password)
        self._salt = utils.generate_salt()
        self._hashed_password = utils.hash_password(validated, self._salt)
        return self._hashed_password

    def verify_password(self, password):
        """ Проверяет введённый пароль на совпадение."""
        if not self._hashed_password:
            return False
        return utils.hash_password(str(password), self._salt) == (
            self._hashed_password
        )

    def to_dict(self):
        """ Возвращает запись для users.json."""
        return {
            "user_id": self._user_id,
            "username": self._username,
            "hashed_password": self._hashed_password,
            "salt": self._salt,
            "registration_date": self._registration_date.isoformat(
                timespec="seconds"
            ),
        }

    @classmethod
    def create(cls, username, password, user_id):
        """ Создаёт пользователя с новой солью и хешем пароля."""
        salt = utils.generate_salt()
        return cls(
            _user_id=user_id,
            _username=username,
            _hashed_password=utils.hash_password(
                utils.validate_password(password), salt
            ),
            _salt=salt,
            _registration_date=datetime.now(),
        )

    @classmethod
    def from_dict(cls, data):
        """ Восстанавливает пользователя из записи users.json."""
        return cls(
            _user_id=data.get("user_id"),
            _username=data.get("username", ""),
            _hashed_password=data.get("hashed_password", ""),
            _salt=data.get("salt", ""),
            _registration_date=utils.parse_datetime(
                data.get("registration_date")
            ),
        )

    def __repr__(self):
        return f"User(user_id={self._user_id}, username='{self._username}')"


class Wallet:
    """ Кошелёк пользователя в одной конкретной валюте
        Атрибуты:
        currency_code: str - код валюты (например, "USD", "BTC").
        _balance: float - баланс в данной валюте (по умолчанию 0.0).
        Методы класса:
        deposit(amount: float) - пополнение баланса.
        withdraw(amount: float) - снятие средств (если баланс позволяет).
        get_balance_info() - вывод информации о текущем балансе.
    """

    def __init__(self, _currency_code, _balance=0.0):
        self._currency_code = utils.validate_currency_code(_currency_code)
        self.balance = _balance

    @property
    def balance(self):
        """ Баланс в данной валюте (по умолчанию 0.0)"""
        return self._balance

    @balance.setter
    def balance(self, value):
        """ Устанавливает баланс: только неотрицательное число."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValidationError(
                f"Баланс должен быть числом, получено: {value!r}"
            )
        if value < 0:
            raise ValidationError("Баланс не может быть отрицательным")
        self._balance = float(value)

    def deposit(self, amount):
        """ Пополнение баланса на положительную сумму. Возвращает новый баланс."""
        value = utils.validate_amount(amount)
        self.balance = self._balance + value
        return self._balance

    def withdraw(self, amount):
        """ Снятие средств (если баланс позволяет). Возвращает новый баланс. """
        value = utils.validate_amount(amount)
        if value > self._balance:
            raise InsufficientFundsError(
                self._currency_code, self._balance, value
            )
        self.balance = self._balance - value
        return self._balance

    def get_balance_info(self):
        """ Вывод информации о текущем балансе """
        return (
            f"{self._currency_code}: "
            f"{utils.format_amount(self._balance, self._currency_code)}"
        )

    def to_dict(self):
        """ Возвращает запись для файла портфеля."""
        return {
            "currency_code": self._currency_code,
            "balance": self._balance,
        }

    @classmethod
    def from_dict(cls, data, currency_code=None):
        """ Восстанавливает кошелёк из записи портфеля portfolios.json."""
        data = data if isinstance(data, dict) else {}
        code = currency_code or data.get("currency_code", "")
        return cls(_currency_code=code, _balance=data.get("balance", 0.0))

    @property
    def currency_code(self):
        """ Код валюты кошелька (только чтение)."""
        return self._currency_code

    def __repr__(self):
        return f"Wallet({self.get_balance_info()})"


class Portfolio:
    """ Управление всеми кошельками одного пользователя
        Атрибуты:
        _user_id: int - уникальный идентификатор пользователя.
        _wallets: dict[str, Wallet] - словарь кошельков, где ключ - код валюты,
        значение - объект Wallet.
        Методы класса:
        add_currency(currency_code: str) - добавляет новый кошелёк
        в портфель (если его ещё нет).
        get_total_value(base_currency='USD') - возвращает общую стоимость
        всех валют пользователя
        в указанной базовой валюте (по курсам, полученным из API или фиктивным данным).
        get_wallet(currency_code) - возвращает объект Wallet по коду валюты.
    """

    def __init__(self, _user_id, _wallets=None, user=None):
        self._user_id = _validate_identifier(_user_id, "user_id")
        self._user = user
        self._wallets = {}
        for code, balance in self._iter_wallet_items(_wallets):
            self.add_currency(code, balance)

    @staticmethod
    def _iter_wallet_items(wallets):
        """ Нормализует входные кошельки в пары (код валюты, баланс)."""
        if not wallets:
            return []
        if isinstance(wallets, dict):
            items = wallets.items()
        else:
            items = ((None, wallet) for wallet in wallets)
        result = []
        for code, wallet in items:
            if isinstance(wallet, Wallet):
                result.append((wallet.currency_code, wallet.balance))
            elif isinstance(wallet, dict):
                result.append(
                    (wallet.get("currency_code") or code,
                     wallet.get("balance", 0.0))
                )
            else:
                result.append((code, wallet))
        return result

    @classmethod
    def from_dict(cls, data, user=None):
        """ Восстанавливает портфель из записи portfolios.json."""
        data = data if isinstance(data, dict) else {}
        return cls(
            _user_id=data.get("user_id"),
            _wallets=data.get("wallets"),
            user=user,
        )

    @property
    def user_id(self):
        """ Идентификатор владельца портфеля (только чтение)."""
        return self._user_id

    @property
    def user(self):
        """ Объект пользователя, которому принадлежит портфель (только чтение)."""
        return self._user

    @property
    def wallets(self):
        """ Копия словаря кошельков: наружу состояние портфеля не отдаётся."""
        return dict(self._wallets)

    def add_currency(self, currency_code, balance=0.0):
        """ Добавляет новый кошелёк в портфель (если его ещё нет) """
        code = utils.validate_currency_code(currency_code)
        if code in self._wallets:
            raise WalletExistsError(code)
        self._wallets[code] = Wallet(_currency_code=code, _balance=balance)
        return self._wallets[code]

    def get_total_value(self, base_currency=None, rates=None):
        """ Возвращает общую стоимость всех валют пользователя в указанной
            базовой валюте (по курсам, полученным из API или фиктивным данным)
            """
        base = utils.validate_currency_code(
            base_currency or utils.BASE_CURRENCY
        )
        table = utils.rates_or_stub(rates)
        if not utils.value_in_base(table, base):
            raise UnknownCurrencyError(base)

        total = 0.0
        for wallet in self._wallets.values():
            rate = self.rate_to_base(wallet.currency_code, base, table)
            total += wallet.balance * rate
        return total

    def get_wallet(self, currency_code):
        """ Возвращает объект Wallet по коду валюты
            """
        code = utils.validate_currency_code(currency_code)
        if code not in self._wallets:
            raise WalletNotFoundError(code)
        return self._wallets[code]

    def bind_user(self, user):
        """ Привязывает объект пользователя; повторная привязка запрещена."""
        if self._user is not None:
            raise ValidationError(
                f"Портфель уже привязан к пользователю "
                f"'{self._user.username}'"
            )
        self._user = user
        return self._user

    def has_wallet(self, currency_code):
        """ True, если кошелёк такой валюты уже есть в портфеле."""
        code = utils.validate_currency_code(currency_code)
        return code in self._wallets

    def wallet_codes(self):
        """ Отсортированный список кодов валют портфеля."""
        return sorted(self._wallets)

    @staticmethod
    def rate_to_base(currency_code, base_currency, rates):
        """ Курс одной единицы валюты в базовой валюте по таблице курсов."""
        found = utils.find_rate(rates, currency_code, base_currency)
        if found is None:
            raise RateLookupError(currency_code, base_currency)
        return found[0]

    def to_dict(self):
        """ Возвращает запись для portfolios.json."""
        return {
            "user_id": self._user_id,
            "wallets": {
                code: {"balance": wallet.balance}
                for code, wallet in sorted(self._wallets.items())
            },
        }

    def __repr__(self):
        codes = ", ".join(self.wallet_codes())
        return f"Portfolio(user_id={self._user_id}, wallets=[{codes}])"
