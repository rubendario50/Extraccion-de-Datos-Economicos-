"""Índices base 100: cada serie pasa a valer 100 en el año base."""

from collections.abc import Mapping


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
