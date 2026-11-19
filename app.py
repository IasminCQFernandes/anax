"""
Painel de Leads ANAX · Streamlit + componente HTML/CSS/JS

Rodar:
    pip install -r requirements.txt
    streamlit run app.py

Configuração em .streamlit/secrets.toml (no Streamlit Cloud: Settings > Secrets):
  [login]  usuário único do painel (veja login.py e gerar_senha.py)
  [sql]    conexão com o SQL Server (veja banco.py)
  [email]  envio do resumo do dia (veja resumo.py)
"""
import datetime as dt
import base64
import getpass
import hashlib
import io
import json
import math
import os
import re
import urllib.parse
from decimal import Decimal
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import login
import resumo
from firebase import ArmazenamentoFirebase, ErroFirebase, Sessao, agora_br, conectar_servico
from armazenamento import Armazenamento, SomenteLeitura
from banco import Banco, diagnosticar, explicar, ler_config, resumo_cfg

BASE = Path(__file__).resolve().parent
_icone = BASE / "assets" / "logo_claro.png"
st.set_page_config(page_title="Leads · ANAX", page_icon=str(_icone) if _icone.exists() else None, layout="wide", initial_sidebar_state="collapsed")

_leads = components.declare_component("anax_leads", path=str(BASE / "componentes" / "leads"))

# Colunas que o componente usa (mesmos nomes do leads.sql)
COLS = ["lead_id", "fornecedor_codigo", "fornecedor_razao", "fornecedor_cnpj", "fornecedor_email", "fornecedor_contato",
        "fornecedor_telefone", "fornecedor_cidade", "fornecedor_uf", "fornecedor_abertura", "fornecedor_risco_sacado",
        "processo_numero", "processo_empresa", "processo_obra", "processo_parcela", "processo_status_cod", "processo_status",
        "processo_conferencia", "processo_aprovado_por", "processo_aprovado_em", "processo_forma_pagamento",
        "processo_ordem_compra", "processo_enviado_risco_sacado", "processo_vencimento", "processo_pagamento",
        "processo_valor", "processo_valor_liquido", "nf_numero", "nf_serie", "nf_emissao", "nf_valor", "nf_chave"]
OBRIG = ["lead_id", "fornecedor_razao", "fornecedor_cnpj", "processo_numero", "processo_pagamento", "processo_valor"]
DATAS = {"processo_vencimento", "processo_pagamento", "nf_emissao", "fornecedor_abertura", "processo_aprovado_em"}
NUMS = {"processo_valor", "processo_valor_liquido", "nf_valor"}
INTS = {"processo_numero", "processo_ordem_compra", "fornecedor_codigo"}
STATUS_VALIDOS = {"prospect", "contatado", "negociando", "cadastro", "ativo", "inativo"}
EXCEL_ZERO = dt.date(1899, 12, 30)


# ---------------------------------------------------------------- conexão
def sql_cfg() -> dict:
    try:
        return ler_config(st.secrets)
    except Exception:  # sem secrets.toml
        return {}


def _assinatura(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()[:16]


@st.cache_resource(show_spinner=False)
def banco_uau(_cfg: dict, assinatura: str) -> Banco:
    return Banco(_cfg, _cfg.get("banco"))


# ---------------------------------------------------------------- normalização (igual ao importador do Portal ANAX)
def _vazio(v):
    return v is None or (isinstance(v, float) and math.isnan(v)) or (isinstance(v, str) and v.strip().upper() in ("", "NULL"))


def _digitos(v) -> str:
    return re.sub(r"\D", "", "" if v is None else str(v))


def _data(v):
    if _vazio(v):
        return None
    if isinstance(v, (pd.Timestamp, dt.datetime)):
        return v.date().isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, (int, float, Decimal)):  # número de série do Excel
        return (EXCEL_ZERO + dt.timedelta(days=round(float(v)))).isoformat()
    s = str(v).strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return m.group(0)
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}" if m else None


