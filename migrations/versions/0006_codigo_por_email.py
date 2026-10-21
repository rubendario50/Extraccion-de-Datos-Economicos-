"""doble factor por código enviado al email

Revisión: 0006
Anterior: 0005
Creada: 2026-10-20 12:00:00

El segundo factor deja de ser una app de autenticación (TOTP) y pasa a ser un código de 6 dígitos
que se manda al email del usuario. Se crea `codigo_email` (solo el hash del código) y se quitan el
secreto TOTP y los códigos de recuperación, que ya no sirven para nada. Los usuarios existentes no
tienen que hacer nada: en el próximo ingreso reciben el código por email.

El downgrade vuelve a crear las columnas y la tabla de antes, vacías: con esa versión cada usuario
tendría que volver a configurar la app de autenticación.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0006'
down_revision: Union[str, None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('codigo_email',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('usuario_id', sa.Integer(), nullable=False),
    sa.Column('hash', sa.String(length=64), nullable=False),
    sa.Column('creado_en', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expira_en', sa.DateTime(timezone=True), nullable=False),
    sa.Column('usado_en', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuario.id'], name=op.f('fk_codigo_email_usuario_id_usuario'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_codigo_email'))
    )
    with op.batch_alter_table('codigo_email', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_codigo_email_usuario_id'), ['usuario_id'], unique=False)

    with op.batch_alter_table('codigo_recuperacion', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_codigo_recuperacion_usuario_id'))
    op.drop_table('codigo_recuperacion')

    with op.batch_alter_table('usuario', schema=None) as batch_op:
        batch_op.drop_column('totp_ultimo_paso')
        batch_op.drop_column('totp_activo')
        batch_op.drop_column('totp_secret_cifrado')


def downgrade() -> None:
    with op.batch_alter_table('usuario', schema=None) as batch_op:
        batch_op.add_column(sa.Column('totp_secret_cifrado', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('totp_activo', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column('totp_ultimo_paso', sa.BigInteger(), nullable=True))

    op.create_table('codigo_recuperacion',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('usuario_id', sa.Integer(), nullable=False),
    sa.Column('hash', sa.String(length=64), nullable=False),
    sa.Column('usado_en', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuario.id'], name=op.f('fk_codigo_recuperacion_usuario_id_usuario'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_codigo_recuperacion'))
    )
    with op.batch_alter_table('codigo_recuperacion', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_codigo_recuperacion_usuario_id'), ['usuario_id'], unique=False)

    with op.batch_alter_table('codigo_email', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_codigo_email_usuario_id'))
    op.drop_table('codigo_email')
