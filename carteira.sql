/* Rodar UMA vez no banco. Guarda o relacionamento de cada fornecedor com a ANAX,
   fora das tabelas do UAU. O painel lê e grava aqui. */
IF OBJECT_ID('dbo.AnaxCarteiraLead') IS NULL
CREATE TABLE dbo.AnaxCarteiraLead (
    cnpj           varchar(14)  NOT NULL PRIMARY KEY,   -- só dígitos
    nome           varchar(200) NULL,
    status         varchar(20)  NOT NULL,               -- prospect, contatado, negociando, cadastro, ativo, inativo
    email          varchar(200) NULL,
    telefone       varchar(30)  NULL,
    atualizado_em  datetime2(0) NOT NULL DEFAULT SYSDATETIME(),
    atualizado_por varchar(80)  NULL
);

/* Para tirar um fornecedor da carteira:
   DELETE FROM dbo.AnaxCarteiraLead WHERE cnpj = '00000000000000'; */
