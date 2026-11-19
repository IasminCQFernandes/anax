"""
Firebase do painel (projeto anaxconsultoria), só com HTTP, sem SDK:
- Gravação: Cloud Firestore, pela conta de serviço do projeto (secrets [firebase_conta]). As regras do Firestore
  fecham o banco para qualquer acesso de fora; só o servidor do painel, com a conta de serviço, lê e grava.
- Opcional: login pelo Firebase Authentication (e-mail e senha), se um dia for usado ([app] login = "firebase").

Coleções no Firestore:
  leads/{cnpj}                 etapa, dados editados, atualizado_em/por
  notas/{id}                   cnpj, tipo (nota|sistema), texto, autor, criado_em
  docs/{id}                    cnpj, nome, tipo, tamanho, autor, enviado_em, partes, compactado, formato
  docs/{id}/partes/{n}         b64 (o arquivo compactado em base64, em partes de até 900 mil caracteres)
  propostas/{lead_id}          cnpj, margem, status, valor, pagamento, obs, criado/atualizado em/por
  config/{chave}               valor (ex.: a tabela de taxas)

A configuração web do Firebase não é segredo. Segredo é a chave da conta de serviço: ela fica só nos Secrets.
"""
from __future__ import annotations

import base64
import datetime as dt
import io
import re
import threading
import time
import uuid
import zlib

import requests

CONFIG_PADRAO = {
    "apiKey": "AIzaSyBVxCHfLsV0JV24IYWeUbPcHAM0mr96--k",
    "authDomain": "anaxconsultoria.firebaseapp.com",
    "projectId": "anaxconsultoria",
    "storageBucket": "anaxconsultoria.firebasestorage.app",
    "messagingSenderId": "302415441695",
    "appId": "1:302415441695:web:77913bd071c12f5d1f4a2a",
}
PARTE = 900_000          # caracteres de base64 por documento do Firestore (o limite de um documento é 1 MiB)
TIMEOUT = 20

ERROS_LOGIN = {
    "EMAIL_NOT_FOUND": "E-mail ou senha incorretos.",
    "INVALID_PASSWORD": "E-mail ou senha incorretos.",
    "INVALID_LOGIN_CREDENTIALS": "E-mail ou senha incorretos.",
    "INVALID_EMAIL": "E-mail inválido.",
    "USER_DISABLED": "Este usuário está desativado no Firebase.",
    "TOO_MANY_ATTEMPTS_TRY_LATER": "Muitas tentativas. O Firebase bloqueou o login por alguns minutos.",
    "CONFIGURATION_NOT_FOUND": "O login por e-mail e senha ainda não foi ativado no Firebase (Authentication > Sign-in method).",
    "OPERATION_NOT_ALLOWED": "O login por e-mail e senha está desligado no Firebase (Authentication > Sign-in method).",
    "PASSWORD_LOGIN_DISABLED": "O login por e-mail e senha está desligado no Firebase (Authentication > Sign-in method).",
}


def agora_br() -> dt.datetime:
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("America/Sao_Paulo")).replace(tzinfo=None)
    except Exception:
        return dt.datetime.utcnow() - dt.timedelta(hours=3)


def agora() -> str:
    return agora_br().strftime("%Y-%m-%d %H:%M:%S")


class ErroFirebase(RuntimeError):
    pass


