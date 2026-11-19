/* Usuário do SQL Server para o painel (rodar uma vez como administrador; troque a senha).
   Lê o UAU e grava só no banco do painel. */

CREATE LOGIN anax_painel WITH PASSWORD = 'troque-esta-senha', CHECK_POLICY = ON;

-- banco do painel, separado do UAU (recomendado)
IF DB_ID('ANAX') IS NULL CREATE DATABASE ANAX;
GO

USE UAU;
CREATE USER anax_painel FOR LOGIN anax_painel;
ALTER ROLE db_datareader ADD MEMBER anax_painel;      -- só leitura no UAU
GO

USE ANAX;
CREATE USER anax_painel FOR LOGIN anax_painel;
ALTER ROLE db_datareader ADD MEMBER anax_painel;
ALTER ROLE db_datawriter ADD MEMBER anax_painel;
GRANT CREATE TABLE TO anax_painel;                     -- para o painel criar as próprias tabelas na primeira vez
GRANT ALTER ON SCHEMA::dbo TO anax_painel;
GO
