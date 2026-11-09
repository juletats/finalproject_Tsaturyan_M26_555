"""Координатор обновления курсов: опрос источников, история, снимок для Core."""

from valutatrade_hub import logging_config
from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.parser_service import config as parser_config
from valutatrade_hub.parser_service.api_clients import (
    CoinGeckoClient,
    ExchangeRateApiClient,
)
from valutatrade_hub.parser_service.storage import RatesStorage

ACTION = "UPDATE_RATES"


class RatesUpdater:
    """ Точка входа логики парсинга: клиенты -> история -> снимок курсов."""

    def __init__(
        self, clients=None, storage=None, settings=None, session=None,
        logger=None,
    ):
        self._settings = settings or parser_config.ParserConfig.from_settings()
        self._storage = storage or RatesStorage(self._settings)
        self._logger = logger or logging_config.parser_logger()
        self._clients = (
            list(clients) if clients is not None
            else self.default_clients(session)
        )

    def default_clients(self, session=None):
        """ Клиенты по умолчанию: крипта и фиат - из разных источников."""
        return [
            CoinGeckoClient(self._settings, session),
            ExchangeRateApiClient(self._settings, session),
        ]

    def select_clients(self, source=None):
        """ Выбирает клиенты по --source и отсекает недоступные.

        Возвращает пару (список клиентов, список пропущенных источников).
        Источник с выключенным ключом API не считается ошибкой: он просто
        недоступен, и пользователю об этом говорится отдельно.
        """
        clients = self._clients
        if source:
            name = self._settings.source_name(source)
            clients = [client for client in clients if client.source == name]
            if not clients:
                raise ValueError(
                    f"Источник '{name}' не подключён к парсеру"
                )
        chosen, skipped = [], []
        for client in clients:
            if client.available:
                chosen.append(client)
            else:
                skipped.append(client.source)
        return chosen, skipped

    def run_update(self, source=None):
        """ Обновляет курсы и возвращает сводку для CLI и планировщика.

        Сводка: total (сколько курсов получено), by_source, history_added,
        snapshot_updated, errors, skipped, last_refresh, rates_path.
        """
        clients, skipped = self.select_clients(source)
        summary = {
            "total": 0,
            "by_source": {},
            "errors": [],
            "skipped": list(skipped),
            "history_added": 0,
            "snapshot_updated": 0,
            "last_refresh": None,
            "rates_path": self._settings.rates_path,
        }
        names = ", ".join(client.source for client in clients) or "нет"
        self._logger.info("%s: старт, источники: %s", ACTION, names)
        for source_name in skipped:
            self._logger.warning(
                "%s: источник %s пропущен (не задан ключ API)",
                ACTION, source_name,
            )

        samples = []
        for client in clients:
            self._logger.info(
                "%s: запрашиваем %s...", ACTION, client.source
            )
            try:
                fetched = client.fetch_samples()
            except ApiRequestError as error:
                summary["errors"].append((client.source, str(error)))
                self._logger.error(
                    "%s: %s - ошибка: %s", ACTION, client.source, error
                )
                continue
            except (TypeError, ValueError) as error:
                summary["errors"].append((client.source, str(error)))
                self._logger.error(
                    "%s: %s - некорректные данные: %s",
                    ACTION, client.source, error,
                )
                continue
            summary["by_source"][client.source] = len(fetched)
            summary["total"] += len(fetched)
            samples.extend(fetched)
            self._logger.info(
                "%s: %s - OK, курсов: %d",
                ACTION, client.source, len(fetched),
            )

        if not samples:
            self._logger.error("%s: ни одного курса не получено", ACTION)
            return summary

        saved = self._storage.save(samples)
        summary["history_added"] = saved["history_added"]
        summary["snapshot_updated"] = saved["snapshot_updated"]
        summary["last_refresh"] = self._storage.read_snapshot().get(
            "last_refresh"
        )
        self._logger.info(
            "%s: запись в %s - обновлено пар: %d, новых в истории: %d",
            ACTION, self._settings.rates_path,
            saved["snapshot_updated"], saved["history_added"],
        )
        if summary["errors"]:
            self._logger.warning(
                "%s: завершено с ошибками: %s",
                ACTION, "; ".join(f"{name}: {text}"
                                  for name, text in summary["errors"]),
            )
        return summary

    def __repr__(self):
        names = ", ".join(client.source for client in self._clients)
        return f"RatesUpdater(clients={names!r}, storage={self._storage!r})"


def build_updater(session=None, settings=None):
    """ Фабрика апдейтера: конфигурация читается в момент вызова. """
    values = settings or parser_config.ParserConfig.from_settings()
    return RatesUpdater(settings=values, session=session)
