"""Инфраструктурный слой: конфигурация приложения и доступ к хранилищу. """


class Singleton(type):
    """ Метакласс «один экземпляр на класс»."""

    # Класс -> его единственный экземпляр
    _instances: dict = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]

    def reset(cls):
        cls._instances.pop(cls, None)
