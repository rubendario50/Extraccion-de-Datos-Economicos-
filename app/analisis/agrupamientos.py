"""Agregado de un grupo de países (Mercosur, G7, ...) a partir de los datos de sus miembros.

Funciones puras: reciben las series de los miembros ya leídas de una sola fuente y no tocan la base.

Cómo se agrega cada indicador (`REGLAS`, el único lugar donde se define):

- Indicadores en niveles (PBI en dólares, población, exportaciones, importaciones): **suma** de los miembros.
- Indicadores en porcentaje del PBI o tasas (deuda, resultado fiscal, crecimiento): **promedio ponderado por
  el PBI en dólares corrientes** (`PBI_USD_CORR`) de cada miembro, de la misma fuente y el mismo año. Así un
  país grande pesa lo que pesa su economía (como en los agregados del FMI, aunque el FMI pondera con PBI en
  paridad de poder adquisitivo, que acá todavía no está).

Qué años tienen valor (la regla más estricta que no deja grupos vacíos por un país que la fuente no cubre):

1. Los miembros de los que la fuente no publica **ningún** dato del indicador (en ningún año) no entran en el
   agregado, y se informan aparte (`fuera`). Por ejemplo, el FMI no publica a Cuba (no es miembro), así que
   «América Latina y el Caribe» con datos del FMI es la suma de los otros 32, y la respuesta lo dice.
2. Para los demás, un año tiene valor **solo si están todos**: el dato de cada miembro y, en los promedios
   ponderados, también su PBI de ese año. Si falta uno, el año queda sin valor y se informa quién falta
   (`faltan`: sin el dato; `faltan_pbi`: con el dato pero sin el PBI para ponderarlo). No se completa con el año anterior ni con estimaciones, y no se mezclan fuentes.

No se acepta una cobertura parcial (por ejemplo, el 90 % de los miembros): en una suma, el total sin un
miembro no es el total del grupo; y en un promedio, el resultado cambiaría de un año a otro según quién
publicó, sin que se note en la serie.

La composición de cada grupo es la actual y se aplica a todos los años (el Mercosur de 1995 se calcula con
los mismos cinco países que hoy).
"""

from collections.abc import Hashable, Mapping
from dataclasses import dataclass, field
from typing import Generic, TypeVar

SUMA = "suma"
PROMEDIO_PONDERADO_PBI = "promedio_ponderado_pbi"
# Indicador con el que se pondera (en la misma fuente que el indicador agregado).
INDICADOR_PESO = "PBI_USD_CORR"

# Código interno del indicador -> cómo se agrega. Un indicador internacional anual nuevo tiene que estar acá
# para poder pedirlo por grupos (un test lo controla).
REGLAS = {
    "PBI_USD_CORR": SUMA,
    "POBLACION": SUMA,
    "EXPORTACIONES_USD": SUMA,
    "IMPORTACIONES_USD": SUMA,
    "PBI_CRECIMIENTO": PROMEDIO_PONDERADO_PBI,
    "DEUDA_GOB_GENERAL": PROMEDIO_PONDERADO_PBI,
    "RESULTADO_FISCAL": PROMEDIO_PONDERADO_PBI,
    "DEUDA_GOB_CENTRAL": PROMEDIO_PONDERADO_PBI,
}

# Cómo se explica cada método en la API y en el panel.
DESCRIPCIONES = {
    SUMA: "Suma de los miembros.",
    PROMEDIO_PONDERADO_PBI: "Promedio ponderado por el PBI en dólares corrientes de cada miembro (misma fuente y año).",
}

K = TypeVar("K", bound=Hashable)


class ErrorAgregado(ValueError):
    """El agregado no se puede calcular (método desconocido o faltan los pesos)."""


@dataclass
class Agregado(Generic[K]):
    valores: dict[int, float | None]  # año -> valor del grupo (None si faltó algún miembro)
    miembros: list[K]  # los que entran: la fuente publica algún dato suyo
    fuera: list[K]  # la fuente no publica ningún dato suyo
    faltan: dict[int, list[K]] = field(default_factory=dict)  # año sin valor -> miembros sin el dato
    faltan_pbi: dict[int, list[K]] = field(default_factory=dict)  # año sin valor -> miembros sin el PBI (peso)


def agregar(
    metodo: str,
    valores: Mapping[K, Mapping[int, float | None]],
    pesos: Mapping[K, Mapping[int, float | None]] | None = None,
) -> Agregado[K]:
    """Agrega las series {año: valor} de los miembros (en el orden de `valores`).

    `pesos`: {miembro: {año: PBI}}, obligatorio para PROMEDIO_PONDERADO_PBI. Los años del resultado son los
    que tienen algún dato de algún miembro que entra; ver la regla de cobertura en el docstring del módulo.
    """
    if metodo not in DESCRIPCIONES:
        raise ErrorAgregado(f"Método de agregación desconocido: {metodo!r}")
    ponderado = metodo == PROMEDIO_PONDERADO_PBI
    if ponderado and pesos is None:
        raise ErrorAgregado("El promedio ponderado necesita el PBI de cada miembro.")

    def con_dato(serie: Mapping[int, float | None]) -> dict[int, float]:
        return {anio: v for anio, v in serie.items() if v is not None}

    series = {m: con_dato(s) for m, s in valores.items()}
    miembros = [m for m, s in series.items() if s]
    fuera = [m for m, s in series.items() if not s]
    pesos_limpios = {m: con_dato((pesos or {}).get(m, {})) for m in miembros}

    resultado: dict[int, float | None] = {}
    faltan: dict[int, list[K]] = {}
    faltan_pbi: dict[int, list[K]] = {}
    for anio in sorted({a for m in miembros for a in series[m]}):
        sin_dato = [m for m in miembros if anio not in series[m]]
        sin_peso = [m for m in miembros if ponderado and anio in series[m] and anio not in pesos_limpios[m]]
        if sin_dato or sin_peso:
            resultado[anio] = None
            if sin_dato:
                faltan[anio] = sin_dato
            if sin_peso:
                faltan_pbi[anio] = sin_peso
        elif ponderado:
            total = sum(pesos_limpios[m][anio] for m in miembros)
            resultado[anio] = (
                sum(series[m][anio] * pesos_limpios[m][anio] for m in miembros) / total if total else None
            )
        else:
            resultado[anio] = sum(series[m][anio] for m in miembros)
    return Agregado(valores=resultado, miembros=miembros, fuera=fuera, faltan=faltan, faltan_pbi=faltan_pbi)
