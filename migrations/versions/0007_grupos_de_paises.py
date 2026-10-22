"""grupos de países

Revisión: 0007
Anterior: 0006
Creada: 2026-10-22 09:00:00

`grupo` (código interno único, nombre y descripción) y `grupo_pais` (qué países forman cada grupo). Los
grupos predefinidos (Mercosur, G7, BRICS, Unión Europea, América Latina y el Caribe, OCDE) se cargan con las
semillas (`data/seed/grupos.csv` y `grupos_paises.csv`), no con la migración.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0007'
down_revision: Union[str, None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('grupo',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('codigo', sa.String(length=20), nullable=False),
    sa.Column('nombre', sa.String(length=150), nullable=False),
    sa.Column('descripcion', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_grupo')),
    sa.UniqueConstraint('codigo', name=op.f('uq_grupo_codigo'))
    )
    op.create_table('grupo_pais',
    sa.Column('grupo_id', sa.Integer(), nullable=False),
    sa.Column('pais_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['grupo_id'], ['grupo.id'], name=op.f('fk_grupo_pais_grupo_id_grupo'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['pais_id'], ['pais.id'], name=op.f('fk_grupo_pais_pais_id_pais'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('grupo_id', 'pais_id', name=op.f('pk_grupo_pais'))
    )
    with op.batch_alter_table('grupo_pais', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_grupo_pais_pais_id'), ['pais_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('grupo_pais', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_grupo_pais_pais_id'))
    op.drop_table('grupo_pais')
    op.drop_table('grupo')
