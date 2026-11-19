/* =====================================================================
   PORTAL ANAX  -  base de leads (UAU)
   Uma linha = uma parcela de processo + NF + fornecedor.
   Rode no SSMS, salve o resultado como Excel (com cabeçalhos) e importe
   em Portal ANAX > Leads > Importar nova base.

   Regras de lead:
     - parcela com StatusParc_proc 1 ou 3
     - pagamento previsto a partir de hoje + 4 dias
     - NF emitida ha 20 dias ou mais
     - fornecedor que NAO e empresa cadastrada no UAU (tira aportes, SCPs e consorcios do grupo)
   ===================================================================== */

SELECT
    CONCAT(p.Empresa_proc, '-', RTRIM(p.Obra_Proc), '-', p.Num_Proc, '-', p.NumParc_Proc) AS lead_id,

    /* ---------- FORNECEDOR ---------- */
    pes.cod_pes                                         AS fornecedor_codigo,
    pes.nome_pes                                        AS fornecedor_razao,
    CASE WHEN LEN(doc.d) > 11
         THEN STUFF(STUFF(STUFF(STUFF(RIGHT('00000000000000' + doc.d, 14), 13, 0, '-'), 9, 0, '/'), 6, 0, '.'), 3, 0, '.')
         ELSE STUFF(STUFF(STUFF(RIGHT('00000000000' + doc.d, 11), 10, 0, '-'), 7, 0, '.'), 4, 0, '.')
    END                                                 AS fornecedor_cnpj,
    pes.Email_pes                                       AS fornecedor_email,
    NULLIF(NULLIF(LTRIM(RTRIM(d.Contato_Proc)), ''), 'Null') AS fornecedor_contato,
    tel.telefone                                        AS fornecedor_telefone,
    ende.cidade                                         AS fornecedor_cidade,
    ende.uf                                             AS fornecedor_uf,
    CONVERT(char(10), pes.dtnasc_pes, 23)               AS fornecedor_abertura,
    CASE WHEN pes.HabilitadoRiscoSacado_pes = 1 THEN 'Sim' ELSE 'Não' END AS fornecedor_risco_sacado,

    /* ---------- PROCESSO / PARCELA ---------- */
    p.Num_Proc                                          AS processo_numero,
    emp.Desc_emp                                        AS processo_empresa,
    obr.descr_obr                                       AS processo_obra,
    CONCAT(p.NumParc_Proc, ' de ', qp.qtd)              AS processo_parcela,      -- "10 de 12": o Excel nao transforma em data
    CAST(p.StatusParc_proc AS varchar(5))               AS processo_status_cod,
    CASE WHEN p.DataAprovEmissao_proc IS NOT NULL THEN 'Aprovado p/ emissão'
         WHEN p.Conf_Proc = 'DVQ'                 THEN 'Conferido (DVQ)'
         ELSE 'Em conferência'
    END                                                 AS processo_status,
    p.Conf_Proc                                         AS processo_conferencia,
    p.UsrAprovEmissao_proc                              AS processo_aprovado_por,
    CONVERT(char(10), p.DataAprovEmissao_proc, 23)      AS processo_aprovado_em,
    p.TipoChq_Proc                                      AS processo_forma_pagamento,
    d.OrdemCompra_Proc                                  AS processo_ordem_compra,
    CASE WHEN p.EnviadoComoRiscoSacado_proc = 1 THEN 'Sim' ELSE 'Não' END AS processo_enviado_risco_sacado,
    CONVERT(char(10), p.DtVencParc_Proc, 23)            AS processo_vencimento,
    CONVERT(char(10), p.DtPagParc_Proc, 23)             AS processo_pagamento,

    CAST(p.ValorParc_Proc AS decimal(18,2))             AS processo_valor,
    FORMAT(CAST(p.ValorParc_Proc AS decimal(18,2)), 'C', 'pt-BR') AS processo_valor_fmt,
    CAST(p.ValorParc_Proc + ISNULL(p.AcrescParc_Proc, 0) - ISNULL(p.descParc_Proc, 0) AS decimal(18,2)) AS processo_valor_liquido,
    FORMAT(CAST(p.ValorParc_Proc + ISNULL(p.AcrescParc_Proc, 0) - ISNULL(p.descParc_Proc, 0) AS decimal(18,2)), 'C', 'pt-BR') AS processo_valor_liquido_fmt,

    /* ---------- NOTA FISCAL ---------- */
    p.DocFiscal_Proc                                    AS nf_numero,
    nfe.serie                                           AS nf_serie,
    CONVERT(char(10), p.DtDocFisc_Proc, 23)             AS nf_emissao,
    CAST(p.VlDocFisc_Proc AS decimal(18,2))             AS nf_valor,
    FORMAT(CAST(p.VlDocFisc_Proc AS decimal(18,2)), 'C', 'pt-BR') AS nf_valor_fmt,
    CASE WHEN nfe.chave IS NOT NULL THEN CONCAT('NFe', nfe.chave) END AS nf_chave  -- prefixo "NFe" impede o Excel de estragar os 44 digitos; o portal tira ao importar

