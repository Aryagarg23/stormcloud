"""Add team-shared article grades and immutable grade history."""

from alembic import op
from stormcloud import models

revision = "0002_article_grades"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    models.ArticleGrade.__table__.create(bind=bind, checkfirst=True)
    models.ArticleGradeEvent.__table__.create(bind=bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    models.ArticleGradeEvent.__table__.drop(bind=bind, checkfirst=True)
    models.ArticleGrade.__table__.drop(bind=bind, checkfirst=True)
