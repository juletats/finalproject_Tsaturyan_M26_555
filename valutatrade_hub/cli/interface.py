"""Командный интерфейс: единственная точка входа для пользовательских команд.

Модуль настраивает логи, разбирает строку ввода, вызывает бизнес-логику из
core/usecases.py и печатает результат. Проверок данных и расчётов здесь нет -
только разбор аргументов, представление результата и подсказки к ошибкам.
"""

import shlex
import sys
import time

from prettytable import PrettyTable

from valutatrade_hub import logging_config
from valutatrade_hub.core import currencies, usecases, utils
from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    CurrencyNotFoundError,
    StaleRatesError,
)
from valutatrade_hub.parser_service import (
    RateScheduler,
    RatesStorage,
    build_updater,
)

DIVIDER = "-" * 33

PROMPT = ">>> "

# Активный планировщик парсера: один на процесс, запускается --interval
ACTIVE_SCHEDULER = {"scheduler": None}

# Обязательные аргументы каждой команды
COMMAND_FLAGS = {
    "register": ("--username", "--password"),
    "login": ("--username", "--password"),
    "show-portfolio": ("--base",),
    "buy": ("--currency", "--amount"),
    "sell": ("--currency", "--amount"),
    "get-rate": ("--from", "--to"),
    "update-rates": ("--source", "--interval"),
    "show-rates": ("--currency", "--top", "--base"),
}

# Справочная информация: команда, аргументы, описание
COMMAND_HELP = (
    ("register", "--username <str> --password <str>",
     "создать нового пользователя"),
    ("login", "--username <str> --password <str>",
     "войти и зафиксировать сессию"),
    ("show-portfolio", "[--base <str>]",
     "показать кошельки и итог в базовой валюте"),
    ("buy", "--currency <str> --amount <float>",
     "купить валюту"),
    ("sell", "--currency <str> --amount <float>",
     "продать валюту"),
    ("get-rate", "--from <str> --to <str>",
     "получить курс одной валюты к другой"),
    ("update-rates", "[--source <str>] [--interval <int>]",
     "обновить курсы через парсер (coingecko, exchangerate)"),
    ("show-rates", "[--currency <str>] [--top <int>] [--base <str>]",
     "показать кеш курсов с фильтрами"),
    ("stop-parser", "", "остановить фоновое обновление курсов"),
    ("help", "", "показать эту справку"),
    ("exit", "", "выйти из приложения"),
)


def tokenize(line):
    """ Разбивает строку ввода по правилам shell: кавычки сохраняют пробелы."""
    return shlex.split(line)


def parse_flags(command, tokens, allowed):
    """ Собирает аргументы вида '--ключ значение' в словарь.

    Неизвестный ключ или отсутствующее значение превращается в ValueError с
    текстом, который CLI показывает пользователю как есть.
    """
    flags = {}
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if not token.startswith("--"):
            raise ValueError(
                f"Лишний аргумент '{token}'. Формат: "
                f"{command} {' '.join(allowed)}"
            )
        if token not in allowed:
            raise ValueError(
                f"Команда '{command}' не знает аргумент {token}"
            )
        if index + 1 >= len(tokens):
            raise ValueError(f"Не указано значение аргумента {token}")
        flags[token] = tokens[index + 1]
        index += 2
    return flags


def require_flags(command, flags, names):
    """ Возвращает значения обязательных аргументов в порядке их перечисления."""
    missing = [name for name in names if name not in flags]
    if missing:
        raise ValueError(
            f"Команда '{command}' требует аргументы: {', '.join(missing)}"
        )
    return tuple(flags[name] for name in names)


def build_help_table():
    """ Собирает таблицу доступных команд."""
    table = PrettyTable(["Команда", "Аргументы", "Описание"])
    for column in table.field_names:
        table.align[column] = "l"
    for command, arguments, description in COMMAND_HELP:
        table.add_row([command, arguments, description])
    return table


