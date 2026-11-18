"""registro con un email que ya tiene cuenta

Revisión: 0008
Anterior: 0007
Creada: 2026-11-18 12:00:00

Registrarse con un email que ya tiene cuenta no lo revela: al dueño le llega un aviso de que ya tiene
cuenta. `usuario.ultimo_aviso_registro` guarda cuándo se mandó el último, para mandar como máximo uno
cada 15 minutos y que el registro no sirva para inundar un buzón. Vacía en los usuarios existentes.

`usuario.cuenta_de_id`: ese registro crea un usuario «pendiente» (con email aleatorio) que pasa por la
misma sesión pendiente, los mismos códigos, intentos y bloqueo que un registro nuevo, pero que ningún
código completa; apunta a la cuenta real. Los usuarios existentes quedan con NULL.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0008'
down_revision: Union[str, None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('usuario', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ultimo_aviso_registro', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('cuenta_de_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_usuario_cuenta_de_id'), ['cuenta_de_id'], unique=False)
        batch_op.create_foreign_key(batch_op.f('fk_usuario_cuenta_de_id_usuario'), 'usuario', ['cuenta_de_id'], ['id'],
                                    ondelete='CASCADE')


def downgrade() -> None:
    with op.batch_alter_table('usuario', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_usuario_cuenta_de_id_usuario'), type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_usuario_cuenta_de_id'))
        batch_op.drop_column('cuenta_de_id')
        batch_op.drop_column('ultimo_aviso_registro')
