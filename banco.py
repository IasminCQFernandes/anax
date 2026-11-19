"""
Conexão com o SQL Server, pensada para o Streamlit Cloud (e para rodar na máquina também).

Configuração em .streamlit/secrets.toml (no Streamlit Cloud: Settings > Secrets):

    [sql]
    servidor = "uau.suaempresa.com.br"   # host ou IP público do SQL Server
    porta = 1433
    banco = "UAU"                        # onde estão as tabelas do UAU (só leitura)
    banco_painel = "ANAX"                # onde o painel grava etapas, propostas, notas e documentos (opcional; padrão = banco)
    usuario = "anax_painel"
    senha = "..."
    criptografar = true                  # Encrypt=yes
    confiar_certificado = true           # TrustServerCertificate=yes (certificado do próprio servidor)
    timeout = 15                         # segundos para conectar

    # ou, no lugar dos campos acima, a string ODBC completa:
    # conn = "DRIVER={ODBC Driver 18 for SQL Server};SERVER=...;DATABASE=UAU;UID=...;PWD=...;Encrypt=yes;TrustServerCertificate=yes"

Usa o pyodbc com o "ODBC Driver 18" ou "17" (o Streamlit Cloud já traz os drivers). Se nenhum driver estiver
instalado, usa o pymssql, que não precisa de driver.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.request
from pathlib import Path

DRIVERS = ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server")


def ler_config(segredos) -> dict:
    """Lê a seção [sql] dos secrets (dict-like). Devolve {} se não houver."""
    try:
        s = dict(segredos["sql"])
    except Exception:
        return {}
    cfg = {k: v for k, v in s.items() if v not in (None, "")}
    if not cfg.get("conn") and not cfg.get("servidor"):
        return {}
    return cfg


def _sim(v, padrao: bool) -> bool:
    if v is None:
        return padrao
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "sim", "yes", "y")


def _chaves(valor: str) -> str:
    """Protege um valor da string ODBC (senha com ; = { })."""
    return "{" + str(valor).replace("}", "}}") + "}"


class Banco:
    """Uma conexão guardada e reaproveitada (com trava), refeita sozinha se cair."""

    def __init__(self, cfg: dict, banco: str | None = None):
        self.cfg = dict(cfg)
        self.banco = banco or cfg.get("banco") or ""
        self.motor = ""          # "pyodbc · ODBC Driver 18 for SQL Server" ou "pymssql"
        self._cn = None
        self._trava = threading.RLock()

    # ---------------------------------------------------------------- abrir
    def _abrir(self):
        c = self.cfg
        timeout = int(c.get("timeout") or 15)
        erro_pyodbc = None
        try:
            import pyodbc
            if c.get("conn"):
                cs = c["conn"]
                if self.banco and self.banco != c.get("banco"):
                    cs = re.sub(r"(?i)(DATABASE|Initial Catalog)\s*=\s*[^;]*", f"DATABASE={self.banco}", cs) if re.search(r"(?i)DATABASE|Initial Catalog", cs) else cs + f";DATABASE={self.banco}"
                m = re.search(r"(?i)DRIVER\s*=\s*\{([^}]*)\}", cs)
                self.motor = f"pyodbc · {m.group(1) if m else 'ODBC'}"
                return pyodbc.connect(cs, timeout=timeout)
            disp = [d for d in DRIVERS if d in pyodbc.drivers()]
            driver = c.get("driver") or (disp[0] if disp else None)
            if driver:
                partes = {
                    "DRIVER": "{" + driver + "}",
                    "SERVER": f"{c['servidor']},{int(c.get('porta') or 1433)}",
                    "DATABASE": self.banco,
                    "UID": c.get("usuario", ""),
                    "PWD": _chaves(c.get("senha", "")),
                    "Encrypt": "yes" if _sim(c.get("criptografar"), True) else "no",
                    "TrustServerCertificate": "yes" if _sim(c.get("confiar_certificado"), True) else "no",
                    "Connection Timeout": str(timeout),
                    "APP": "ANAX Painel de Leads",
                }
                self.motor = f"pyodbc · {driver}"
                return pyodbc.connect(";".join(f"{k}={v}" for k, v in partes.items() if v != ""), timeout=timeout)
            erro_pyodbc = "nenhum ODBC Driver 17/18 instalado"
        except ImportError as e:
            erro_pyodbc = f"pyodbc indisponível ({e})"
        if c.get("conn"):
            raise RuntimeError(f"A string [sql] conn precisa do pyodbc com driver ODBC: {erro_pyodbc}. "
                               "Use os campos servidor/porta/banco/usuario/senha para o painel usar o pymssql.")
        import pymssql  # reserva: não precisa de driver ODBC
        self.motor = "pymssql"
        return pymssql.connect(server=str(c["servidor"]), port=str(int(c.get("porta") or 1433)), user=c.get("usuario", ""),
                               password=c.get("senha", ""), database=self.banco, login_timeout=timeout, timeout=300,
                               appname="ANAX Painel de Leads", charset="UTF-8", tds_version="7.4")

    def _fechar(self):
        try:
            if self._cn is not None:
                self._cn.close()
        except Exception:
            pass
        self._cn = None

    @property
    def estilo(self) -> str:
        return "%s" if self.motor == "pymssql" else "?"

    def sql(self, texto: str) -> str:
        """As consultas do painel usam "?"; o pymssql usa "%s"."""
        return texto.replace("?", "%s") if self.estilo == "%s" else texto

    # ---------------------------------------------------------------- executar
    def run(self, fn):
        """Executa fn(conexão) com commit; se a conexão caiu, reconecta e tenta mais uma vez."""
        with self._trava:
            for tentativa in (1, 2):
                try:
                    if self._cn is None:
                        self._cn = self._abrir()
                    r = fn(self._cn)
                    self._cn.commit()
                    return r
                except Exception:
                    viva = self._viva()
                    if tentativa == 1 and not viva:
                        self._fechar()
                        continue
                    if viva:
                        try:
                            self._cn.rollback()
                        except Exception:
                            pass
                    raise

    def _viva(self) -> bool:
        if self._cn is None:
            return False
        try:
            cur = self._cn.cursor()
            cur.execute("SELECT 1")
            cur.fetchall()
            return True
        except Exception:
            return False

    def consultar(self, texto: str, *params) -> list[dict]:
        def f(cn):
            cur = cn.cursor()
            cur.execute(self.sql(texto), params) if params else cur.execute(texto)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
        return self.run(f)

    def executar(self, texto: str, *params) -> int:
        def f(cn):
            cur = cn.cursor()
            cur.execute(self.sql(texto), params) if params else cur.execute(texto)
            return cur.rowcount
        return self.run(f)


# ---------------------------------------------------------------- diagnóstico (botão "Testar conexão")
def ip_de_saida() -> str:
    """IP público de saída deste servidor (é o que a TI libera no firewall)."""
    for url in ("https://api.ipify.org", "https://checkip.amazonaws.com"):
        try:
            with urllib.request.urlopen(url, timeout=4) as r:
                ip = r.read().decode().strip()
                if re.fullmatch(r"[\d.]{7,15}|[0-9a-fA-F:]{3,39}", ip):
                    return ip
        except Exception:
            continue
    return ""


def explicar(erro: Exception | str) -> str:
    t = str(erro)
    tl = t.lower()
    if re.search(r"18456|login failed|falha de logon", tl):
        return "O SQL Server recusou o usuário ou a senha (confira [sql] usuario e senha)."
    if re.search(r"4060|cannot open database|não é possível abrir o banco", tl):
        return "O banco não existe ou este usuário não tem acesso a ele (confira [sql] banco e banco_painel)."
    if re.search(r"certificate|certificado|ssl|tls", tl):
        return "Problema no certificado da conexão criptografada: use confiar_certificado = true."
    if re.search(r"timeout|hyt00|08001|unable to connect|adaptive server is unavailable|tcp provider|network-related|20009|tempo limite", tl):
        return ("O servidor não respondeu. Quase sempre é o firewall: o SQL Server precisa aceitar conexões vindas deste app "
                "(endereço público + porta liberados para o IP de saída). Confira também servidor e porta.")
    m = re.search(r"(?:invalid column name|nome de coluna)\s*'([^']+)'", t, re.I)
    if m or "42s22" in tl:
        return f"A consulta usa uma coluna que não existe neste UAU ({m.group(1) if m else '?'}): a conexão está ok, falta ajustar o leads.sql."
    m = re.search(r"(?:invalid object name|nome de objeto)\s*'([^']+)'", t, re.I)
    if m or "42s02" in tl:
        return f"A consulta usa uma tabela que não existe neste banco ({m.group(1) if m else '?'}): confira [sql] banco."
    if re.search(r"permission denied|permissão negada|\b(229|262|297|300)\b", tl):
        return "O usuário conecta, mas não tem permissão para esta operação (veja as permissões no README)."
    if re.search(r"im002|can't open lib|data source name not found|libodbc|no module named 'pyodbc'|no module named 'pymssql'", tl):
        return "Faltou o driver de conexão: confira o requirements.txt (pyodbc e pymssql)."
    return ""


def diagnosticar(cfg: dict, so_leitura: bool = False) -> dict:
    """Testa as duas conexões (UAU para leitura, painel para gravação) e devolve um resumo para a tela."""
    if not cfg:
        return {"ok": False, "linhas": ["SQL Server não configurado: preencha a seção [sql] nos Secrets."], "ip": ip_de_saida()}
    linhas, ok = [], True
    for rotulo, nome in (("Leitura (UAU)", cfg.get("banco")), ("Gravação (painel)", cfg.get("banco_painel") or cfg.get("banco"))):
        b = Banco(cfg, nome)
        t0 = time.perf_counter()
        try:
            r = b.consultar("SELECT DB_NAME() AS banco, @@SERVERNAME AS servidor, CAST(SERVERPROPERTY('ProductVersion') AS varchar(30)) AS versao")[0]
            linhas.append(f"{rotulo}: conectado ao banco {r['banco']} em {r['servidor']} (SQL Server {r['versao']}), {b.motor}, "
                          f"{(time.perf_counter() - t0) * 1000:.0f} ms.")
        except Exception as e:
            ok = False
            dica = explicar(e)
            linhas.append(f"{rotulo}: falhou{' (' + b.motor + ')' if b.motor else ''}. {dica} Erro: {str(e)[:300]}")
        finally:
            b._fechar()
        if so_leitura:
            break
        if cfg.get("banco_painel") in (None, "", cfg.get("banco")) and rotulo.startswith("Leitura"):
            linhas.append("Gravação (painel): usa o mesmo banco do UAU (defina [sql] banco_painel para separar).")
            break
    return {"ok": ok, "linhas": linhas, "ip": ip_de_saida()}


def criar_tabelas(banco: Banco, arquivo: Path) -> str:
    """Cria as tabelas do painel (tabelas_anax.sql) se faltarem. Devolve "" se deu certo ou a mensagem de erro."""
    texto = arquivo.read_text(encoding="utf-8")
    try:
        banco.run(lambda cn: cn.cursor().execute(texto))
        return ""
    except Exception as e:
        return f"{explicar(e) or 'Não consegui criar as tabelas do painel.'} Erro: {str(e)[:300]}"


def resumo_cfg(cfg: dict) -> str:
    """Texto curto para a tela, sem senha."""
    if not cfg:
        return ""
    if cfg.get("conn"):
        cs = re.sub(r"(?i)(PWD|Password)\s*=\s*(\{[^}]*\}|[^;]*)", r"\1=***", cfg["conn"])
        return cs[:160]
    return f"{cfg.get('servidor')}:{cfg.get('porta') or 1433} · UAU em {cfg.get('banco')}"


if __name__ == "__main__":  # python banco.py  -> testa a conexão com o .streamlit/secrets.toml local
    import tomllib
    s = tomllib.loads((Path(__file__).parent / ".streamlit" / "secrets.toml").read_text(encoding="utf-8"))
    print(json.dumps(diagnosticar(ler_config(s)), ensure_ascii=False, indent=2))
