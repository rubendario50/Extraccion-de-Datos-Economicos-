"""contador de intentos del segundo factor

Revisión: 0003
Anterior: 0002
Creada: 2026-10-18 13:30:00

Los fallos de código (TOTP o recuperación) se cuentan aparte de los de contraseña, para que
volver a poner la contraseña correcta no reinicie el contador del segundo factor.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('usuario', schema=None) as batch_op:
        batch_op.add_column(sa.Column('intentos_2fa', sa.Integer(), server_default='0', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('usuario', schema=None) as batch_op:
        batch_op.drop_column('intentos_2fa')
