"""año desde el que una serie externa es proyección

Revisión: 0005
Anterior: 0004
Creada: 2026-10-19 09:00:00

El FMI DataMapper publica datos del WEO con proyecciones. `proyeccion_desde` guarda el año de la
edición del WEO con la que se cargó cada serie: desde ese año los valores son proyecciones.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('indicador_serie_externa', schema=None) as batch_op:
        batch_op.add_column(sa.Column('proyeccion_desde', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('indicador_serie_externa', schema=None) as batch_op:
        batch_op.drop_column('proyeccion_desde')
