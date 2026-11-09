"""Бизнес-логика платформы: регистрация, вход, сделки с портфелем и курсы.

Модуль - единственный владелец состояния: сессии, кеша курсов и обращений к
хранилищу (Singleton DatabaseManager). Сюда подключаются иерархия валют
(core/currencies.py), доменные исключения (core/exceptions.py) и логирование
операций декоратором @log_action (decorators.py). Печати и разбора строки ввода
здесь нет - это слой cli/interface.py.

Курсы берутся только из локального кеша rates.json: внешними API занимается
сервис парсинга (parser_service), а Core сообщает, что данные устарели"""

from valutatrade_hub import decorators
from valutatrade_hub.core import currencies, utils
from valutatrade_hub.core.exceptions import (
    DuplicateUsernameError,
    NoSessionError,
    RateLookupError,
    StaleRatesError,
    UnknownCurrencyError,
    UserNotFoundError,
    WrongPasswordError,
)
from valutatrade_hub.core.models import Portfolio, User
from valutatrade_hub.infra.database import DatabaseManager

# Сделки считаются «оценочно»: по умолчанию покупка не списывает и продажа не
# начисляет USD. Чтобы включить расчёты через USD-кошелёк, поставьте True.
SETTLE_IN_USD = False

# Кэш курсов на замыкании: пары не перечитываются с диска в пределах сессии
rate_cache = utils.create_rate_cache()

session = {"user": None}

# Хранилище и конфигурация - синглтоны инфраструктурного слоя
DATABASE = DatabaseManager()

# Декоратору нужно имя пользователя для строк лога; резолвер передаётся сюда,
# чтобы decorators не импортировал usecases (обратный импорт = цикл)
decorators.set_username_resolver(lambda: logged_in_username())


# --- Сессия ------------------------------------------------------------------

def current_user():
    """ Возвращает пользователя текущей сессии """
    user = session["user"]
    if user is None:
        raise NoSessionError()
    return user


def logged_in_username():
    """ Имя пользователя текущей сессии либо None."""
    user = session["user"]
    return user.username if user else None


def logout():
    """ Завершает текущую сессию."""
    session["user"] = None


# --- Хранилище через DatabaseManager ----------------------------------------

def load_users():
    """ Читает список пользователей из коллекции users."""
    records = DATABASE.read("users", default=[])
    if not isinstance(records, list):
        return []
    return [
        User.from_dict(record)
        for record in records
        if isinstance(record, dict)
    ]


def save_users(users):
    """ Перезаписывает коллекцию users целиком."""
    DATABASE.write("users", [user.to_dict() for user in users])


def find_user(username):
    """ Возвращает пользователя по имени (регистр не значим)."""
    for user in load_users():
        if user.username.lower() == username.lower():
            return user
    raise UserNotFoundError(username)


def load_portfolio(user_id, user=None):
    """ Читает портфель пользователя; пустого - если записи ещё нет."""
    records = DATABASE.read("portfolios", default=[])
    if isinstance(records, list):
        for record in records:
            if isinstance(record, dict) and record.get("user_id") == user_id:
                return Portfolio.from_dict(record, user=user)
    return Portfolio(_user_id=user_id, user=user)


def save_portfolio(portfolio):
    """ Сохраняет портфель безопасной операцией чтение->изменение->запись."""
    payload = portfolio.to_dict()

    def _replace_or_append(records):
        """ Ставит запись портфеля на место существующей или добавляет её."""
        items = records if isinstance(records, list) else []
        for index, record in enumerate(items):
            same_owner = (
                    isinstance(record, dict)
                    and record.get("user_id") == payload["user_id"]
            )
            if same_owner:
                items[index] = payload
                return items
        items.append(payload)
        return items

    return DATABASE.update("portfolios", _replace_or_append)


# --- Курсы -------------------------------------------------------------------

