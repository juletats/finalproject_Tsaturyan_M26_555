"""Бизнес-логика платформы: регистрация, вход, сделки с портфелем и курсы.
"""

from datetime import datetime

from valutatrade_hub.core import utils
from valutatrade_hub.core.models import (
    DuplicateUsernameError,
    NoSessionError,
    Portfolio,
    RateLookupError,
    RateServiceError,
    UnknownCurrencyError,
    User,
    UserNotFoundError,
    WrongPasswordError,
)

# Сделки считаются «оценочно»: по умолчанию покупка не списывает и продажа не
# начисляет USD. Чтобы включить расчёты через USD-кошелёк, поставьте True.
SETTLE_IN_USD = False

# Кэш курсов на замыкании: пары не перечитываются с диска в пределах сессии
rate_cache = utils.create_rate_cache()

session = {"user": None}


def current_user():
    """ Возвращает пользователя текущей сессии """
    user = session["user"]
    if user is None:
        raise NoSessionError()
    return user


def logged_in_username():
    user = session["user"]
    return user.username if user else None


def logout():
    """ Завершает текущую сессию."""
    session["user"] = None


def load_users():
    """ Читает список пользователей из users.json."""
    records = utils.load_json(utils.USERS_FILE, default=[])
    if not isinstance(records, list):
        return []
    return [
        User.from_dict(record)
        for record in records
        if isinstance(record, dict)
    ]


def save_users(users):
    utils.save_json(utils.USERS_FILE, [user.to_dict() for user in users])


def find_user(username):
    for user in load_users():
        if user.username.lower() == username.lower():
            return user
    raise UserNotFoundError(username)


def load_portfolio(user_id, user=None):
    records = utils.load_json(utils.PORTFOLIOS_FILE, default=[])
    if isinstance(records, list):
        for record in records:
            if isinstance(record, dict) and record.get("user_id") == user_id:
                return Portfolio.from_dict(record, user=user)
    return Portfolio(_user_id=user_id, user=user)


def save_portfolio(portfolio):
    records = utils.load_json(utils.PORTFOLIOS_FILE, default=[])
    if not isinstance(records, list):
        records = []
    payload = portfolio.to_dict()
    replaced = False
    for index, record in enumerate(records):
        if isinstance(record, dict) and record.get("user_id") == (
                portfolio.user_id
        ):
            records[index] = payload
            replaced = True
            break
    if not replaced:
        records.append(payload)
    utils.save_json(utils.PORTFOLIOS_FILE, records)


def refresh_rates(rates, now=None):
    """ Обновляет таблицу курсов и сохраняет её в rates.json.
    Пока Parser Service не подключён, курсы берутся из заглушки
    utils.build_stub_rates. Для подключения сервиса достаточно заменить тело
    функции на обращение к сервису: контракт (формат rates.json) не изменится.
    """
    updated = utils.refresh_rates(rates, now)
    utils.save_rates(updated)
    rate_cache.clear()
    return updated


def fresh_rates():
    """ Возвращает таблицу курсов, обновляя кеш, если он устарел."""
    rates = utils.load_rates()
    if not utils.is_fresh(rates.get("last_refresh")):
        rates = refresh_rates(rates)
    return rates


def lookup_rate(currency_from, currency_to):
    """ Читает курс пары из кеша, при протухании - обновляет курсы.
        Возвращает словарь {"rate": float, "updated_at": datetime}.
    """
    rates = utils.load_rates()
    found = utils.find_rate(rates, currency_from, currency_to)
    if found is None or not utils.is_fresh(found[1]):
        rates = refresh_rates(rates)
        found = utils.find_rate(rates, currency_from, currency_to)
    if found is None:
        raise RateServiceError(currency_from, currency_to)
    rate, updated_at = found
    return {
        "rate": rate,
        "updated_at": utils.parse_datetime(updated_at) or datetime.now(),
    }


def get_rate(currency_from, currency_to):
    """ Возвращает курс одной валюты к другой и обратный курс.
        Результат кэшируется на время сессии, поэтому повторный запрос той же пары
        не читает и не обновляет файл.
    """
    from_code = utils.validate_currency_code(currency_from)
    to_code = utils.validate_currency_code(currency_to)
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
    users.append(user)
    save_users(users)
    save_portfolio(Portfolio(_user_id=user_id, user=user))
    return {"user_id": user.user_id, "username": user.username}


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
    rates = fresh_rates()
    if utils.value_in_base(rates, base) is None:
        raise UnknownCurrencyError(base)

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


def buy_currency(currency_code, amount):
    """ Покупает валюту: создаёт кошелёк при необходимости и пополняет баланс.

    Возвращает данные для отчёта: курс, изменения балансов, оценочную стоимость.
    """
    user = current_user()
    code = utils.validate_currency_code(currency_code)
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
    return {
        "operation": "buy",
        "currency_code": code,
        "amount": value,
        "rate": price,
        "base": utils.BASE_CURRENCY,
        "changes": changes,
        "estimate": value * price,
    }


def sell_currency(currency_code, amount):
    """ Продаёт валюту: списывает баланс, при SETTLE_IN_USD начисляет USD.

    Возвращает данные для отчёта: курс, изменения балансов, оценочную выручку.
    """
    user = current_user()
    code = utils.validate_currency_code(currency_code)
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
    return {
        "operation": "sell",
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
