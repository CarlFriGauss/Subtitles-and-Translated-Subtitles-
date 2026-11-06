"""Keep SubGen's tables out of Supabase's public Data API.

Supabase serves every table in the ``public`` schema through PostgREST, and new
tables are granted to the ``anon`` and ``authenticated`` roles. The anon key is
public by design (SubGen even returns it from /v1/public-config), so without
these statements anyone could read or modify every user's jobs, transcripts,
e-mail addresses and credential ciphertexts at
``https://<project>.supabase.co/rest/v1/cloud_jobs``.

SubGen itself connects as the table owner, which bypasses row-level security,
so enabling RLS with no policies blocks the Data API without affecting the app.
"""

import re

SUPABASE_API_ROLES = ("anon", "authenticated")
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _quoted(identifier):
    if not _IDENTIFIER.match(identifier):
        raise ValueError(f"Unexpected SQL identifier: {identifier!r}")
    return f'"{identifier}"'


def lockdown_statements(table_names, existing_roles):
    """SQL that enables RLS on each table and revokes the Data API roles' access.

    ``existing_roles`` limits the REVOKE to roles present in this database, so
    the same code runs on plain PostgreSQL (no Supabase roles) and on Supabase.
    """
    roles = [role for role in SUPABASE_API_ROLES if role in set(existing_roles)]
    statements = []
    for table in sorted(table_names):
        quoted = _quoted(table)
        statements.append(f"ALTER TABLE {quoted} ENABLE ROW LEVEL SECURITY")
        if roles:
            statements.append(f"REVOKE ALL ON TABLE {quoted} FROM {', '.join(roles)}")
    return statements
