"""Настройка логов приложения: уровень, формат, ротация """

import json
import logging
import os
from logging.handlers import RotatingFileHandler

from valutatrade_hub.infra.settings import SettingsLoader

LOGGER_NAME = "valutatrade_hub"
PARSER_LOGGER_NAME = f"{LOGGER_NAME}.parser"
DEFAULT_LEVEL = "INFO"
# Строковый формат: уровень, ISO-время, затем сообщение декоратора
LOG_FORMAT = "%(levelname)s %(asctime)s %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"
TEXT_FORMAT = "text"
JSON_FORMAT = "json"

_configured: dict = {}


class JsonFormatter(logging.Formatter):

    def format(self, record):
        """ Собирает запись логгера в одну JSON-строку."""
        text = record.getMessage()
        try:
            payload = json.loads(text)
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            payload = {"message": text}
        fields = {
            "level": record.levelname,
            "time": self.formatTime(record, DATE_FORMAT),
            **payload,
        }
        return json.dumps(fields, ensure_ascii=False)


def log_filepath(settings=None):
    """ Полный путь файла журнала операций из конфигурации."""
    values = settings or SettingsLoader()
    return os.path.join(values.get("log_dir"), values.get("log_file"))


def parser_log_filepath(settings=None):
    """ Полный путь файла журнала парсера (logs/parser.log)."""
    values = settings or SettingsLoader()
    return os.path.join(values.get("log_dir"), values.get("parser_log_file"))


def resolve_level(settings=None):
    """ Числовой уровень логирования из строкового значения конфигурации."""
    values = settings or SettingsLoader()
    name = str(values.get("log_level", DEFAULT_LEVEL)).upper()
    return getattr(logging, name, logging.INFO)


def uses_json_format(settings=None):
    """ Включён ли JSON-формат журнала (по умолчанию - текстовый)."""
    values = settings or SettingsLoader()
    fmt = str(values.get("log_format", TEXT_FORMAT)).strip().lower()
    return fmt == JSON_FORMAT


def configure_logger(name, destination, force=False):
    """ Настраивает один логгер: уровень, формат, файл с ротацией.

    Ротация - по размеру файла: log_max_bytes байт на файл и log_backup_count
    архивных копий (actions.log.1, actions.log.2 ...). Повторные вызовы
    игнорируются, если не передан force.
    Если каталог для логов недоступен на запись, приложение не падает: логгеру
    остаётся только NullHandler, то есть журнал молча пропускается.
    """
    if _configured.get(name) and not force:
        return logging.getLogger(name)

    settings = SettingsLoader()
    logger = logging.getLogger(name)
    logger.setLevel(resolve_level(settings))
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = (
        JsonFormatter()
        if uses_json_format(settings)
        else logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    )
    try:
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        file_handler = RotatingFileHandler(
            destination,
            maxBytes=int(settings.get("log_max_bytes", 1000000)),
            backupCount=int(settings.get("log_backup_count", 3)),
            encoding="utf-8",
        )
    except OSError as error:
        logger.debug("Файл логов недоступен: %s", error)
        logger.addHandler(logging.NullHandler())
    else:
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    _configured[name] = True
    return logger


def setup_logging(force=False):
    """ Настраивает журнал операций приложения (logs/actions.log)."""
    return configure_logger(LOGGER_NAME, log_filepath(), force)


def setup_parser_logging(force=False):
    """ Настраивает журнал парсера (logs/parser.log)."""
    return configure_logger(PARSER_LOGGER_NAME, parser_log_filepath(), force)


def get_logger(name=None):
    """ Возвращает настроенный логгер приложения."""
    target = name or LOGGER_NAME
    if not _configured.get(target):
        if target == PARSER_LOGGER_NAME:
            setup_parser_logging()
        else:
            setup_logging()
    return logging.getLogger(target)


def parser_logger():
    """ Возвращает настроенный логгер сервиса парсинга."""
    return get_logger(PARSER_LOGGER_NAME)
