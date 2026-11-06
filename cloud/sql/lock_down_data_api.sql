-- Keep SubGen's tables out of Supabase's public Data API (PostgREST).
--
-- SubGen's API and worker run the same statements automatically on every start
-- (subgen_cloud.db.lock_down_data_api). Run this file manually in the Supabase
-- SQL editor for a deployment that existed before that change, then verify with
-- the query at the end.

ALTER TABLE cloud_users                ENABLE ROW LEVEL SECURITY;
ALTER TABLE cloud_user_settings        ENABLE ROW LEVEL SECURITY;
ALTER TABLE cloud_provider_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE cloud_videos               ENABLE ROW LEVEL SECURITY;
ALTER TABLE cloud_uploads              ENABLE ROW LEVEL SECURITY;
ALTER TABLE cloud_jobs                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE cloud_artifacts            ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE cloud_users, cloud_user_settings, cloud_provider_credentials,
    cloud_videos, cloud_uploads, cloud_jobs, cloud_artifacts
    FROM anon, authenticated;

-- Verify: every row must show rowsecurity = true and no anon/authenticated grants.
SELECT c.relname AS table_name, c.relrowsecurity AS rowsecurity,
       (SELECT string_agg(DISTINCT grantee || ':' || privilege_type, ', ')
          FROM information_schema.role_table_grants g
         WHERE g.table_name = c.relname AND g.grantee IN ('anon', 'authenticated')) AS api_grants
  FROM pg_class c
 WHERE c.relname LIKE 'cloud\_%' AND c.relkind = 'r'
 ORDER BY 1;
