# Painel de Leads ANAX (Streamlit)

Cada lead é um fornecedor com processos a receber da LCM, vindos do UAU. A tela mostra os processos (o que a LCM paga) e, dentro de cada um, as parcelas; a proposta e a margem são por parcela. A equipe acompanha a etapa, guarda documentos e anotações, corrige dados e registra a margem negociada. A aba Minhas operações soma o que está em negociação.

## Estrutura

```
painel_leads_anax/
├── app.py                 # Streamlit: login, consulta o UAU, trata o que a tela envia
├── login.py               # login de um usuário (senha com hash, bloqueio por tentativas, sessão de 12 h)
├── gerar_senha.py         # gera o hash da senha para os Secrets
├── banco.py               # conexão com o SQL Server (pyodbc com ODBC 18/17, ou pymssql) e teste de conexão
├── firebase.py            # grava etapas, propostas, notas, taxas e documentos no Firestore
├── firestore.rules        # regras do Firestore (fecha o banco para acesso de fora)
├── armazenamento.py       # alternativa: gravar no SQL Server ([app] salvar = "sql")
├── resumo.py              # resumo executivo do dia em PDF e por e-mail
├── leads.sql              # consulta da base de leads (UAU)
├── tabelas_anax.sql       # tabelas do painel (o app cria sozinho se tiver permissão)
├── permissoes_sql.sql     # usuário do SQL Server para o painel (a TI roda uma vez)
├── requirements.txt
├── .gitignore             # deixa o secrets.toml e os dados locais fora do GitHub
├── assets/                # logo e fontes (Jost e DM Sans, licença OFL)
├── .streamlit/config.toml
├── .streamlit/secrets.toml.exemplo
└── componentes/leads/     # a tela, em HTML, CSS e JS (sem build)
```

## Onde o painel grava: Firebase (Firestore)

O SQL Server só é **lido** (o UAU). Etapas, propostas, notas, taxas e documentos ficam no **Firestore** do projeto `anaxconsultoria`. O servidor do painel grava com a conta de serviço do projeto; o login continua sendo o usuário e a senha dos Secrets.

Para ligar (uma vez, no console do Firebase):
1. **Firestore Database** > **Criar banco de dados** > modo de produção > local `southamerica-east1 (São Paulo)`.
2. **Firestore Database** > **Regras**: cole o conteúdo do `firestore.rules` e clique em **Publicar**. As regras fecham o banco para qualquer acesso de fora; só o painel, pelo servidor, lê e grava.
3. **Configurações do projeto** (engrenagem) > **Contas de serviço** > **Gerar nova chave privada**. Baixa um arquivo `.json`.
4. Nos Secrets do Streamlit, seção `[firebase_conta]`: cole o conteúdo inteiro desse arquivo entre as aspas triplas (veja o `secrets.toml.exemplo`). Guarde o arquivo num lugar seguro e não suba para o GitHub: com ele, qualquer um grava no projeto.

Como fica no Firestore: `leads/{cnpj}`, `notas/{id}`, `propostas/{lead_id}`, `config/taxas` e `docs/{id}`. Os documentos são compactados (fotos viram JPEG de até 2000 px; o resto, zlib) e guardados em base64 em `docs/{id}/partes/`, em pedaços de até 900 mil caracteres (cada documento do Firestore aceita até 1 MiB).

Sem a seção `[firebase_conta]`, ou enquanto o Firestore não estiver criado, o painel avisa e funciona só consultando, sem gravar.

O plano gratuito do Firebase (Spark) cobre o uso de uma equipe pequena: 1 GiB guardado, 50 mil leituras e 20 mil gravações por dia.

## Publicar no Streamlit Cloud

