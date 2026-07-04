"""add mail domains and mail accounts

Revision ID: a1f3c9d20b84
Revises: e1a7c0b93f52
Create Date: 2026-07-04 17:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1f3c9d20b84'
down_revision: Union[str, Sequence[str], None] = 'e1a7c0b93f52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('mail_domains',
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('domain', sa.String(length=255), nullable=False),
    sa.Column('status', sa.Enum('PENDING', 'ACTIVE', 'DISABLED', name='maildomainstatus', native_enum=False, length=16), server_default='pending', nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_mail_domains_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_mail_domains'))
    )
    op.create_index('ix_mail_domains_domain_lower', 'mail_domains', [sa.text('lower(domain)')], unique=True)
    op.create_index('ix_mail_domains_workspace_id', 'mail_domains', ['workspace_id'], unique=False)
    op.create_table('mail_accounts',
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('domain_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('provider', sa.Enum('STALWART', name='mailprovider', native_enum=False, length=32), server_default='stalwart', nullable=False),
    sa.Column('provider_account_id', sa.String(length=255), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('display_name', sa.String(length=120), nullable=True),
    sa.Column('status', sa.Enum('ACTIVE', 'SUSPENDED', 'DISABLED', name='mailaccountstatus', native_enum=False, length=16), server_default='active', nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['domain_id'], ['mail_domains.id'], name=op.f('fk_mail_accounts_domain_id_mail_domains'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_mail_accounts_user_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_mail_accounts_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_mail_accounts')),
    sa.UniqueConstraint('provider', 'provider_account_id', name='uq_mail_accounts_provider_provider_account_id')
    )
    op.create_index('ix_mail_accounts_domain_id', 'mail_accounts', ['domain_id'], unique=False)
    op.create_index('ix_mail_accounts_email_lower', 'mail_accounts', [sa.text('lower(email)')], unique=True)
    op.create_index('ix_mail_accounts_user_id', 'mail_accounts', ['user_id'], unique=False)
    op.create_index('ix_mail_accounts_workspace_id', 'mail_accounts', ['workspace_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_mail_accounts_workspace_id', table_name='mail_accounts')
    op.drop_index('ix_mail_accounts_user_id', table_name='mail_accounts')
    op.drop_index('ix_mail_accounts_email_lower', table_name='mail_accounts')
    op.drop_index('ix_mail_accounts_domain_id', table_name='mail_accounts')
    op.drop_table('mail_accounts')
    op.drop_index('ix_mail_domains_workspace_id', table_name='mail_domains')
    op.drop_index('ix_mail_domains_domain_lower', table_name='mail_domains')
    op.drop_table('mail_domains')
