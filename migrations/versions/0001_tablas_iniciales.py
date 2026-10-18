"""tablas iniciales

Revisión: 0001
Anterior: 
Creada: 2026-10-18 11:54:28.027492
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('fuente',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('codigo', sa.String(length=20), nullable=False),
    sa.Column('nombre', sa.String(length=150), nullable=False),
    sa.Column('url', sa.String(length=300), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_fuente')),
    sa.UniqueConstraint('codigo', name=op.f('uq_fuente_codigo'))
    )
    op.create_table('indicador',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('codigo', sa.String(length=50), nullable=False),
    sa.Column('nombre', sa.String(length=200), nullable=False),
    sa.Column('unidad', sa.String(length=100), nullable=False),
    sa.Column('escala', sa.String(length=50), nullable=True),
    sa.Column('alcance', sa.String(length=20), nullable=False),
    sa.Column('frecuencia', sa.String(length=20), nullable=False),
    sa.Column('descripcion', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_indicador')),
    sa.UniqueConstraint('codigo', name=op.f('uq_indicador_codigo'))
    )
    op.create_table('pais',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('codigo', sa.String(length=3), nullable=False),
    sa.Column('nombre', sa.String(length=150), nullable=False),
    sa.Column('nombre_en', sa.String(length=150), nullable=False),
    sa.Column('iso2', sa.String(length=2), nullable=True),
    sa.Column('iso3', sa.String(length=3), nullable=True),
    sa.Column('es_agregado', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pais')),
    sa.UniqueConstraint('codigo', name=op.f('uq_pais_codigo'))
    )
    op.create_table('cotizacion_diaria',
    sa.Column('indicador_id', sa.Integer(), nullable=False),
    sa.Column('fuente_id', sa.Integer(), nullable=False),
    sa.Column('fecha', sa.Date(), nullable=False),
    sa.Column('cierre', sa.Double(), nullable=True),
    sa.Column('actualizado_en', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['fuente_id'], ['fuente.id'], name=op.f('fk_cotizacion_diaria_fuente_id_fuente')),
    sa.ForeignKeyConstraint(['indicador_id'], ['indicador.id'], name=op.f('fk_cotizacion_diaria_indicador_id_indicador')),
    sa.PrimaryKeyConstraint('indicador_id', 'fuente_id', 'fecha', name=op.f('pk_cotizacion_diaria'))
    )
    op.create_table('dato_internacional_anual',
    sa.Column('pais_id', sa.Integer(), nullable=False),
    sa.Column('indicador_id', sa.Integer(), nullable=False),
    sa.Column('fuente_id', sa.Integer(), nullable=False),
    sa.Column('anio', sa.Integer(), nullable=False),
    sa.Column('valor', sa.Double(), nullable=True),
    sa.Column('actualizado_en', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['fuente_id'], ['fuente.id'], name=op.f('fk_dato_internacional_anual_fuente_id_fuente')),
    sa.ForeignKeyConstraint(['indicador_id'], ['indicador.id'], name=op.f('fk_dato_internacional_anual_indicador_id_indicador')),
    sa.ForeignKeyConstraint(['pais_id'], ['pais.id'], name=op.f('fk_dato_internacional_anual_pais_id_pais')),
    sa.PrimaryKeyConstraint('pais_id', 'indicador_id', 'fuente_id', 'anio', name=op.f('pk_dato_internacional_anual'))
    )
    op.create_table('dato_internacional_mensual',
    sa.Column('pais_id', sa.Integer(), nullable=False),
    sa.Column('indicador_id', sa.Integer(), nullable=False),
    sa.Column('fuente_id', sa.Integer(), nullable=False),
    sa.Column('periodo', sa.Date(), nullable=False),
    sa.Column('valor', sa.Double(), nullable=True),
    sa.Column('actualizado_en', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['fuente_id'], ['fuente.id'], name=op.f('fk_dato_internacional_mensual_fuente_id_fuente')),
    sa.ForeignKeyConstraint(['indicador_id'], ['indicador.id'], name=op.f('fk_dato_internacional_mensual_indicador_id_indicador')),
    sa.ForeignKeyConstraint(['pais_id'], ['pais.id'], name=op.f('fk_dato_internacional_mensual_pais_id_pais')),
    sa.PrimaryKeyConstraint('pais_id', 'indicador_id', 'fuente_id', 'periodo', name=op.f('pk_dato_internacional_mensual'))
    )
    op.create_table('dato_nacional_anual',
    sa.Column('indicador_id', sa.Integer(), nullable=False),
    sa.Column('fuente_id', sa.Integer(), nullable=False),
    sa.Column('anio', sa.Integer(), nullable=False),
    sa.Column('valor', sa.Double(), nullable=True),
    sa.Column('actualizado_en', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['fuente_id'], ['fuente.id'], name=op.f('fk_dato_nacional_anual_fuente_id_fuente')),
    sa.ForeignKeyConstraint(['indicador_id'], ['indicador.id'], name=op.f('fk_dato_nacional_anual_indicador_id_indicador')),
    sa.PrimaryKeyConstraint('indicador_id', 'fuente_id', 'anio', name=op.f('pk_dato_nacional_anual'))
    )
    op.create_table('dato_nacional_mensual',
    sa.Column('indicador_id', sa.Integer(), nullable=False),
    sa.Column('fuente_id', sa.Integer(), nullable=False),
    sa.Column('periodo', sa.Date(), nullable=False),
    sa.Column('valor', sa.Double(), nullable=True),
    sa.Column('actualizado_en', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['fuente_id'], ['fuente.id'], name=op.f('fk_dato_nacional_mensual_fuente_id_fuente')),
    sa.ForeignKeyConstraint(['indicador_id'], ['indicador.id'], name=op.f('fk_dato_nacional_mensual_indicador_id_indicador')),
    sa.PrimaryKeyConstraint('indicador_id', 'fuente_id', 'periodo', name=op.f('pk_dato_nacional_mensual'))
    )
    op.create_table('indicador_serie_externa',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('indicador_id', sa.Integer(), nullable=False),
    sa.Column('fuente_id', sa.Integer(), nullable=False),
    sa.Column('codigo_externo', sa.String(length=50), nullable=False),
    sa.ForeignKeyConstraint(['fuente_id'], ['fuente.id'], name=op.f('fk_indicador_serie_externa_fuente_id_fuente')),
    sa.ForeignKeyConstraint(['indicador_id'], ['indicador.id'], name=op.f('fk_indicador_serie_externa_indicador_id_indicador'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_indicador_serie_externa')),
    sa.UniqueConstraint('fuente_id', 'codigo_externo', name=op.f('uq_indicador_serie_externa_fuente_id_codigo_externo'))
    )
    with op.batch_alter_table('indicador_serie_externa', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_indicador_serie_externa_indicador_id'), ['indicador_id'], unique=False)

    op.create_table('pais_codigo_externo',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('pais_id', sa.Integer(), nullable=False),
    sa.Column('organismo', sa.String(length=20), nullable=False),
    sa.Column('codigo', sa.String(length=30), nullable=False),
    sa.ForeignKeyConstraint(['pais_id'], ['pais.id'], name=op.f('fk_pais_codigo_externo_pais_id_pais'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pais_codigo_externo')),
    sa.UniqueConstraint('organismo', 'codigo', name=op.f('uq_pais_codigo_externo_organismo_codigo'))
    )
    with op.batch_alter_table('pais_codigo_externo', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_pais_codigo_externo_pais_id'), ['pais_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('pais_codigo_externo', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_pais_codigo_externo_pais_id'))

    op.drop_table('pais_codigo_externo')
    with op.batch_alter_table('indicador_serie_externa', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_indicador_serie_externa_indicador_id'))

    op.drop_table('indicador_serie_externa')
    op.drop_table('dato_nacional_mensual')
    op.drop_table('dato_nacional_anual')
    op.drop_table('dato_internacional_mensual')
    op.drop_table('dato_internacional_anual')
    op.drop_table('cotizacion_diaria')
    op.drop_table('pais')
    op.drop_table('indicador')
    op.drop_table('fuente')
