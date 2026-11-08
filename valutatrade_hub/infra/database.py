"""Singleton DatabaseManager: абстракция над JSON-хранилищем приложения."""

import json
import os

from valutatrade_hub.infra import Singleton
from valutatrade_hub.infra.settings import SettingsLoader

# Имя коллекции -> ключ пути в конфигурации
COLLECTIONS = {
    "users": "users_file",
    "portfolios": "portfolios_file",
    "rates": "rates_file",
}

# Временный файл при записи переименовывается на месте
TEMP_SUFFIX = ".tmp"


class DatabaseManager(metaclass=Singleton):
    """ Единая точка доступа к JSON-файлам хранилища. """

    def __init__(self):
        self._settings = SettingsLoader()

    def path(self, collection):
        """ Полный путь файла коллекции ('users', 'portfolios', 'rates')."""
        try:
            filename = self._settings.get(COLLECTIONS[collection])
        except KeyError as error:
            raise ValueError(f"Неизвестная коллекция: '{collection}'") from error
        return os.path.join(self._settings.get("data_dir"), filename)

    def read(self, collection, default):
        """ Читает коллекцию; default - если файла нет или он повреждён."""
        try:
            with open(self.path(collection), "r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError):
            return default
        return default if data is None else data

    def write(self, collection, data):
        """ Записывает коллекцию атомарно: временный файл + os.replace."""
        filepath = self.path(collection)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        temp_path = filepath + TEMP_SUFFIX
        with open(temp_path, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
        os.replace(temp_path, filepath)
        return data

    def update(self, collection, transform, default=None):
        """ Безопасная операция чтение -> модификация -> запись. """
        data = self.read(collection, [] if default is None else default)
        result = transform(data)
        payload = data if result is None else result
        self.write(collection, payload)
        return payload

    def __repr__(self):
        return f"DatabaseManager(data_dir={self._settings.get('data_dir')!r})"