def seed_stub_rates():
    """ Наполняет пустой кеш курсов заглушкой (первый запуск без парсера).
    """
    rates = utils.build_stub_rates()
    utils.save_rates(rates)
    rate_cache.clear()
    return rates


def invalidate_rate_cache():
    """ Сбрасывает кеш курса на замыкании: после обновления парсером """
    rate_cache.clear()


def fresh_rates():
    """ Возвращает таблицу курсов из локального кеша"""
    rates = utils.load_rates()
    if not utils.pairs_of(rates):
        return seed_stub_rates()
    if not utils.is_cache_fresh(rates):
        raise StaleRatesError(
            utils.to_utc_iso(utils.cache_updated_at(rates)),
            utils.rates_ttl(),
        )
    return rates


def lookup_rate(currency_from, currency_to):
    """ Читает курс пары из кеша. Возвращает словарь
        {"rate": float, "updated_at": datetime}.
    """
    rates = fresh_rates()
    found = utils.find_rate(rates, currency_from, currency_to)
    if found is None:
        raise RateLookupError(currency_from, currency_to)
    rate, updated_at = found
    pair = utils.pair_key(currency_from, currency_to)
    if not utils.is_fresh(updated_at):
        raise StaleRatesError(updated_at, utils.rates_ttl(), pair)
    return {
        "rate": rate,
        "updated_at": utils.parse_datetime(updated_at) or utils.now_utc(),
    }


@decorators.log_action("GET_RATE")
def get_rate(currency_from, currency_to):
    """ Возвращает курс одной валюты к другой и обратный курс.
    """
    from_code = utils.validate_currency_code(currency_from)
    to_code = utils.validate_currency_code(currency_to)
    currencies.get_currency(from_code)
    currencies.get_currency(to_code)
    entry = rate_cache((from_code, to_code), lambda key: lookup_rate(*key))
    return {
        "currency_from": from_code,
        "currency_to": to_code,
        "rate": entry["rate"],
        "reverse": 1 / entry["rate"] if entry["rate"] else 0.0,
        "updated_at": entry["updated_at"],
    }


def price_to_base(currency_code, rates, base_currency):
    """ Курс одной единицы валюты в базовой валюте для расчёта сделок."""
    found = utils.find_rate(rates, currency_code, base_currency)
    if found is None:
        raise RateLookupError(currency_code, base_currency)
    return found[0]


# --- Команды пользователя ----------------------------------------------------

@decorators.log_action("REGISTER")
def register_user(username, password):
    """ Создаёт пользователя и пустой портфель.

    Возвращает словарь с итогом регистрации; вход при этом не выполняется.
    """
    name = utils.validate_username(username)
    utils.validate_password(password)

    users = load_users()
    if any(user.username.lower() == name.lower() for user in users):
        raise DuplicateUsernameError(name)

    user_id = utils.next_identifier(
        [user.to_dict() for user in users], "user_id"
    )
    user = User.create(username=name, password=password, user_id=user_id)

    def _append(records):
        """ Добавляет запись пользователя в конец коллекции."""
        items = records if isinstance(records, list) else []
        items.append(user.to_dict())
        return items

    DATABASE.update("users", _append)
    save_portfolio(Portfolio(_user_id=user_id, user=user))
    return {"user_id": user.user_id, "username": user.username}


@decorators.log_action("LOGIN")
def login_user(username, password):
    """ Проверяет пароль и фиксирует сессию пользователя."""
    name = utils.validate_username(username)
    user = find_user(name)
    if not user.verify_password("" if password is None else str(password)):
        raise WrongPasswordError()
    session["user"] = user
    return {"username": user.username, "user_id": user.user_id}


