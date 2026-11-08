"""Вспомогательные функции: пути к данным, валидаторы, хеширование, курсы.
"""

import hashlib
import json
import os
import re
import secrets
from datetime import datetime

# --- Пути к хранилищу -------------------------------------------------------
ENV_DATA_DIR = "VALUTATRADE_HOME"
DATA_DIR = os.environ.get(ENV_DATA_DIR) or os.path.join(os.getcwd(), "data")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
PORTFOLIOS_FILE = os.path.join(DATA_DIR, "portfolios.json")
RATES_FILE = os.path.join(DATA_DIR, "rates.json")

# --- Правила данных ---------------------------------------------------------
BASE_CURRENCY = "USD"
MIN_PASSWORD_LENGTH = 4
SALT_LENGTH = 8
# Код валюты: 2-5 символов, только цифры и заглавные латинские буквы
CURRENCY_PATTERN = re.compile(r"^[A-Z0-9]{2,5}$")
# Балансы крипто-валют показываются с четырьмя знаками, фиатные - с двумя
CRYPTO_CURRENCIES = frozenset({"BTC", "ETH"})
# Сколько секунд запись в rates.json считается актуальной
RATES_TTL_SECONDS = 5 * 60
# Источник курсов, пока Parser Service не подключён
STUB_SOURCE = "RateServiceStub"

# Курсы-заглушка: 1 единица валюты = N базовых валют (USD)
DEFAULT_EXCHANGE_RATES = {
    "EUR": 1.0786,
    "RUB": 0.01016,
    "BTC": 59337.21,
    "ETH": 3720.00,
}


# --- Работа с JSON ----------------------------------------------------------


