"""Upsert (insertar o actualizar) portable entre PostgreSQL y SQLite."""

from collections.abc import Sequence

from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

TAMANIO_LOTE = 500


def upsert(sesion: Session, modelo, filas: Sequence[dict], claves: Sequence[str]) -> int:
    """Inserta las filas; si ya existe una con las mismas `claves`, actualiza el resto de columnas.

    `claves` debe corresponder a la clave primaria o a una restricción UNIQUE de la tabla.
    Devuelve la cantidad de filas procesadas.
    """
    if not filas:
        return 0
    dialecto = sesion.get_bind().dialect.name
    if dialecto == "postgresql":
        insertar = postgresql.insert
    elif dialecto == "sqlite":
        insertar = sqlite.insert
    else:
        raise NotImplementedError(f"Upsert no soportado para el dialecto {dialecto}")

    tabla = modelo.__table__
    for inicio in range(0, len(filas), TAMANIO_LOTE):
        lote = filas[inicio : inicio + TAMANIO_LOTE]
        sentencia = insertar(tabla).values(list(lote))
        a_actualizar = {
            columna: sentencia.excluded[columna] for columna in lote[0] if columna not in claves
        }
        if a_actualizar:
            sentencia = sentencia.on_conflict_do_update(index_elements=list(claves), set_=a_actualizar)
        else:
            sentencia = sentencia.on_conflict_do_nothing(index_elements=list(claves))
        sesion.execute(sentencia)
    return len(filas)