1. **GitHub:** crie um repositório **privado** (ex.: `anax-painel-leads`) e suba o conteúdo desta pasta (Add file > Upload files). O `.gitignore` já deixa o `secrets.toml` de fora; confira que ele não foi junto.
2. **Senha do login:** escolha a senha e coloque em `[login] senha` nos Secrets (passo 4). Os Secrets do Streamlit Cloud não vão para o GitHub. Se quiser guardar só o hash, rode `python gerar_senha.py` (só precisa do Python) e use `senha_hash` e `chave_sessao` no lugar de `senha`.
3. **Criar o app:** em share.streamlit.io, crie um app a partir do GitHub, escolhendo o repositório, a branch `main` e o arquivo `app.py`. Nas configurações avançadas, escolha Python 3.12.
4. **Secrets:** nas configurações avançadas, campo *Secrets* (ou depois em *Settings* > *Secrets* do app), cole o conteúdo do `.streamlit/secrets.toml.exemplo` preenchido: `[login]` com usuário e senha, `[sql]` com o endereço que a TI liberar. Depois de salvar, o app reinicia sozinho em cerca de 1 minuto.
5. **Quem pode abrir:** nas opções de compartilhamento do app, deixe-o privado e convide só os e-mails da equipe. O login do painel é uma segunda barreira.
6. **Conferir:** entre no painel, abra **Base de dados** > **Testar conexão**. O teste mostra se a leitura do UAU e a gravação no banco do painel funcionaram e qual o IP de saída do app.

## O que a TI precisa fazer no SQL Server

O Streamlit Cloud roda na internet: ele não enxerga endereços internos (10.x, 192.168.x). Para o painel ler o UAU de verdade:

1. **Endereço público:** expor o SQL Server num host ou IP público, numa porta (1433 ou outra), com criptografia ligada.
2. **Firewall:** liberar essa porta **só** para os IPs do Streamlit Cloud (lista oficial em docs.streamlit.io > Deploy > Community Cloud > Status and limitations). Hoje são: 35.230.127.150, 35.203.151.101, 34.19.100.134, 34.83.176.217, 35.230.58.211, 35.203.187.165, 35.185.209.55, 34.127.88.74, 34.127.0.121, 35.230.78.192, 35.247.110.67, 35.197.92.111, 34.168.247.159, 35.230.56.30, 34.127.33.101, 35.227.190.87, 35.199.156.97, 34.82.135.155. O Streamlit avisa que podem mudar sem aviso: se o painel parar de conectar, o botão **Testar conexão** mostra o IP de saída atual para incluir.
3. **Usuário de leitura:** um login do SQL Server com **só leitura** no banco do UAU (`db_datareader`) basta para o modo consulta. Quando a gravação for ligada, o `permissoes_sql.sql` cria o banco `ANAX` separado onde o painel grava; nada é escrito nas tabelas do UAU.

Enquanto o SQL Server não estiver acessível, o painel abre, avisa que não conseguiu consultar o UAU (com o motivo) e aceita a planilha exportada no lugar.

## Rodar na sua máquina

1. `pip install -r requirements.txt`
2. Copie `.streamlit/secrets.toml.exemplo` para `.streamlit/secrets.toml` e preencha (`[login]` é obrigatório; sem `[sql]`, grava em `dados/anax_leads.sqlite`).
3. `streamlit run app.py`. Para testar só a conexão: `python banco.py`.

## Login

Um usuário só, definido em `[login]` nos Secrets (`usuario` e `senha`, ou `senha_hash` gerado pelo `gerar_senha.py`). A senha nunca fica no código. Depois de 5 senhas erradas o login trava por 5 minutos (dobra a cada novo bloqueio). O navegador fica conectado por 12 horas (`horas`); **Sair** desconecta. Para trocar a senha, atualize os Secrets: todos os navegadores são desconectados.

## Usando o painel

Ao entrar, o painel consulta o UAU sozinho (o resultado fica guardado por 15 minutos para todos os acessos). Na barra do topo:
- **Base de dados:** consulta o UAU de novo, envia uma planilha ou testa a conexão.
- **Taxas:** a tabela de taxas da antecipação, salva para toda a equipe (tabela `anax_config`).
- **Seu nome** e **Sair:** o nome vem do login e aparece nas notas, propostas e no resumo.
- **Enviar resumo do dia:** o resumo executivo em PDF.

## A tela

