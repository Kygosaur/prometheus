"""Initial production schema."""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("users", sa.Column("username", sa.String(100), primary_key=True), sa.Column("password_hash", sa.Text(), nullable=False), sa.Column("role", sa.String(20), nullable=False), sa.Column("active", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("schedule_runs", sa.Column("id", sa.String(36), primary_key=True), sa.Column("status", sa.String(20), nullable=False), sa.Column("request_text", sa.Text(), nullable=False), sa.Column("result_json", sa.JSON(), nullable=False), sa.Column("created_by", sa.String(100), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("reviewed_by", sa.String(100)), sa.Column("reviewed_at", sa.DateTime(timezone=True)), sa.Column("review_comment", sa.Text()))
    op.create_table("audit_events", sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True), sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False), sa.Column("actor", sa.String(100), nullable=False), sa.Column("action", sa.String(100), nullable=False), sa.Column("entity_type", sa.String(50), nullable=False), sa.Column("entity_id", sa.String(100)), sa.Column("details_json", sa.JSON(), nullable=False))
    op.create_table("chat_runs", sa.Column("id", sa.String(36), primary_key=True), sa.Column("actor", sa.String(100), nullable=False), sa.Column("question", sa.Text(), nullable=False), sa.Column("intents_json", sa.JSON()), sa.Column("response_json", sa.JSON()), sa.Column("status", sa.String(20), nullable=False), sa.Column("request_id", sa.String(100)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("completed_at", sa.DateTime(timezone=True)))
    op.create_index("idx_schedule_created", "schedule_runs", ["created_at"])
    op.create_index("idx_audit_timestamp", "audit_events", ["timestamp"])


def downgrade() -> None:
    op.drop_table("chat_runs")
    op.drop_table("audit_events")
    op.drop_table("schedule_runs")
    op.drop_table("users")
