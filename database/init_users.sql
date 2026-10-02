-- ============================================================================
-- Least-Privilege Database Role Management (PostgreSQL 16)
-- ============================================================================

-- Create Users with passwords (can be overridden via ENV vars)
-- Default roles created for reference or production least-privilege configuration
DO $$
DECLARE
    v_admin_pwd TEXT := COALESCE(NULLIF(current_setting('custom.lib_admin_password', true), ''), 'ChangeMe_AdminPass!');
    v_app_pwd TEXT := COALESCE(NULLIF(current_setting('custom.lib_app_password', true), ''), 'ChangeMe_AppServicePass!');
    v_readonly_pwd TEXT := COALESCE(NULLIF(current_setting('custom.lib_readonly_password', true), ''), 'ChangeMe_ReadOnlyPass!');
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'lib_admin') THEN
        EXECUTE format('CREATE ROLE lib_admin WITH LOGIN PASSWORD %L;', v_admin_pwd);
    END IF;

    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'lib_app') THEN
        EXECUTE format('CREATE ROLE lib_app WITH LOGIN PASSWORD %L;', v_app_pwd);
    END IF;

    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'lib_readonly') THEN
        EXECUTE format('CREATE ROLE lib_readonly WITH LOGIN PASSWORD %L;', v_readonly_pwd);
    END IF;
END $$;

-- Grants for lib_admin (DBA Admin)
GRANT ALL PRIVILEGES ON DATABASE library_db TO lib_admin;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO lib_admin;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO lib_admin;
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public TO lib_admin;

-- Grants for lib_app (Application DML + Procedure execution)
GRANT CONNECT ON DATABASE library_db TO lib_app;
GRANT USAGE ON SCHEMA public TO lib_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO lib_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO lib_app;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO lib_app;

-- Grants for lib_readonly (Data Pipeline Worker / Analytics / Reporting)
GRANT CONNECT ON DATABASE library_db TO lib_readonly;
GRANT USAGE ON SCHEMA public TO lib_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO lib_readonly;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO lib_readonly;
-- Explicitly revoke write permissions for read-only analytics role
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA public FROM lib_readonly;