def print_help():
    """ Печатает справку по всем командам."""
    print("\n***<Valuta Trade Hub>***")
    print(build_help_table())


def welcome():
    """ Печатает приветствие при запуске приложения."""
    print("Добро пожаловать в платформу Valuta Trade Hub!")
    print("Зарегистрируйтесь и следите за курсами.")


def supported_currencies_text():
    """ Строка с кодами валют, которые поддерживает реестр."""
    return ", ".join(currencies.supported_codes())


def print_register(result):
    """ Печатает итог регистрации."""
    username = result["username"]
    print(
        f"Пользователь '{username}' зарегистрирован "
        f"(id={result['user_id']}). Войдите: login --username {username} "
        "--password ****"
    )


def render_login(result):
    """ Печатает подтверждение входа."""
    print(f"Вы вошли как '{result['username']}'")


def render_portfolio(summary):
    """ Печатает кошельки пользователя и итоговую стоимость в базовой валюте."""
    base = summary["base"]
    username = summary["username"]
    print(f"Портфель пользователя '{username}' (база: {base}):")

    if not summary["rows"]:
        print(
            "Кошельков пока нет. Валюта создаётся автоматически при первой "
            "покупке: buy --currency EUR --amount 10"
        )
        return

    for row in summary["rows"]:
        code = row["currency_code"]
        balance = utils.format_amount(row["balance"], code)
        value = f"{row['value']:.2f}"
        print(f"- {code}: {balance}  → {value} {base}")

    print(DIVIDER)
    print(f"ИТОГО: {utils.format_money(summary['total'], base)}")


def render_trade(result):
    """ Печатает итог покупки или продажи с изменениями портфеля."""
    code = result["currency_code"]
    base = result["base"]
    amount = utils.format_amount(result["amount"], code)
    rate = utils.format_rate_value(result["rate"])
    verb = (
        "Покупка выполнена" if result["operation"] == "buy"
        else "Продажа выполнена"
    )
    print(f"{verb}: {amount} {code} по курсу {rate} {base}/{code}")
    print("Изменения в портфеле:")
    for change in result["changes"]:
        change_code = change["currency_code"]
        was = utils.format_amount(change["was"], change_code)
        became = utils.format_amount(change["became"], change_code)
        print(f"- {change_code}: было {was} → стало {became}")

    label = (
        "Оценочная стоимость покупки" if result["operation"] == "buy"
        else "Оценочная выручка"
    )
    estimate = utils.format_money(result["estimate"], base)
    print(f"{label}: {estimate}")

    currency = currencies.find_currency(result["currency_code"])
    if currency is not None:
        print(f"Валюта сделки: {currency.get_display_info()}")


def render_rate(info):
    """ Печатает курс пары валют и обратный курс."""
    from_code = info["currency_from"]
    to_code = info["currency_to"]
    updated_at = utils.format_datetime(info["updated_at"])
    print(
        f"Курс {from_code}→{to_code}: "
        f"{utils.format_rate_value(info['rate'])} (обновлено: {updated_at})"
    )
    print(
        f"Обратный курс {to_code}→{from_code}: "
        f"{utils.format_rate_value(info['reverse'])}"
    )


# --- Парсер курсов: вывод -------------------------------------------------------


def rates_storage():
    """ Хранилище парсера: создаётся по запросу, чтобы пути и настройки
    брались из актуального Singleton SettingsLoader."""
    return RatesStorage()


