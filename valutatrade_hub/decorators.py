"""Декоратор @log_action: прозрачная трассировка доменных операций.

Используется в core/usecases.py для buy_currency, sell_currency, get_rate,
register_user и login_user, запись об ошибке попадает в лог, а само
исключение пробрасывается вызывающему коду (и в итоге CLI).

"""

import functools
import inspect
import json

from valutatrade_hub import logging_config
from valutatrade_hub.core import utils

# Поля аргументов, которые не должны попасть в лог
SECRET_ARGUMENTS = ("password", "salt", "hashed_password", "new_password")
RESULT_OK = "OK"
RESULT_ERROR = "ERROR"

_username_resolver = None


def set_username_resolver(resolver):
    global _username_resolver
    _username_resolver = resolver


def current_username():
    if _username_resolver is None:
        return None
    try:
        return _username_resolver()
    except Exception:  # логирование не имеет право ронять операцию
        return None


def _identity(arguments):
    username = arguments.get("username") or current_username()
    if username:
        return "user", str(username), True
    user_id = arguments.get("user_id")
    if user_id is not None:
        return "user_id", user_id, False
    return "user", None, False


def _currency(arguments):
    code = arguments.get("currency_code")
    if code is not None:
        return str(code)
    source = arguments.get("currency_from")
    target = arguments.get("currency_to")
    if source and target:
        return f"{source}→{target}"
    return None


def _number(value, formatter, default=None):
    if isinstance(value, bool):
        return default
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return default
    if not isinstance(value, (int, float)):
        return default
    return formatter(value)


def _context(arguments, result):
    parts = []
    if isinstance(result, dict):
        changes = result.get("changes")
        if isinstance(changes, list) and changes:
            rendered = []
            for change in changes:
                if not isinstance(change, dict):
                    continue
                code = change.get("currency_code", "")
                was = utils.format_amount(change.get("was", 0.0), code)
                became = utils.format_amount(change.get("became", 0.0), code)
                rendered.append(f"{code}:{was}->{became}")
            if rendered:
                parts.append(f"wallets=[{', '.join(rendered)}]")
        estimate = result.get("estimate")
        text = _number(estimate, lambda value: f"{value:.2f}")
        if text:
            parts.append(f"estimate={text}")
    elif arguments.get("amount") is not None and result is not None:
        parts.append(f"result_value={result!r}")
    return parts


def build_fields(action, arguments, result=None, error=None, verbose=False):
    currency = _currency(arguments)
    fields = [("action", action.upper(), False), _identity(arguments)]
    if currency:
        fields.append(("currency", currency, True))
    amount = _number(
        arguments.get("amount"), lambda value: utils.format_amount(
            value, currency or ""
        )
    )
    if amount is not None:
        fields.append(("amount", amount, False))
    if isinstance(result, dict):
        rate = _number(result.get("rate"), utils.format_rate_value)
        if rate is not None:
            fields.append(("rate", rate, False))
        base = result.get("base")
        if base:
            fields.append(("base", base, True))
    if error is None:
        fields.append(("result", RESULT_OK, False))
    else:
        fields.append(("result", RESULT_ERROR, False))
        fields.append(("error_type", type(error).__name__, False))
        fields.append(("error_message", str(error), True))
    if verbose:
        for extra in _context(arguments, result):
            key, _, value = extra.partition("=")
            fields.append((key, value, False))
    return fields


def render_text(fields):
    parts = []
    for key, value, quoted in fields:
        if key == "action":
            parts.append(str(value))
        elif quoted:
            parts.append(f"{key}={value!r}")
        else:
            parts.append(f"{key}={value}")
    return " ".join(parts)


def render_json(fields):
    payload = {}
    for key, value, _quoted in fields:
        payload[key] = value
    return json.dumps(payload, ensure_ascii=False)


def build_message(action, arguments, result=None, error=None, verbose=False):
    fields = build_fields(action, arguments, result, error, verbose)
    if logging_config.uses_json_format():
        return render_json(fields)
    return render_text(fields)


def safe_arguments(func, args, kwargs):
    try:
        bound = inspect.signature(func).bind(*args, **kwargs)
    except TypeError:
        return {}
    bound.apply_defaults()
    return {
        name: value
        for name, value in bound.arguments.items()
        if name not in SECRET_ARGUMENTS
    }


def log_action(action, verbose=False, logger=None):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            log = logger or logging_config.get_logger()
            arguments = safe_arguments(func, args, kwargs)
            try:
                result = func(*args, **kwargs)
            except Exception as error:
                log.info(
                    build_message(action, arguments, None, error, verbose)
                )
                raise
            log.info(build_message(action, arguments, result, None, verbose))
            return result

        return wrapper

    return decorator
