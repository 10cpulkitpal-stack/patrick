"""Create or upgrade the Patrick schema and add query indexes."""

from alembic import op
import sqlalchemy as sa

from backend.models import Base

revision = "20261006_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # create_all safely creates tables missing from older deployments. Existing
    # tables are then upgraded column-by-column to avoid losing user data.
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)
    inspector = sa.inspect(bind)
    existing = {table: {column["name"] for column in inspector.get_columns(table)}
                for table in inspector.get_table_names()}

    additions = {
        "users": [
            sa.Column("display_name", sa.String(120)),
            sa.Column("auth_provider", sa.String(20), nullable=False, server_default="password"),
            sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("preferred_provider", sa.String(20)),
            sa.Column("preferred_model", sa.String(160)),
        ],
        "messages": [
            sa.Column("attachment_type", sa.String(20)),
            sa.Column("attachment_name", sa.String(255)),
            sa.Column("attachment_data", sa.Text()),
            sa.Column("attachment_truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
        ],
    }
    for table, columns in additions.items():
        for column in columns:
            if column.name not in existing.get(table, set()):
                op.add_column(table, column)

    inspector = sa.inspect(bind)
    indexes = {table: {index["name"] for index in inspector.get_indexes(table)}
               for table in inspector.get_table_names()}
    for table in Base.metadata.sorted_tables:
        for index in table.indexes:
            if index.name not in indexes.get(table.name, set()):
                op.create_index(index.name, table.name,
                                [column.name for column in index.columns], unique=index.unique)


def downgrade():
    # The baseline migration is intentionally non-destructive: existing data
    # should never be dropped automatically during a rollback.
    pass
