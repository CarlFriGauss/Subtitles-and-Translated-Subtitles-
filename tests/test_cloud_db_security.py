"""SEC-5: SubGen tables must not be readable through Supabase's Data API."""

import pytest

from subgen_cloud.db_security import lockdown_statements

TABLES = ["cloud_jobs", "cloud_users"]


def test_enables_rls_and_revokes_supabase_roles():
    statements = lockdown_statements(TABLES, {"anon", "authenticated", "postgres"})
    assert 'ALTER TABLE "cloud_jobs" ENABLE ROW LEVEL SECURITY' in statements
    assert 'REVOKE ALL ON TABLE "cloud_jobs" FROM anon, authenticated' in statements
    assert 'ALTER TABLE "cloud_users" ENABLE ROW LEVEL SECURITY' in statements


def test_plain_postgres_without_supabase_roles_only_enables_rls():
    statements = lockdown_statements(TABLES, set())
    assert all(statement.startswith("ALTER TABLE") for statement in statements)


def test_rejects_unexpected_identifiers():
    with pytest.raises(ValueError):
        lockdown_statements(['cloud_jobs"; DROP TABLE x; --'], {"anon"})


def test_every_model_table_is_covered():
    db = pytest.importorskip("subgen_cloud.db", reason="cloud extras not installed")
    statements = lockdown_statements(db.Base.metadata.tables.keys(), {"anon"})
    for table in db.Base.metadata.tables:
        assert f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY' in statements