- **Leads:** lista de fornecedores à esquerda, com busca, filtros, etapa e ordenação. O detalhe fica à direita. A divisória entre os dois pode ser arrastada (ou ajustada com as setas do teclado; duplo clique volta ao padrão), e a largura fica guardada no navegador:
  - **Funil de etapas:** Novo, Contatado, Negociação, Cadastro e Ativo, mais "Marcar como perdido". Mover para Negociação abre a proposta, agrupada por processo: você marca as parcelas e informa a margem (% a.m.) de cada uma. Quando só há uma parcela no prazo, ela já vem marcada.
  - **Resumo:** um bloco por processo (número, empresa, obra, valor, NF) com as parcelas dentro: valor, pagamento, líquido, margem (negociada ou da tabela), deságio e a situação da proposta (Propor, Alterar margem, Aceita, Recusada, Reabrir). Mais contato rápido e a última anotação.
  - **Processos:** cada processo com conferência, forma de pagamento, ordem de compra, NFs (série, emissão, valor, chave) e vencimento e pagamento de cada parcela.
  - **Documentos:** envio por arraste ou seleção (até 15 MB), download e exclusão.
  - **Notas:** anotações livres, mais o histórico automático de etapa, margem e dados.
  - **Dados:** contato, telefone, e-mail, cidade, UF e responsável. O que você edita fica no painel; o cadastro do UAU não muda.
- **Perfil ideal:** nota de 0 a 100 para cada fornecedor, com a taxa da tabela, o valor aprovado no prazo, a receita potencial e os motivos (✓ a favor, ✕ contra). Critérios e pesos: prazo até o pagamento entre 15 e 90 dias (25), de R$ 20 mil a R$ 500 mil aprovados no prazo (20), pequena ou média empresa (15), setor que usa muito capital de giro (15), recorrência com a LCM (10), espera longa entre NF e pagamento (5), empresa de 1 a 10 anos (5) e telefone no cadastro (5). Perfil ideal: 75+ com prazo e valor na faixa; bom potencial: 55 a 74. Ficam fora: grupo LCM, pessoa física, órgão público/tributo, banco/seguradora, consórcio/SCP, recuperação judicial e concessionária. As faixas de prazo e valor são editáveis na tela. Na aba Leads, cada fornecedor mostra a nota e a taxa, e dá para filtrar e ordenar por perfil.
- **Minhas operações:** uma linha por parcela com proposta, identificada pelo nº do processo e a obra, filtrando Em negociação, Aceitas, Recusadas ou Todas. Mostra valor, margem, deságio, líquido e quem propôs, com os botões Aceita, Recusada e Reabrir.

## Como o Python e a tela conversam

A tela envia eventos `{id, acao, ...}` e o `app.py` grava e recarrega:
`etapa`, `proposta` (parcelas e margem de cada uma), `proposta_status` (aceita, recusada, reabrir ou remover), `dados`, `nota_add`, `nota_del`, `doc_add`, `doc_del`, `doc_baixar`.

## Resumo do dia em PDF

O botão **Enviar resumo do dia** (no topo do painel) abre a janela do resumo executivo, feito para gestores e donos:
escolha o **dia** (hoje ou outro) e se os números do dia são da **equipe toda** ou **só seus**. A prévia mostra o PDF.

O PDF (uma página A4) traz:
- **O dia:** valor proposto (parcelas e fornecedores trabalhados), receita prevista (deságio), aceites e margem média contra a tabela.
- **A carteira hoje:** em negociação, aceitas no total, conversão (valor aceito ÷ valor decidido) e potencial da base (parcelas aprovadas no prazo, fora do grupo, e quanto já está em proposta).
- **Gráficos:** valor proposto por dia nos últimos 14 dias, fornecedores por etapa, carteira por situação e as 5 maiores negociações em aberto.
- **Equipe no dia:** parcelas, valor proposto, receita e aceites por pessoa.

Botões:
- **Baixar PDF:** `resumo-anax-AAAA-MM-DD.pdf`.
- **Abrir no meu e-mail:** abre o seu programa de e-mail com assunto e os números principais; anexe o PDF baixado.
- **Enviar com o PDF:** aparece quando a seção `[email]` do `.streamlit/secrets.toml` está preenchida (veja o `secrets.toml.exemplo`). Envia direto, com os números no corpo e o PDF em anexo.
