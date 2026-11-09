"""Вспомогательные функции: валидаторы, хеширование, курсы, форматирование.

Пути к хранилищу и параметры свежести курсов берутся из Singleton
SettingsLoader, а ввод-вывод JSON - из Singleton DatabaseManager: файл
открыть и записать можно только через слой infra, бизнес-логика работает со
словарями.
"""

import hashlib
import re
import secrets
from datetime import datetime, timezone

from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import SettingsLoader

SETTINGS = SettingsLoader()
DATABASE = DatabaseManager()

# --- Правила данных ---------------------------------------------------------
BASE_CURRENCY = SETTINGS.get("base_currency", "USD")
MIN_PASSWORD_LENGTH = int(SETTINGS.get("min_password_length", 4))
SALT_LENGTH = 8
# Код валюты: 2-5 символов, только цифры и заглавные латинские буквы
CURRENCY_PATTERN = re.compile(r"^[A-Z0-9]{2,5}$")
# Балансы крипто-валют показываются с четырьмя знаками, фиатные - с двумя.
# Типы валют как объекты описаны в core/currencies.py, здесь только правило
# вывода чисел
CRYPTO_CURRENCIES = frozenset({"BTC", "ETH", "SOL"})
# Сколько секунд запись в rates.json считается актуальной (значение по
# умолчанию; реально TTL читается из конфигурации в момент проверки)
RATES_TTL_SECONDS = 5 * 60
# Источник курсов, пока Parser Service не наполнял кеш
STUB_SOURCE = "RateServiceStub"

# Курсы-заглушка: 1 единица валюты = N базовых валют (USD)
DEFAULT_EXCHANGE_RATES = {
    "EUR": 1.0786,
    "GBP": 1.2635,
    "RUB": 0.01016,
    "TRY": 0.0238,
    "BTC": 59337.21,
    "ETH": 3720.00,
    "SOL": 145.12,
}


# --- Хранилище и конфигурация ------------------------------------------------


def data_dir():
    """ Каталог с JSON-файлами из конфигурации."""
    return SETTINGS.get("data_dir")


def storage_path(collection):
    """ Путь файла коллекции ('users', 'portfolios', 'rates')."""
    return DATABASE.path(collection)


