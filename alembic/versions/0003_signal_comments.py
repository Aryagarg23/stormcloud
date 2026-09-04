"""Add team-shared signal comments."""

from alembic import op

from stormcloud import models

revision = "0003_signal_comments"
down_revision = "0002_article_grades"
branch_labels = None
depends_on = None


def upgrade():
    models.SignalComment.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade():
    models.SignalComment.__table__.drop(bind=op.get_bind(), checkfirst=True)