def render_update(summary):
    """ Печатает ход и итог обновления курсов (примеры ТЗ 4.4.6)."""
    print("INFO: Обновление курсов: старт")
    for source, count in summary["by_source"].items():
        print(f"INFO: {source}... OK ({count} курса)")
    for source in summary["skipped"]:
        print(
            f"INFO: {source}... пропущен: не задан EXCHANGERATE_API_KEY"
        )
    for source, message in summary["errors"]:
        print(f"ERROR: {source}... ошибка: {message}")

    total = summary["total"]
    if not total:
        print(
            "Обновление не выполнено: курсы не получены. Проверьте сеть и "
            "ключ API, журнал: make parser-logs"
        )
        return
    print(
        f"INFO: запись {summary['snapshot_updated']} курсов в "
        f"{summary['rates_path']}..."
    )
    refresh = summary["last_refresh"] or "нет данных"
    if summary["errors"] or summary["skipped"]:
        print(
            "Обновление завершено с замечаниями. "
            "Подробности: logs/parser.log"
        )
    else:
        print("Обновление успешно.")
    print(
        f"Всего получено курсов: {total}, новых в истории: "
        f"{summary['history_added']}. Последний снимок: {refresh}"
    )


def render_scheduler_status(status):
    """ Печатает состояние фонового обновления курсов."""
    print(
        f"Планировщик запущен: интервал {status['interval_seconds']} с, "
        f"источник: {status['source'] or 'все'}"
    )
    print(
        "Первое обновление выполнено сразу, дальше - по расписанию. "
        "Остановка: stop-parser"
    )


def format_moment(value):
    """ Метка времени записи кеша для таблицы: локальное время или прочерк."""
    moment = utils.parse_datetime(value)
    return utils.format_datetime(moment) if moment else "-"


def render_rates(rows, last_refresh, stale):
    """ Печатает таблицу курсов из локального кеша."""
    print(f"Курсы из локального кеша (обновлено: {format_moment(last_refresh)}):")
    table = PrettyTable(["Пара", "Курс", "Обновлено", "Источник"])
    for column in table.field_names:
        table.align[column] = "l"
    for row in rows:
        table.add_row([
            row["pair"],
            utils.format_rate_value(row["rate"]),
            format_moment(row["updated_at"]),
            row["source"] or "-",
        ])
    print(table)
    if stale:
        print(
            f"Внимание: данные старше срока годности "
            f"{utils.rates_ttl():.0f} с - выполните update-rates."
        )


# --- Команды -----------------------------------------------------------------


def register(tokens):
    """ Команда register: создаёт пользователя и пустой портфель."""
    flags = parse_flags("register", tokens, COMMAND_FLAGS["register"])
    username, password = require_flags("register", flags,
                                       ("--username", "--password"))
    print_register(usecases.register_user(username, password))


def handle_login(tokens):
    """ Команда login: проверяет пароль и фиксирует сессию."""
    flags = parse_flags("login", tokens, COMMAND_FLAGS["login"])
    username, password = require_flags(
        "login", flags, ("--username", "--password")
    )
    render_login(usecases.login_user(username, password))


def handle_show_portfolio(tokens):
    """ Команда show-portfolio: кошельки и итог в базовой валюте."""
    flags = parse_flags(
        "show-portfolio", tokens, COMMAND_FLAGS["show-portfolio"]
    )
    base = flags.get("--base")
    render_portfolio(usecases.get_portfolio_summary(base))


def handle_buy(tokens):
    """ Команда buy: покупка валюты в кошелёк текущего пользователя."""
    flags = parse_flags("buy", tokens, COMMAND_FLAGS["buy"])
    currency, amount = require_flags(
        "buy", flags, ("--currency", "--amount")
    )
    render_trade(usecases.buy_currency(currency, amount))


def handle_sell(tokens):
    """ Команда sell: продажа валюты с кошелька текущего пользователя."""
    flags = parse_flags("sell", tokens, COMMAND_FLAGS["sell"])
    currency, amount = require_flags(
        "sell", flags, ("--currency", "--amount")
    )
    render_trade(usecases.sell_currency(currency, amount))


def handle_get_rate(tokens):
    """ Команда get-rate: курс одной валюты к другой и обратный курс."""
    flags = parse_flags("get-rate", tokens, COMMAND_FLAGS["get-rate"])
    currency_from, currency_to = require_flags(
        "get-rate", flags, ("--from", "--to")
    )
    render_rate(usecases.get_rate(currency_from, currency_to))