def rates_ttl():
    """ TTL курсов в секундах.

    Значение читается каждый раз при обращении, поэтому SettingsLoader.reload()
    меняет политику свежести без перезапуска приложения.
    """
    try:
        return float(SETTINGS.get("rates_ttl_seconds", RATES_TTL_SECONDS))
    except (TypeError, ValueError):
        return float(RATES_TTL_SECONDS)


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
    """ Форматирует дату и время для вывода: метка UTC показывается местно."""
    if moment is not None and moment.tzinfo is not None:
        moment = moment.astimezone()
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def parse_datetime(value):
    """ Разбирает строку ISO в datetime. Возвращает None, если строка некорректна."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def now_utc():
    """ Текущее время в UTC с часовой меткой - единая шкала для сравнений."""
    return datetime.now(timezone.utc)


def utc_timestamp():
    """ Метка времени ISO в UTC с суффиксом Z: формат записей парсера."""
    text = now_utc().isoformat(timespec="seconds")
    return text.replace("+00:00", "Z")


def to_aware(moment):
    """ Приводит datetime к aware-UTC. Наивные метки считаются локальными"""
    if moment is None or moment.tzinfo is not None:
        return moment
    return moment.astimezone()


def to_utc_iso(moment):
    """ Метка ISO в UTC с суффиксом Z из datetime (None - если момента нет)."""
    moment = to_aware(moment)
    if moment is None:
        return None
    return moment.astimezone(timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")


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


def is_fresh(updated_at, now=None, ttl_seconds=None):
    """ True, если метка времени обновления не старше TTL из конфигурации."""
    moment = to_aware(parse_datetime(updated_at))
    if moment is None:
        return False
    reference = to_aware(now) if now is not None else now_utc()
    lifetime = rates_ttl() if ttl_seconds is None else float(ttl_seconds)
    return (reference - moment).total_seconds() <= lifetime


# --- Формат кеша курсов -----------------------------------------------------
# Parser Service пишет вложенный формат
# {"pairs": {...}, "last_refresh": ...} (ТЗ 4.4),
# бизнес-логика работает с плоским словарём, поэтому конвертация
# живёт в одном месте: на чтении и на записи.
RATES_PAIRS_KEY = "pairs"


def pairs_of(rates):
    """ Словарь пар из кеша любого формата: вложенного или плоского."""
    if not isinstance(rates, dict):
        return {}
    nested = rates.get(RATES_PAIRS_KEY)
    if isinstance(nested, dict):
        return dict(nested)
    return {
        key: value for key, value in rates.items() if isinstance(value, dict)
    }


def normalize_rates(rates):
    """ Плоское представление кеша: пары на верхнем уровне + время снимка."""
    table = pairs_of(rates)
    if not isinstance(rates, dict):
        return table
    for key in ("source", "last_refresh"):
        if key in rates:
            table[key] = rates[key]
    return table


def wrap_rates(rates):
    """ Собирает содержимое rates.json из плоской таблицы курсов."""
    source = STUB_SOURCE
    if isinstance(rates, dict):
        source = rates.get("source", STUB_SOURCE)
    pairs = {}
    for key, entry in pairs_of(rates).items():
        record = dict(entry)
        record.setdefault("source", source)
        pairs[key] = record
    last_refresh = (rates or {}).get("last_refresh") or utc_timestamp()
    return {RATES_PAIRS_KEY: pairs, "last_refresh": last_refresh}


def cache_updated_at(rates):
    """ Самая свежая метка обновления среди записей пар (datetime или None)."""
    stamps = [
        to_aware(parse_datetime(entry.get("updated_at")))
        for entry in pairs_of(rates).values() if isinstance(entry, dict)
    ]
    stamps = [stamp for stamp in stamps if stamp is not None]
    return max(stamps) if stamps else None


def is_cache_fresh(rates, now=None, ttl_seconds=None):
    """ True, если кеш содержит хотя бы одну свежую по TTL запись."""
    moment = cache_updated_at(rates)
    if moment is None:
        return False
    reference = to_aware(now) if now is not None else now_utc()
    lifetime = rates_ttl() if ttl_seconds is None else float(ttl_seconds)
    return (reference - moment).total_seconds() <= lifetime


def build_stub_rates(now=None):
    """ Собирает таблицу курсов в формате rates.json из данных-заглушки.
        Заглушка наполняет только пустой кеш при первом запуске: живые курсы
        пишет парсер (parser_service), Core к внешним API не обращается.
    """
    timestamp = to_utc_iso(now) if now else utc_timestamp()
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


def load_rates():
    """ Читает кеш курсов из rates.json (плоский вид, пустой словарь без файла)."""
    rates = DATABASE.read("rates", default={})
    return normalize_rates(rates) if isinstance(rates, dict) else {}


def save_rates(rates):
    """ Сохраняет кеш курсов в rates.json атомарной записью (формат 'pairs')."""
    DATABASE.write("rates", wrap_rates(rates))


def rates_or_stub(rates=None):
    """ Возвращает таблицу курсов для расчётов: кеш либо заглушку.
        Пустой или повреждённый rates.json (например, при первом запуске без
        каталога данных) не должен ломать расчёт стоимости - в этом случае
        используются фиктивные курсы DEFAULT_EXCHANGE_RATES. Файл при этом не
        меняется: наполнение кеша - задача Parser Service.
    """
    table = normalize_rates(rates) if rates is not None else load_rates()
    if pairs_of(table):
        return table
    return build_stub_rates()


def create_rate_cache(ttl_seconds=None):
    """ Создаёт кэш курсов
        Возвращает cached_rate(key, loader): значение помнится TTL секунд -
        либо из аргумента, либо из конфигурации (проверяется при каждом
        обращении),
        по истечении - вычисляется loader(key) заново. У cached_rate есть метод
        clear() для сброса после обновления курса.
    """
    cache = {}

    def cached_rate(key, loader):
        """ Возвращает свежее значение из кэша либо вычисляет его."""
        now = datetime.now()
        lifetime = rates_ttl() if ttl_seconds is None else float(ttl_seconds)
        entry = cache.get(key)
        if entry is not None:
            stored_at, value = entry
            if (now - stored_at).total_seconds() <= lifetime:
                return value
        value = loader(key)
        cache[key] = (now, value)
        return value

    def clear():
        cache.clear()

    cached_rate.clear = clear
    return cached_rate
