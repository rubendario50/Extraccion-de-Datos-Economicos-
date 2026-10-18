"""factor de escala por serie externa

Revisión: 0004
Anterior: 0003
Creada: 2026-10-18 18:00:00

Cada fuente puede publicar un indicador en otra escala (el FMI en miles de millones de dólares,
el Banco Mundial en dólares). `factor` lleva el valor de la fuente a la escala del indicador interno.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('indicador_serie_externa', schema=None) as batch_op:
        batch_op.add_column(sa.Column('factor', sa.Double(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('indicador_serie_externa', schema=None) as batch_op:
        batch_op.drop_column('factor')
