"""Настройка логов приложения: уровень, формат, ротация """

import json
import logging
import os
from logging.handlers import RotatingFileHandler

from valutatrade_hub.infra.settings import SettingsLoader

LOGGER_NAME = "valutatrade_hub"
DEFAULT_LEVEL = "INFO"
# Строковый формат: уровень, ISO-время, затем сообщение декоратора
LOG_FORMAT = "%(levelname)s %(asctime)s %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"
TEXT_FORMAT = "text"
JSON_FORMAT = "json"

_configured = False


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
    """ Полный путь файла логов из конфигурации."""
    values = settings or SettingsLoader()
    return os.path.join(values.get("log_dir"), values.get("log_file"))


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


def setup_logging(force=False):
    """ Настраивает логгер приложения; повторные вызовы игнорируются.
    Ротация - по размеру файла:
    log_max_bytes байт на файл
    log_backup_count архивных копий (actions.log.1, actions.log.2 ...)
    Если каталог для логов недоступен на запись, приложение не падает:
    логгеру остаётся только NullHandler, то есть журнал молча пропускается.
    """
    global _configured
    if _configured and not force:
        return logging.getLogger(LOGGER_NAME)

    settings = SettingsLoader()
    logger = logging.getLogger(LOGGER_NAME)
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
        destination = log_filepath(settings)
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

    _configured = True
    return logger


def get_logger(name=None):
    if not _configured:
        setup_logging()
    return logging.getLogger(name or LOGGER_NAME)