def get_portfolio_summary(base_currency=None):
    """ Возвращает кошельки пользователя и их стоимость в базовой валюте."""
    user = current_user()
    base = utils.validate_currency_code(
        base_currency or utils.BASE_CURRENCY
    )

    if currencies.find_currency(base) is None:
        raise UnknownCurrencyError(base)
    rates = fresh_rates()
    if utils.value_in_base(rates, base) is None:
        raise RateLookupError(base, utils.BASE_CURRENCY)

    portfolio = load_portfolio(user.user_id, user=user)
    rows = []
    total = 0.0
    for code in portfolio.wallet_codes():
        wallet = portfolio.get_wallet(code)
        rate = price_to_base(code, rates, base)
        value = wallet.balance * rate
        total += value
        rows.append({
            "currency_code": code,
            "balance": wallet.balance,
            "rate": rate,
            "value": value,
        })
    return {
        "username": user.username,
        "base": base,
        "rows": rows,
        "total": total,
    }


@decorators.log_action("BUY", verbose=True)
def buy_currency(currency_code, amount):
    """ Покупает валюту: создаёт кошелёк при необходимости и пополняет баланс.

    Код валюты проходит проверку формата и проверку присутствия в реестре
    валют, сумма - проверку положительности. Возвращает данные для отчёта:
    курс, изменения балансов, оценочную стоимость.
    """
    user = current_user()
    code = validate_tradable_code(currency_code)
    value = utils.validate_amount(amount)

    portfolio = load_portfolio(user.user_id, user=user)
    rates = fresh_rates()
    price = price_to_base(code, rates, utils.BASE_CURRENCY)

    if not portfolio.has_wallet(code):
        portfolio.add_currency(code)
    wallet = portfolio.get_wallet(code)
    changes = [apply(wallet, lambda: wallet.deposit(value))]

    if SETTLE_IN_USD and code != utils.BASE_CURRENCY:
        cost = value * price
        usd = settlement_wallet(portfolio)
        changes.append(apply(usd, lambda: usd.withdraw(cost)))

    save_portfolio(portfolio)
    return trade_result("buy", user.username, code, value, price, changes)


@decorators.log_action("SELL", verbose=True)
def sell_currency(currency_code, amount):
    """ Продаёт валюту: списывает баланс, при SETTLE_IN_USD начисляет USD.

    Снятие средств контролирует сам кошелёк: при нехватке денег возникает
    InsufficientFundsError, и портфель не сохраняется.
    """
    user = current_user()
    code = validate_tradable_code(currency_code)
    value = utils.validate_amount(amount)

    portfolio = load_portfolio(user.user_id, user=user)
    wallet = portfolio.get_wallet(code)
    rates = fresh_rates()
    price = price_to_base(code, rates, utils.BASE_CURRENCY)

    changes = [apply(wallet, lambda: wallet.withdraw(value))]
    if SETTLE_IN_USD and code != utils.BASE_CURRENCY:
        usd = settlement_wallet(portfolio)
        changes.append(apply(usd, lambda: usd.deposit(value * price)))

    save_portfolio(portfolio)
    return trade_result("sell", user.username, code, value, price, changes)


def validate_tradable_code(currency_code):
    """ Нормализует код валюты и проверяет, что она есть в реестре."""
    code = utils.validate_currency_code(currency_code)
    return currencies.get_currency(code).code


def trade_result(operation, username, code, value, price, changes):
    """ Собирает единый результат сделки для CLI и лога."""
    return {
        "operation": operation,
        "username": username,
        "currency_code": code,
        "amount": value,
        "rate": price,
        "base": utils.BASE_CURRENCY,
        "changes": changes,
        "estimate": value * price,
    }


def settlement_wallet(portfolio):
    """ Возвращает USD-кошелёк для расчётов, создавая его при отсутствии."""
    base = utils.BASE_CURRENCY
    if not portfolio.has_wallet(base):
        portfolio.add_currency(base)
    return portfolio.get_wallet(base)


def apply(wallet, operation):
    """ Выполняет операцию над кошельком и возвращает пару «было -> стало»."""
    was = wallet.balance
    operation()
    return {
        "currency_code": wallet.currency_code,
        "was": was,
        "became": wallet.balance,
    }
