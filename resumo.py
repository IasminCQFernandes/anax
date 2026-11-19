"""
Resumo executivo do dia do Painel de Leads ANAX, para gestores e donos:
números do dia, situação da carteira, potencial da base e gráficos, em PDF (A4) e no corpo do e-mail.

E-mail: .streamlit/secrets.toml  ->  [email] host, porta, usuario, senha, remetente, para, seguranca
"""
import datetime as dt
import html
import io
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from pathlib import Path

DIAS_SEMANA = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
ETAPAS = [("novo", "Novo"), ("contatado", "Contatado"), ("negociando", "Em negociação"), ("cadastro", "Cadastro enviado"),
          ("ativo", "Ativo"), ("perdido", "Perdido")]
SITUACAO = {"negociando": "Em negociação", "aceita": "Aceita", "recusada": "Recusada"}
DEF_PARAMS = {"taxaBase": 3.5, "ajPorte": {"pequeno": 0.7, "medio": 0, "grande": -0.3}, "ajScore": {"medio": 0.3},
              "faixaPequenoAte": 100000, "faixaMedioAte": 500000, "taxaMinima": 3.0, "prazoMax": 120}

# identidade ANAX
PRETO, OURO, OURO_P, MARFIM, LINHA, CINZA, PAPEL = "#121212", "#B8955A", "#7A5C2E", "#F6F2EA", "#E2D9C6", "#5E574C", "#FFFDF8"
# situação da proposta (ordem fixa: aceita, em negociação, recusada; validada para daltonismo nessa ordem)
COR_SIT = {"aceita": "#1D7A4B", "negociando": "#C98A2E", "recusada": "#B3261E"}


def brl(v) -> str:
    s = f"{float(v or 0):,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def brl_curto(v) -> str:
    v = float(v or 0)
    if abs(v) >= 1e6:
        return "R$ " + f"{v / 1e6:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".") + " mi"
    if abs(v) >= 1e3:
        return "R$ " + f"{v / 1e3:,.0f}".replace(",", ".") + " mil"
    return brl(v)


def pct(v) -> str:
    return f"{float(v):.2f}".replace(".", ",") + "%"


def num(v) -> str:
    return f"{int(v):,}".replace(",", ".")


def data_br(d: dt.date) -> str:
    return d.strftime("%d/%m/%Y")