def validate_positive_int(value, label):
    """ Целое из строки аргумента команды: только положительное."""
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"{label} должен быть целым числом") from None
    if number <= 0:
        raise ValueError(f"{label} должен быть положительным числом")
    return number


def stop_scheduler():
    """ Останавливает активный планировщик. Возвращает число проходов."""
    scheduler = ACTIVE_SCHEDULER["scheduler"]
    if scheduler is None:
        return None
    ACTIVE_SCHEDULER["scheduler"] = None
    return scheduler.stop()


def handle_update_rates(tokens):
    """ Команда update-rates: немедленное обновление курсов парсером.

    С --interval обновление уходит в фоновый поток и повторяется по
    расписанию, REPL при этом остаётся отзывчивым.
    """
    flags = parse_flags("update-rates", tokens, COMMAND_FLAGS["update-rates"])
    source = flags.get("--source")
    updater = build_updater()
    interval = flags.get("--interval")
    if interval is None:
        render_update(updater.run_update(source))
        usecases.invalidate_rate_cache()
        return

    seconds = validate_positive_int(interval, "--interval")
    if stop_scheduler() is not None:
        print("Прежний планировщик остановлен.")
    scheduler = RateScheduler(updater=updater, interval_seconds=seconds)
    scheduler.start(source)
    ACTIVE_SCHEDULER["scheduler"] = scheduler
    render_scheduler_status(scheduler.status())


def handle_stop_parser(tokens):
    """ Команда stop-parser: гасит фоновое обновление курсов."""
    if tokens:
        raise ValueError("Команда 'stop-parser' не принимает аргументов")
    runs = stop_scheduler()
    if runs is None:
        print("Фоновое обновление курсов не запущено.")
        return
    print(f"Фоновое обновление остановлено, выполнено проходов: {runs}.")


def rate_entries(table=None):
    """ Записи пар из кеша курсов: код пары, курс, время, источник."""
    snapshot = table if table is not None else rates_storage().read_snapshot()
    rows = []
    for key, entry in sorted(utils.pairs_of(snapshot).items()):
        found = utils.entry_rate(entry)
        if found is None:
            continue
        rate, updated_at = found
        rows.append({
            "pair": key,
            "rate": rate,
            "updated_at": updated_at,
            "source": entry.get("source") if isinstance(entry, dict) else None,
        })
    return rows


def filter_currency(rows, code):
    """ Строки только по одной валюте (с любой стороны пары).

    Пустой результат сопровождается текстом из ТЗ 4.4.6: «Курс для 'ABC' не
    найден в кеше» - подсказка ближе к фильтру, чем общий текст об отсутствии
    строк.
    """
    wanted = utils.validate_currency_code(code)
    found = [
        row for row in rows
        if wanted in str(row["pair"]).split("_")
    ]
    if not found:
        print(f"Курс для '{wanted}' не найден в кеше.")
    return found


def rebase_rows(rows, base):
    """ Пересчитывает курсы относительно другой базовой валюты."""
    code = currencies.get_currency(
        utils.validate_currency_code(base)
    ).code
    table = rates_storage().read_snapshot()
    result = []
    for row in rows:
        currency_from, _, _ = str(row["pair"]).partition("_")
        if currency_from == code:
            result.append(row)
            continue
        found = utils.find_rate(table, currency_from, code)
        if found is None:
            continue
        rate, updated_at = found
        result.append({
            "pair": utils.pair_key(currency_from, code),
            "rate": rate,
            "updated_at": updated_at,
            "source": row["source"],
        })
    return result


def top_cryptos(rows, count):
    """ N самых дорогих криптовалют по курсу."""
    crypto = [
        row for row in rows
        if str(row["pair"]).partition("_")[0] in utils.CRYPTO_CURRENCIES
    ]
    crypto.sort(key=lambda row: row["rate"], reverse=True)
    return crypto[:count]