# ---------------------------------------------------------------- conversão Firestore <-> Python
def _para_valor(v):
    if v is None:
        return {"nullValue": None}
    if isinstance(v, bool):
        return {"booleanValue": v}
    if isinstance(v, int):
        return {"integerValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    if isinstance(v, dict):
        return {"mapValue": {"fields": {k: _para_valor(x) for k, x in v.items()}}}
    if isinstance(v, (list, tuple)):
        return {"arrayValue": {"values": [_para_valor(x) for x in v]}}
    if isinstance(v, (dt.date, dt.datetime)):
        return {"stringValue": str(v)}
    return {"stringValue": str(v)}


def _de_valor(v: dict):
    (tipo, x), = v.items()
    if tipo == "integerValue":
        return int(x)
    if tipo == "doubleValue":
        return float(x)
    if tipo == "mapValue":
        return {k: _de_valor(y) for k, y in (x.get("fields") or {}).items()}
    if tipo == "arrayValue":
        return [_de_valor(y) for y in (x.get("values") or [])]
    if tipo == "nullValue":
        return None
    return x


def _de_doc(d: dict) -> tuple[str, dict]:
    return d["name"].rsplit("/", 1)[-1], {k: _de_valor(v) for k, v in (d.get("fields") or {}).items()}


# ---------------------------------------------------------------- cliente
class Firebase:
    def __init__(self, cfg: dict | None = None, emulador: dict | None = None):
        """emulador = {"auth": "127.0.0.1:9099", "firestore": "127.0.0.1:8080"} só para testes locais."""
        self.cfg = {**CONFIG_PADRAO, **(cfg or {})}
        self.chave = self.cfg["apiKey"]
        pid = self.cfg["projectId"]
        emu = emulador or {}
        self.url_auth = f"http://{emu['auth']}/identitytoolkit.googleapis.com/v1" if emu.get("auth") else "https://identitytoolkit.googleapis.com/v1"
        self.url_token = f"http://{emu['auth']}/securetoken.googleapis.com/v1/token" if emu.get("auth") else "https://securetoken.googleapis.com/v1/token"
        fs = f"http://{emu['firestore']}" if emu.get("firestore") else "https://firestore.googleapis.com"
        self.url_docs = f"{fs}/v1/projects/{pid}/databases/(default)/documents"
        self.http = requests.Session()

    # ---- login
    def _auth(self, url: str, dados: dict) -> dict:
        r = self.http.post(url, params={"key": self.chave}, json=dados, timeout=TIMEOUT)
        j = r.json() if r.content else {}
        if r.status_code != 200:
            cod = str((j.get("error") or {}).get("message") or r.status_code)
            raise ErroFirebase(ERROS_LOGIN.get(cod.split(" ")[0].split(":")[0], f"O Firebase recusou o login ({cod})."))
        return j

    def entrar(self, email: str, senha: str) -> dict:
        j = self._auth(f"{self.url_auth}/accounts:signInWithPassword", {"email": email, "password": senha, "returnSecureToken": True})
        return {"uid": j["localId"], "email": j["email"], "nome": j.get("displayName") or j["email"].split("@")[0],
                "id_token": j["idToken"], "refresh": j["refreshToken"], "expira": time.time() + int(j.get("expiresIn", 3600)) - 120}

    def renovar(self, refresh: str, base: dict | None = None) -> dict:
        r = self.http.post(self.url_token, params={"key": self.chave}, data={"grant_type": "refresh_token", "refresh_token": refresh}, timeout=TIMEOUT)
        if r.status_code != 200:
            raise ErroFirebase("A sessão expirou. Entre de novo.")
        j = r.json()
        s = dict(base or {})
        s.update(uid=j["user_id"], id_token=j["id_token"], refresh=j["refresh_token"], expira=time.time() + int(j.get("expires_in", 3600)) - 120)
        if not s.get("email"):
            info = self.http.post(f"{self.url_auth}/accounts:lookup", params={"key": self.chave}, json={"idToken": j["id_token"]}, timeout=TIMEOUT).json()
            u = (info.get("users") or [{}])[0]
            s["email"] = u.get("email", "")
            s["nome"] = u.get("displayName") or s["email"].split("@")[0]
        return s


class Sessao:
    """Token de quem entrou, renovado sozinho quando está para vencer (dura 1 hora)."""

    def __init__(self, fb: Firebase, sessao: dict):
        self.fb, self.s, self._trava = fb, dict(sessao), threading.Lock()

    def token(self) -> str:
        with self._trava:
            if time.time() >= self.s["expira"]:
                self.s = self.fb.renovar(self.s["refresh"], self.s)
            return self.s["id_token"]

    def pedir(self, metodo: str, caminho: str, **kw):
        url = caminho if caminho.startswith("http") else f"{self.fb.url_docs}/{caminho}"
        for tentativa in (1, 2):
            r = self.fb.http.request(metodo, url, headers={"Authorization": f"Bearer {self.token()}"}, timeout=TIMEOUT, **kw)
            if r.status_code == 401 and tentativa == 1:
                self.s["expira"] = 0
                continue
            break
        if r.status_code == 404 and metodo == "GET":
            return None
        if r.status_code >= 400:
            j = r.json() if r.content else {}
            msg = (j.get("error") or {}).get("message") or r.text[:200]
            if r.status_code == 403 and "has not been used" in msg:
                msg = "o Cloud Firestore ainda não foi criado no projeto (Firebase > Firestore Database > Criar banco de dados)"
            elif r.status_code == 403:
                msg = "acesso recusado (confira se a conta de serviço é deste projeto e tem o papel de Firebase Admin)"
            elif r.status_code == 404 or "does not exist" in msg:
                msg = "o banco do Firestore ainda não foi criado (Firebase > Firestore Database > Criar banco de dados)"
            raise ErroFirebase(f"Firestore: {msg}")
        return r.json() if r.content else {}


class SessaoServico(Sessao):
    """Acesso do servidor ao Firestore com a conta de serviço (não depende de login no Firebase)."""

    def __init__(self, fb: Firebase, conta: dict | None):
        self.fb, self._trava, self.conta = fb, threading.Lock(), dict(conta or {})
        self._cred = None
        self.s = {}

    def token(self) -> str:
        if not self.conta:  # emulador local: "owner" passa por cima das regras
            return "owner"
        with self._trava:
            if self._cred is None:
                from google.oauth2 import service_account
                info = dict(self.conta)
                info["private_key"] = str(info.get("private_key", "")).replace("\\n", "\n")
                self._cred = service_account.Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/datastore"])
            if not self._cred.valid:
                from google.auth.transport.requests import Request
                self._cred.refresh(Request())
            return self._cred.token


def conectar_servico(conta: dict | None, emulador_firestore: str | None = None) -> "ArmazenamentoFirebase":
    cfg = {"projectId": conta["project_id"]} if conta and conta.get("project_id") else {}
    fb = Firebase(cfg, {"firestore": emulador_firestore} if emulador_firestore else None)
    return ArmazenamentoFirebase(SessaoServico(fb, conta))


# ---------------------------------------------------------------- armazenamento do painel no Firestore
class ArmazenamentoFirebase:
    modo = "firebase"
    banco = None

    def __init__(self, sessao: Sessao, cache_s: int = 20):
        self.sx = sessao
        self.erro = ""
        self._cache, self._cache_s = {}, cache_s

    def descricao(self) -> str:
        return f"Gravando no Firebase ({self.sx.fb.cfg['projectId']})"

    # ---- leitura em lote, guardada por alguns segundos (a tela relê tudo a cada clique)
    def _colecao(self, nome: str) -> list[tuple[str, dict]]:
        c = self._cache.get(nome)
        if c and time.time() - c[0] < self._cache_s:
            return c[1]
        out, token = [], None
        while True:
            params = {"pageSize": 300}
            if token:
                params["pageToken"] = token
            if nome == "docs":
                params["mask.fieldPaths"] = ["cnpj", "nome", "tipo", "tamanho", "autor", "enviado_em"]
            j = self.sx.pedir("GET", nome, params=params) or {}
            out += [_de_doc(d) for d in j.get("documents", [])]
            token = j.get("nextPageToken")
            if not token:
                break
        self._cache[nome] = (time.time(), out)
        return out

    def _sujou(self, *nomes):
        for n in nomes:
            self._cache.pop(n, None)

    def _gravar(self, caminho: str, dados: dict, mesclar: bool = True):
        params = [("updateMask.fieldPaths", k) for k in dados] if mesclar else None
        self.sx.pedir("PATCH", caminho, params=params, json={"fields": {k: _para_valor(v) for k, v in dados.items()}})

    def _apagar(self, caminho: str):
        self.sx.pedir("DELETE", caminho)

    # ---- mesma interface do Armazenamento (SQL Server/SQLite)
    def leads(self) -> dict:
        return {i: d for i, d in self._colecao("leads")}

    def notas(self) -> dict:
        out = {}
        for i, d in sorted(self._colecao("notas"), key=lambda x: x[1].get("criado_em", ""), reverse=True):
            out.setdefault(d.get("cnpj"), []).append({"id": i, **{k: d.get(k) for k in ("tipo", "texto", "autor", "criado_em")}})
        return out

    def docs(self) -> dict:
        out = {}
        for i, d in sorted(self._colecao("docs"), key=lambda x: x[1].get("enviado_em", ""), reverse=True):
            out.setdefault(d.get("cnpj"), []).append({"id": i, **{k: d.get(k) for k in ("nome", "tipo", "tamanho", "autor", "enviado_em")}})
        return out

    def propostas(self) -> dict:
        return {i: d for i, d in self._colecao("propostas")}

    def config(self, chave: str):
        try:
            d = self.sx.pedir("GET", f"config/{chave}")
        except ErroFirebase:
            return None
        return _de_doc(d)[1].get("valor") if d else None

    def salvar_config(self, chave: str, valor, usuario: str):
        self._gravar(f"config/{chave}", {"valor": valor, "atualizado_em": agora(), "atualizado_por": usuario}, mesclar=False)

    def do_dia(self, dia: str) -> dict:
        notas = [{"id": i, **d} for i, d in self._colecao("notas") if str(d.get("criado_em", "")).startswith(dia)]
        docs = [d for _, d in self._colecao("docs") if str(d.get("enviado_em", "")).startswith(dia)]
        props = [{"lead_id": i, **d} for i, d in self._colecao("propostas")
                 if str(d.get("criado_em", "")).startswith(dia) or str(d.get("atualizado_em", "")).startswith(dia)]
        chave = lambda k: (lambda x: x.get(k, ""))
        return {"notas": sorted(notas, key=chave("criado_em")), "docs": sorted(docs, key=chave("enviado_em")), "propostas": props}

    def salvar_lead(self, cnpj: str, campos: dict, usuario: str):
        atual = dict(self.leads().get(cnpj) or {})
        dados = {**campos, "atualizado_em": agora(), "atualizado_por": usuario}
        if not atual.get("etapa") and "etapa" not in dados:
            dados["etapa"] = "novo"
        self._gravar(f"leads/{cnpj}", dados)
        self._sujou("leads")

    def nota(self, cnpj: str, texto: str, usuario: str, tipo: str = "nota"):
        self._gravar(f"notas/{uuid.uuid4().hex}", {"cnpj": cnpj, "tipo": tipo, "texto": texto[:4000], "autor": usuario, "criado_em": agora()}, mesclar=False)
        self._sujou("notas")

    def apagar_nota(self, nota_id: str):
        d = self.sx.pedir("GET", f"notas/{nota_id}")
        if d and _de_doc(d)[1].get("tipo") == "nota":
            self._apagar(f"notas/{nota_id}")
        self._sujou("notas")

    def salvar_proposta(self, lead_id: str, cnpj: str, margem: float, valor, pagamento, obs: str, usuario: str):
        atual = self.propostas().get(lead_id)
        dados = {"cnpj": cnpj, "margem": float(margem), "status": "negociando", "valor": float(valor) if valor is not None else None,
                 "pagamento": pagamento, "obs": obs, "atualizado_em": agora(), "atualizado_por": usuario}
        if not atual:
            dados.update(criado_em=agora(), criado_por=usuario)
        self._gravar(f"propostas/{lead_id}", dados)
        self._sujou("propostas")

    def status_proposta(self, lead_id: str, status: str | None, usuario: str):
        if status is None:
            self._apagar(f"propostas/{lead_id}")
        else:
            self._gravar(f"propostas/{lead_id}", {"status": status, "atualizado_em": agora(), "atualizado_por": usuario})
        self._sujou("propostas")

    # ---- documentos: compactados e em base64, em partes (cada documento do Firestore aceita até 1 MiB)
    def doc_add(self, cnpj: str, nome: str, tipo: str, conteudo: bytes, usuario: str):
        dados, formato, tipo_final = compactar(conteudo, tipo or "", nome)
        if tipo_final != (tipo or "") and tipo_final == "image/jpeg":  # foto convertida para JPEG
            nome = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", nome) + ".jpg"
        b64 = base64.b64encode(dados).decode()
        partes = [b64[i:i + PARTE] for i in range(0, len(b64), PARTE)] or [""]
        doc_id = uuid.uuid4().hex
        for n, p in enumerate(partes):
            self._gravar(f"docs/{doc_id}/partes/{n:03d}", {"b64": p}, mesclar=False)
        self._gravar(f"docs/{doc_id}", {"cnpj": cnpj, "nome": nome[:255], "tipo": tipo_final[:120], "tamanho": len(conteudo),
                                        "tamanho_gravado": len(dados), "formato": formato, "partes": len(partes),
                                        "autor": usuario, "enviado_em": agora()}, mesclar=False)
        self._sujou("docs")

    def doc(self, doc_id: str):
        d = self.sx.pedir("GET", f"docs/{doc_id}")
        if not d:
            return None
        meta = _de_doc(d)[1]
        b64 = "".join(_de_doc(self.sx.pedir("GET", f"docs/{doc_id}/partes/{n:03d}") or {"name": "x", "fields": {}})[1].get("b64", "")
                      for n in range(int(meta.get("partes") or 0)))
        bruto = base64.b64decode(b64)
        return {"nome": meta.get("nome"), "tipo": meta.get("tipo"), "conteudo": descompactar(bruto, meta.get("formato", ""))}

    def apagar_doc(self, doc_id: str):
        d = self.sx.pedir("GET", f"docs/{doc_id}")
        n = int(_de_doc(d)[1].get("partes") or 0) if d else 0
        for i in range(n):
            self._apagar(f"docs/{doc_id}/partes/{i:03d}")
        self._apagar(f"docs/{doc_id}")
        self._sujou("docs")


# ---------------------------------------------------------------- compactação dos documentos
def compactar(conteudo: bytes, tipo: str, nome: str) -> tuple[bytes, str, str]:
    """Fotos grandes viram JPEG de até 2000 px (qualidade 82); o resto é compactado com zlib quando vale a pena.
    Devolve (bytes, formato, tipo): formato "zlib" ou "" (como veio)."""
    eh_imagem = tipo.startswith("image/") and not tipo.endswith(("svg+xml", "gif"))
    if eh_imagem and len(conteudo) > 300_000:
        try:
            from PIL import Image, ImageOps
            im = ImageOps.exif_transpose(Image.open(io.BytesIO(conteudo)))
            im.thumbnail((2000, 2000))
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            b = io.BytesIO()
            im.save(b, format="JPEG", quality=82, optimize=True)
            if b.tell() < len(conteudo):
                return b.getvalue(), "", "image/jpeg"
        except Exception:
            pass
    z = zlib.compress(conteudo, 9)
    if len(z) < len(conteudo) * 0.95:
        return z, "zlib", tipo
    return conteudo, "", tipo


def descompactar(dados: bytes, formato: str) -> bytes:
    return zlib.decompress(dados) if formato == "zlib" else dados
