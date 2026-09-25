\set ON_ERROR_STOP on
DO $$ BEGIN
 IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='nachtlabs_migrator') THEN CREATE ROLE nachtlabs_migrator LOGIN; END IF;
 IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='nachtlabs_api') THEN CREATE ROLE nachtlabs_api LOGIN; END IF;
 IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='nachtlabs_executor') THEN CREATE ROLE nachtlabs_executor LOGIN; END IF;
 IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='nachtlabs_worker') THEN CREATE ROLE nachtlabs_worker LOGIN; END IF;
END $$;
SELECT 'CREATE DATABASE nachtlabs OWNER nachtlabs_migrator' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname='nachtlabs')\gexec
\connect nachtlabs
REVOKE ALL ON DATABASE nachtlabs FROM PUBLIC;
GRANT CONNECT ON DATABASE nachtlabs TO nachtlabs_api,nachtlabs_worker,nachtlabs_executor,nachtlabs_migrator;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO nachtlabs_api,nachtlabs_worker,nachtlabs_executor;