def load_json(filepath, default):
    """ Читает JSON-файл.

    Возвращает default, если файла ещё нет, он пуст или содержит повреждённые
    данные - приложение не должно падать из-за хранилища.
    """
    try:
        with open(filepath, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return default
    if data is None:
        return default
    return data


def save_json(filepath, data):
    """ Сохраняет данные в JSON-файл, создавая каталог при необходимости."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def next_identifier(records, key):
    """ Возвращает следующий свободный числовой идентификатор (максимум + 1)."""
    existing = [record[key] for record in records
                if isinstance(record, dict) and isinstance(record.get(key), int)]
    return max(existing, default=0) + 1


# --- Валидаторы --------------------------------------------------------------


def validate_username(username):
    """ Проверяет имя пользователя: непустая строка без лишних пробелов."""
    cleaned = str(username).strip() if username is not None else ""
    if not cleaned:
        raise ValueError("Имя пользователя не может быть пустым")
    return cleaned


def validate_password(password):
    """ Проверяет пароль: строка не короче MIN_PASSWORD_LENGTH символов."""
    value = "" if password is None else str(password)
    if len(value) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов"
        )
    return value


def validate_currency_code(currency_code):
    """ Проверяет код валюты и приводит его к верхнему регистру."""
    value = "" if currency_code is None else str(currency_code).strip().upper()
    if not CURRENCY_PATTERN.match(value):
        raise ValueError(f"Некорректный код валюты: '{currency_code}'")
    return value


def validate_amount(amount):
    """ Проверяет сумму: положительное число, приведённое к float."""
    try:
        value = float(amount)
    except (TypeError, ValueError):
        raise ValueError(
            "'amount' должен быть положительным числом"
        ) from None
    if value <= 0:
        raise ValueError("'amount' должен быть положительным числом")
    return value


# --- Хеширование пароля ------------------------------------------------------


def generate_salt(length=SALT_LENGTH):
    """ Возвращает криптостойкую случайную соль."""
    return secrets.token_urlsafe(length)


def hash_password(password, salt):
    """ Возвращает односторонний псевдо-хеш пароля: sha256(password + salt)."""
    digest = hashlib.sha256(f"{password}{salt}".encode("utf-8"))
    return digest.hexdigest()


# --- Форматирование ----------------------------------------------------------


def amount_precision(currency_code):
    """ Сколько знаков после запятой использовать для баланса валюты."""
    return 4 if currency_code in CRYPTO_CURRENCIES else 2


def format_amount(value, currency_code):
    """ Форматирует количество валюты: 0.0500 BTC, 150.00 USD."""
    return f"{value:.{amount_precision(currency_code)}f}"


def format_money(value, currency_code):
    """ Форматирует денежную сумму с разделителем тысяч: 3,329.00 USD."""
    return f"{value:,.2f} {currency_code}"


def format_rate_value(value):
    """ Форматирует курс: крупные значения с двумя знаками, мелкие - с восемью."""
    return f"{value:.2f}" if abs(value) >= 1 else f"{value:.8f}"


def format_datetime(moment):
    """ Форматирует дату и время для вывода """
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def parse_datetime(value):
    """ Разбирает строку ISO в datetime. Возвращает None, если строка некорректна."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def pair_key(currency_from, currency_to):
    """ Ключ пары валют в rates.json: EUR_USD - сколько USD стоит 1 EUR."""
    return f"{currency_from}_{currency_to}"


def entry_rate(entry):
    """ Возвращает (курс, время обновления) из записи rates.json или None."""
    if not isinstance(entry, dict) or "rate" not in entry:
        return None
    try:
        return float(entry["rate"]), entry.get("updated_at")
    except (TypeError, ValueError):
        return None


def value_in_base(rates, currency_code, base=BASE_CURRENCY):
    """ Курс одной единицы валюты в базовой валюте или None без данных."""
    if currency_code == base:
        return 1.0, format_datetime(datetime.now())
    for key in (pair_key(currency_code, base), pair_key(base, currency_code)):
        found = entry_rate(rates.get(key))
        if found is None:
            continue
        rate, updated_at = found
        direct = key.endswith(f"_{base}")
        return (rate if direct else 1 / rate), updated_at
    return None


def find_rate(rates, currency_from, currency_to):
    """ Ищет курс пары в таблице курсов.
        Сначала прямой ключ, затем обратный, затем расчёт через базовую валюту.
        Возвращает (курс, updated_at) либо None, если данных нет.
    """
    direct = entry_rate(rates.get(pair_key(currency_from, currency_to)))
    if direct is not None:
        return direct

    reverse = entry_rate(rates.get(pair_key(currency_to, currency_from)))
    if reverse is not None:
        rate, updated_at = reverse
        return 1 / rate, updated_at

    from_value = value_in_base(rates, currency_from)
    to_value = value_in_base(rates, currency_to)
    if from_value is None or to_value is None:
        return None
    from_rate, from_updated = from_value
    to_rate, to_updated = to_value
    stamps = [stamp for stamp in (from_updated, to_updated) if stamp]
    return from_rate / to_rate, min(stamps) if stamps else None


def is_fresh(updated_at, now=None, ttl_seconds=RATES_TTL_SECONDS):
    moment = parse_datetime(updated_at)
    if moment is None:
        return False
    reference = now or datetime.now()
    return (reference - moment).total_seconds() <= ttl_seconds


def build_stub_rates(now=None):
    """ Собирает таблицу курсов в формате rates.json из данных-заглушки.
        Заглушка эмулирует ответ Parser Service и подключается до того этапа,
        когда сервис будет реализован: достаточно заменить тело refresh_rates().
    """
    timestamp = (now or datetime.now()).isoformat(timespec="seconds")
    rates = {
        pair_key(code, BASE_CURRENCY): {
            "rate": rate,
            "updated_at": timestamp,
        }
        for code, rate in DEFAULT_EXCHANGE_RATES.items()
    }
    rates["source"] = STUB_SOURCE
    rates["last_refresh"] = timestamp
    return rates


def refresh_rates(rates, now=None):
    """ Обновляет кеш курсов: объединяет имеющиеся данные с актуальными.
        Возвращает новую таблицу в формате rates.json.
    """
    fresh = build_stub_rates(now)
    merged = {
        key: value
        for key, value in rates.items()
        if isinstance(value, dict)
    }
    merged.update(fresh)
    merged["source"] = fresh["source"]
    merged["last_refresh"] = fresh["last_refresh"]
    return merged


def load_rates():
    """ Читает кеш курсов из rates.json (пустой словарь, если файла нет)."""
    rates = load_json(RATES_FILE, default={})
    return rates if isinstance(rates, dict) else {}


def save_rates(rates):
    """ Сохраняет кеш курсов в rates.json."""
    save_json(RATES_FILE, rates)


def rates_or_stub(rates=None):
    """ Возвращает таблицу курсов для расчётов: кеш либо заглушку.
        Пустой или повреждённый rates.json (например, при первом запуске без
        каталога данных) не должен ломать расчёт стоимости - в этом случае
        используются фиктивные курсы DEFAULT_EXCHANGE_RATES. Файл при этом не
        меняется: обновление кеша остаётся ответственностью бизнес-логики.
    """
    table = rates if rates is not None else load_rates()
    if any(isinstance(entry, dict) for entry in table.values()):
        return table
    return build_stub_rates()


def create_rate_cache(ttl_seconds=RATES_TTL_SECONDS):
    """ Создаёт кэш курсов
        Возвращает cached_rate(key, loader): значение помнится ttl_seconds секунд,
        по истечении - вычисляется loader(key) заново. У cached_rate есть метод
        clear() для сброса после обновления курса.
    """
    cache = {}

    def cached_rate(key, loader):
        """ Возвращает свежее значение из кэша либо вычисляет его."""
        now = datetime.now()
        entry = cache.get(key)
        if entry is not None:
            stored_at, value = entry
            if (now - stored_at).total_seconds() <= ttl_seconds:
                return value
        value = loader(key)
        cache[key] = (now, value)
        return value

    def clear():
        cache.clear()

    cached_rate.clear = clear
    return cached_rate