def handle_show_rates(tokens):
    """ Команда show-rates: курсы из локального кеша с фильтрами."""
    flags = parse_flags("show-rates", tokens, COMMAND_FLAGS["show-rates"])
    storage = rates_storage()
    table = storage.read_snapshot()
    rows = rate_entries(table)
    if not rows:
        print(
            "Локальный кеш курсов пуст. Выполните 'update-rates', чтобы "
            "загрузить данные."
        )
        return

    currency = flags.get("--currency")
    if currency is not None:
        rows = filter_currency(rows, currency)
        # Текст «не найдено» уже напечатан фильтром
        if not rows:
            return
    base = flags.get("--base")
    if base is not None:
        rows = rebase_rows(rows, base)
    top = flags.get("--top")
    if top is not None:
        rows = top_cryptos(rows, validate_positive_int(top, "--top"))
    if not rows:
        print("Под выбранные фильтры курсов в кеше нет.")
        return
    render_rates(
        rows,
        table.get("last_refresh"),
        not utils.is_cache_fresh(table),
    )


COMMAND_HANDLERS = {
    "register": register,
    "login": handle_login,
    "show-portfolio": handle_show_portfolio,
    "buy": handle_buy,
    "sell": handle_sell,
    "get-rate": handle_get_rate,
    "update-rates": handle_update_rates,
    "show-rates": handle_show_rates,
    "stop-parser": handle_stop_parser,
}


def dispatch(command, tokens):
    """ Выполняет команду. Возвращает False, если приложение нужно завершить."""
    if command == "help":
        print_help()
        return True
    if command in ("exit", "quit"):
        return False

    handler = COMMAND_HANDLERS.get(command)
    if handler is None:
        print(f"Функции {command} нет. Попробуйте снова.")
        return True

    try:
        handler(tokens)
    except CurrencyNotFoundError as error:
        # Доменное исключение печатается как есть, к нему добавляется подсказка
        print(error)
        print(f"Поддерживаемые валюты: {supported_currencies_text()}. "
              "Справка: help get-rate")
    except ApiRequestError as error:
        print(error)
        print("Повторите попытку позже или проверьте подключение к сети: "
              "курсы обновляются сервисом парсинга.")
    except StaleRatesError as error:
        print(error)
        print(f"Срок годности кеша задаёт настройка rates_ttl_seconds "
              f"(сейчас {utils.rates_ttl():.0f} с).")
    except ValueError as error:
        print(error)
    return True


def execute_line(line):
    """ Выполняет одну строку ввода пользователя."""
    try:
        tokens = tokenize(line)
    except ValueError:
        print(f"Некорректное значение: {line}. Попробуйте снова.")
        return True
    if not tokens:
        return True
    return dispatch(tokens[0], tokens[1:])


def read_line():
    """ Читает строку команды. Возвращает None при EOF (Ctrl-D)."""
    try:
        return input(PROMPT)
    except EOFError:
        print()
        return None


def run():
    """ Читает и выполняет команды до exit."""
    welcome()
    print_help()

    while True:
        line = read_line()
        if line is None or not line.strip():
            if line is None:
                break
            continue
        if not execute_line(line):
            break

    runs = stop_scheduler()
    if runs is not None:
        print(f"Фоновое обновление курсов остановлено, проходов: {runs}.")
    print("До встречи!")


def wait_for_scheduler():
    """ Держит процесс, пока работает фоновое обновление.

    Нужен для однократного запуска (python main.py update-rates --interval 60):
    планировщик - демон-поток, и без ожидания процесс завершился бы сразу.
    """
    if ACTIVE_SCHEDULER["scheduler"] is None:
        return
    print("Фоновое обновление курсов работает. Остановка: Ctrl+C.")
    try:
        while ACTIVE_SCHEDULER["scheduler"].running:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print()
    stop_scheduler()


def main(argv=None):
    """ Точка входа для пользовательских команд """
    logging_config.setup_logging()
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments:
        dispatch(arguments[0], arguments[1:])
        wait_for_scheduler()
        return
    run()

