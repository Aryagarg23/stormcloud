"""__message__

Revision ID: __up_revision__
Revises: __down_revision__"""
from alembic import op
import sqlalchemy as sa
__imports__

revision = __repr__(up_revision)
down_revision = __repr__(down_revision)
branch_labels = __repr__(branch_labels)
depends_on = __repr__(depends_on)

def upgrade():
    __upgrades__

def downgrade():
    __downgrades__
