-- Cria o database `vooai` no Postgres FourDev (uma vez).
-- Rodar conectado em `postgres` ou `sdr` com usuário que tenha CREATEDB:
--   docker exec -i sdr_postgres psql -U sdr -d postgres < pipelines/sql/01_create_database.sql
--
-- Depois aplique o schema (a API também cria tabelas no startup via init_db):
--   docker exec -i sdr_postgres psql -U sdr -d vooai < pipelines/sql/02_schema.sql

SELECT 'Criando database vooai (ignore erro se já existir)...' AS info;

CREATE DATABASE vooai OWNER CURRENT_USER;
