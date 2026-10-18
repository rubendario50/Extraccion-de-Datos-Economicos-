"""usuarios y sesiones

Revisión: 0002
Anterior: 0001
Creada: 2026-10-18 12:03:18.571534
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('usuario',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('nombre', sa.String(length=100), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=True),
    sa.Column('google_sub', sa.String(length=255), nullable=True),
    sa.Column('totp_secret_cifrado', sa.String(length=255), nullable=True),
    sa.Column('totp_activo', sa.Boolean(), nullable=False),
    sa.Column('totp_ultimo_paso', sa.BigInteger(), nullable=True),
    sa.Column('rol', sa.String(length=20), nullable=False),
    sa.Column('intentos_fallidos', sa.Integer(), nullable=False),
    sa.Column('bloqueado_hasta', sa.DateTime(timezone=True), nullable=True),
    sa.Column('creado_en', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ultimo_ingreso', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_usuario')),
    sa.UniqueConstraint('email', name=op.f('uq_usuario_email')),
    sa.UniqueConstraint('google_sub', name=op.f('uq_usuario_google_sub'))
    )
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

    op.create_table('sesion',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('usuario_id', sa.Integer(), nullable=False),
    sa.Column('mfa_ok', sa.Boolean(), nullable=False),
    sa.Column('creada_en', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expira_en', sa.DateTime(timezone=True), nullable=False),
    sa.Column('user_agent', sa.String(length=300), nullable=True),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuario.id'], name=op.f('fk_sesion_usuario_id_usuario'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sesion')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_sesion_token_hash'))
    )
    with op.batch_alter_table('sesion', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_sesion_usuario_id'), ['usuario_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('sesion', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sesion_usuario_id'))

    op.drop_table('sesion')
    with op.batch_alter_table('codigo_recuperacion', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_codigo_recuperacion_usuario_id'))

    op.drop_table('codigo_recuperacion')
    op.drop_table('usuario')
