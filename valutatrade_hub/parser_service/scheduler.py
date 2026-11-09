"""Планировщик периодического обновления курсов."""

import threading
from datetime import timedelta

from valutatrade_hub import logging_config
from valutatrade_hub.core import utils
from valutatrade_hub.parser_service import config as parser_config
from valutatrade_hub.parser_service.updater import RatesUpdater

ACTION = "SCHEDULER"


class RateScheduler:
    """ Периодический запуск апдейтера в отдельном потоке."""

    def __init__(
        self, updater=None, interval_seconds=None, settings=None, logger=None,
    ):
        self._settings = settings or parser_config.ParserConfig.from_settings()
        self._updater = updater or RatesUpdater(settings=self._settings)
        # Ноль и пустая строка - разные случаи: явный 0 должен отклоняться,
        # а не молча заменяться настройкой
        interval = (
            self._settings.update_interval_seconds
            if interval_seconds is None else interval_seconds
        )
        try:
            self._interval = int(float(str(interval).strip()))
        except (TypeError, ValueError):
            raise ValueError(
                "Интервал обновления должен быть целым числом секунд"
            ) from None
        if self._interval <= 0:
            raise ValueError(
                "Интервал обновления должен быть положительным числом"
            )
        self._logger = logger or logging_config.parser_logger()
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._last_run = None
        self._state = {
            "runs": 0,
            "failures": 0,
            "last_summary": None,
            "source": None,
        }

    @property
    def interval_seconds(self):
        """ Период обновления в секундах."""
        return self._interval

    @property
    def running(self):
        """ Работает ли поток планировщика сейчас."""
        return self._thread is not None and self._thread.is_alive()

    def start(self, source=None):
        """ Включает планировщик: первый проход сразу, дальше - по интервалу."""
        if self.running:
            raise ValueError("Планировщик уже запущен")
        self._stop.clear()
        with self._lock:
            self._state["source"] = source
        self._thread = threading.Thread(
            target=self._loop,
            args=(source,),
            name="valutatrade-parser",
            daemon=True,
        )
        self._thread.start()
        self._logger.info(
            "%s: запущен, интервал %d с, источник: %s",
            ACTION, self._interval, source or "все",
        )
        return self

    def _loop(self, source):
        """ Тело фонового потока: обновление, ожидание, остановка по Event."""
        while not self._stop.is_set():
            self.run_once(source)
            if self._stop.wait(self._interval):
                break

    def run_once(self, source=None):
        """ Один проход обновления; аварию протоколирует, поток не роняет."""
        try:
            summary = self._updater.run_update(source)
        except (OSError, ValueError, TypeError) as error:
            with self._lock:
                self._state["runs"] += 1
                self._state["failures"] += 1
                self._last_run = utils.now_utc()
            self._logger.error("%s: проход сорвался: %s", ACTION, error)
            return None
        with self._lock:
            self._state["runs"] += 1
            self._state["last_summary"] = summary
            self._last_run = utils.now_utc()
        return summary

    def stop(self, timeout=5.0):
        """ Гасит поток и возвращает число выполненных проходов."""
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout)
        with self._lock:
            runs = self._state["runs"]
        self._logger.info("%s: остановлен, проходов: %d", ACTION, runs)
        return runs

    def status(self):
        """ Состояние планировщика для вывода в CLI."""
        with self._lock:
            snapshot = dict(self._state)
            moment = self._last_run
        next_run = None
        if self.running and moment is not None:
            next_run = utils.to_utc_iso(
                moment + timedelta(seconds=self._interval)
            )
        return {
            "running": self.running,
            "interval_seconds": self._interval,
            "runs": snapshot["runs"],
            "failures": snapshot["failures"],
            "last_run": utils.to_utc_iso(moment) if moment else None,
            "next_run": next_run,
            "source": snapshot["source"],
            "last_summary": snapshot["last_summary"],
        }

    def __repr__(self):
        return (
            f"RateScheduler(running={self.running!r}, "
            f"interval={self._interval!r}, updater={self._updater!r})"
        )