FROM Parc_Proc p
JOIN Dados_Proc d
       ON d.Empresa_proc = p.Empresa_proc
      AND d.Obra_Proc    = p.Obra_Proc
      AND d.Num_Proc     = p.Num_Proc
LEFT JOIN pessoas  pes ON pes.cod_pes     = d.CodForn_Proc
LEFT JOIN empresas emp ON emp.Codigo_emp  = p.Empresa_proc
LEFT JOIN obras    obr ON obr.Empresa_obr = p.Empresa_proc
                      AND obr.cod_obr     = p.Obra_Proc

/* CNPJ/CPF so com digitos */
CROSS APPLY (SELECT REPLACE(REPLACE(REPLACE(LTRIM(RTRIM(CONVERT(varchar(20), pes.cpf_pes))), '.', ''), '/', ''), '-', '') AS d) doc

/* maior numero de parcela do processo (contar linhas falha quando parcelas ja pagas saem da Parc_Proc) */
OUTER APPLY (SELECT MAX(x.NumParc_Proc) AS qtd
               FROM Parc_Proc x
              WHERE x.Empresa_proc = p.Empresa_proc
                AND x.Obra_Proc    = p.Obra_Proc
                AND x.Num_Proc     = p.Num_Proc) qp

/* 1 telefone por fornecedor (sem TOP 1, cada telefone repetiria o card) */
OUTER APPLY (SELECT TOP 1
                    CONCAT(CASE WHEN NULLIF(LTRIM(RTRIM(CONVERT(varchar(5), t.ddd_tel))), '') IS NOT NULL
                                THEN CONCAT('(', LTRIM(RTRIM(CONVERT(varchar(5), t.ddd_tel))), ') ') END,
                           LTRIM(RTRIM(CONVERT(varchar(20), t.fone_tel)))) AS telefone
               FROM PesTel t
              WHERE t.pes_tel = pes.cod_pes
                AND NULLIF(LTRIM(RTRIM(CONVERT(varchar(20), t.fone_tel))), '') IS NOT NULL) tel

/* 1 endereco por fornecedor (no painel, os nomes das colunas da PesEndereco sao descobertos sozinhos) */
OUTER APPLY (SELECT TOP 1
                    e.cidade_pend AS cidade,    -- (confirmar) cidade_pend
                    e.uf_pend     AS uf         -- (confirmar) uf_pend
               FROM PesEndereco e
              WHERE e.pes_pend = pes.cod_pes) ende   -- (confirmar) pes_pend = codigo da pessoa

/* NF de entrada (mesmos criterios da sua consulta) */
OUTER APPLY (SELECT TOP 1
                    n.serie_nfe    AS serie,
                    n.chavenfe_nfe AS chave
               FROM NotasFiscaisEnt n
              WHERE n.NumNfAux_nfe     = p.DocFiscal_Proc
                AND n.Empresa_nfe      = p.Empresa_proc
                AND n.ValorTotNota_nfe = p.VlDocFisc_Proc) nfe

WHERE p.StatusParc_proc IN (1, 3)
  AND p.DtPagParc_Proc >= DATEADD(DAY, 4, CAST(GETDATE() AS date))     -- pagamento a partir de hoje + 4
  AND p.DtDocFisc_Proc <= DATEADD(DAY, -20, CAST(GETDATE() AS date))   -- NF emitida ha 20 dias ou mais

  /* tira fornecedores que sao empresas do proprio UAU (aportes, SCPs, consorcios) */
  AND NOT EXISTS (SELECT 1
                    FROM empresas e2
                   WHERE RIGHT('00000000000000' + REPLACE(REPLACE(REPLACE(LTRIM(RTRIM(CONVERT(varchar(20), e2.CGC_emp))), '.', ''), '/', ''), '-', ''), 14)
                       = RIGHT('00000000000000' + doc.d, 14))

  -- teste com um processo so:
  -- AND p.Empresa_proc = 696 AND p.Obra_Proc = '696' AND p.Num_Proc = 628
