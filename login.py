"""
Login do painel: um usuário com senha nos Secrets (seção [login] abaixo).
(Existe também o login pelo Firebase Authentication, desligado: [app] login = "firebase".)

Secrets (.streamlit/secrets.toml ou Settings > Secrets no Streamlit Cloud):

    [login]
    usuario = "iasmin"
    nome = "Iasmin Fernandes"     # aparece no topo do painel
    senha = "..."                 # a senha (os Secrets do Streamlit Cloud não vão para o GitHub)
    horas = 12                    # quanto tempo o navegador fica conectado

Opcional, mais seguro: no lugar de "senha", use senha_hash = "pbkdf2_sha256$..." (gere com python gerar_senha.py)
e chave_sessao = "texto aleatório". A senha nunca fica no código. Depois de 5 senhas erradas o login trava por 5 minutos
(o tempo dobra a cada novo bloqueio). A sessão fica num cookie assinado; trocar a senha ou a chave_sessao
desconecta todos os navegadores.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets as _rnd
import threading
import time
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

COOKIE = "anax_sessao"
TENTATIVAS = 5
BLOQUEIO_S = 300


# ---------------------------------------------------------------- senha
def gerar_hash(senha: str, iteracoes: int = 600_000) -> str:
    sal = _rnd.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), sal, iteracoes)
    return f"pbkdf2_sha256${iteracoes}${base64.b64encode(sal).decode()}${base64.b64encode(h).decode()}"


def confere(senha: str, guardado: str) -> bool:
    try:
        alg, it, sal, h = guardado.split("$")
        if alg != "pbkdf2_sha256":
            return False
        novo = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), base64.b64decode(sal), int(it))
        return hmac.compare_digest(novo, base64.b64decode(h))
    except Exception:
        return False


# ---------------------------------------------------------------- configuração
def config() -> dict:
    try:
        c = dict(st.secrets["login"])
    except Exception:
        return {}
    if not c.get("usuario") or not (c.get("senha_hash") or c.get("senha")):
        return {}
    c["usuario"] = str(c["usuario"]).strip()
    c["nome"] = c.get("nome") or c["usuario"]
    c["horas"] = float(c.get("horas") or 12)
    return c


def _chave(c: dict) -> bytes:
    segredo = c.get("senha_hash") or hashlib.sha256(("anax|" + str(c.get("senha"))).encode()).hexdigest()
    return hashlib.sha256(f"{c.get('chave_sessao', '')}|{segredo}".encode()).digest()


def _senha_ok(c: dict, senha: str) -> bool:
    if c.get("senha_hash"):
        return confere(senha, c["senha_hash"])
    return hmac.compare_digest(senha.encode("utf-8"), str(c.get("senha")).encode("utf-8"))


def _o_que_falta() -> str:
    try:
        bruto = dict(st.secrets["login"])
    except Exception:
        return "a seção [login] não existe nos Secrets"
    falta = [k for k in ("usuario",) if not bruto.get(k)] + ([] if bruto.get("senha") or bruto.get("senha_hash") else ["senha"])
    return "falta " + " e ".join(falta) + " na seção [login]" if falta else "confira a seção [login]"


# ---------------------------------------------------------------- sessão no cookie (assinada com HMAC)
def _token(c: dict) -> str:
    exp = int(time.time() + c["horas"] * 3600)
    corpo = f"{c['usuario']}|{exp}"
    sig = hmac.new(_chave(c), corpo.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{corpo}|{sig}".encode()).decode().rstrip("=")


def _valida(c: dict, token: str) -> bool:
    try:
        bruto = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
        usuario, exp, sig = bruto.rsplit("|", 2)
        certo = hmac.new(_chave(c), f"{usuario}|{exp}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, certo) and usuario == c["usuario"] and int(exp) > time.time()
    except Exception:
        return False


def _cookie_js(valor: str, max_age: int):
    """Grava/apaga o cookie na página do app (o iframe do components.html é da mesma origem)."""
    url = str(getattr(st.context, "url", "") or "")
    seguro = "; Secure" if url.startswith("https") or "localhost" in url else ""
    components.html(f"""<script>
    (function(){{var c="{COOKIE}={valor}; Path=/; Max-Age={max_age}; SameSite=Strict{seguro}";
      try{{window.parent.document.cookie=c}}catch(e){{}} try{{window.top.document.cookie=c}}catch(e){{}} document.cookie=c;}})();
    </script>""", height=0)


# ---------------------------------------------------------------- bloqueio por tentativas (vale para todos os navegadores)
@st.cache_resource(show_spinner=False)
def _contador():
    return {"falhas": 0, "ate": 0.0, "nivel": 0, "trava": threading.Lock()}


def _bloqueado() -> int:
    c = _contador()
    return max(0, int(c["ate"] - time.time()))


def _registrar(ok: bool):
    c = _contador()
    with c["trava"]:
        if ok:
            c.update(falhas=0, nivel=0)
            return
        c["falhas"] += 1
        if c["falhas"] >= TENTATIVAS:
            c["nivel"] += 1
            c["ate"] = time.time() + BLOQUEIO_S * (2 ** (c["nivel"] - 1))
            c["falhas"] = 0


# ---------------------------------------------------------------- tela
def _estilo():
    st.markdown("""<style>
    @import url('https://fonts.googleapis.com/css2?family=Jost:wght@400;500&family=DM+Sans:wght@400;500;600&display=swap');
    section[data-testid="stSidebar"],[data-testid="stSidebarCollapsedControl"],header[data-testid="stHeader"]{display:none!important}
    .block-container{max-width:420px!important;padding-top:11vh!important}
    .stApp,.stApp input,.stApp label,.stApp button,.stApp p{font-family:'DM Sans',sans-serif!important}
    [data-testid="stForm"]{background:#FFFDF8;border:1px solid #E2D9C6;border-radius:8px;padding:30px 30px 22px}
    [data-testid="stForm"] [data-testid="stImage"]{margin-bottom:6px}
    .anax-eyebrow{font:500 10.5px/1 Jost,sans-serif!important;letter-spacing:.24em;text-transform:uppercase;color:#7A5C2E!important;margin:14px 0 8px!important}
    .anax-titulo{font:400 26px/1.15 Jost,sans-serif!important;color:#121212!important;margin:0 0 4px!important}
    .anax-sub{font-size:13px!important;color:#5E574C!important;margin:0 0 10px!important}
    .stApp label p{font-size:12.5px!important;font-weight:600!important;color:#121212!important}
    .stApp input{background:#fff!important}
    [data-testid="stFormSubmitButton"] button{width:100%;height:42px;background:#B8955A;border-color:#B8955A;color:#121212;font-weight:600;margin-top:4px}
    [data-testid="stFormSubmitButton"] button:hover{background:#7A5C2E;border-color:#7A5C2E;color:#fff}
    .anax-rodape{text-align:center;font-size:11.5px!important;color:#5E574C!important;margin-top:14px!important}
    </style>""", unsafe_allow_html=True)


# ---------------------------------------------------------------- Firebase Authentication (padrão)
def usa_firebase() -> bool:
    """Padrão: usuário e senha dos Secrets ([login]). Login pelo Firebase só com [app] login = "firebase"."""
    try:
        return str(st.secrets["app"].get("login", "secrets")).lower() == "firebase"
    except Exception:
        return False


def firebase_cfg() -> tuple[dict, dict | None, list[str]]:
    try:
        f = dict(st.secrets["firebase"])
    except Exception:
        f = {}
    emu = {k: f.pop(k) for k in ("emulador_auth", "emulador_firestore") if k in f}
    emu = {"auth": emu.get("emulador_auth"), "firestore": emu.get("emulador_firestore")} if emu else None
    emails = [str(e).strip().lower() for e in (f.pop("emails", None) or [])]
    return f, emu, emails


@st.cache_resource(show_spinner=False)
def _fb(cfg_txt: str, emu_txt: str):
    from firebase import Firebase
    import json as _j
    return Firebase(_j.loads(cfg_txt), _j.loads(emu_txt) if emu_txt != "null" else None)


def cliente_firebase():
    import json as _j
    cfg, emu, _ = firebase_cfg()
    return _fb(_j.dumps(cfg, sort_keys=True), _j.dumps(emu, sort_keys=True))


@st.cache_resource(show_spinner=False)
def _segredo_processo() -> bytes:
    return _rnd.token_bytes(32)


def _chave_cookie() -> bytes:
    try:
        k = str(st.secrets["firebase"].get("chave_sessao", ""))
    except Exception:
        k = ""
    return hashlib.sha256(k.encode()).digest() if k else _segredo_processo()


def _token_fb(sessao: dict, horas: float) -> str:
    corpo = base64.urlsafe_b64encode(f"{sessao['refresh']}|{int(time.time() + horas * 3600)}".encode()).decode().rstrip("=")
    sig = hmac.new(_chave_cookie(), corpo.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{corpo}.{sig}"


def _refresh_do_cookie(token: str) -> str | None:
    try:
        corpo, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(sig, hmac.new(_chave_cookie(), corpo.encode(), hashlib.sha256).hexdigest()[:32]):
            return None
        refresh, exp = base64.urlsafe_b64decode(corpo + "=" * (-len(corpo) % 4)).decode().rsplit("|", 1)
        return refresh if int(exp) > time.time() else None
    except Exception:
        return None


def _conta(sessao: dict) -> dict:
    return {"usuario": sessao["email"], "nome": sessao.get("nome") or sessao["email"].split("@")[0], "fb": sessao}


def _exigir_firebase(logo: Path | None) -> dict:
    from firebase import ErroFirebase
    horas = 12.0
    try:
        horas = float(st.secrets["firebase"].get("horas", 12))
    except Exception:
        pass
    if st.session_state.get("logado"):
        if st.session_state.pop("gravar_cookie", None):
            _cookie_js(_token_fb(st.session_state.logado["fb"], horas), int(horas * 3600))
        return st.session_state.logado

    _estilo()
    _, _, emails = firebase_cfg()
    fb = cliente_firebase()
    if st.session_state.pop("apagar_cookie", False):
        _cookie_js("", 0)
    else:
        refresh = _refresh_do_cookie(st.context.cookies.get(COOKIE, ""))
        if refresh:
            try:
                s = fb.renovar(refresh)
                if not emails or s["email"].lower() in emails:
                    st.session_state.logado = _conta(s)
                    st.rerun()
            except ErroFirebase:
                pass

    espera = _bloqueado()
    with st.form("login", clear_on_submit=False, border=False):
        if logo and logo.exists():
            st.image(str(logo), width=132)
        st.markdown('<p class="anax-eyebrow">Painel de leads</p><p class="anax-titulo">Entrar</p>'
                    '<p class="anax-sub">Acesso restrito à equipe ANAX.</p>', unsafe_allow_html=True)
        email = st.text_input("E-mail", autocomplete="username")
        senha = st.text_input("Senha", type="password", autocomplete="current-password")
        try:
            entrar = st.form_submit_button("Entrar", disabled=espera > 0, width="stretch")
        except TypeError:
            entrar = st.form_submit_button("Entrar", disabled=espera > 0, use_container_width=True)
    if espera > 0:
        st.warning(f"Muitas tentativas erradas. Tente de novo em {espera // 60} min {espera % 60:02d} s.")
    elif entrar:
        email = email.strip()
        try:
            if not email or not senha:
                raise ErroFirebase("Preencha e-mail e senha.")
            s = fb.entrar(email, senha)
            if emails and s["email"].lower() not in emails:
                raise ErroFirebase("Este e-mail não tem acesso ao painel.")
            _registrar(True)
            st.session_state.logado = _conta(s)
            st.session_state.gravar_cookie = True
            st.rerun()
        except ErroFirebase as e:
            if "incorretos" in str(e):
                _registrar(False)
            st.error(str(e))
        except Exception as e:
            st.error(f"Não consegui falar com o Firebase: {str(e)[:200]}")
    st.markdown('<p class="anax-rodape">ANAX · Consultoria de Crédito</p>', unsafe_allow_html=True)
    st.stop()


def atualizar_nome(nome: str):
    """Grava o nome de exibição na conta do Firebase (aparece nas notas, propostas e no resumo)."""
    s = st.session_state.logado["fb"]
    sx = st.session_state.get("fb_sessao")
    token = sx.token() if sx else s["id_token"]
    fb = cliente_firebase()
    r = fb.http.post(f"{fb.url_auth}/accounts:update", params={"key": fb.chave},
                     json={"idToken": token, "displayName": nome, "returnSecureToken": False}, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"O Firebase não aceitou o nome ({r.text[:120]}).")
    s["nome"] = nome
    st.session_state.logado["nome"] = nome


def exigir(logo: Path | None = None) -> dict:
    """Mostra o login até a pessoa entrar. Devolve {"usuario", "nome"} da sessão (e "fb" no login pelo Firebase)."""
    if usa_firebase():
        return _exigir_firebase(logo)
    c = config()
    if st.session_state.get("logado"):
        if st.session_state.pop("gravar_cookie", None) and c:
            _cookie_js(_token(c), int(c["horas"] * 3600))
        return st.session_state.logado

    _estilo()
    if st.session_state.pop("apagar_cookie", False):
        _cookie_js("", 0)
    elif c and _valida(c, st.context.cookies.get(COOKIE, "")):
        st.session_state.logado = {"usuario": c["usuario"], "nome": c["nome"]}
        st.rerun()

    if not c:
        if logo and logo.exists():
            st.image(str(logo), width=140)
        st.error(f"O login ainda não foi configurado: {_o_que_falta()}. No Streamlit Cloud, abra o app > Settings > Secrets, "
                 "cole o bloco abaixo trocando a senha, salve e espere o app reiniciar (cerca de 1 minuto).")
        st.code('[login]\nusuario = "iasmin"\nnome = "Iasmin Fernandes"\nsenha = "troque-por-uma-senha-forte"', language="toml")
        st.stop()

    espera = _bloqueado()
    with st.form("login", clear_on_submit=False, border=False):
        if logo and logo.exists():
            st.image(str(logo), width=132)
        st.markdown('<p class="anax-eyebrow">Painel de leads</p><p class="anax-titulo">Entrar</p>'
                    '<p class="anax-sub">Acesso restrito à equipe ANAX.</p>', unsafe_allow_html=True)
        usuario = st.text_input("Usuário", autocomplete="username")
        senha = st.text_input("Senha", type="password", autocomplete="current-password")
        try:
            entrar = st.form_submit_button("Entrar", disabled=espera > 0, width="stretch")
        except TypeError:  # Streamlit mais antigo
            entrar = st.form_submit_button("Entrar", disabled=espera > 0, use_container_width=True)
    if espera > 0:
        st.warning(f"Muitas tentativas erradas. Tente de novo em {espera // 60} min {espera % 60:02d} s.")
    elif entrar:
        ok = hmac.compare_digest(usuario.strip().lower(), c["usuario"].lower()) & _senha_ok(c, senha)
        _registrar(ok)
        if ok:
            st.session_state.logado = {"usuario": c["usuario"], "nome": c["nome"]}
            st.session_state.gravar_cookie = True
            st.rerun()
        restam = TENTATIVAS - _contador()["falhas"]
        st.error("Usuário ou senha incorretos." + (f" Restam {restam} tentativa(s) antes de bloquear." if 0 < restam < TENTATIVAS else ""))
    st.markdown('<p class="anax-rodape">ANAX · Consultoria de Crédito</p>', unsafe_allow_html=True)
    st.stop()


def sair():
    st.session_state.pop("logado", None)
    st.session_state.pop("fb_sessao", None)
    st.session_state.apagar_cookie = True
