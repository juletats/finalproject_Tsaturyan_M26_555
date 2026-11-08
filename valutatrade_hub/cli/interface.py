"""Командный интерфейс: единственная точка входа для пользовательских команд.

Модуль разбирает строку ввода, вызывает бизнес-логику из core/usecases.py и
печатает результат. Проверок данных и расчётов здесь нет - только разбор
аргументов и представление результата.
"""

import shlex
import sys

from prettytable import PrettyTable

from valutatrade_hub.core import usecases, utils

DIVIDER = "-" * 33

PROMPT = ">>> "

# Обязательные аргументы каждой команды
COMMAND_FLAGS = {
    "register": ("--username", "--password"),
    "login": ("--username", "--password"),
    "show-portfolio": ("--base",),
    "buy": ("--currency", "--amount"),
    "sell": ("--currency", "--amount"),
    "get-rate": ("--from", "--to"),
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


COMMAND_HANDLERS = {
    "register": register,
    "login": handle_login,
    "show-portfolio": handle_show_portfolio,
    "buy": handle_buy,
    "sell": handle_sell,
    "get-rate": handle_get_rate,
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
    except ValueError as error:
        # Доменные ошибки несут готовый текст для пользователя
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

    print("До встречи!")


def main(argv=None):
    """ Точка входа для пользовательских команд """
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments:
        dispatch(arguments[0], arguments[1:])
        return
    run()


if __name__ == "__main__":
    main()