def _data(v):
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def _dig(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def _interno(cnpj: str, nome: str) -> bool:
    return cnpj.startswith("19758842") or bool(re.search(r"\b(APORTE|LCM)\b", nome or "", re.I))


def _taxa_tabela(volume: float, p: dict) -> float:
    porte = "pequeno" if volume <= p["faixaPequenoAte"] else "medio" if volume <= p["faixaMedioAte"] else "grande"
    return max(p["taxaMinima"], round(p["taxaBase"] + p["ajPorte"].get(porte, 0) + p["ajScore"].get("medio", 0), 2))


# ---------------------------------------------------------------- números
def coletar(db, dia: dt.date, autor: str | None, linhas: list[dict], crm: dict, params: dict | None = None) -> dict:
    """autor = None para a equipe toda, ou o nome de quem fez (vale para os números do dia)."""
    p = {**DEF_PARAMS, **(params or {})}
    forn = {}
    for l in linhas:
        c = _dig(l.get("fornecedor_cnpj"))
        f = forn.setdefault(c, {"nome": l.get("fornecedor_razao") or c, "volume": 0.0, "interno": _interno(c, l.get("fornecedor_razao"))})
        f["volume"] += float(l.get("processo_valor") or 0)
    taxa = {c: _taxa_tabela(f["volume"], p) for c, f in forn.items()}

    props = []
    for lid, x in db.propostas().items():
        base, pg = _data(x.get("criado_em")) or dia, _data(x.get("pagamento"))
        dias = max((pg - base).days, 0) if pg else 0
        valor = float(x.get("valor") or 0)
        c = x.get("cnpj") or ""
        props.append({**x, "lead_id": lid, "valor": valor, "dias": dias, "receita": round(valor * x["margem"] / 100 * dias / 30, 2),
                      "nome": (forn.get(c) or {}).get("nome") or (crm.get(c) or {}).get("nome") or c,
                      "tabela": taxa.get(c, p["taxaBase"]), "criado": _data(x.get("criado_em")), "decidido": _data(x.get("atualizado_em"))})
    meu = (lambda q: q == autor) if autor else (lambda q: True)
    soma = lambda xs, k="valor": sum(x[k] for x in xs)

    # ---- o dia
    feitas = [x for x in props if x["criado"] == dia and meu(x.get("criado_por"))]
    decididas = lambda st: [x for x in props if x["status"] == st and x["decidido"] == dia and meu(x.get("atualizado_por"))]
    aceitas_dia, recusadas_dia = decididas("aceita"), decididas("recusada")
    v_feitas = soma(feitas)
    margem_media = sum(x["valor"] * x["margem"] for x in feitas) / v_feitas if v_feitas else None
    tabela_media = sum(x["valor"] * x["tabela"] for x in feitas) / v_feitas if v_feitas else None
    bruto = db.do_dia(dia.isoformat())
    notas = [n for n in bruto["notas"] if meu(n.get("autor"))]
    trabalhados = {n["cnpj"] for n in notas} | {x["cnpj"] for x in feitas} | {x["cnpj"] for x in aceitas_dia + recusadas_dia}

    # ---- carteira (estado atual, equipe toda)
    neg = [x for x in props if x["status"] == "negociando"]
    ac = [x for x in props if x["status"] == "aceita"]
    rc = [x for x in props if x["status"] == "recusada"]
    decidido = soma(ac) + soma(rc)

    # ---- potencial da base: parcelas aprovadas com pagamento dentro do prazo, fora do grupo
    por_lead = {x["lead_id"]: x for x in props}
    pot_v = pot_r = em_prop = 0.0
    pot_f = set()
    for l in linhas:
        c = _dig(l.get("fornecedor_cnpj"))
        if forn.get(c, {}).get("interno"):
            continue
        pg, v = _data(l.get("processo_pagamento")), float(l.get("processo_valor") or 0)
        d = (pg - dia).days if pg else None
        if d is None or not (0 < d <= p["prazoMax"]) or v <= 0:
            continue
        pot_v += v
        pot_r += v * taxa.get(c, p["taxaBase"]) / 100 * d / 30
        pot_f.add(c)
        x = por_lead.get(l.get("lead_id"))
        if x and x["status"] in ("negociando", "aceita"):
            em_prop += v

    # ---- últimos 14 dias
    serie = []
    for i in range(13, -1, -1):
        d = dia - dt.timedelta(days=i)
        serie.append({"dia": d, "proposto": soma([x for x in props if x["criado"] == d and meu(x.get("criado_por"))]),
                      "aceito": soma([x for x in props if x["status"] == "aceita" and x["decidido"] == d and meu(x.get("atualizado_por"))])})

    # ---- funil de fornecedores (etapa atual)
    funil = {k: {"n": 0} for k, _ in ETAPAS}
    for c, f in forn.items():
        if f["interno"]:
            continue
        funil.setdefault((crm.get(c) or {}).get("etapa") or "novo", {"n": 0})["n"] += 1

    # ---- maiores negociações em aberto, por fornecedor
    g = {}
    for x in neg:
        t = g.setdefault(x["cnpj"], {"nome": x["nome"], "valor": 0.0, "receita": 0.0, "n": 0})
        t["valor"] += x["valor"]
        t["receita"] += x["receita"]
        t["n"] += 1
    top = sorted(g.values(), key=lambda t: -t["valor"])[:5]

    # ---- equipe no dia
    equipe = {}
    for x in feitas:
        e = equipe.setdefault(x.get("criado_por") or "—", {"n": 0, "valor": 0.0, "receita": 0.0, "ac": 0, "v_ac": 0.0})
        e["n"] += 1
        e["valor"] += x["valor"]
        e["receita"] += x["receita"]
    for x in aceitas_dia:
        e = equipe.setdefault(x.get("atualizado_por") or "—", {"n": 0, "valor": 0.0, "receita": 0.0, "ac": 0, "v_ac": 0.0})
        e["ac"] += 1
        e["v_ac"] += x["valor"]

    return {
        "dia": dia, "autor": autor,
        "dia_n": len(feitas), "dia_valor": v_feitas, "dia_receita": soma(feitas, "receita"),
        "dia_aceitas_n": len(aceitas_dia), "dia_aceitas_valor": soma(aceitas_dia), "dia_aceitas_receita": soma(aceitas_dia, "receita"),
        "dia_recusadas_n": len(recusadas_dia), "dia_recusadas_valor": soma(recusadas_dia),
        "margem_media": margem_media, "tabela_media": tabela_media,
        "trabalhados": len(trabalhados), "contatos": sum(1 for n in notas if n["tipo"] == "nota"), "docs": sum(1 for d in bruto["docs"] if meu(d.get("autor"))),
        "neg_n": len(neg), "neg_valor": soma(neg), "neg_receita": soma(neg, "receita"), "neg_forn": len({x["cnpj"] for x in neg}),
        "ac_n": len(ac), "ac_valor": soma(ac), "ac_receita": soma(ac, "receita"),
        "rc_n": len(rc), "rc_valor": soma(rc),
        "conversao": soma(ac) / decidido if decidido else None,
        "pot_valor": pot_v, "pot_receita": pot_r, "pot_forn": len(pot_f), "pot_em_prop": em_prop,
        "serie": serie, "funil": funil, "top": top,
        "equipe": sorted(({"quem": k, **v} for k, v in equipe.items()), key=lambda e: -e["valor"]),
        "prazo_max": p["prazoMax"],
        "vazio": not (feitas or aceitas_dia or recusadas_dia or notas),
    }


def assunto(r: dict) -> str:
    quem = f" · {r['autor']}" if r["autor"] else ""
    return f"ANAX · Resumo executivo {data_br(r['dia'])}{quem}"


def nome_pdf(r: dict) -> str:
    quem = ("-" + re.sub(r"[^a-z0-9]+", "-", r["autor"].lower()).strip("-")) if r["autor"] else ""
    return f"resumo-anax-{r['dia'].isoformat()}{quem}.pdf"


def _titulo_dia(dia: dt.date) -> str:
    t = f"{DIAS_SEMANA[dia.weekday()]}, {data_br(dia)}"
    return t[0].upper() + t[1:]


def _kpis(r: dict) -> tuple[list, list]:
    """(rótulo, valor, detalhe) dos quadros do dia e da carteira."""
    mm = r["margem_media"]
    dia = [
        ("Propostas no dia", brl_curto(r["dia_valor"]), f"{num(r['dia_n'])} parcela(s) · {num(r['trabalhados'])} fornecedor(es) trabalhado(s)"),
        ("Receita prevista", brl(r["dia_receita"]), "deságio das propostas do dia"),
        ("Aceites no dia", brl_curto(r["dia_aceitas_valor"]), f"{num(r['dia_aceitas_n'])} parcela(s) · receita {brl(r['dia_aceitas_receita'])}"),
        ("Margem média", (pct(mm) + " a.m.") if mm is not None else "—",
         (f"tabela {pct(r['tabela_media'])} · " + (f"{abs(mm - r['tabela_media']):.2f} p.p. {'acima' if mm > r['tabela_media'] else 'abaixo'}".replace(".", ",", 1)
                                                    if abs(mm - r['tabela_media']) >= 0.005 else "igual à tabela")) if mm is not None else "sem propostas no dia"),
    ]
    conv = r["conversao"]
    carteira = [
        ("Em negociação", brl_curto(r["neg_valor"]), f"{num(r['neg_n'])} parcela(s) · {num(r['neg_forn'])} fornecedor(es) · receita {brl_curto(r['neg_receita'])}"),
        ("Aceitas (total)", brl_curto(r["ac_valor"]), f"{num(r['ac_n'])} parcela(s) · receita {brl(r['ac_receita'])}"),
        ("Conversão", f"{conv * 100:.0f}%".replace(".", ",") if conv is not None else "—", "do valor decidido foi aceito" if conv is not None else "nenhuma proposta decidida ainda"),
        ("Potencial da base", brl_curto(r["pot_valor"]),
         f"{num(r['pot_forn'])} fornecedor(es) · " + f"{(r['pot_em_prop'] / r['pot_valor'] * 100 if r['pot_valor'] else 0):.1f}".replace(".", ",") + "% já em proposta"),
    ]
    return dia, carteira


# ---------------------------------------------------------------- e-mail (HTML com tabelas e estilos em linha)
def _e(v) -> str:
    return html.escape(str(v if v is not None else ""))


def gerar_html(r: dict, logo_src: str | None) -> str:
    fonte = "font-family:'DM Sans',Arial,Helvetica,sans-serif;"
    disp = "font-family:Jost,'Century Gothic',Arial,sans-serif;"
    escopo = f"Números do dia: {_e(r['autor'])}" if r["autor"] else "Números do dia: toda a equipe"
    dia, carteira = _kpis(r)

    def linha_kpis(itens, destaque):
        tds = "".join(
            f'<td width="25%" style="padding:12px;border:1px solid {LINHA};background:{"#F1E6D0" if i == destaque else PAPEL};vertical-align:top">'
            f'<div style="{disp}font-size:9.5px;letter-spacing:.16em;text-transform:uppercase;color:{CINZA}">{_e(k)}</div>'
            f'<div style="{disp}font-size:20px;color:{PRETO};margin-top:4px;white-space:nowrap">{_e(v)}</div>'
            f'<div style="{fonte}font-size:11px;color:{CINZA};margin-top:2px">{_e(s)}</div></td>' for i, (k, v, s) in enumerate(itens))
        return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse"><tr>{tds}</tr></table>'

    secao = lambda t: f'<div style="{disp}font-size:11px;letter-spacing:.2em;text-transform:uppercase;color:{OURO_P};font-weight:600;margin:22px 0 8px">{t}</div>'
    logo = (f'<img src="{logo_src}" width="135" height="44" alt="ANAX Consultoria de Crédito" style="display:block;border:0">'
            if logo_src else f'<div style="{disp}font-size:20px;letter-spacing:.3em;color:{PRETO}">ANAX</div>')
    td = f"{fonte}font-size:13px;color:{PRETO};padding:8px 10px;border-bottom:1px solid {LINHA};"
    top = "".join(f'<tr><td style="{td}"><b>{_e(t["nome"])}</b><div style="font-size:11.5px;color:{CINZA}">{num(t["n"])} parcela(s)</div></td>'
                  f'<td style="{td}text-align:right;white-space:nowrap">{brl(t["valor"])}<div style="font-size:11.5px;color:{CINZA}">receita {brl(t["receita"])}</div></td></tr>'
                  for t in r["top"]) or f'<tr><td style="{td}color:{CINZA}">Nenhuma negociação em aberto.</td></tr>'
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(assunto(r))}</title></head><body style="margin:0;padding:0;background:{MARFIM}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{MARFIM}"><tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="680" cellpadding="0" cellspacing="0" style="width:100%;max-width:680px;background:{PAPEL};border:1px solid {LINHA}">
<tr><td style="height:4px;background:{PRETO};font-size:0;line-height:0">&nbsp;</td></tr>
<tr><td style="padding:22px 28px 16px;border-bottom:1px solid {LINHA}"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
<td style="vertical-align:middle">{logo}</td><td style="vertical-align:middle;text-align:right;{fonte}font-size:12px;color:{CINZA}">Resumo executivo<br><span style="color:{OURO_P}">{escopo}</span></td></tr></table></td></tr>
<tr><td style="padding:20px 28px 26px">
<div style="{disp}font-size:24px;color:{PRETO}">{_e(_titulo_dia(r['dia']))}</div>
{secao("O dia")}{linha_kpis(dia, 1)}
{secao("A carteira hoje")}{linha_kpis(carteira, 0)}
{secao("Maiores negociações em aberto")}<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse">{top}</table>
<p style="{fonte}font-size:12.5px;color:{CINZA};margin:18px 0 0">Gráficos dos últimos 14 dias, funil de fornecedores e carteira por situação no PDF em anexo.</p>
</td></tr></table></td></tr></table></body></html>"""


def gerar_texto(r: dict) -> str:
    dia, carteira = _kpis(r)
    l = [assunto(r), ""]
    l += ["O DIA"] + [f"- {k}: {v} ({s})" for k, v, s in dia] + ["", "A CARTEIRA HOJE"] + [f"- {k}: {v} ({s})" for k, v, s in carteira]
    if r["top"]:
        l += ["", "MAIORES NEGOCIAÇÕES EM ABERTO"] + [f"- {t['nome']}: {brl(t['valor'])} · receita {brl(t['receita'])}" for t in r["top"]]
    return "\n".join(l + ["", "Detalhes e gráficos no PDF em anexo."])


# ---------------------------------------------------------------- PDF (A4, fontes Jost e DM Sans em assets/fonts)
FONTES = Path(__file__).parent / "assets" / "fonts"


def _registrar_fontes() -> tuple[str, str, str, str]:
    """Registra Jost e DM Sans no reportlab; sem os arquivos, usa Helvetica."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    nomes = {"Jost": "Jost_400Regular", "Jost-Medium": "Jost_500Medium", "DMSans": "DMSans_400Regular", "DMSans-Bold": "DMSans_700Bold"}
    try:
        for n, arq in nomes.items():
            if n not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(n, str(FONTES / f"{arq}.ttf")))
        return "Jost", "Jost-Medium", "DMSans", "DMSans-Bold"
    except Exception:
        return "Helvetica", "Helvetica", "Helvetica", "Helvetica-Bold"


