"""Хранилище парсера: журнал замеров и снимок курсов для Core.

Два файла - две роли. data/exchange_rates.json хранит историю: одна запись на
один уникальный замер, дубликаты отбрасываются по id, поэтому повторный опрос
пройдера за тот же час не «портит» историю. data/rates.json - снимок текущего
мира: у каждой пары остаётся один последний срез, и именно его читает Core.
Запись в оба файла атомарная (временный файл + os.replace) - её делает
Singleton DatabaseManager, поэтому здесь остаётся только чтение-изменение-запись.
"""

from valutatrade_hub.core import utils
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.parser_service import config as parser_config

# Имена коллекций хранилища (см. infra/database.py)
HISTORY_COLLECTION = "exchange_rates"
SNAPSHOT_COLLECTION = "rates"


class RatesStorage:
    """ Единая точка доступа парсера к JSON-файлам курсов."""

    def __init__(self, settings=None, database=None):
        self._settings = settings or parser_config.ParserConfig.from_settings()
        self._database = database or DatabaseManager()

    # --- История замеров -----------------------------------------------------

    def history(self):
        """ Список записей журнала (пустой список, если файла ещё нет)."""
        records = self._database.read(HISTORY_COLLECTION, default=[])
        return records if isinstance(records, list) else []

    @staticmethod
    def record_id(sample):
        """ id замера: <FROM>_<TO>_<ISO UTC> - правило уникальности из ТЗ."""
        return f"{sample.pair}_{sample.timestamp}"

    def to_record(self, sample):
        """ Запись истории: пары, курс, время, источник и сырые метаданные."""
        currency_from, currency_to = sample.codes
        return {
            "id": self.record_id(sample),
            "from_currency": currency_from,
            "to_currency": currency_to,
            "rate": sample.rate,
            "timestamp": sample.timestamp,
            "source": sample.source,
            "meta": dict(sample.meta),
        }

    def append_history(self, samples):
        """ Добавляет замеры в журнал и возвращает число новых записей.

        Запись попадает в файл только после успешного ответа API и проверки
        данных (курс положительный, коды валидны - это делает RateSample),
        а дубликаты по id пропускаются.
        """
        if not samples:
            return 0
        counter = {"added": 0}

        def _merge(records):
            """ Дописывает в журнал замеры, каких в нём ещё нет."""
            items = records if isinstance(records, list) else []
            known = {
                record.get("id")
                for record in items
                if isinstance(record, dict)
            }
            for sample in samples:
                record = self.to_record(sample)
                if record["id"] in known:
                    continue
                known.add(record["id"])
                items.append(record)
                counter["added"] += 1
            limit = self._settings.history_limit
            if limit and len(items) > limit:
                items = items[-limit:]
            return items

        self._database.update(HISTORY_COLLECTION, _merge, default=[])
        return counter["added"]

    # --- Снимок для Core -----------------------------------------------------

    def read_snapshot(self):
        """ Плоская таблица курсов из rates.json (пустой словарь без файла)."""
        raw = self._database.read(SNAPSHOT_COLLECTION, default={})
        return utils.normalize_rates(raw if isinstance(raw, dict) else {})

    @staticmethod
    def is_newer(entry, sample):
        """ True, если замер свежее уже сохранённого среза пары."""
        moment = utils.to_aware(utils.parse_datetime(sample.fetched_at))
        if moment is None:
            return False
        if not isinstance(entry, dict):
            return True
        stored = utils.to_aware(utils.parse_datetime(entry.get("updated_at")))
        return stored is None or moment >= stored

    def write_snapshot(self, samples):
        """ Перезаписывает снимок пар: «побеждает» более свежий updated_at.

        Возвращает число пар, значения которых действительно обновились.
        Формат файла - из ТЗ 4.4.2: {"pairs": {...}, "last_refresh": ...}.
        """
        counter = {"written": 0}

        def _merge(raw):
            """ Вкладывает замеры в таблицу курсов и оборачивает в формат файла."""
            table = utils.normalize_rates(raw if isinstance(raw, dict) else {})
            for sample in samples:
                if not self.is_newer(table.get(sample.pair), sample):
                    continue
                table[sample.pair] = {
                    "rate": sample.rate,
                    "updated_at": sample.fetched_at,
                    "source": sample.source,
                }
                counter["written"] += 1
            table["last_refresh"] = utils.utc_timestamp()
            return utils.wrap_rates(table)

        self._database.update(SNAPSHOT_COLLECTION, _merge, default={})
        return counter["written"]

    def save(self, samples):
        """ Полный цикл: сначала история, затем снимок для Core."""
        return {
            "history_added": self.append_history(samples),
            "snapshot_updated": self.write_snapshot(samples),
        }

    def __repr__(self):
        return (
            f"RatesStorage(history={self._settings.history_path!r}, "
            f"snapshot={self._settings.rates_path!r})"
        )
