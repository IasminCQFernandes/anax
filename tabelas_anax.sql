/* Tabelas do painel. O app cria sozinho se o usuário do SQL tiver permissão (CREATE TABLE); se não, rode este script uma vez
   no banco do painel (de preferência um banco separado do UAU, ex.: ANAX). */

IF OBJECT_ID('dbo.anax_lead') IS NULL
CREATE TABLE dbo.anax_lead (
    cnpj            varchar(14)    NOT NULL PRIMARY KEY,   -- só dígitos
    nome            varchar(200)   NULL,
    etapa           varchar(20)    NOT NULL DEFAULT 'novo', -- novo, contatado, negociando, cadastro, ativo, perdido
    margem          decimal(9,4)   NULL,                    -- % ao mês negociada
    margem_em       varchar(19)    NULL,
    margem_por      varchar(80)    NULL,
    contato         varchar(120)   NULL,                    -- dados editados no painel (vazio = usa o do UAU)
    telefone        varchar(30)    NULL,
    email           varchar(200)   NULL,
    cidade          varchar(80)    NULL,
    uf              varchar(2)     NULL,
    responsavel     varchar(80)    NULL,
    atualizado_em   varchar(19)    NULL,
    atualizado_por  varchar(80)    NULL
);

IF OBJECT_ID('dbo.anax_lead_nota') IS NULL
BEGIN
    CREATE TABLE dbo.anax_lead_nota (
        id         varchar(40)    NOT NULL PRIMARY KEY,
        cnpj       varchar(14)    NOT NULL,
        tipo       varchar(10)    NOT NULL DEFAULT 'nota',  -- nota | sistema (mudança de etapa, margem, dados)
        texto      nvarchar(4000) NOT NULL,
        autor      varchar(80)    NULL,
        criado_em  varchar(19)    NOT NULL
    );
    CREATE INDEX ix_anax_lead_nota_cnpj ON dbo.anax_lead_nota (cnpj);
END

IF OBJECT_ID('dbo.anax_lead_doc') IS NULL
BEGIN
    CREATE TABLE dbo.anax_lead_doc (
        id          varchar(40)     NOT NULL PRIMARY KEY,
        cnpj        varchar(14)     NOT NULL,
        nome        nvarchar(255)   NOT NULL,
        tipo        varchar(120)    NULL,
        tamanho     int             NULL,
        conteudo    varbinary(max)  NOT NULL,
        autor       varchar(80)     NULL,
        enviado_em  varchar(19)     NOT NULL
    );
    CREATE INDEX ix_anax_lead_doc_cnpj ON dbo.anax_lead_doc (cnpj);
END

IF OBJECT_ID('dbo.anax_proposta') IS NULL
BEGIN
    CREATE TABLE dbo.anax_proposta (               -- uma proposta por parcela
        lead_id         varchar(80)    NOT NULL PRIMARY KEY,   -- empresa-obra-processo-parcela (lead_id do leads.sql)
        cnpj            varchar(14)    NOT NULL,
        margem          decimal(9,4)   NOT NULL,               -- % ao mês negociada
        status          varchar(12)    NOT NULL,               -- negociando, aceita, recusada
        valor           decimal(18,2)  NULL,                   -- valor da parcela no momento da proposta
        pagamento       varchar(10)    NULL,                   -- pagamento previsto no momento da proposta
        obs             nvarchar(1000) NULL,
        criado_em       varchar(19)    NULL,
        criado_por      varchar(80)    NULL,
        atualizado_em   varchar(19)    NULL,
        atualizado_por  varchar(80)    NULL
    );
    CREATE INDEX ix_anax_proposta_cnpj ON dbo.anax_proposta (cnpj);
END

IF OBJECT_ID('dbo.anax_config') IS NULL
CREATE TABLE dbo.anax_config (                     -- configurações da equipe (ex.: tabela de taxas), em JSON
    chave           varchar(40)     NOT NULL PRIMARY KEY,
    valor           nvarchar(max)   NOT NULL,
    atualizado_em   varchar(19)     NULL,
    atualizado_por  varchar(80)     NULL
);
