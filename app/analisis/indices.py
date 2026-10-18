"""Índices base 100: cada serie pasa a valer 100 en el año base (o en el promedio del año base)."""

from collections.abc import Mapping
from datetime import date


class ErrorIndice(ValueError):
    """La serie no se puede llevar a base 100 con el año pedido."""


def a_base_100(serie: Mapping[int, float | None], anio_base: int) -> dict[int, float | None]:
    """Convierte {año: valor} en {año: valor / valor_base * 100}.

    Los valores faltantes (None) se mantienen como None.
    Lanza ErrorIndice si no hay dato en el año base o si ese dato es 0.
    """
    base = serie.get(anio_base)
    if base is None:
        raise ErrorIndice(f"No hay dato para el año base {anio_base}.")
    if base == 0:
        raise ErrorIndice(f"El valor del año base {anio_base} es 0: no se puede calcular el índice.")
    return {anio: None if valor is None else valor / base * 100 for anio, valor in serie.items()}


def a_base_100_promedio(serie: Mapping[date, float | None], anio_base: int) -> dict[date, float | None]:
    """Para series mensuales o diarias: el promedio del año base vale 100.

    Es la convención de los índices oficiales (por ejemplo, "IPC base 2010 = 100" significa que el
    promedio de 2010 vale 100). Lanza ErrorIndice si no hay datos en el año base o si su promedio es 0.
    """
    del_anio = [valor for fecha, valor in serie.items() if fecha.year == anio_base and valor is not None]
    if not del_anio:
        raise ErrorIndice(f"No hay datos en el año base {anio_base}.")
    base = sum(del_anio) / len(del_anio)
    if base == 0:
        raise ErrorIndice(f"El promedio del año base {anio_base} es 0: no se puede calcular el índice.")
    return {fecha: None if valor is None else valor / base * 100 for fecha, valor in serie.items()}
