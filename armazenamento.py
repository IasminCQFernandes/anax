"""
Onde o painel guarda o que a equipe da ANAX faz com cada lead: etapa, margem negociada,
dados editados, anotações e documentos.

- SQL Server: usado quando a conexão está configurada ([sql] nos secrets). As tabelas de tabelas_anax.sql são
  criadas sozinhas no banco do painel se faltarem (o usuário precisa de permissão CREATE TABLE).
- SQLite: arquivo local dados/anax_leads.sqlite, criado sozinho. Serve para testar numa máquina só.
  No Streamlit Cloud esse arquivo se perde quando o app reinicia: lá, use o SQL Server.
As consultas são as mesmas nos dois (parâmetros com "?").
"""
import datetime as dt
import json
import sqlite3
import uuid
from pathlib import Path

CAMPOS_LEAD = ["nome", "etapa", "margem", "margem_em", "margem_por", "contato", "telefone", "email",
               "cidade", "uf", "responsavel", "atualizado_em", "atualizado_por"]

DDL_SQLITE = [
    """CREATE TABLE IF NOT EXISTS anax_lead (
        cnpj TEXT PRIMARY KEY, nome TEXT, etapa TEXT NOT NULL DEFAULT 'novo', margem REAL, margem_em TEXT, margem_por TEXT,
        contato TEXT, telefone TEXT, email TEXT, cidade TEXT, uf TEXT, responsavel TEXT, atualizado_em TEXT, atualizado_por TEXT)""",
    """CREATE TABLE IF NOT EXISTS anax_lead_nota (
        id TEXT PRIMARY KEY, cnpj TEXT NOT NULL, tipo TEXT NOT NULL DEFAULT 'nota', texto TEXT NOT NULL, autor TEXT, criado_em TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS ix_nota_cnpj ON anax_lead_nota (cnpj)",
    """CREATE TABLE IF NOT EXISTS anax_lead_doc (
        id TEXT PRIMARY KEY, cnpj TEXT NOT NULL, nome TEXT NOT NULL, tipo TEXT, tamanho INTEGER, conteudo BLOB NOT NULL, autor TEXT, enviado_em TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS ix_doc_cnpj ON anax_lead_doc (cnpj)",
    """CREATE TABLE IF NOT EXISTS anax_proposta (
        lead_id TEXT PRIMARY KEY, cnpj TEXT NOT NULL, margem REAL NOT NULL, status TEXT NOT NULL, valor REAL, pagamento TEXT, obs TEXT,
        criado_em TEXT, criado_por TEXT, atualizado_em TEXT, atualizado_por TEXT)""",
    "CREATE INDEX IF NOT EXISTS ix_prop_cnpj ON anax_proposta (cnpj)",
    """CREATE TABLE IF NOT EXISTS anax_config (chave TEXT PRIMARY KEY, valor TEXT NOT NULL, atualizado_em TEXT, atualizado_por TEXT)""",
]


def agora() -> str:  # horário de Brasília (o Streamlit Cloud roda em UTC)
    from firebase import agora as _agora
    return _agora()


class Armazenamento:
    def __init__(self, banco=None, pasta_sqlite: Path | None = None, ddl: Path | None = None):
        """banco = banco.Banco já configurado para o banco do painel (ou None para usar o SQLite)."""
        self.modo = "sqlite"
        self.banco = None
        self.erro = ""  # por que não está no SQL Server, quando a conexão foi configurada
        if banco is not None:
            from banco import criar_tabelas, explicar
            try:
                try:
                    banco.consultar("SELECT TOP 1 chave FROM dbo.anax_config")
                except Exception:
                    falha = criar_tabelas(banco, ddl) if ddl else "tabelas do painel não encontradas"
                    if falha:
                        raise RuntimeError(falha)
                    banco.consultar("SELECT TOP 1 chave FROM dbo.anax_config")
                self.banco, self.modo = banco, "sqlserver"
            except Exception as e:
                self.erro = str(e) if str(e).startswith(("O ", "Não", "Problema", "Faltou")) else f"{explicar(e)} {str(e)[:300]}".strip()
        if self.modo == "sqlite":
            pasta = pasta_sqlite or Path("dados")
            pasta.mkdir(parents=True, exist_ok=True)
            self.arquivo = pasta / "anax_leads.sqlite"
            cn = self._cn()
            try:
                for ddl in DDL_SQLITE:
                    cn.execute(ddl)
                cn.commit()
            finally:
                cn.close()

    # ---------------------------------------------------------------- conexão
    def _cn(self):
        return sqlite3.connect(self.arquivo, timeout=15)

    def _t(self, nome: str) -> str:
        return f"dbo.{nome}" if self.modo == "sqlserver" else nome

    def descricao(self) -> str:
        if self.modo == "sqlserver":
            return f"Gravando no SQL Server (banco {self.banco.banco})"
        return f"Gravando no arquivo local dados/{self.arquivo.name}" + (" — SQL Server indisponível" if self.erro else "")

    def _exec(self, sql, *params):
        if self.modo == "sqlserver":
            return self.banco.executar(sql, *params)
        cn = self._cn()
        try:
            cur = cn.cursor()
            cur.execute(sql, params)
            n = cur.rowcount
            cn.commit()
            return n
        finally:
            cn.close()

    def _todos(self, sql, *params):
        if self.modo == "sqlserver":
            return self.banco.consultar(sql, *params)
        cn = self._cn()
        try:
            cur = cn.cursor()
            cur.execute(sql, params)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
        finally:
            cn.close()

    # ---------------------------------------------------------------- leituras
    def leads(self) -> dict:
        out = {}
        for r in self._todos(f"SELECT cnpj, {', '.join(CAMPOS_LEAD)} FROM {self._t('anax_lead')}"):
            c = r.pop("cnpj")
            r["margem"] = float(r["margem"]) if r.get("margem") is not None else None
            out[c] = {k: (str(v) if isinstance(v, (dt.datetime, dt.date)) else v) for k, v in r.items()}
        return out

    def notas(self) -> dict:
        out = {}
        for r in self._todos(f"SELECT id, cnpj, tipo, texto, autor, criado_em FROM {self._t('anax_lead_nota')} ORDER BY criado_em DESC"):
            r["criado_em"] = str(r["criado_em"])
            out.setdefault(r.pop("cnpj"), []).append(r)
        return out

    def docs(self) -> dict:
        out = {}
        for r in self._todos(f"SELECT id, cnpj, nome, tipo, tamanho, autor, enviado_em FROM {self._t('anax_lead_doc')} ORDER BY enviado_em DESC"):
            r["enviado_em"] = str(r["enviado_em"])
            out.setdefault(r.pop("cnpj"), []).append(r)
        return out

    def propostas(self) -> dict:
        out = {}
        for r in self._todos(f"SELECT lead_id, cnpj, margem, status, valor, pagamento, obs, criado_em, criado_por, atualizado_em, atualizado_por FROM {self._t('anax_proposta')}"):
            lid = r.pop("lead_id")
            r["margem"] = float(r["margem"])
            r["valor"] = float(r["valor"]) if r.get("valor") is not None else None
            out[lid] = {k: (str(v) if isinstance(v, (dt.datetime, dt.date)) else v) for k, v in r.items()}
        return out

    def config(self, chave: str):
        """Configuração compartilhada da equipe (ex.: tabela de taxas), guardada como JSON. None se não houver."""
        try:
            rs = self._todos(f"SELECT valor FROM {self._t('anax_config')} WHERE chave = ?", chave)
            return json.loads(rs[0]["valor"]) if rs else None
        except Exception:
            return None

    def salvar_config(self, chave: str, valor, usuario: str):
        txt = json.dumps(valor, ensure_ascii=False)
        n = self._exec(f"UPDATE {self._t('anax_config')} SET valor = ?, atualizado_em = ?, atualizado_por = ? WHERE chave = ?", txt, agora(), usuario, chave)
        if not n:
            self._exec(f"INSERT INTO {self._t('anax_config')} (chave, valor, atualizado_em, atualizado_por) VALUES (?, ?, ?, ?)", chave, txt, agora(), usuario)

    def doc(self, doc_id: str):
        rs = self._todos(f"SELECT nome, tipo, conteudo FROM {self._t('anax_lead_doc')} WHERE id = ?", doc_id)
        return rs[0] if rs else None

    def do_dia(self, dia: str) -> dict:
        """Tudo o que foi registrado em um dia (dia = 'AAAA-MM-DD'): anotações, documentos e propostas."""
        pre = dia + "%"
        notas = self._todos(f"SELECT id, cnpj, tipo, texto, autor, criado_em FROM {self._t('anax_lead_nota')} WHERE criado_em LIKE ? ORDER BY criado_em", pre)
        docs = self._todos(f"SELECT cnpj, nome, tamanho, autor, enviado_em FROM {self._t('anax_lead_doc')} WHERE enviado_em LIKE ? ORDER BY enviado_em", pre)
        props = self._todos(f"SELECT lead_id, cnpj, margem, status, valor, pagamento, criado_em, criado_por, atualizado_em, atualizado_por FROM {self._t('anax_proposta')} "
                            f"WHERE criado_em LIKE ? OR atualizado_em LIKE ?", pre, pre)
        for r in notas + docs + props:
            for k, v in list(r.items()):
                if isinstance(v, (dt.datetime, dt.date)):
                    r[k] = str(v)
        for r in props:
            r["margem"] = float(r["margem"])
            r["valor"] = float(r["valor"]) if r.get("valor") is not None else None
        return {"notas": notas, "docs": docs, "propostas": props}

    # ---------------------------------------------------------------- escritas
    def salvar_lead(self, cnpj: str, campos: dict, usuario: str):
        campos = {k: v for k, v in campos.items() if k in CAMPOS_LEAD}
        campos.update(atualizado_em=agora(), atualizado_por=usuario)
        sets = ", ".join(f"{k} = ?" for k in campos)
        n = self._exec(f"UPDATE {self._t('anax_lead')} SET {sets} WHERE cnpj = ?", *campos.values(), cnpj)
        if not n:
            campos.setdefault("etapa", "novo")
            cols = ["cnpj", *campos.keys()]
            self._exec(f"INSERT INTO {self._t('anax_lead')} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", cnpj, *campos.values())

    def nota(self, cnpj: str, texto: str, usuario: str, tipo: str = "nota"):
        self._exec(f"INSERT INTO {self._t('anax_lead_nota')} (id, cnpj, tipo, texto, autor, criado_em) VALUES (?, ?, ?, ?, ?, ?)",
                   uuid.uuid4().hex, cnpj, tipo, texto[:4000], usuario, agora())

    def apagar_nota(self, nota_id: str):
        self._exec(f"DELETE FROM {self._t('anax_lead_nota')} WHERE id = ? AND tipo = 'nota'", nota_id)

    def doc_add(self, cnpj: str, nome: str, tipo: str, conteudo: bytes, usuario: str):
        self._exec(f"INSERT INTO {self._t('anax_lead_doc')} (id, cnpj, nome, tipo, tamanho, conteudo, autor, enviado_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   uuid.uuid4().hex, cnpj, nome[:255], (tipo or "")[:120], len(conteudo), conteudo, usuario, agora())

    def salvar_proposta(self, lead_id: str, cnpj: str, margem: float, valor, pagamento, obs: str, usuario: str):
        t = self._t("anax_proposta")
        n = self._exec(f"UPDATE {t} SET margem = ?, status = 'negociando', valor = ?, pagamento = ?, obs = ?, atualizado_em = ?, atualizado_por = ? WHERE lead_id = ?",
                       margem, valor, pagamento, obs, agora(), usuario, lead_id)
        if not n:
            self._exec(f"INSERT INTO {t} (lead_id, cnpj, margem, status, valor, pagamento, obs, criado_em, criado_por, atualizado_em, atualizado_por) VALUES (?, ?, ?, 'negociando', ?, ?, ?, ?, ?, ?, ?)",
                       lead_id, cnpj, margem, valor, pagamento, obs, agora(), usuario, agora(), usuario)

    def status_proposta(self, lead_id: str, status: str | None, usuario: str):
        t = self._t("anax_proposta")
        if status is None:
            self._exec(f"DELETE FROM {t} WHERE lead_id = ?", lead_id)
        else:
            self._exec(f"UPDATE {t} SET status = ?, atualizado_em = ?, atualizado_por = ? WHERE lead_id = ?", status, agora(), usuario, lead_id)

    def apagar_doc(self, doc_id: str):
        self._exec(f"DELETE FROM {self._t('anax_lead_doc')} WHERE id = ?", doc_id)


class SomenteLeitura:
    """Modo consulta: o painel só lê o UAU e não grava nada (nem no SQL Server, nem em arquivo)."""
    modo = "leitura"
    erro = ""
    banco = None

    def descricao(self) -> str:
        return "Modo consulta: nada é salvo"

    def leads(self) -> dict:
        return {}

    def notas(self) -> dict:
        return {}

    def docs(self) -> dict:
        return {}

    def propostas(self) -> dict:
        return {}

    def config(self, chave: str):
        return None

    def doc(self, doc_id: str):
        return None

    def do_dia(self, dia: str) -> dict:
        return {"notas": [], "docs": [], "propostas": []}

    def __getattr__(self, nome):  # qualquer escrita
        def recusa(*a, **k):
            raise RuntimeError("Modo consulta: o painel não grava nada.")
        return recusa