def _num(v):
    if _vazio(v):
        return None
    if isinstance(v, (int, float, Decimal)):
        return float(v)
    s = re.sub(r"R\$|\s", "", str(v))
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _parcela(v):
    if _vazio(v):
        return None
    if isinstance(v, (pd.Timestamp, dt.datetime, dt.date)):  # o Excel transforma "10/2" em data
        return f"{v.day}/{v.month}"
    if isinstance(v, (int, float)) and v > 20000:
        d = EXCEL_ZERO + dt.timedelta(days=round(v))
        return f"{d.day}/{d.month}"
    s = str(v).strip()
    m = re.match(r"^(\d+)\s*de\s*(\d+)$", s, re.I)
    return f"{m.group(1)}/{m.group(2)}" if m else s


def _doc(v):
    d = _digitos(v)
    if not d:
        return ""
    if len(d) > 11:
        d = d.zfill(14)
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    d = d.zfill(11)
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"


def _chave(v):
    if _vazio(v) or isinstance(v, (int, float)):  # número = o Excel já estragou a chave
        return None
    d = _digitos(v)
    return d if len(d) in (44, 50) else None  # 44 = NF-e/CT-e, 50 = NFS-e nacional


def _telefone(v):
    if _vazio(v):
        return None
    d = _digitos(v)
    if len(d) >= 12 and d.startswith("55"):
        d = d[2:]
    if len(d) == 11:
        return f"({d[:2]}) {d[2:7]}-{d[7:]}"
    if len(d) == 10:
        return f"({d[:2]}) {d[2:6]}-{d[6:]}"
    return str(v).strip() if len(d) >= 8 else None


def _texto(v):
    if _vazio(v):
        return None
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def normalizar(registros: list[dict]) -> dict:
    if not registros:
        raise ValueError("A consulta não trouxe nenhuma linha.")
    falta = [c for c in OBRIG if c not in registros[0]]
    if falta:
        raise ValueError("Faltam colunas do leads.sql: " + ", ".join(falta))
    linhas, vistos = [], set()
    for r in registros:
        out = []
        for c in COLS:
            v = r.get(c)
            if c in DATAS:
                v = _data(v)
            elif c in NUMS:
                v = _num(v)
            elif c in INTS:
                n = _num(v)
                v = int(n) if n is not None and float(n).is_integer() else n
            elif c == "processo_parcela":
                v = _parcela(v)
            elif c == "fornecedor_cnpj":
                v = _doc(v)
            elif c == "nf_chave":
                v = _chave(v)
            elif c == "fornecedor_telefone":
                v = _telefone(v)
            else:
                v = _texto(v)
            out.append(v)
        if out[0] and out[0] not in vistos:
            vistos.add(out[0])
            linhas.append(out)
    corpo = json.dumps(linhas, ensure_ascii=False, separators=(",", ":"))
    return {"versao": hashlib.sha1(corpo.encode()).hexdigest()[:12], "cols": COLS, "rows": linhas}