def _teto(v: float) -> float:
    """Topo "redondo" do eixo (1, 2, 2,5 ou 5 × 10^n)."""
    if v <= 0:
        return 1
    import math
    e = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * e:
            return m * e
    return 10 * e


def _corta(t: str, n: int) -> str:
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def gerar_pdf(r: dict, logo: bytes | None) -> bytes:
    from reportlab.graphics.shapes import Drawing, Line, Rect, String
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.platypus import BaseDocTemplate, Frame, KeepTogether, PageTemplate, Paragraph, Spacer, Table, TableStyle

    DISP, DISP_M, CORPO, CORPO_B = _registrar_fontes()
    H = colors.HexColor
    est = lambda nome, **kw: ParagraphStyle(nome, **{"fontName": CORPO, "fontSize": 9, "leading": 12, "textColor": H(PRETO), **kw})
    S = {
        "eyebrow": est("eyebrow", fontName=DISP_M, fontSize=8, leading=10, textColor=H(OURO_P)),
        "titulo": est("titulo", fontName=DISP, fontSize=21, leading=25),
        "escopo": est("escopo", fontSize=9, textColor=H(CINZA)),
        "secao": est("secao", fontName=DISP_M, fontSize=8.5, leading=11, textColor=H(OURO_P), spaceBefore=12, spaceAfter=6),
        "kpi_k": est("kpi_k", fontName=DISP_M, fontSize=6.6, leading=9, textColor=H(CINZA)),
        "kpi_v": est("kpi_v", fontName=DISP, fontSize=15.5, leading=19),
        "kpi_s": est("kpi_s", fontSize=7.3, leading=9.5, textColor=H(CINZA)),
        "graf": est("graf", fontName=CORPO_B, fontSize=8.6, leading=11),
        "graf_s": est("graf_s", fontSize=7.3, leading=9.5, textColor=H(CINZA), spaceAfter=4),
        "th": est("th", fontName=CORPO_B, fontSize=6.8, leading=9, textColor=H(CINZA)),
        "thr": est("thr", fontName=CORPO_B, fontSize=6.8, leading=9, textColor=H(CINZA), alignment=TA_RIGHT),
        "td": est("td", fontSize=8.6, leading=11.5),
        "num": est("num", fontSize=8.6, leading=11.5, alignment=TA_RIGHT),
        "nota": est("nota", fontSize=7.3, leading=9.5, textColor=H(CINZA)),
    }
    esp = lambda t: " ".join(t.upper()).replace("   ", " &nbsp; &nbsp;")  # rótulos com letras espaçadas
    P = lambda t, st="td": Paragraph(t, S[st])
    W = A4[0] - 36 * mm
    COL = (W - 14) / 2  # largura de cada gráfico, lado a lado
    tinta, muted, linha = H(PRETO), H(CINZA), H(LINHA)

    def txt(x, y, t, size=7, cor=muted, fonte=CORPO, anchor="start"):
        return String(x, y, t, fontName=fonte, fontSize=size, fillColor=cor, textAnchor=anchor)

    # ---- gráfico 1: valor proposto por dia, 14 dias (uma série; o dia do resumo em ouro profundo)
    def g_dias():
        h, base, esq = 128, 16, 34
        d = Drawing(COL, h)
        vals = [x["proposto"] for x in r["serie"]]
        teto = _teto(max(vals) * 1.15) if max(vals) > 0 else 1
        area = h - base - 14
        for k in range(0, 5):  # grade recessiva
            y = base + area * k / 4
            d.add(Line(esq, y, COL, y, strokeColor=linha, strokeWidth=0.4 if k else 0.8))
            if k in (2, 4) and max(vals) > 0:
                d.add(txt(esq - 4, y - 2.5, brl_curto(teto * k / 4).replace("R$ ", ""), 6.3, anchor="end"))
        slot = (COL - esq) / len(vals)
        bw = slot * 0.58
        imax = max(range(len(vals)), key=lambda i: vals[i])
        for i, x in enumerate(r["serie"]):
            cx = esq + slot * i + slot / 2
            hv = area * x["proposto"] / teto
            ult = i == len(vals) - 1
            if hv > 0:
                d.add(Rect(cx - bw / 2, base, bw, max(hv, 1.2), rx=1.6, ry=1.6, fillColor=H(OURO_P if ult else OURO), strokeColor=None))
            if hv > 0 and (ult or i == imax):  # rótulo só no dia do resumo e no maior
                d.add(txt(cx, base + hv + 3, brl_curto(x["proposto"]).replace("R$ ", ""), 6.4, tinta, CORPO_B, "middle"))
            if (len(vals) - 1 - i) % 2 == 0:  # rótulo dia sim, dia não, contando a partir do dia do resumo
                d.add(txt(cx, base - 10, x["dia"].strftime("%d/%m"), 6.2, tinta if ult else muted, CORPO_B if ult else CORPO, "middle"))
        if max(vals) == 0:
            d.add(txt(esq + (COL - esq) / 2, base + area / 2, "Nenhuma proposta no período", 8, muted, CORPO, "middle"))
        return d

    # ---- gráfico 2: funil de fornecedores por etapa (barras horizontais, uma série)
    def g_funil():
        itens = [(nome, r["funil"].get(k, {"n": 0})["n"], k) for k, nome in ETAPAS]
        lh, h = 17, 17 * len(itens) + 4
        d = Drawing(COL, h)
        esq, dir_ = 74, 34
        mx = max([n for _, n, k in itens if k != "novo"] + [1])  # "Novo" fica fora da escala para não achatar o resto
        for i, (nome, n, k) in enumerate(itens):
            y = h - (i + 1) * lh + 3
            d.add(txt(0, y + 3.2, nome, 7.4, tinta))
            if k == "novo":
                d.add(txt(esq, y + 3.2, "ainda não abordados", 7, muted))
                d.add(txt(COL, y + 2.5, num(n), 7.6, tinta, CORPO_B, "end"))
                continue
            larg = (COL - esq - dir_) * n / mx
            d.add(Rect(esq, y, COL - esq - dir_, 10, fillColor=H(MARFIM), strokeColor=None, rx=1.6, ry=1.6))
            if n:
                d.add(Rect(esq, y, max(larg, 2), 10, fillColor=H("#9C9384" if k == "perdido" else OURO),
                           strokeColor=None, rx=1.6, ry=1.6))
            d.add(txt(COL, y + 2.5, num(n), 7.6, tinta, CORPO_B, "end"))
        return d

    # ---- gráfico 3: carteira por situação (uma barra empilhada, 2 pt de vão entre partes, legenda com valores)
    def g_situacao():
        partes = [("aceita", "Aceitas", r["ac_valor"], r["ac_n"]), ("negociando", "Em negociação", r["neg_valor"], r["neg_n"]),
                  ("recusada", "Recusadas", r["rc_valor"], r["rc_n"])]
        tot = sum(p[2] for p in partes)
        h = 74
        d = Drawing(COL, h)
        y = h - 18
        if tot <= 0:
            d.add(Rect(0, y, COL, 12, fillColor=H(MARFIM), strokeColor=None, rx=2, ry=2))
            d.add(txt(COL / 2, y - 14, "Nenhuma proposta registrada", 8, muted, CORPO, "middle"))
            return d
        x, vivas = 0.0, [p for p in partes if p[2] > 0]
        util = COL - 2 * (len(vivas) - 1)
        for k, nome, v, n in vivas:
            w = util * v / tot
            d.add(Rect(x, y, max(w, 1.5), 12, fillColor=H(COR_SIT[k]), strokeColor=None, rx=1.6, ry=1.6))
            x += w + 2
        for i, (k, nome, v, n) in enumerate(partes):  # legenda sempre presente, com valor e % (cor nunca sozinha)
            ly = y - 16 - i * 13
            d.add(Rect(0, ly, 7, 7, fillColor=H(COR_SIT[k]), strokeColor=None, rx=1, ry=1))
            d.add(txt(11, ly + 0.8, nome, 7.4, tinta))
            d.add(txt(COL * 0.62, ly + 0.8, f"{num(n)} parc.", 7.2, muted, CORPO, "end"))
            d.add(txt(COL, ly + 0.8, f"{brl_curto(v)} · {v / tot * 100:.0f}%".replace(".", ","), 7.4, tinta, CORPO_B, "end"))
        return d

    # ---- gráfico 4: maiores negociações em aberto (top 5, barras horizontais)
    def g_top():
        itens = r["top"]
        lh = 21
        h = max(lh * len(itens), 30) + 2
        d = Drawing(COL, h)
        if not itens:
            d.add(txt(0, h - 14, "Nenhuma negociação em aberto.", 8, muted))
            return d
        mx = max(t["valor"] for t in itens) or 1
        for i, t in enumerate(itens):
            y = h - (i + 1) * lh
            d.add(txt(0, y + 12, _corta(t["nome"], 40), 7.2, tinta))
            d.add(Rect(0, y + 2, (COL - 74) * t["valor"] / mx, 7, fillColor=H(OURO), strokeColor=None, rx=1.6, ry=1.6))
            d.add(txt(COL, y + 12, brl_curto(t["valor"]), 7.4, tinta, CORPO_B, "end"))
            d.add(txt(COL, y + 3, "receita " + brl_curto(t["receita"]), 6.5, muted, CORPO, "end"))
        return d

    def bloco(titulo, sub, desenho):
        return [P(_e(titulo), "graf"), P(_e(sub), "graf_s"), desenho]

    def par(a, b):
        t = Table([[a, b]], colWidths=[COL + 7, COL + 7])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (0, -1), 14),
                               ("RIGHTPADDING", (1, 0), (1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
        return t

    def kpis(itens, destaque):
        t = Table([[[P(esp(k), "kpi_k"), P(_e(v), "kpi_v"), P(_e(s), "kpi_s")] for k, v, s in itens]], colWidths=[W / 4] * 4)
        t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, linha), ("INNERGRID", (0, 0), (-1, -1), 0.6, linha),
                               ("BACKGROUND", (0, 0), (-1, -1), H(PAPEL)), ("BACKGROUND", (destaque, 0), (destaque, 0), H("#F1E6D0")),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                               ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 6)]))
        return t

    dia_k, cart_k = _kpis(r)
    escopo = f"Números do dia: {r['autor']}" if r["autor"] else "Números do dia: toda a equipe. Carteira e potencial: estado atual do painel."
    hist = [P(esp("Resumo executivo"), "eyebrow"), P(_e(_titulo_dia(r["dia"])), "titulo"), Spacer(1, 2), P(_e(escopo), "escopo"),
            P(esp("O dia"), "secao"), kpis(dia_k, 1),
            P(esp("A carteira hoje"), "secao"), kpis(cart_k, 0),
            P(esp("Gráficos"), "secao"),
            par(bloco("Valor proposto por dia", f"Últimos 14 dias, até {data_br(r['dia'])} (em destaque)", g_dias()),
                bloco("Fornecedores por etapa", "Etapa atual de cada fornecedor da base", g_funil())),
            Spacer(1, 12),
            par(bloco("Carteira por situação", "Valor de face das parcelas com proposta", g_situacao()),
                bloco("Maiores negociações em aberto", "Valor em negociação por fornecedor", g_top()))]

    if r["equipe"]:
        linhas = [[P(esp("Quem"), "th"), P(esp("Parcelas"), "thr"), P(esp("Proposto"), "thr"), P(esp("Receita"), "thr"), P(esp("Aceites"), "thr")]]
        for e in r["equipe"]:
            linhas.append([P(_e(e["quem"])), P(num(e["n"]), "num"), P(brl(e["valor"]), "num"), P(brl(e["receita"]), "num"),
                           P(f"{num(e['ac'])} · {brl_curto(e['v_ac'])}", "num")])
        t = Table(linhas, colWidths=[W * .32, W * .12, W * .2, W * .18, W * .18])
        t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.5, linha), ("LINEBELOW", (0, 0), (-1, 0), 0.8, linha),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                               ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]))
        hist += [KeepTogether([P(esp("Equipe no dia"), "secao"), t])]

    hist += [Spacer(1, 10), P(_e(f"Receita = deságio da ANAX: valor × margem × dias até o pagamento ÷ 30. Potencial da base: parcelas aprovadas "
                                 f"com pagamento nos próximos {r['prazo_max']} dias, fora do grupo LCM, à taxa da tabela."), "nota")]

    logo_img = ImageReader(io.BytesIO(logo)) if logo else None
    from firebase import agora_br
    gerado = agora_br().strftime("%d/%m/%Y às %H:%M")
    dia = r["dia"]

    class Pagina(rl_canvas.Canvas):  # moldura e "página 1 de N"
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self._paginas = []

        def showPage(self):
            self._paginas.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._paginas)
            for i, estado in enumerate(self._paginas, 1):
                self.__dict__.update(estado)
                self._moldura(i, total)
                super().showPage()
            super().save()

        def _moldura(self, n, total):
            larg, alt = A4
            self.setFillColor(tinta)
            self.rect(0, alt - 4, larg, 4, stroke=0, fill=1)
            if n == 1:
                if logo_img:
                    self.drawImage(logo_img, 18 * mm, alt - 24 * mm, width=38 * mm, height=12.4 * mm, mask="auto", preserveAspectRatio=True)
                self.setFont(CORPO, 8.5)
                self.setFillColor(muted)
                self.drawRightString(larg - 18 * mm, alt - 16 * mm, "Painel de Leads")
                self.setFillColor(H(OURO_P))
                self.drawRightString(larg - 18 * mm, alt - 20.5 * mm, f"Resumo de {data_br(dia)}")
                self.setStrokeColor(linha)
                self.setLineWidth(0.6)
                self.line(18 * mm, alt - 28 * mm, larg - 18 * mm, alt - 28 * mm)
            else:
                self.setFont(CORPO, 7.5)
                self.setFillColor(muted)
                self.drawString(18 * mm, alt - 12 * mm, f"ANAX · Resumo executivo {data_br(dia)}")
            self.setStrokeColor(linha)
            self.setLineWidth(0.6)
            self.line(18 * mm, 15 * mm, larg - 18 * mm, 15 * mm)
            self.setFont(CORPO, 7)
            self.setFillColor(muted)
            self.drawString(18 * mm, 10.5 * mm, f"Gerado pelo Painel de Leads ANAX em {gerado}")
            self.drawRightString(larg - 18 * mm, 10.5 * mm, f"página {n} de {total}")

    buf = io.BytesIO()
    larg, alt = A4
    quadro = lambda topo: Frame(18 * mm, 18 * mm, larg - 36 * mm, alt - topo - 18 * mm, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc = BaseDocTemplate(buf, pagesize=A4, title=assunto(r), author="ANAX · Painel de Leads", subject="Resumo executivo do dia",
                          pageTemplates=[PageTemplate(id="primeira", frames=[quadro(33 * mm)], autoNextPageTemplate="demais"),
                                         PageTemplate(id="demais", frames=[quadro(18 * mm)])])
    doc.build(hist, canvasmaker=Pagina)
    return buf.getvalue()


def paginas_png(pdf: bytes, escala: float = 1.6) -> list[bytes]:
    """Prévia do PDF como imagens (usa pypdfium2; sem ele, devolve lista vazia)."""
    try:
        import pypdfium2 as pdfium
    except Exception:
        return []
    out = []
    doc = pdfium.PdfDocument(pdf)
    for pg in doc:
        img = pg.render(scale=escala).to_pil()
        b = io.BytesIO()
        img.save(b, format="PNG")
        out.append(b.getvalue())
    return out


# ---------------------------------------------------------------- envio
def config_email(secrets) -> dict | None:
    try:
        c = dict(secrets["email"])
    except Exception:
        return None
    if not c.get("host") or not c.get("remetente"):
        return None
    c.setdefault("porta", 587)
    c.setdefault("seguranca", "starttls")
    return c


def destinatarios(texto: str) -> list[str]:
    out = []
    for p in re.split(r"[;,\s]+", texto or ""):
        p = p.strip()
        if p and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", parseaddr(p)[1] or ""):
            out.append(p)
    return out


def enviar(cfg: dict, para: list[str], r: dict, html_cid: str, texto: str, logo: bytes | None, pdf: bytes | None = None):
    msg = EmailMessage()
    msg["Subject"] = assunto(r)
    nome, end = parseaddr(cfg["remetente"])
    msg["From"] = formataddr((nome or "ANAX · Painel de Leads", end))
    msg["To"] = ", ".join(para)
    msg.set_content(texto)
    msg.add_alternative(html_cid, subtype="html")
    if logo:
        msg.get_payload()[1].add_related(logo, maintype="image", subtype="png", cid="<logo-anax>")
    if pdf:
        msg.add_attachment(pdf, maintype="application", subtype="pdf", filename=nome_pdf(r))
    porta, seg = int(cfg["porta"]), str(cfg["seguranca"]).lower()
    ctx = ssl.create_default_context()
    if seg == "ssl":
        srv = smtplib.SMTP_SSL(cfg["host"], porta, context=ctx, timeout=30)
    else:
        srv = smtplib.SMTP(cfg["host"], porta, timeout=30)
        if seg == "starttls":
            srv.starttls(context=ctx)
    with srv:
        if cfg.get("usuario"):
            srv.login(cfg["usuario"], cfg.get("senha", ""))
        srv.send_message(msg)