# ---------------------------------------------------------------- fontes de dados
def _colunas(banco: Banco, tabela: str) -> list[str]:
    return [r["COLUMN_NAME"] for r in banco.consultar(
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION", tabela)]


def _acha(cols: list[str], preferidas: tuple, filtro=None):
    baixo = {c.lower(): c for c in cols}
    for nome in preferidas:
        if nome in baixo:
            return baixo[nome]
    return next((c for c in cols if filtro and filtro(c.lower())), None)


def adaptar_sql(sql: str, banco: Banco) -> tuple[str, str]:
    """O endereço (cidade/UF) fica na PesEndereco, cujos nomes de coluna variam entre versões do UAU.
    Descobre as colunas certas no próprio banco; se não achar, segue sem cidade/UF em vez de falhar."""
    cols = _colunas(banco, "PesEndereco")
    pes = _acha(cols, ("pes_pend", "codpes_pend", "cod_pes_pend", "codpessoa_pend", "pessoa_pend"),
                lambda c: c.endswith("_pend") and "pes" in c and not re.search(r"cidade|uf|tipo|end|cep|num|compl|bairro", c))
    cid = _acha(cols, ("cidade_pend", "nomecidade_pend", "cid_pend", "municipio_pend"), lambda c: "cidade" in c or "munic" in c)
    uf = _acha(cols, ("uf_pend", "estado_pend", "siglauf_pend"), lambda c: c.startswith("uf") or c.endswith("uf_pend"))
    bloco = re.search(r"OUTER APPLY \(SELECT TOP 1\s+e\.cidade_pend.*?\) ende", sql, re.S)
    if pes and (cid or uf):
        sql = (sql.replace("e.pes_pend", f"e.[{pes}]")
                  .replace("e.cidade_pend", f"e.[{cid}]" if cid else "CAST(NULL AS varchar(80))")
                  .replace("e.uf_pend", f"e.[{uf}]" if uf else "CAST(NULL AS varchar(2))"))
        info = f"Endereço: PesEndereco.{pes} → pessoa, cidade em {cid or '—'}, UF em {uf or '—'}."
    else:
        if bloco:
            sql = sql.replace(bloco.group(0), "OUTER APPLY (SELECT CAST(NULL AS varchar(80)) AS cidade, CAST(NULL AS varchar(2)) AS uf) ende")
        info = ("Endereço: não achei na PesEndereco a coluna que liga à pessoa; cidade e UF ficam vazias. "
                f"Colunas da PesEndereco: {', '.join(cols) or 'tabela não encontrada'}.")
    return sql, info


def consultar_uau() -> list[dict]:
    cfg = sql_cfg()
    if not cfg:
        raise RuntimeError("SQL Server não configurado: preencha a seção [sql] nos Secrets do app.")
    arquivo = BASE / (cfg.get("consulta") or "leads.sql")
    sql = arquivo.read_text(encoding="utf-8").strip().rstrip(";")
    banco = banco_uau(cfg, _assinatura(cfg))
    try:
        sql, info = adaptar_sql(sql, banco)
        st.session_state["info_consulta"] = info
    except Exception as e:  # sem acesso ao INFORMATION_SCHEMA: tenta a consulta como está
        st.session_state["info_consulta"] = f"Não consegui ler as colunas da PesEndereco ({str(e)[:120]})."
    try:
        return banco.consultar(sql)
    except Exception as e:
        m = re.search(r"(?:invalid column name|nome de coluna)\s*'([^']+)'", str(e), re.I)
        if not m:
            raise
        tabelas = {"_pend": "PesEndereco", "_tel": "PesTel", "_nfe": "NotasFiscaisEnt", "_proc": "Parc_Proc", "_pes": "pessoas", "_emp": "empresas", "_obr": "obras"}
        tab = next((t for suf, t in tabelas.items() if m.group(1).lower().endswith(suf)), None)
        extra = f" Colunas da {tab}: {', '.join(_colunas(banco, tab))}." if tab else ""
        raise RuntimeError(f"{e}{extra}") from e


def ler_planilha(arquivo) -> list[dict]:
    nome = arquivo.name.lower()
    if nome.endswith(".csv"):
        df = pd.read_csv(arquivo, sep=None, engine="python", dtype=str, encoding="utf-8-sig")
    else:
        df = pd.read_excel(arquivo, dtype=object)
    df.columns = [str(c).strip() for c in df.columns]
    return df.to_dict("records")


# ---------------------------------------------------------------- armazenamento (etapa, margem, dados, notas, documentos)
ETAPAS = {"novo": "Novo", "contatado": "Contatado", "negociando": "Em negociação", "cadastro": "Cadastro enviado", "ativo": "Ativo", "perdido": "Perdido"}
EDITAVEIS = {"contato", "telefone", "email", "cidade", "uf", "responsavel"}
LIMITE_DOC = 15 * 1024 * 1024


@st.cache_data(ttl=900, show_spinner=False, max_entries=2)
def base_uau(assinatura: str) -> tuple[dict, str]:
    """Resultado do leads.sql já normalizado, guardado por 15 minutos para todos os acessos."""
    return normalizar(consultar_uau()), agora_br().isoformat()


@st.cache_resource(show_spinner="Conectando ao banco do painel…")
def armazenamento(_cfg: dict, assinatura: str) -> Armazenamento:
    painel = Banco(_cfg, _cfg.get("banco_painel") or _cfg.get("banco")) if _cfg else None
    return Armazenamento(painel, BASE / "dados", BASE / "tabelas_anax.sql")


def usuario_padrao() -> str:
    try:
        return getpass.getuser()[:80]
    except Exception:
        return ""


def pct(v) -> str:
    return f"{float(v):.2f}".replace(".", ",") + "%"


def tratar(ev: dict, db: Armazenamento, quem: str):
    acao, cnpj = ev.get("acao"), _digitos(ev.get("cnpj"))
    if acao == "etapa" and cnpj:
        para = ev.get("para")
        if para not in ETAPAS:
            return
        campos = {"etapa": para, "nome": (ev.get("nome") or "")[:200]}
        texto = f"Etapa: {ETAPAS.get(ev.get('de'), ev.get('de') or 'Novo')} → {ETAPAS[para]}" if ev.get("de") != para else ""
        if ev.get("margem") is not None:
            m = float(ev["margem"])
            if not 0 < m <= 20:
                st.toast("Margem fora do intervalo (0 a 20% a.m.). Nada foi salvo.")
                return
            campos.update(margem=round(m, 4), margem_em=agora_txt(), margem_por=quem)
            texto = (texto + " · " if texto else "") + f"margem negociada {pct(m)} a.m."
        db.salvar_lead(cnpj, campos, quem)
        if ev.get("obs"):
            texto += f"\n{ev['obs']}"
        if texto:
            db.nota(cnpj, texto, quem, "sistema")
    elif acao == "proposta" and cnpj:
        itens = [i for i in (ev.get("itens") or []) if i.get("lead_id") and i.get("margem") is not None]
        if not itens or not all(0 < float(i["margem"]) <= 20 for i in itens):
            st.toast("Margem fora do intervalo (0 a 20% a.m.). Nada foi salvo.")
            return
        obs = (ev.get("obs") or "").strip()[:1000] or None
        for i in itens:
            db.salvar_proposta(str(i["lead_id"]), cnpj, round(float(i["margem"]), 4), i.get("valor"), i.get("pagamento"), obs, quem)
        de, para = ev.get("de"), ev.get("para")
        if para in ETAPAS:
            db.salvar_lead(cnpj, {"etapa": para, "nome": (ev.get("nome") or "")[:200]}, quem)
        linhas = [f"{i.get('rotulo') or i['lead_id']}: {pct(i['margem'])} a.m." for i in itens]
        texto = (f"Etapa: {ETAPAS.get(de, de or 'Novo')} → {ETAPAS[para]}\n" if para in ETAPAS and para != de else "") + "Proposta: " + "; ".join(linhas)
        db.nota(cnpj, texto + (f"\n{obs}" if obs else ""), quem, "sistema")
    elif acao == "proposta_status" and ev.get("lead_id"):
        status = ev.get("status")
        if status not in (None, "negociando", "aceita", "recusada"):
            return
        db.status_proposta(str(ev["lead_id"]), status, quem)
        rot = ev.get("rotulo") or ev["lead_id"]
        texto = {None: f"Proposta removida: {rot}", "negociando": f"Proposta reaberta: {rot}", "aceita": f"Proposta aceita: {rot}", "recusada": f"Proposta recusada: {rot}"}[status]
        if cnpj:
            db.nota(cnpj, texto, quem, "sistema")
    elif acao == "dados" and cnpj:
        campos = {k: (v or None) for k, v in (ev.get("campos") or {}).items() if k in EDITAVEIS}
        if campos.get("uf"):
            campos["uf"] = campos["uf"].upper()[:2]
        campos["nome"] = (ev.get("nome") or "")[:200]
        db.salvar_lead(cnpj, campos, quem)
        mudou = [k for k, v in campos.items() if k != "nome" and v]
        db.nota(cnpj, "Dados editados no painel: " + ", ".join(mudou) if mudou else "Dados voltaram aos do UAU", quem, "sistema")
    elif acao == "nota_add" and cnpj and (ev.get("texto") or "").strip():
        db.nota(cnpj, ev["texto"].strip(), quem)
    elif acao == "nota_del" and ev.get("nota_id"):
        db.apagar_nota(ev["nota_id"])
    elif acao == "doc_add" and cnpj:
        for a in ev.get("arquivos") or []:
            conteudo = base64.b64decode(a.get("b64") or "")
            if not conteudo or len(conteudo) > LIMITE_DOC:
                st.toast(f"{a.get('nome')}: arquivo vazio ou acima de 15 MB.")
                continue
            db.doc_add(cnpj, a.get("nome") or "documento", a.get("tipo") or "", conteudo, quem)
    elif acao == "doc_del" and ev.get("doc_id"):
        db.apagar_doc(ev["doc_id"])
    elif acao == "resumo":
        st.session_state.abrir_resumo = True
    elif acao == "doc_baixar" and ev.get("doc_id"):
        d = db.doc(ev["doc_id"])
        if d:
            st.session_state.download = {"token": ev["id"], "nome": d["nome"], "tipo": d["tipo"],
                                         "b64": base64.b64encode(bytes(d["conteudo"])).decode()}


def agora_txt() -> str:
    return agora_br().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- resumo do dia por e-mail
@st.dialog("Resumo do dia em PDF", width="large")
def janela_resumo(db: Armazenamento, quem: str, params: dict):
    hoje = agora_br().date()
    c1, c2 = st.columns([1, 1.6])
    dia = c1.date_input("Dia", value=hoje, max_value=hoje, format="DD/MM/YYYY")
    escopo = c2.radio("Números do dia", ["Toda a equipe", f"Só o que eu fiz ({quem})"], horizontal=True,
                      help="A carteira, o funil e o potencial da base mostram sempre o painel inteiro.")
    try:
        cfg = resumo.config_email(st.secrets)
    except Exception:
        cfg = None
    padrao = st.session_state.get("resumo_para")
    if padrao is None and cfg:
        padrao = cfg.get("para") if isinstance(cfg.get("para"), str) else ", ".join(cfg.get("para") or [])
    para_txt = st.text_input("Enviar para", value=padrao or "", placeholder="nome@empresa.com.br, outra@empresa.com.br",
                             help="Separe os e-mails por vírgula.")

    dados = st.session_state.get("dados") or {}
    cols = dados.get("cols") or []
    linhas = [dict(zip(cols, r)) for r in dados.get("rows") or []]
    r = resumo.coletar(db, dia, None if escopo == "Toda a equipe" else quem, linhas, db.leads(), params)

    logo_path = BASE / "assets" / "logo_claro.png"
    logo = logo_path.read_bytes() if logo_path.exists() else None
    html_arquivo = resumo.gerar_html(r, "data:image/png;base64," + base64.b64encode(logo).decode() if logo else None)
    texto = resumo.gerar_texto(r)
    try:
        pdf = resumo.gerar_pdf(r, logo)
    except Exception as e:
        pdf = None
        st.error(f"Não consegui gerar o PDF: {e}")

    imgs = resumo.paginas_png(pdf) if pdf else []
    if imgs:
        with st.container(height=460, border=True):
            _, meio, _ = st.columns([1, 4, 1])
            for im in imgs:
                meio.image(im, use_container_width=True)
    else:  # sem o pypdfium2 instalado: mostra a versão do e-mail
        if hasattr(st, "iframe"):
            st.iframe(html_arquivo, height=420)
        else:
            components.html(html_arquivo, height=420, scrolling=True)

    para = resumo.destinatarios(para_txt)
    b1, b2, b3 = st.columns(3)
    if cfg:
        if b1.button("Enviar com o PDF", type="primary", use_container_width=True, disabled=pdf is None):
            if not para:
                st.error("Informe pelo menos um e-mail válido.")
            else:
                try:
                    with st.spinner("Enviando…"):
                        resumo.enviar(cfg, para, r, resumo.gerar_html(r, "cid:logo-anax" if logo else None), texto, logo, pdf)
                    st.session_state.resumo_para = ", ".join(para)
                    st.success(f"Resumo de {resumo.data_br(dia)} enviado para {', '.join(para)}, com o PDF em anexo.")
                except Exception as e:
                    st.error(f"Não consegui enviar: {e}")
    if pdf:
        (b2 if cfg else b1).download_button("Baixar PDF", pdf, file_name=resumo.nome_pdf(r), mime="application/pdf",
                                            type="secondary" if cfg else "primary", use_container_width=True)
    corpo = (f"Olá,\n\nSegue em anexo o resumo do Painel de Leads ANAX de {resumo.data_br(dia)} ({resumo.nome_pdf(r)}).\n\n"
             + f"Propostas no dia: {resumo.brl(r['dia_valor'])} ({r['dia_n']} parcela(s)), receita prevista {resumo.brl(r['dia_receita'])}\n"
             + f"Aceites no dia: {resumo.brl(r['dia_aceitas_valor'])}\n"
             + f"Em negociação: {resumo.brl(r['neg_valor'])} · aceitas no total: {resumo.brl(r['ac_valor'])}\n")
    link = "mailto:" + ",".join(para) + "?subject=" + urllib.parse.quote(resumo.assunto(r)) + "&body=" + urllib.parse.quote(corpo)
    (b3 if cfg else b2).link_button("Abrir no meu e-mail", link, use_container_width=True)
    if not cfg:
        st.caption("Baixe o PDF e anexe no e-mail que abre no seu programa (o navegador não consegue anexar sozinho). "
                   "Para enviar direto daqui com o PDF em anexo, preencha a seção [email] do .streamlit/secrets.toml (veja o secrets.toml.exemplo).")


# ---------------------------------------------------------------- página (sem menu lateral: tudo fica na barra do topo do painel)
st.markdown("""<style>
section[data-testid="stSidebar"],[data-testid="stSidebarCollapsedControl"],[data-testid="collapsedControl"],[data-testid="stSidebarCollapseButton"]{display:none!important}
header[data-testid="stHeader"]{display:none}
.block-container{padding:.75rem 1.25rem 0 !important;max-width:100%}
[data-testid="stElementContainer"]:has(iframe[height="0"]){display:none}
</style>""", unsafe_allow_html=True)

TAXAS_PADRAO = {"taxaBase": 3.5, "ajPorte": {"pequeno": 0.7, "medio": 0.0, "grande": -0.3}, "ajScore": {"baixo": 0, "medio": 0.3, "alto": 0.8},
                "faixaPequenoAte": 100000.0, "faixaMedioAte": 500000.0, "taxaMinima": 3.0, "prazoMax": 120}


def onde_gravar() -> str:
    """firebase (padrão, com o login do Firebase) | sql ([app] salvar = "sql") | nada ([app] salvar = false)."""
    try:
        v = st.secrets["app"].get("salvar", None)
    except Exception:
        v = None
    t = str(v).strip().lower() if v is not None else ""
    if t in ("false", "nao", "não", "0", "nada"):
        return "nada"
    if t == "sql":
        return "sql"
    return "firebase" if (firebase_conta() or login.usa_firebase()) else ("sql" if t in ("true", "sim", "1") else "nada")


def firebase_conta() -> dict:
    """A chave da conta de serviço do Firebase colada nos Secrets em [firebase_conta] (ou o emulador, nos testes)."""
    try:
        c = dict(st.secrets["firebase_conta"])
    except Exception:
        return {}
    if c.get("json"):  # o arquivo .json da chave colado inteiro entre aspas triplas
        try:
            c = {**json.loads(str(c["json"])), **{k: v for k, v in c.items() if k != "json"}}
        except Exception:
            st.session_state.erro_firebase = "A chave colada em [firebase_conta] json não é um JSON válido: copie o arquivo inteiro, de { até }."
            return {}
    return c if (c.get("private_key") and c.get("client_email")) or c.get("emulador_firestore") else {}


@st.cache_resource(show_spinner=False)
def _firestore(assinatura: str, _conta: dict) -> ArmazenamentoFirebase:
    emu = _conta.get("emulador_firestore")
    return conectar_servico(None if emu else _conta, emu)


def taxas(db) -> dict:
    salvo = st.session_state.get("taxas_sessao") or db.config("taxas") or {}
    p = {**TAXAS_PADRAO, **{k: v for k, v in salvo.items() if k in TAXAS_PADRAO}}
    p["ajPorte"] = {**TAXAS_PADRAO["ajPorte"], **(salvo.get("ajPorte") or {})}
    p["ajScore"] = {**TAXAS_PADRAO["ajScore"], **(salvo.get("ajScore") or {})}
    return p


def avisar(texto: str, tipo: str = "ok"):
    st.session_state.aviso = {"token": agora_br().isoformat(), "tipo": tipo, "texto": texto}


def carregar(pacote: dict, fonte: str):
    st.session_state.dados = pacote
    st.session_state.meta = {"fonte": fonte, "carregado": agora_br().isoformat()}
    avisar(f"Base carregada: {len(pacote['rows']):,} parcelas.".replace(",", "."))


class _Arquivo(io.BytesIO):  # o leitor de planilha usa .name para saber o formato
    def __init__(self, dados: bytes, nome: str):
        super().__init__(dados)
        self.name = nome


conta = login.exigir(BASE / "assets" / "logo_claro.png")
cfg = sql_cfg()
GRAVAR = onde_gravar()
SO_LEITURA = GRAVAR == "nada"
if GRAVAR == "firebase":
    _fc = firebase_conta()
    if _fc:  # conta de serviço: o servidor grava, o login continua o dos Secrets
        db = _firestore(_assinatura(_fc), _fc)
    else:  # login pelo Firebase Authentication ([app] login = "firebase")
        if "fb_sessao" not in st.session_state or st.session_state.get("fb_uid") != conta["fb"]["uid"]:
            st.session_state.fb_sessao = Sessao(login.cliente_firebase(), conta["fb"])
            st.session_state.fb_uid = conta["fb"]["uid"]
            st.session_state.fb_db = ArmazenamentoFirebase(st.session_state.fb_sessao)
        db = st.session_state.fb_db
    try:
        db.leads()
        db.erro = ""
    except ErroFirebase as e:
        db.erro = str(e)
    except Exception as e:
        db.erro = f"Não consegui falar com o Firebase: {str(e)[:160]}"
    if db.erro:  # sem Firestore pronto, o painel segue só consultando
        st.session_state.erro_firebase = db.erro
        db = SomenteLeitura()
        SO_LEITURA = True
elif GRAVAR == "sql":
    db = armazenamento(cfg, _assinatura(cfg))
else:
    db = SomenteLeitura()
quem = conta["nome"]
params = taxas(db)

# ao entrar, traz a base do UAU sozinho (guardada por 15 min para não repetir a consulta a cada acesso)
if cfg and "dados" not in st.session_state and not st.session_state.get("auto_tentado"):
    st.session_state.auto_tentado = True
    try:
        with st.spinner("Consultando o UAU…"):
            pacote, quando = base_uau(_assinatura(cfg))
        st.session_state.dados = pacote
        st.session_state.meta = {"fonte": "SQL Server (UAU)", "carregado": quando}
    except Exception as e:
        st.session_state.erro_uau = explicar(e) or str(e)[:200]
        avisar(f"Não consegui consultar o UAU. {explicar(e)} ({str(e)[:240]})", "erro")

# ---------------------------------------------------------------- tela
dados = st.session_state.get("dados")
meta = dict(st.session_state.get("meta", {}))
meta["armazenamento"] = db.descricao()
meta["login"] = {"usuario": conta["usuario"], "nome": conta["nome"]}  # sem os tokens
meta["sql"] = {"configurado": bool(cfg), "resumo": resumo_cfg(cfg), "erro": db.erro, "erro_uau": st.session_state.get("erro_uau", "")}
meta["somenteLeitura"] = SO_LEITURA
meta["firebase"] = {"ligado": GRAVAR == "firebase" and bool(conta.get("fb")), "erro": st.session_state.get("erro_firebase", "") if SO_LEITURA else ""}
meta["teste_sql"] = st.session_state.get("teste_sql")
meta["aviso"] = st.session_state.get("aviso")
download = st.session_state.pop("download", None)

ev = _leads(dados=dados, crm=db.leads(), propostas=db.propostas(), notas=db.notas(), docs=db.docs(), download=download,
            params=params, meta=meta, usuario=quem, key="painel_leads", default=None)

if ev and ev.get("id") != st.session_state.get("ultimo_evento"):
    st.session_state.ultimo_evento = ev.get("id")
    acao = ev.get("acao")
    autor = quem
    try:
        if acao == "usuario":
            if conta.get("fb"):
                novo = str(ev.get("nome") or "").strip()[:80]
                if novo and not ev.get("inicio"):
                    login.atualizar_nome(novo)
                    avisar("Nome atualizado.")
        elif acao == "sair":
            login.sair()
        elif acao == "testar_sql":
            with st.spinner("Testando a conexão…"):
                st.session_state.teste_sql = {**diagnosticar(cfg, so_leitura=SO_LEITURA), "quando": agora_br().isoformat()}
                if st.session_state.teste_sql["ok"]:
                    try:
                        st.session_state.teste_sql["linhas"].append(adaptar_sql("", banco_uau(cfg, _assinatura(cfg)))[1])
                    except Exception as e:
                        st.session_state.teste_sql["linhas"].append(f"Não consegui ler as colunas da PesEndereco: {str(e)[:160]}")
            if st.session_state.teste_sql["ok"]:
                st.session_state.erro_uau = ""
                armazenamento.clear()
        elif acao == "carregar_uau":
            try:
                base_uau.clear()
                pacote, _ = base_uau(_assinatura(cfg))
                carregar(pacote, "SQL Server (UAU)")
                st.session_state.erro_uau = ""
            except Exception as e:
                st.session_state.erro_uau = explicar(e) or str(e)[:200]
                avisar(f"Não consegui consultar o UAU. {explicar(e)} ({str(e)[:240]})", "erro")
        elif acao == "planilha":
            try:
                arq = _Arquivo(base64.b64decode(ev.get("b64") or ""), str(ev.get("nome") or "planilha.xlsx"))
                carregar(normalizar(ler_planilha(arq)), f"Planilha {arq.name}")
            except Exception as e:
                avisar(f"Não consegui ler a planilha: {e}", "erro")
        elif acao == "params":
            p = ev.get("params") or {}
            novo_p = {k: p[k] for k in TAXAS_PADRAO if k in p}
            if SO_LEITURA:
                st.session_state.taxas_sessao = novo_p
                avisar("Taxas aplicadas nesta sessão (modo consulta: nada é salvo).")
                raise StopIteration
            try:
                db.salvar_config("taxas", novo_p, autor)
                avisar("Tabela de taxas salva para toda a equipe.")
            except Exception as e:
                avisar(f"Não consegui salvar as taxas: {e}. No SQL Server, rode de novo o tabelas_anax.sql.", "erro")
        elif SO_LEITURA:
            avisar("Modo consulta: o painel não grava nada por enquanto.", "erro")
        else:
            tratar(ev, db, autor)
    except StopIteration:
        pass
    except Exception as e:
        avisar(f"Não consegui salvar: {e}", "erro")
    if acao != "resumo":
        st.rerun()

if st.session_state.pop("abrir_resumo", False):
    janela_resumo(db, quem, params)
