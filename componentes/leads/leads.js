/* Painel de Leads ANAX — componente do Streamlit (HTML + CSS + JS, sem build).
   Lead = fornecedor (CNPJ). Dentro dele, os PROCESSOS a pagar pela LCM; dentro de cada processo, as parcelas.
   A proposta (margem negociada e situação) é feita por parcela.
   Recebe do Python: dados, crm, propostas, notas, docs, download, params, meta, usuario.
   Envia também: usuario, carregar_uau, planilha, params (tabela de taxas) e resumo.
   Devolve eventos {id, acao, ...}: etapa, proposta, proposta_status, dados, nota_add, nota_del, doc_add, doc_del, doc_baixar. */
(() => {
'use strict';

/* ---------- protocolo de componente do Streamlit ---------- */
const STL = {
  send(type, data) { window.parent.postMessage(Object.assign({ isStreamlitMessage: true, type }, data || {}), '*'); },
  ready() { this.send('streamlit:componentReady', { apiVersion: 1 }); },
  height(h) { this.send('streamlit:setFrameHeight', { height: h }); },
  value(v) { this.send('streamlit:setComponentValue', { value: v, dataType: 'json' }); },
};
const evento = (acao, dados) => STL.value(Object.assign({ id: Date.now().toString(36) + Math.random().toString(36).slice(2, 7), acao, quem: (typeof S !== 'undefined' && S.usuario) || '' }, dados));

/* ---------- utilidades ---------- */
const $ = s => document.querySelector(s);
const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const digits = s => String(s == null ? '' : s).replace(/\D/g, '');
const r2 = x => Math.round((x + Number.EPSILON) * 100) / 100;
const dayN = iso => { const [y, m, d] = iso.split('-').map(Number); return Math.round(Date.UTC(y, m - 1, d) / 864e5); };
const diffDays = (a, b) => dayN(b) - dayN(a);
const todayISO = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const addDays = (iso, n) => { const [y, m, d] = iso.split('-').map(Number); return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10); };
const fData = iso => { if (!iso) return '—'; const s = String(iso).slice(0, 10).split('-'); return s.length === 3 ? `${s[2]}/${s[1]}/${s[0]}` : String(iso); };
const fCurta = iso => { if (!iso) return '—'; const s = String(iso).slice(0, 10).split('-'); return `${s[2]}/${s[1]}`; };
const fTS = iso => { if (!iso) return '—'; const d = new Date(String(iso).replace(' ', 'T')); return isNaN(d) ? String(iso) : d.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }); };
const BRL = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });
const brl = n => BRL.format(Number(n) || 0);
const pct = n => (Number(n) || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + '%';
const fN = n => Number(n || 0).toLocaleString('pt-BR');
const fK = v => v >= 1e6 ? 'R$ ' + (v / 1e6).toLocaleString('pt-BR', { maximumFractionDigits: 2 }) + ' mi' : v >= 1e4 ? 'R$ ' + (v / 1e3).toLocaleString('pt-BR', { maximumFractionDigits: 1 }) + ' mil' : brl(v);
const fTam = b => b >= 1048576 ? (b / 1048576).toLocaleString('pt-BR', { maximumFractionDigits: 1 }) + ' MB' : Math.max(1, Math.round(b / 1024)) + ' KB';
const plural = (n, um, varios) => `${fN(n)} ${n === 1 ? um : varios}`;
const norm = s => String(s == null ? '' : s).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
const parseBR = s => { s = String(s == null ? '' : s).trim().replace(/%/g, ''); if (!s) return NaN; return s.includes(',') ? Number(s.replace(/\./g, '').replace(',', '.')) : Number(s); };
const fmtTaxa = v => String(r2(Number(v))).replace('.', ',');
const RO = () => !!(S.meta && S.meta.somenteLeitura);  // modo consulta: só lê o UAU, não grava nada
const tag = (t, k) => `<span class="tag ${k || ''}">${esc(t)}</span>`;
const cp = t => `<button class="copy" type="button" data-act="copy" data-t="${esc(t)}">copiar</button>`;
const getPath = (o, p) => p.split('.').reduce((x, k) => x == null ? x : x[k], o);
const setPath = (o, p, v) => { const k = p.split('.'); let x = o; for (let i = 0; i < k.length - 1; i++) { if (x[k[i]] == null) x[k[i]] = {}; x = x[k[i]]; } x[k[k.length - 1]] = v; };
let tt = 0;
function toast(m, k) { const t = $('#toast'); t.textContent = m; t.className = 'toast on ' + (k || ''); clearTimeout(tt); tt = setTimeout(() => { t.className = 'toast'; }, 3500); }
async function copy(t) { try { await navigator.clipboard.writeText(t); toast('Copiado.', 'ok'); } catch (e) { toast('Não deu para copiar. Selecione o texto: ' + t, 'bad'); } }
function campo(bind, label, o) { o = o || {}; const id = 'f_' + bind.replace(/\W/g, '_'); const v = getPath(S, bind);
  return `<div class="fld ${o.cls || ''}"><label for="${id}">${esc(label)}</label>${o.area ? `<textarea id="${id}" data-bind="${bind}"${o.ph ? ` placeholder="${esc(o.ph)}"` : ''}>${esc(v || '')}</textarea>` : `<input id="${id}" data-bind="${bind}" type="${o.type || 'text'}" value="${esc(v == null ? '' : v)}"${o.ph ? ` placeholder="${esc(o.ph)}"` : ''}${o.live ? ' data-live="1"' : ''} autocomplete="off">`}${o.hint ? `<span class="hint">${o.hint}</span>` : ''}</div>`; }

/* ---------- tabela de taxas (mesma regra do Portal ANAX) ---------- */
const DEF = { taxaBase: 3.5, ajPorte: { pequeno: 0.7, medio: 0, grande: -0.3 }, ajScore: { baixo: 0, medio: 0.3, alto: 0.8 }, faixaPequenoAte: 100000, faixaMedioAte: 500000, taxaMinima: 3.0, prazoMax: 120, grupo: [] };
const portePor = (vol, p) => vol <= p.faixaPequenoAte ? 'pequeno' : vol <= p.faixaMedioAte ? 'medio' : 'grande';
function taxaTabela(vol, p) { const porte = portePor(vol, p), bruta = r2(p.taxaBase + p.ajPorte[porte] + p.ajScore.medio); return { taxa: Math.max(p.taxaMinima, bruta), porte }; }
const calc = (valor, dias, taxa) => { const d = r2(valor * taxa / 100 * dias / 30); return { desc: d, liq: r2(valor - d) }; };

/* ---------- etapas e propostas ---------- */
const ETAPAS = [['novo', 'Novo'], ['contatado', 'Contatado'], ['negociando', 'Em negociação'], ['cadastro', 'Cadastro enviado'], ['ativo', 'Ativo']];
const ET_CURTO = { novo: 'Novo', contatado: 'Contatado', negociando: 'Negociação', cadastro: 'Cadastro', ativo: 'Ativo' };
const ET_L = Object.assign(Object.fromEntries(ETAPAS), { perdido: 'Perdido' });
const ET_ORD = ['novo', 'contatado', 'negociando', 'cadastro', 'ativo', 'perdido'];
const ET_COR = { novo: '', contatado: 'gold', negociando: 'warn', cadastro: 'gold', ativo: 'ok', perdido: 'bad' };
const etTag = e => tag(ET_L[e] || e, ET_COR[e]);
const PROP = { negociando: ['Proposta em negociação', 'warn'], aceita: ['Proposta aceita', 'ok'], recusada: ['Proposta recusada', 'bad'] };

/* ---------- perfil ideal de cliente ----------
   O pagamento já está aprovado no UAU, então o risco de crédito é da LCM. O que muda a chance de fechar é
   (1) quanto o fornecedor ganha em antecipar, (2) se o ticket paga o custo da operação e (3) quanto ele precisa de caixa. */
const PERFIL_DEF = { dMin: 15, dMax: 90, vMin: 20000, vMax: 500000 };
const FAIXAS = { ideal: ['Perfil ideal', 'ok'], bom: ['Bom potencial', 'gold'], baixa: ['Baixa prioridade', 'plain'], fora: ['Fora do perfil', 'bad'] };
const FX_ORD = ['ideal', 'bom', 'baixa', 'fora'];
const EXCLUI = [
  ['Órgão público, tributo ou entidade', /receita federal|secretaria|prefeitura|municipio d|fazenda|\binss\b|detran|tribunal|ministerio|cartorio|tabelionato|servico autonomo|autarquia|sindicato|conselho regional|federacao|confederacao/, 'Pagamento de tributo ou contribuição: não há empresa para vender a antecipação.'],
  ['Banco, seguradora ou financeira', /\bbanco\b|financeira|seguro|seguradora|leasing|credito|capitaliza|investimentos|caixa economica|sicoob|sicredi|previdencia|administradora de consorcio|pagseguro|corretora/, 'Instituição financeira tem custo de dinheiro menor que a nossa taxa.'],
  ['Consórcio ou SCP de obra', /consorcio|\bscp\b/, 'Consórcio ou SCP é parceiro da obra, não fornecedor.'],
  ['Em recuperação judicial', /recuperacao judicial|massa falida|\bfalida\b/, 'Empresa em recuperação judicial: a cessão do crédito depende do processo judicial.'],
  ['Concessionária de serviço público', /cemig|copel|energisa|equatorial|neoenergia|eletrobras|\benel\b|cpfl|distribui\w* de energia|telefonica|telecom|\bclaro\b|\bvivo\b|sabesp|copasa|embasa|cagece|corsan|agua e esgoto/, 'Concessionária grande, com caixa e crédito próprios.'],
];
const SETORES = [
  ['Locação de máquinas e equipamentos', /locac|locad|aluguel|guindast|maquina|equipament|trator/],
  ['Transporte e logística', /transport|logistic|caminh|frete|cargas/],
  ['Combustíveis e lubrificantes', /combust|\bposto\b|diesel|lubrific|petroleo|derivados/],
  ['Peças, pneus e manutenção', /pecas|autopeca|pneu|recauchut|mecanic|manuten|oficina|retifica|hidraul|usinagem|solda|metalurg/],
  ['Materiais de construção', /materia|ferrag|ferrament|madeir|cimento|tubos|eletric/],
  ['Mineração, brita e asfalto', /minera|pedreira|brita|areia|asfalt|quimica/],
  ['Serviços de obra e engenharia', /engenharia|constru|terraplan|concret|paviment|drenag|fundac|sondagem|topograf|sinaliz|empreiteir|obras/],
];
const RE_GRANDE = /(\bs\/a\b|\bs\.a\b\.?|\bs a$|\bsa$|\bcompanhia\b|\bcia\b)/;
const RE_PEQUENA = /\b(me|epp|eireli|slu|mei)\b/;
const autorizado = l => !l.processo_status || /aprovad/i.test(l.processo_status);
const perfilCfg = () => Object.assign({}, PERFIL_DEF, S.ui.perfil || {});
const anos = iso => iso ? diffDays(iso, todayISO()) / 365.25 : null;
const kBRL = v => v >= 1e6 ? 'R$ ' + (v / 1e6).toLocaleString('pt-BR', { maximumFractionDigits: 1 }) + ' mi' : v >= 1e3 ? 'R$ ' + Math.round(v / 1e3).toLocaleString('pt-BR') + ' mil' : brl(v);
function avaliar(f) {
  const C = perfilCfg(), p = S.params, nome = norm(f.nome), M = [];
  const add = (s, pts, c, t) => M.push({ s, pts, c, t });
  const el = f.todas.filter(l => l._ok && autorizado(l));
  const v = el.reduce((a, l) => a + l.processo_valor, 0);
  const d = v ? el.reduce((a, l) => a + l.processo_valor * l.dias_pagamento, 0) / v : 0;
  const receita = el.reduce((a, l) => a + l._des, 0);
  const base = { nota: 0, faixa: 'fora', motivos: M, valor: v, dias: d, receita, nEl: el.length, setor: null };
  let exc = null;
  if (f.interno) exc = ['Empresa do grupo LCM', 'Pagamento interno do grupo: não se antecipa para o próprio grupo.'];
  else if (digits(f.doc).length <= 11) exc = ['Pessoa física', 'Pessoa física: a cessão de crédito exige outro contrato e o perfil é diferente (terrenos, aluguéis, serviços avulsos).'];
  else { const e = EXCLUI.find(x => x[1].test(nome)); if (e) exc = [e[0], e[2]]; }
  if (!exc && !el.length) exc = ['Nada no prazo', `Nenhuma parcela aprovada com pagamento nos próximos ${p.prazoMax} dias.`];
  if (exc) { add(-1, 0, exc[0], exc[1]); return base; }
  // 1. prazo até o pagamento (25)
  const dd = Math.round(d);
  if (d >= C.dMin && d <= C.dMax) add(1, 25, `Recebe em ${dd} dias`, `Recebe em ${dd} dias, em média: antecipar adianta quase ${dd >= 45 ? Math.round(dd / 30) + ' meses' : dd + ' dias'} de caixa.`);
  else if (d > C.dMax) add(0, 18, `Recebe em ${dd} dias`, `Prazo longo (${dd} dias): ele ganha muito em antecipar, mas o deságio fica mais alto.`);
  else if (d >= 8) add(0, 12, `Recebe em ${dd} dias`, `Recebe em ${dd} dias: o ganho em antecipar é pequeno.`);
  else add(-1, 3, `Recebe em ${dd} dias`, `Recebe em até 7 dias: quase não há o que antecipar.`);
  // 2. valor autorizado no prazo (20)
  if (v >= C.vMin && v <= C.vMax) add(1, 20, `${kBRL(v)} no prazo`, `${brl(v)} aprovados no prazo: o valor compensa o custo da operação.`);
  else if (v > C.vMax) add(0, 12, `${kBRL(v)} no prazo`, `${brl(v)} no prazo: conta grande, exige mais recurso e negociação mais dura.`);
  else if (v >= C.vMin / 4) add(0, 8, `${kBRL(v)} no prazo`, `${brl(v)} no prazo: valor baixo para uma operação sozinha.`);
  else add(-1, 0, `${kBRL(v)} no prazo`, `Só ${brl(v)} no prazo: não paga o custo da operação.`);
  // 3. porte (15)
  if (RE_GRANDE.test(nome)) add(-1, 3, 'Grande empresa', 'Sociedade anônima: costuma ter crédito bancário barato e tesouraria própria.');
  else if (RE_PEQUENA.test(nome)) add(1, 15, 'Pequena empresa', 'Pequena empresa (ME, EPP ou EIRELI): o crédito no banco é caro ou difícil.');
  else add(1, 12, 'Pequeno ou médio porte', 'Limitada de pequeno ou médio porte: nossa taxa concorre com o capital de giro do banco.');
  // 4. setor (15)
  const st = SETORES.find(x => x[1].test(nome)); base.setor = st ? st[0] : null;
  if (st) add(1, 15, st[0], `${st[0]}: paga diesel, peças e equipe antes de receber.`);
  else add(0, 5, 'Setor não identificado', 'O nome não indica um setor que usa muito capital de giro.');
  // 5. recorrência (10)
  const nProc = f.procs.length, nObra = new Set(f.todas.map(l => l.processo_obra)).size;
  if (nProc >= 5 || nObra >= 2) add(1, 10, `${nProc} processos, ${plural(nObra, 'obra', 'obras')}`, `${plural(nProc, 'processo', 'processos')} em ${plural(nObra, 'obra', 'obras')}: relação recorrente com a LCM, dá para operar de novo.`);
  else if (nProc >= 2) add(0, 6, `${nProc} processos`, `${nProc} processos: alguma recorrência com a LCM.`);
  else add(0, 2, '1 processo', 'Um processo só: operação pontual.');
  // 6. espera entre a NF e o pagamento (5)
  const sp = el.filter(l => l.nf_emissao && l.processo_pagamento).map(l => diffDays(l.nf_emissao, l.processo_pagamento));
  const esp = sp.length ? Math.round(sp.reduce((a, b) => a + b, 0) / sp.length) : null;
  if (esp != null && esp >= 45) add(1, 5, `Espera ${esp} dias`, `Espera em média ${esp} dias entre a NF e o pagamento.`);
  else add(0, 2, esp != null ? `Espera ${esp} dias` : 'Sem data da NF', esp != null ? `Espera ${esp} dias entre a NF e o pagamento.` : 'Sem a data da NF para medir a espera.');
  // 7. tempo de empresa (5)
  const a = anos(f.base.fornecedor_abertura);
  if (a != null && a >= 1 && a <= 10) add(1, 5, `${Math.floor(a)} ${Math.floor(a) === 1 ? 'ano' : 'anos'} de empresa`, `Empresa com ${Math.floor(a)} ${Math.floor(a) === 1 ? 'ano' : 'anos'}: fase de crescimento, caixa mais apertado.`);
  else if (a != null && a < 1) add(0, 3, 'Menos de 1 ano', 'Empresa com menos de 1 ano: pedir documentos com mais cuidado.');
  else if (a != null) add(0, 2, `${Math.floor(a)} anos de empresa`, `Empresa com ${Math.floor(a)} anos: mais estruturada, menos dependente de antecipação.`);
  else add(0, 2, 'Sem data de abertura', 'Sem a data de abertura da empresa.');
  // 8. contato (5)
  const tel = ef(f.base, 'telefone', 'fornecedor_telefone'), mail = ef(f.base, 'email', 'fornecedor_email');
  if (tel) add(1, 5, 'Tem telefone', 'Telefone no cadastro: dá para abordar direto.');
  else if (mail) add(0, 3, 'Só e-mail', 'Só e-mail no cadastro: abordagem mais lenta.');
  else add(-1, 0, 'Sem contato', 'Sem telefone nem e-mail no cadastro.');
  const naoAut = f.todas.filter(l => l._ok && !autorizado(l)).length;
  if (naoAut) add(0, 0, `${naoAut} aguardando aprovação`, `${plural(naoAut, 'parcela ainda não aprovada', 'parcelas ainda não aprovadas')} para emissão: fica fora da conta até aprovar.`);
  base.nota = Math.min(100, M.reduce((x, m) => x + m.pts, 0));
  const prazoOk = M[0].pts >= 18, valorOk = M[1].pts >= 12;
  base.faixa = base.nota >= 75 && prazoOk && valorOk ? 'ideal' : base.nota >= 55 ? 'bom' : 'baixa';
  return base;
}
const fxTag = pf => tag(FAIXAS[pf.faixa][0], FAIXAS[pf.faixa][1]);
const notaPill = pf => `<span class="np ${pf.faixa}" title="${esc(FAIXAS[pf.faixa][0])}">${pf.faixa === 'fora' ? '—' : pf.nota}</span>`;
const motIc = s => s > 0 ? '✓' : s < 0 ? '✕' : '•';
function motivosHTML(pf, curto) {
  return `<ul class="mot${curto ? ' curto' : ''}">${pf.motivos.map(m => `<li class="${m.s > 0 ? 'pos' : m.s < 0 ? 'neg' : 'neu'}"${curto ? ` title="${esc(m.t)}"` : ''}><i>${motIc(m.s)}</i><span>${esc(curto ? m.c : m.t)}</span>${curto || !m.pts && m.s >= 0 ? '' : `<em>${m.pts}</em>`}</li>`).join('')}</ul>`;
}

/* ---------- campos de filtro (por parcela) ---------- */
const CAMPOS = [
  { key: 'fornecedor_razao', label: 'Fornecedor', group: 'Fornecedor', type: 'text' },
  { key: 'fornecedor_cnpj', label: 'CNPJ/CPF', group: 'Fornecedor', type: 'text' },
  { key: 'fornecedor_uf', label: 'UF', group: 'Fornecedor', type: 'enum' },
  { key: 'fornecedor_cidade', label: 'Cidade', group: 'Fornecedor', type: 'enum' },
  { key: 'fornecedor_risco_sacado', label: 'Habilitado a risco sacado', group: 'Fornecedor', type: 'enum' },
  { key: 'processo_numero', label: 'Nº do processo', group: 'Processo', type: 'text' },
  { key: 'processo_empresa', label: 'Empresa', group: 'Processo', type: 'enum' },
  { key: 'processo_obra', label: 'Obra', group: 'Processo', type: 'enum' },
  { key: 'processo_status', label: 'Conferência', group: 'Processo', type: 'enum' },
  { key: 'processo_forma_pagamento', label: 'Forma de pagamento', group: 'Processo', type: 'enum' },
  { key: 'processo_pagamento', label: 'Pagamento previsto', group: 'Processo', type: 'date' },
  { key: 'dias_pagamento', label: 'Dias até o pagamento', group: 'Processo', type: 'number' },
  { key: 'processo_valor', label: 'Valor da parcela', group: 'Processo', type: 'money' },
  { key: 'nf_numero', label: 'Nº da NF', group: 'Nota fiscal', type: 'text' },
  { key: 'nf_emissao', label: 'Emissão da NF', group: 'Nota fiscal', type: 'date' },
  { key: 'nf_valor', label: 'Valor da NF', group: 'Nota fiscal', type: 'money' },
];
const CF = Object.fromEntries(CAMPOS.map(c => [c.key, c]));
const FACETAS = ['processo_empresa', 'processo_forma_pagamento', 'processo_status', 'fornecedor_uf'];
const OPS = {
  text: [['contem', 'contém'], ['nao_contem', 'não contém'], ['igual', 'é igual a']],
  number: [['gte', '≥'], ['lte', '≤'], ['eq', '='], ['entre', 'entre']],
  money: [['gte', 'a partir de'], ['lte', 'até'], ['entre', 'entre']],
  date: [['proximos', 'nos próximos N dias'], ['antes', 'antes de'], ['depois', 'depois de'], ['entre', 'entre']],
  enum: [['em', 'é um de'], ['nao_em', 'não é']] };
const ORDENS = [['perfil', 'Melhor perfil'], ['receita', 'Maior receita potencial'], ['maior', 'Maior processo'], ['prox', 'Pagamento mais próximo'], ['propostas', 'Com propostas primeiro'], ['nome', 'Nome A–Z'], ['atual', 'Atualizados por último']];
const RAIZ_LCM = '19758842';
const PERFIS_F = [['todos', 'Todos os perfis'], ['ideal', 'Só perfil ideal'], ['bom', 'Ideal e bom potencial'], ['baixa', 'Baixa prioridade'], ['fora', 'Fora do perfil']];
const EDITAVEIS = [['contato', 'Contato', 'fornecedor_contato'], ['telefone', 'Telefone', 'fornecedor_telefone'], ['email', 'E-mail', 'fornecedor_email'], ['cidade', 'Cidade', 'fornecedor_cidade'], ['uf', 'UF', 'fornecedor_uf'], ['responsavel', 'Responsável na ANAX', null]];

/* ---------- estado ---------- */
const LS = 'anax-leads-ui-v5';
const S = { params: { ...DEF }, rows: [], versao: null, crm: {}, propostas: {}, notas: {}, docs: {}, meta: {}, alt: 860, usuario: '', dlVisto: null,
  pend: {}, pendP: {}, modal: null, form: null,
  ui: { aba: 'leads', q: '', etapa: 'todas', ordem: 'perfil', perfilF: 'todos', perfil: { ...PERFIL_DEF }, pfFx: 'ideal', pfOrd: 'nota', pfLim: 60, ocultarInternos: true, facets: {}, rules: [], filtros: false, fq: {}, rd: null, lim: 80, sel: null, tab: 'resumo', nota: '', opsSt: 'negociando' } };
try { const x = JSON.parse(localStorage.getItem(LS) || 'null'); if (x) Object.assign(S.ui, { q: x.q || '', etapa: x.etapa || 'todas', ordem: ORDENS.some(o => o[0] === x.ordem) ? x.ordem : 'perfil', ocultarInternos: x.ocultarInternos !== false, facets: x.facets || {}, rules: x.rules || [], opsSt: x.opsSt || 'negociando', esq: Number(x.esq) || null, perfilF: x.perfilF || 'todos', perfil: Object.assign({}, PERFIL_DEF, x.perfil || {}), pfFx: x.pfFx || 'ideal', pfOrd: x.pfOrd || 'nota' }); } catch (e) {}
function salvarUI() { try { const u = S.ui; localStorage.setItem(LS, JSON.stringify({ q: u.q, etapa: u.etapa, ordem: u.ordem, ocultarInternos: u.ocultarInternos, facets: u.facets, rules: u.rules, opsSt: u.opsSt, esq: u.esq, perfilF: u.perfilF, perfil: u.perfil, pfFx: u.pfFx, pfOrd: u.pfOrd })); } catch (e) {} }

/* ---------- dados ---------- */
function prepara(pk) {
  const hoje = todayISO();
  return (pk.rows || []).map(a => {
    const l = Object.fromEntries(pk.cols.map((c, i) => [c, a[i]]));
    l._cnpj = digits(l.fornecedor_cnpj);
    l._proc = [l.processo_empresa, l.processo_obra, l.processo_numero].join('|');
    l._parcN = parseInt(String(l.processo_parcela || '').split('/')[0], 10) || 0;
    l.dias_pagamento = l.processo_pagamento ? diffDays(hoje, l.processo_pagamento) : null;
    l.dias_emissao = l.nf_emissao ? diffDays(l.nf_emissao, hoje) : null;
    l._busca = norm([l.fornecedor_razao, l.fornecedor_cnpj, l.fornecedor_cidade, l.fornecedor_email, l.processo_empresa, l.processo_obra].join(' '));
    l._dig = [l.fornecedor_cnpj, l.processo_numero, l.nf_numero, l.nf_chave].map(digits).join(' ');
    l.interno = l._cnpj.startsWith(RAIZ_LCM) || /\bAPORTE\b|\bLCM\b/i.test(l.fornecedor_razao || '') || (S.params.grupo || []).map(digits).includes(l._cnpj);
    return l;
  });
}
const crmDe = c => S.crm[c] || {};
const etapaDe = c => S.pend[c] || crmDe(c).etapa || 'novo';
const propDe = id => (id in S.pendP) ? S.pendP[id] : (S.propostas[id] || null);
const ef = (l, k, uau) => { const v = crmDe(l._cnpj)[k]; return v != null && v !== '' ? v : (uau ? l[uau] : null); };
const rotulo = l => `Processo ${l.processo_numero} · parcela ${l.processo_parcela || '—'}`;
const onde = (emp, obra) => { const e = String(emp || '').trim(), o = String(obra || '').trim(); return esc(!o || o === e ? e : e ? e + ' · ' + o : o); };
const local = l => [ef(l, 'cidade', 'fornecedor_cidade'), ef(l, 'uf', 'fornecedor_uf')].filter(Boolean).join('/');

/* agrupa parcelas em processos (o que a LCM paga ao fornecedor) */
function processos(ls) {
  const m = new Map();
  ls.forEach(l => { let p = m.get(l._proc); if (!p) { p = { key: l._proc, numero: l.processo_numero, empresa: l.processo_empresa, obra: l.processo_obra, ps: [], valor: 0, prox: null, nOk: 0, nProp: 0, nfs: [] }; m.set(l._proc, p); }
    p.ps.push(l); p.valor += l.processo_valor || 0; if (l._ok) p.nOk++; if (l._prop && l._prop.status === 'negociando') p.nProp++;
    if (l.nf_numero != null && !p.nfs.includes(String(l.nf_numero))) p.nfs.push(String(l.nf_numero));
    if (l.processo_pagamento && l.dias_pagamento > 0 && (!p.prox || l.processo_pagamento < p.prox)) p.prox = l.processo_pagamento; });
  const out = [...m.values()]; out.forEach(p => p.ps.sort((a, b) => a._parcN - b._parcN));
  return out.sort((a, b) => (a.prox || '9999').localeCompare(b.prox || '9999') || String(a.numero).localeCompare(String(b.numero), 'pt-BR', { numeric: true }));
}
let CACHE = null;
function porFornecedor() {
  if (CACHE) return CACHE;
  const p = S.params, m = new Map();
  S.rows.forEach(l => { let f = m.get(l._cnpj); if (!f) { f = { cnpj: l._cnpj, nome: l.fornecedor_razao, doc: l.fornecedor_cnpj, base: l, todas: [], volume: 0, interno: l.interno }; m.set(l._cnpj, f); } f.todas.push(l); f.volume += l.processo_valor || 0; });
  m.forEach(f => {
    const tab = taxaTabela(f.volume, p); f.tabela = tab.taxa; f.porte = tab.porte;
    f.todas.forEach(l => {
      const d = l.dias_pagamento; l._ok = d != null && d > 0 && d <= p.prazoMax && l.processo_valor > 0;
      const pr = propDe(l.lead_id); l._prop = pr && pr.status ? pr : null; l._taxa = l._prop ? Number(l._prop.margem) : tab.taxa;
      if (l._ok) { const c = calc(l.processo_valor, d, l._taxa); l._des = c.desc; l._liq = c.liq; } else { l._des = 0; l._liq = 0; }
    });
    f.procs = processos(f.todas);
    f.etapa = etapaDe(f.cnpj); f.atual = crmDe(f.cnpj).atualizado_em || '';
    f.nProp = f.todas.filter(l => l._prop && l._prop.status === 'negociando').length;
    f.nOk = f.todas.filter(l => l._ok).length;
  });
  m.forEach(f => { f.perfil = avaliar(f); });
  CACHE = m; return m;
}
const invalida = () => { CACHE = null; };

/* ---------- filtros ---------- */
function testa(l, r) {
  const f = CF[r.key]; if (!f) return true; let v = l[r.key];
  if (f.type === 'text') { const a = norm(v), b = norm(r.v1); return r.op === 'contem' ? a.includes(b) : r.op === 'nao_contem' ? !a.includes(b) : a === b; }
  if (f.type === 'number' || f.type === 'money') { if (v == null) return false; v = Number(v); const a = Number(r.v1), b = Number(r.v2); return ({ eq: v === a, gte: v >= a, lte: v <= a, entre: v >= Math.min(a, b) && v <= Math.max(a, b) })[r.op] ?? true; }
  if (f.type === 'date') { if (!v) return false; const h = todayISO(); if (r.op === 'proximos') return v >= h && v <= addDays(h, Number(r.v1)); if (r.op === 'antes') return v < r.v1; if (r.op === 'depois') return v > r.v1; const a = r.v1 < r.v2 ? r.v1 : r.v2, b = r.v1 < r.v2 ? r.v2 : r.v1; return v >= a && v <= b; }
  const has = (r.vals || []).includes(String(v == null ? '' : v)); return r.op === 'nao_em' ? !has : has;
}
function passaParcela(l, exceto) {
  const u = S.ui;
  if (u.ocultarInternos && l.interno) return false;
  const q = u.q.trim(); if (q && !norm(q).split(/\s+/).filter(Boolean).every(t => { const d = t.replace(/\D/g, ''); return l._busca.includes(t) || (d.length >= 3 && l._dig.includes(d)); })) return false;
  if (!u.rules.every(r => testa(l, r))) return false;
  return Object.entries(u.facets).every(([k, vs]) => k === exceto || !vs || !vs.length || vs.includes(String(l[k] == null ? '' : l[k])));
}
function valores(key) { return [...new Set(S.rows.map(l => l[key]).filter(v => v != null && v !== ''))].map(String).sort((a, b) => a.localeCompare(b, 'pt-BR', { numeric: true })); }
function descreve(r) { const f = CF[r.key]; if (!f) return esc(r.key); const op = ((OPS[f.type].find(o => o[0] === r.op)) || [])[1] || r.op; const fm = v => f.type === 'money' ? brl(Number(v)) : f.type === 'date' ? fData(v) : esc(v);
  if (f.type === 'enum') return `<em>${esc(f.label)}</em> ${esc(op)} ${esc((r.vals || []).slice(0, 2).join(', '))}${(r.vals || []).length > 2 ? ' +' + (r.vals.length - 2) : ''}`;
  if (r.op === 'proximos') return `<em>${esc(f.label)}</em> nos próximos ${esc(r.v1)} dias`;
  return `<em>${esc(f.label)}</em> ${esc(op)} ${r.op === 'entre' ? fm(r.v1) + ' e ' + fm(r.v2) : fm(r.v1)}`; }

/* leads visíveis: parcelas filtradas, agrupadas por fornecedor e processo */
function leadsVisiveis() {
  const u = S.ui, cont = { todas: 0 }; ET_ORD.forEach(e => { cont[e] = 0; });
  const out = [];
  porFornecedor().forEach(f => {
    const ps = f.todas.filter(l => passaParcela(l)); if (!ps.length) return;
    const fx = f.perfil.faixa, pf = u.perfilF;
    if (pf !== 'todos' && !(pf === 'bom' ? fx === 'ideal' || fx === 'bom' : fx === pf)) return;
    cont.todas++; cont[f.etapa] = (cont[f.etapa] || 0) + 1;
    if (u.etapa !== 'todas' && f.etapa !== u.etapa) return;
    const pr = processos(ps);
    out.push({ f, ps, nProc: pr.length, maior: Math.max(...pr.map(p => p.valor)), prox: pr.map(p => p.prox).filter(Boolean).sort()[0] || null });
  });
  const ord = { perfil: (a, b) => b.f.perfil.nota - a.f.perfil.nota || b.f.perfil.receita - a.f.perfil.receita, receita: (a, b) => b.f.perfil.receita - a.f.perfil.receita, maior: (a, b) => b.maior - a.maior, prox: (a, b) => (a.prox || '9999').localeCompare(b.prox || '9999'), propostas: (a, b) => b.f.nProp - a.f.nProp || b.maior - a.maior, nome: (a, b) => a.f.nome.localeCompare(b.f.nome, 'pt-BR'), atual: (a, b) => (b.f.atual || '').localeCompare(a.f.atual || '') || b.maior - a.maior }[u.ordem] || (() => 0);
  out.sort(ord);
  return { out, cont };
}

/* ---------- ações que vão para o Python ---------- */
function mudarEtapa(cnpj, para) {
  const de = etapaDe(cnpj); if (de === para) return;
  if (para === 'negociando' && !porFornecedor().get(cnpj).nProp) { abrirProposta(cnpj, null, para); return; }
  S.pend[cnpj] = para; invalida();
  evento('etapa', { cnpj, de, para, nome: porFornecedor().get(cnpj)?.nome || '' });
  toast(`Etapa: ${ET_L[para]}.`, 'ok'); render();
}
function abrirProposta(cnpj, soId, para) {
  const f = porFornecedor().get(cnpj); if (!f) return;
  const itens = {}, elegiveis = f.todas.filter(l => l._ok && (!soId || l.lead_id === soId));
  if (!elegiveis.length) { toast(`Nenhuma parcela dentro do prazo de ${S.params.prazoMax} dias para propor.`, 'bad'); return; }
  elegiveis.forEach(l => { const pr = l._prop;
    itens[l.lead_id] = { on: soId || elegiveis.length === 1 ? true : !!(pr && pr.status === 'negociando'), margem: fmtTaxa(pr ? pr.margem : f.tabela) }; });
  S.modal = { cnpj, para: para || null, so: soId || null, itens, todas: fmtTaxa(f.tabela), obs: '', err: '' };
  render();
}
function salvarProposta() {
  const M = S.modal; if (!M) return;
  const sel = Object.entries(M.itens).filter(([, i]) => i.on);
  if (!sel.length) { M.err = 'Marque pelo menos uma parcela.'; render(); return; }
  const ruins = sel.filter(([, i]) => { const v = parseBR(i.margem); return !(v > 0 && v <= 20); });
  if (ruins.length) { M.err = `Margem inválida em ${plural(ruins.length, 'parcela', 'parcelas')}: use % ao mês, entre 0 e 20.`; render(); return; }
  const f = porFornecedor().get(M.cnpj), por = Object.fromEntries(f.todas.map(l => [l.lead_id, l]));
  const itens = sel.map(([id, i]) => { const l = por[id]; return { lead_id: id, margem: r2(parseBR(i.margem) * 10000) / 10000, valor: l.processo_valor, pagamento: l.processo_pagamento, rotulo: rotulo(l) }; });
  itens.forEach(i => { S.pendP[i.lead_id] = Object.assign({}, propDe(i.lead_id), { margem: i.margem, status: 'negociando' }); });
  const de = etapaDe(M.cnpj), para = M.para || (de === 'novo' || de === 'contatado' ? 'negociando' : de);
  if (para !== de) S.pend[M.cnpj] = para;
  invalida();
  evento('proposta', { cnpj: M.cnpj, de, para, itens, obs: M.obs.trim(), nome: f.nome });
  toast(`Proposta salva em ${plural(itens.length, 'parcela', 'parcelas')}.`, 'ok');
  S.modal = null; render();
}
function statusProposta(id, status) {
  const l = S.rows.find(x => x.lead_id === id); if (!l) return; const pr = propDe(id);
  S.pendP[id] = status ? Object.assign({}, pr, { status }) : { status: null }; invalida();
  evento('proposta_status', { lead_id: id, cnpj: l._cnpj, status, rotulo: rotulo(l), nome: l.fornecedor_razao });
  toast(status === 'negociando' ? 'Proposta reaberta.' : status ? `${PROP[status][0]}.` : 'Proposta removida.', 'ok'); render();
}
function enviarDocs(files) {
  const c = S.ui.sel; if (!c || !files.length) return;
  const grandes = files.filter(f => f.size > 15 * 1048576); if (grandes.length) toast(`${grandes[0].name}: acima de 15 MB.`, 'bad');
  const ok = files.filter(f => f.size <= 15 * 1048576); if (!ok.length) return;
  Promise.all(ok.map(f => new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res({ nome: f.name, tipo: f.type || 'application/octet-stream', tamanho: f.size, b64: String(r.result).split(',')[1] || '' }); r.onerror = rej; r.readAsDataURL(f); })))
    .then(arqs => { evento('doc_add', { cnpj: c, arquivos: arqs }); toast(`Enviando ${plural(arqs.length, 'documento', 'documentos')}…`); })
    .catch(() => toast('Não consegui ler o arquivo.', 'bad'));
}
function baixar(d) {
  try { const bin = atob(d.b64), u8 = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
    const url = URL.createObjectURL(new Blob([u8], { type: d.tipo || 'application/octet-stream' })); const a = document.createElement('a'); a.href = url; a.download = d.nome || 'documento'; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 4000);
  } catch (e) { toast('Não consegui baixar o arquivo.', 'bad'); }
}

/* ---------- topo e filtros ---------- */
function topo() {
  let neg = 0; porFornecedor().forEach(f => { neg += f.nProp; });
  const m = S.meta || {};
  return avisoSQL() + `<div class="top"><div class="tabs" role="tablist">
  <button role="tab" type="button" aria-selected="${S.ui.aba === 'leads'}" data-act="aba" data-v="leads">Leads</button>
  <button role="tab" type="button" aria-selected="${S.ui.aba === 'perfil'}" data-act="aba" data-v="perfil">Perfil ideal</button>
  ${RO() ? '' : `<button role="tab" type="button" aria-selected="${S.ui.aba === 'ops'}" data-act="aba" data-v="ops">Minhas operações${neg ? `<span class="n">${neg}</span>` : ''}</button>`}</div>
  <div class="top-r"><div class="src">${esc(m.fonte || '')}${m.carregado ? ' · ' + fTS(m.carregado) : ''}<br>${esc(m.armazenamento || '')}</div>
  <div class="acoes-top"><button class="btn ghost sm" type="button" data-act="janela" data-v="base">Base de dados</button>
  <button class="btn ghost sm" type="button" data-act="janela" data-v="taxas">Taxas</button>
  ${m.login ? `${(m.firebase || {}).ligado ? `<button class="btn ghost sm conta" type="button" data-act="janela" data-v="nome" title="Conectado como ${esc(m.login.usuario)} · clique para mudar o nome">${esc(m.login.nome)}</button>` : `<span class="conta" title="Conectado como ${esc(m.login.usuario)}">${esc(m.login.nome)}</span>`}<button class="btn ghost sm" type="button" data-act="sair">Sair</button>`
    : `<button class="btn ghost sm quem${S.usuario ? '' : ' falta'}" type="button" data-act="janela" data-v="nome" title="Seu nome aparece nas notas, nas propostas e no resumo">${esc(S.usuario || 'Definir seu nome')}</button>`}
  ${RO() ? '' : '<button class="btn gold sm" type="button" data-act="resumo" title="Resumo executivo em PDF do dia, para mandar por e-mail">Enviar resumo do dia</button>'}</div></div></div>`;
}
function painelFiltros() {
  const u = S.ui; if (!u.filtros) return '';
  const fac = FACETAS.map(k => {
    const cont = {}; S.rows.forEach(l => { if (passaParcela(l, k)) { const v = String(l[k] == null ? '' : l[k]); cont[v] = (cont[v] || 0) + 1; } });
    const sel = new Set(u.facets[k] || []), all = valores(k), q = norm(u.fq[k] || ''), vs = all.filter(v => norm(v).includes(q));
    return `<div><p class="eyebrow">${esc(CF[k].label)}</p>${all.length > 8 ? `<input class="inp" id="f_fq_${k}" data-bind="ui.fq.${k}" data-live="1" placeholder="Procurar…" value="${esc(u.fq[k] || '')}" style="height:30px" aria-label="Procurar ${esc(CF[k].label)}">` : ''}
    <div class="opts">${vs.slice(0, 200).map(v => `<label class="opt${!cont[v] && !sel.has(v) ? ' zero' : ''}"><input type="checkbox" data-act="fac" data-k="${k}" data-v="${esc(v)}"${sel.has(v) ? ' checked' : ''}><span>${esc(v)}</span><small>${fN(cont[v] || 0)}</small></label>`).join('') || '<span class="hint">Nada encontrado.</span>'}</div></div>`; }).join('');
  let cond = '';
  if (u.rd) { const d = u.rd; if (d._k !== d.key) { d.op = OPS[CF[d.key].type][0][0]; d.v1 = ''; d.v2 = ''; d.vals = []; d._k = d.key; }
    const f = CF[d.key], ops = OPS[f.type]; if (!ops.some(o => o[0] === d.op)) d.op = ops[0][0];
    const grupos = [...new Set(CAMPOS.map(c => c.group))];
    let val;
    if (f.type === 'enum') { const s = new Set(d.vals); val = `<div class="opts">${valores(d.key).slice(0, 200).map(v => `<label class="opt"><input type="checkbox" data-act="rdVal" data-v="${esc(v)}"${s.has(v) ? ' checked' : ''}><span>${esc(v)}</span></label>`).join('')}</div>`; }
    else { const tp = f.type === 'date' && d.op !== 'proximos' ? 'date' : f.type === 'text' ? 'text' : 'number'; val = d.op === 'entre' ? `<div class="grid2">${campo('ui.rd.v1', 'De', { type: tp })}${campo('ui.rd.v2', 'Até', { type: tp })}</div>` : campo('ui.rd.v1', d.op === 'proximos' ? 'Dias' : 'Valor', { type: tp }); }
    cond = `<div class="full" style="border-top:1px solid var(--line);padding-top:var(--s4)"><p class="eyebrow">Nova condição</p><div class="grid2"><div class="fld"><label for="f_rk">Campo</label><select id="f_rk" data-bind="ui.rd.key">${grupos.map(g => `<optgroup label="${esc(g)}">${CAMPOS.filter(c => c.group === g).map(c => `<option value="${c.key}"${c.key === d.key ? ' selected' : ''}>${esc(c.label)}</option>`).join('')}</optgroup>`).join('')}</select></div><div class="fld"><label for="f_ro">Condição</label><select id="f_ro" data-bind="ui.rd.op">${ops.map(([k, t]) => `<option value="${k}"${k === d.op ? ' selected' : ''}>${esc(t)}</option>`).join('')}</select></div></div>
    <div style="margin-top:var(--s2)">${val}</div><div class="row" style="margin-top:var(--s3)"><button class="btn gold sm" type="button" data-act="rdOk">Aplicar condição</button><button class="btn ghost sm" type="button" data-act="rdX">Cancelar</button></div></div>`; }
  return `<div class="painel-f">${fac}<div><p class="eyebrow">Mais</p><label class="check"><input type="checkbox" data-act="internos"${u.ocultarInternos ? ' checked' : ''}><span>Ocultar lançamentos internos do grupo LCM</span></label>
  ${u.rd ? '' : '<div style="margin-top:var(--s3)"><button class="link" type="button" data-act="rdNovo">+ Condição em qualquer campo</button></div>'}</div>${cond}</div>`;
}
function chipsAtivos() {
  const u = S.ui, c = [];
  if (u.q.trim()) c.push(`<span class="chip"><span><em>Busca</em> “${esc(u.q.trim())}”</span><button type="button" data-act="rm" data-k="q" aria-label="Remover busca">×</button></span>`);
  Object.entries(u.facets).forEach(([k, vs]) => { if (vs && vs.length && CF[k]) c.push(`<span class="chip"><span><em>${esc(CF[k].label)}:</em> ${esc(vs.slice(0, 2).join(', '))}${vs.length > 2 ? ' +' + (vs.length - 2) : ''}</span><button type="button" data-act="rm" data-k="f:${k}" aria-label="Remover filtro">×</button></span>`); });
  u.rules.forEach(r => c.push(`<span class="chip"><span>${descreve(r)}</span><button type="button" data-act="rm" data-k="r:${esc(r.id)}" aria-label="Remover condição">×</button></span>`));
  if (u.perfilF !== 'todos') c.unshift(`<span class="chip"><span><em>Perfil:</em> ${esc(PERFIS_F.find(x => x[0] === u.perfilF)[1])}</span><button type="button" data-act="rm" data-k="perfil" aria-label="Remover filtro de perfil">×</button></span>`);
  return c.length ? `<div class="chips">${c.join('')}<button class="link" type="button" data-act="limpar">Limpar tudo</button></div>` : '';
}

/* ---------- tela de leads ---------- */
function telaLeads() {
  const u = S.ui, { out, cont } = leadsVisiveis();
  let nProc = 0, nProp = 0, desProp = 0; out.forEach(x => { nProc += x.nProc; x.ps.forEach(l => { if (l._prop && l._prop.status === 'negociando') { nProp++; desProp += l._des; } }); });
  const nf = Object.values(u.facets).filter(v => v && v.length).length + u.rules.length;
  if (u.sel && !out.some(x => x.f.cnpj === u.sel)) { u.sel = out.length ? out[0].f.cnpj : null; S.form = null; }
  if (!u.sel && out.length) u.sel = out[0].f.cnpj;
  const lista = out.length ? out.slice(0, u.lim).map(x => { const f = x.f, lc = local(f.base), nd = (S.docs[f.cnpj] || []).length, nn = (S.notas[f.cnpj] || []).filter(n => n.tipo !== 'sistema').length;
    return `<div class="lrow${u.sel === f.cnpj ? ' on' : ''}" data-act="sel" data-c="${f.cnpj}" tabindex="0" role="button" aria-pressed="${u.sel === f.cnpj}">
    <div class="lr-t"><b>${esc(f.nome)}</b>${notaPill(f.perfil)}</div>
    <div class="lr-s">${esc(f.doc)}${lc ? ' · ' + esc(lc) : ''} · ${plural(x.nProc, 'processo', 'processos')}</div>
    <div class="lr-m">${RO() ? '' : etTag(f.etapa)}${f.nProp ? tag(fN(f.nProp) + ' em proposta', 'gold') : ''}<span class="lr-i"><b>${pct(f.tabela)} a.m.</b> · ${[x.prox ? 'próx. pagamento ' + fCurta(x.prox) : '', 'maior ' + brl(x.maior), nd ? plural(nd, 'doc', 'docs') : '', nn ? plural(nn, 'nota', 'notas') : ''].filter(Boolean).join(' · ')}</span></div></div>`; }).join('')
    + (out.length > u.lim ? `<div class="mais"><button class="btn ghost sm" type="button" data-act="mais">Mostrar mais ${Math.min(80, out.length - u.lim)} de ${fN(out.length - u.lim)}</button></div>` : '')
    : `<div class="vazio"><strong>Nenhum lead com esses filtros</strong><button class="link" type="button" data-act="limpar">Limpar filtros</button></div>`;
  return `<div class="leads">
  <div class="kpis"><div class="kpi"><div class="k">Leads</div><div class="v">${fN(out.length)}</div></div><div class="kpi"><div class="k">Processos a receber</div><div class="v">${fN(nProc)}</div></div>${RO() ? `<div class="kpi hi"><div class="k">Aprovado no prazo</div><div class="v">${fK(out.reduce((a, x) => a + x.f.perfil.valor, 0))}</div></div><div class="kpi"><div class="k">Receita potencial</div><div class="v">${fK(out.reduce((a, x) => a + x.f.perfil.receita, 0))}</div></div></div>`
  : `<div class="kpi hi"><div class="k">Parcelas em proposta</div><div class="v">${fN(nProp)}</div></div><div class="kpi"><div class="k">Deságio das propostas</div><div class="v">${fK(desProp)}</div></div></div>`}
  <div class="tool"><input class="inp" type="search" id="f_q" data-bind="ui.q" data-live="1" placeholder="Buscar fornecedor, CNPJ, nº do processo, NF ou obra" value="${esc(u.q)}" aria-label="Buscar">
  <button class="fbtn${u.filtros || nf ? ' on' : ''}" type="button" data-act="filtros" aria-expanded="${u.filtros}">Filtros${nf ? ' · ' + nf : ''}</button>
  <select class="inp" id="f_perfilF" data-bind="ui.perfilF" aria-label="Perfil">${PERFIS_F.map(([k, t]) => `<option value="${k}"${u.perfilF === k ? ' selected' : ''}>${t}</option>`).join('')}</select>
  <select class="inp" id="f_ordem" data-bind="ui.ordem" aria-label="Ordenar">${ORDENS.map(([k, t]) => `<option value="${k}"${u.ordem === k ? ' selected' : ''}>${t}</option>`).join('')}</select></div>
  <div class="seg seg-etapa" role="group" aria-label="Etapa">${[['todas', 'Todas'], ...ETAPAS, ['perdido', 'Perdido']].map(([k, t]) => `<button type="button" data-act="etapaF" data-v="${k}" aria-pressed="${u.etapa === k}">${t}<span>${fN(cont[k] || 0)}</span></button>`).join('')}</div>
  ${painelFiltros()}${chipsAtivos()}
  <div class="split"${u.esq ? ` style="--esq:${u.esq}%"` : ''}><div class="lista">${lista}</div>
  <div class="divisor" role="separator" aria-orientation="vertical" aria-label="Largura da lista de leads" aria-valuemin="${ESQ_MIN}" aria-valuemax="${ESQ_MAX}" aria-valuenow="${Math.round(u.esq || ESQ_PADRAO)}" tabindex="0" title="Arraste para ajustar a largura da lista · clique duas vezes para voltar ao padrão"></div>
  <div class="det">${detalhe()}</div></div></div>`;
}

/* uma parcela com a sua proposta */
function linhaParcela(l) {
  const pr = l._prop, id = esc(l.lead_id);
  const tx = l._ok ? `<span class="par-t">${pr ? `<strong>${pct(l._taxa)}</strong> negociada` : `${pct(l._taxa)} tabela`} · deságio ${brl(l._des)}</span>` : '';
  let acoes;
  if (!l._ok) acoes = `<span class="tag plain">Fora do prazo de ${S.params.prazoMax} dias</span>`;
  else if (!pr) acoes = `<span class="tag plain">Sem proposta</span>${tx}<span class="spacer"></span><button class="btn gold xs" type="button" data-act="propor" data-id="${id}">Propor</button>`;
  else if (pr.status === 'negociando') acoes = `${tag(PROP.negociando[0], PROP.negociando[1])}${tx}<span class="spacer"></span><button class="btn ghost xs" type="button" data-act="propor" data-id="${id}">Alterar margem</button><button class="btn ghost xs" type="button" data-act="propSt" data-id="${id}" data-s="aceita">Aceita</button><button class="btn bad xs" type="button" data-act="propSt" data-id="${id}" data-s="recusada">Recusada</button>`;
  else acoes = `${tag(PROP[pr.status][0], PROP[pr.status][1])}${tx}<span class="spacer"></span><button class="btn ghost xs" type="button" data-act="propSt" data-id="${id}" data-s="negociando">Reabrir</button>`;
  return `<div class="par${l._ok ? '' : ' off'}">
  <div class="par-a"><b>Parcela ${esc(l.processo_parcela || '—')}</b><span>pagamento ${fData(l.processo_pagamento)}${l.dias_pagamento != null ? ` · em ${l.dias_pagamento} d` : ''}</span></div>
  <div class="par-v"><b>${brl(l.processo_valor)}</b>${l._ok ? `<span>líquido ${brl(l._liq)}</span>` : ''}</div>
  <div class="par-s">${acoes}</div></div>`;
}
/* um processo: cabeçalho + parcelas */
function blocoProcesso(p, completo) {
  const l0 = p.ps[0];
  const info = completo ? `<div class="proc-info">
    <div class="kv"><span>Conferência</span><span>${l0.processo_aprovado_por ? 'Aprovado por ' + esc(l0.processo_aprovado_por) + ' em ' + fData(l0.processo_aprovado_em) : esc(l0.processo_status || '—')}</span></div>
    <div class="kv"><span>Forma de pagamento</span><span>${esc(l0.processo_forma_pagamento || '—')}</span></div>
    <div class="kv"><span>Ordem de compra</span><span>${esc(l0.processo_ordem_compra || '—')}</span></div>
    ${[...new Map(p.ps.map(l => [String(l.nf_numero), l])).values()].map(l => `<div class="kv"><span>NF ${esc(l.nf_numero || '—')}${l.nf_serie ? ' · série ' + esc(l.nf_serie) : ''}</span><span>emissão ${fData(l.nf_emissao)} · ${brl(l.nf_valor)}${l.nf_chave ? cp(l.nf_chave) : ''}</span></div>`).join('')}
    ${p.ps.map(l => `<div class="kv"><span>Parcela ${esc(l.processo_parcela || '—')}</span><span>vencimento ${fData(l.processo_vencimento)} · pagamento ${fData(l.processo_pagamento)}</span></div>`).join('')}</div>` : '';
  return `<section class="proc"><header class="proc-h"><div><b>Processo ${esc(p.numero)}</b><span>${onde(p.empresa, p.obra)}</span></div>
  <div class="proc-v"><b>${brl(p.valor)}</b><span>${plural(p.ps.length, 'parcela', 'parcelas')} · NF ${esc(p.nfs.join(', ') || '—')}</span></div></header>
  ${info}${completo ? '' : p.ps.map(linhaParcela).join('')}</section>`;
}
function detalhe() {
  const c = S.ui.sel, f = c && porFornecedor().get(c);
  if (!f) return `<div class="vazio"><strong>Selecione um lead</strong>Clique em um fornecedor na lista.</div>`;
  const u = S.ui, l0 = f.base, cr = crmDe(c), notas = S.notas[c] || [], docs = S.docs[c] || [], lc = local(l0);
  const idx = ETAPAS.findIndex(e => e[0] === f.etapa);
  const funil = ETAPAS.map(([k, tl], i) => `<button type="button" data-act="etapa" data-v="${k}" class="${f.etapa === k ? 'atual' : i < idx ? 'feito' : ''}" aria-pressed="${f.etapa === k}" title="${tl}">${ET_CURTO[k]}</button>`).join('');
  const nNotas = notas.filter(n => n.tipo !== 'sistema').length;
  const tabs = [['resumo', 'Resumo', 0], ['processos', 'Processos', f.procs.length], ['docs', 'Documentos', docs.length], ['notas', 'Notas', nNotas], ['dados', 'Dados', 0]];
  const tel = ef(l0, 'telefone', 'fornecedor_telefone'), mail = ef(l0, 'email', 'fornecedor_email');
  let corpo = '';
  if (u.tab === 'resumo') {
    const pf = f.perfil;
    corpo = `<div class="box pf-box"><div class="box-h"><p class="eyebrow">Perfil para antecipação</p>${fxTag(pf)}</div>
    <div class="pf-l">${notaPill(pf)}<div class="pf-n"><b>${pf.faixa === 'fora' ? 'Fora do perfil' : 'Nota ' + pf.nota + ' de 100'}</b><span>Taxa da tabela <b>${pct(f.tabela)} a.m.</b>${pf.nEl ? ` · ${brl(pf.valor)} aprovados no prazo · receita potencial <b>${brl(pf.receita)}</b>` : ''}</span></div></div>
    ${motivosHTML(pf, false)}</div>
    ${f.etapa === 'negociando' && !f.nProp ? `<div class="box warn"><span><b>Nenhuma parcela em proposta.</b> Escolha as parcelas e a margem de cada uma.</span><button class="btn gold sm" type="button" data-act="proposta">Montar proposta</button></div>` : ''}
    <div><div class="box-h"><p class="eyebrow">Processos a receber</p>${f.nOk ? '<button class="btn gold sm" type="button" data-act="proposta">Nova proposta</button>' : ''}</div>
    <p class="hint" style="margin-bottom:var(--s3)">${plural(f.procs.length, 'processo', 'processos')} · ${plural(f.todas.length, 'parcela', 'parcelas')}, ${fN(f.nOk)} dentro do prazo de ${S.params.prazoMax} dias. A proposta é feita por parcela.</p>
    ${f.procs.map(p => blocoProcesso(p, false)).join('')}</div>
    <div class="box"><div class="box-h"><p class="eyebrow">Contato</p><button class="link" type="button" data-act="tab" data-v="dados">Editar dados</button></div>
    <div class="kv"><span>Contato</span><span>${esc(ef(l0, 'contato', 'fornecedor_contato') || '—')}</span></div>
    <div class="kv"><span>Telefone</span><span>${tel ? esc(tel) + cp(tel) + (digits(tel).length >= 10 ? ` <a class="copy" href="https://wa.me/55${digits(tel)}" target="_blank" rel="noopener">WhatsApp</a>` : '') : '—'}</span></div>
    <div class="kv"><span>E-mail</span><span>${mail ? esc(mail) + cp(mail) : '—'}</span></div>
    <div class="kv"><span>Responsável na ANAX</span><span>${esc(cr.responsavel || '—')}</span></div></div>
    ${notas.length ? `<div class="box"><div class="box-h"><p class="eyebrow">Última anotação</p><button class="link" type="button" data-act="tab" data-v="notas">Ver todas</button></div><div class="nota${notas[0].tipo === 'sistema' ? ' sis' : ''}"><p>${esc(notas[0].texto)}</p><span class="w">${esc(notas[0].autor || '')} · ${fTS(notas[0].criado_em)}</span></div></div>` : ''}`;
  } else if (u.tab === 'processos') {
    corpo = `<div>${f.procs.map(p => blocoProcesso(p, true)).join('')}</div>`;
  } else if (u.tab === 'docs') {
    corpo = `<label class="drop" data-drop for="f_docs"><b>Arraste arquivos aqui ou clique para escolher</b><span class="hint">Contrato social, CNH, proposta assinada, comprovantes. Até 15 MB por arquivo.</span><input type="file" id="f_docs" data-file="docs" multiple hidden></label>
    <div class="box">${docs.length ? docs.map(d => { const ext = (String(d.nome).split('.').pop() || '').slice(0, 4); return `<div class="doc"><span class="ic">${esc(ext)}</span><div class="i"><b title="${esc(d.nome)}">${esc(d.nome)}</b><span>${fTam(d.tamanho || 0)} · ${esc(d.autor || '')} · ${fTS(d.enviado_em)}</span></div><button class="btn ghost xs" type="button" data-act="docBaixar" data-id="${esc(d.id)}">Baixar</button><button class="btn bad xs" type="button" data-act="docDel" data-id="${esc(d.id)}" aria-label="Excluir ${esc(d.nome)}">Excluir</button></div>`; }).join('') : '<p class="hint">Nenhum documento deste fornecedor ainda.</p>'}</div>`;
  } else if (u.tab === 'notas') {
    corpo = `<div class="box">${campo('ui.nota', 'Nova anotação', { area: true, ph: 'O que foi conversado, próximos passos, combinados…' })}<div class="row" style="margin-top:var(--s3);justify-content:flex-end"><button class="btn gold sm" type="button" data-act="notaAdd">Salvar anotação</button></div></div>
    <div class="box">${notas.length ? notas.map(n => `<div class="nota${n.tipo === 'sistema' ? ' sis' : ''}"><p>${esc(n.texto)}</p>${n.tipo === 'sistema' ? '<span></span>' : `<button class="btn bad xs" type="button" data-act="notaDel" data-id="${esc(n.id)}">Excluir</button>`}<span class="w">${esc(n.autor || '')} · ${fTS(n.criado_em)}${n.tipo === 'sistema' ? ' · automático' : ''}</span></div>`).join('') : '<p class="hint">Nenhuma anotação ainda.</p>'}</div>`;
  } else {
    if (!S.form || S.form._c !== c) { S.form = { _c: c }; EDITAVEIS.forEach(([k, , uau]) => { S.form[k] = ef(l0, k, uau) || ''; }); }
    corpo = `<div class="box"><div class="grid2">${EDITAVEIS.map(([k, lb, uau]) => campo('form.' + k, lb, { hint: uau ? (cr[k] ? 'Editado no painel. No UAU: ' + esc(l0[uau] || 'vazio') : 'Vem do UAU') : 'Só no painel', cls: k === 'email' ? 'full' : '' })).join('')}</div>
    <div class="row" style="margin-top:var(--s4)"><button class="btn gold sm" type="button" data-act="dadosSalvar">Salvar dados</button>${EDITAVEIS.some(([k]) => cr[k]) ? '<button class="btn ghost sm" type="button" data-act="dadosUau">Voltar aos dados do UAU</button>' : ''}<span class="hint" style="margin-left:auto">As alterações não mudam o cadastro do UAU.</span></div></div>
    <div class="box"><p class="eyebrow">Do UAU</p><div class="kv"><span>Razão social</span><span>${esc(f.nome)}</span></div><div class="kv"><span>CNPJ/CPF</span><span>${esc(f.doc)}${cp(f.doc)}</span></div><div class="kv"><span>Abertura</span><span>${fData(l0.fornecedor_abertura)}</span></div><div class="kv"><span>Risco sacado</span><span>${l0.fornecedor_risco_sacado === 'Sim' ? 'Habilitado' : 'Não habilitado'}</span></div></div>`;
  }
  return `<div class="det-h"><h2>${esc(f.nome)}</h2><div class="sub"><span>${esc(f.doc)}</span>${cp(f.doc)}${lc ? `<span>· ${esc(lc)}</span>` : ''}${f.interno ? tag('Interno do grupo', 'plain') : ''}</div>
  <div class="funil" role="group" aria-label="Etapa do lead">${funil}</div>
  <div class="funil-x"><span>${cr.atualizado_em ? 'Atualizado em ' + fTS(cr.atualizado_em) + (cr.atualizado_por ? ' por ' + esc(cr.atualizado_por) : '') : 'Ainda sem movimentação'}</span>${f.etapa === 'perdido' ? `<button class="link" type="button" data-act="etapa" data-v="novo">Reabrir lead</button>` : `<button class="link bad" type="button" data-act="etapa" data-v="perdido">Marcar como perdido</button>`}</div>
  <div class="dtabs" role="tablist">${tabs.map(([k, tl, n]) => `<button role="tab" type="button" data-act="tab" data-v="${k}" aria-selected="${u.tab === k}">${tl}${n ? `<span>${n}</span>` : ''}</button>`).join('')}</div></div>
  <div class="det-b">${corpo}</div>`;
}

/* ---------- perfil ideal: filtro recomendado com a nota e os motivos de cada fornecedor ---------- */
function telaPerfil() {
  const u = S.ui, C = perfilCfg(), todos = [...porFornecedor().values()];
  const tot = {}; FX_ORD.forEach(k => { tot[k] = { n: 0, v: 0, r: 0 }; });
  todos.forEach(f => { const t = tot[f.perfil.faixa]; t.n++; t.v += f.perfil.valor; t.r += f.perfil.receita; });
  // leitura da base (parcelas e fornecedores carregados)
  const rs = S.rows.filter(l => !l.interno), nR = rs.length || 1, pc = x => Math.round(x / nR * 100) + '%';
  const ate7 = rs.filter(l => l.dias_pagamento != null && l.dias_pagamento <= 7).length, faixaD = rs.filter(l => l.dias_pagamento >= C.dMin && l.dias_pagamento <= C.dMax).length;
  const ate5k = rs.filter(l => (l.processo_valor || 0) < 5000).length;
  const um = todos.filter(f => f.procs.length === 1).length, nF = todos.length || 1;
  const set = todos.filter(f => f.perfil.setor).length, grandes = todos.filter(f => RE_GRANDE.test(norm(f.nome))).length;
  const exc = {}; todos.forEach(f => { if (f.perfil.faixa === 'fora') { const k = f.perfil.motivos[0].c; exc[k] = (exc[k] || 0) + 1; } });
  const num = (b, w) => `<input class="inp num" type="number" min="0" data-bind="ui.perfil.${b}" value="${esc(C[b])}" style="width:${w}px" aria-label="${b}">`;
  const crit = [
    [25, `Pagamento entre ${num('dMin', 64)} e ${num('dMax', 64)} dias`, 'É o tempo que ele ganha. Abaixo de 15 dias o ganho é pequeno; acima de 90 o deságio assusta.', `Na base, ${pc(ate7)} das parcelas vencem em até 7 dias e ${pc(faixaD)} caem nesta faixa.`],
    [20, `De ${num('vMin', 96)} a ${num('vMax', 110)} aprovados no prazo`, 'Cada operação tem custo fixo (cadastro, cessão, transferência). Abaixo disso não se paga; muito acima exige mais recurso.', `${pc(ate5k)} das parcelas são de menos de R$ 5 mil, por isso a soma por fornecedor importa.`],
    [15, 'Pequena ou média empresa (LTDA, ME, EPP, EIRELI)', 'Paga mais caro no banco, então a nossa taxa é competitiva. S.A. costuma ter crédito barato.', `${fN(grandes)} fornecedores da base são S.A. ou companhia.`],
    [15, 'Setor que usa muito capital de giro', 'Locação de máquinas, transporte, combustíveis, peças, materiais, mineração e serviços de obra pagam diesel, peças e equipe antes de receber.', `${fN(set)} de ${fN(nF)} fornecedores estão nesses setores.`],
    [10, 'Fornecedor recorrente (5+ processos ou 2+ obras)', 'Quem fecha uma vez tende a repetir; o custo de conquista se dilui.', `${Math.round(um / nF * 100)}% dos fornecedores têm um processo só.`],
    [5, 'Espera longa entre a NF e o pagamento (45+ dias)', 'Quanto mais tempo ele financiou a LCM, maior a dor de caixa.', ''],
    [5, 'Empresa de 1 a 10 anos', 'Fase de crescimento, com menos reserva de caixa.', ''],
    [5, 'Telefone no cadastro', 'Abordagem direta fecha mais rápido que e-mail.', ''],
  ];
  const lista = todos.filter(f => f.perfil.faixa === u.pfFx);
  const ordF = { nota: (a, b) => b.perfil.nota - a.perfil.nota || b.perfil.receita - a.perfil.receita, receita: (a, b) => b.perfil.receita - a.perfil.receita, valor: (a, b) => b.perfil.valor - a.perfil.valor, nome: (a, b) => a.nome.localeCompare(b.nome, 'pt-BR') }[u.pfOrd] || (() => 0);
  lista.sort(ordF);
  const linhas = lista.slice(0, u.pfLim).map(f => { const pf = f.perfil; return `<tr data-act="abrirLead" data-c="${f.cnpj}" tabindex="0">
    <td class="n">${notaPill(pf)}</td>
    <td><b>${esc(f.nome)}</b><small>${esc(f.doc)}${pf.setor ? ' · ' + esc(pf.setor) : ''}</small></td>
    <td class="n"><b>${pct(f.tabela)}</b><small>a.m.</small></td>
    <td class="n">${pf.nEl ? brl(pf.valor) : '—'}<small>${pf.nEl ? plural(pf.nEl, 'parcela', 'parcelas') + ' · ' + Math.round(pf.dias) + ' d' : 'nada no prazo'}</small></td>
    <td class="n"><b>${pf.nEl ? brl(pf.receita) : '—'}</b><small>${pf.nEl ? 'deságio a ' + pct(f.tabela) : ''}</small></td>
    <td>${motivosHTML(pf, true)}</td></tr>`; }).join('');
  return `<div class="ops perfil">
  <div><h1>Perfil ideal de cliente</h1><p class="hint" style="margin-top:var(--s1);max-width:860px">O pagamento já está aprovado para emissão no UAU, então quem paga é a LCM: o risco de crédito é dela, não do fornecedor. A chance de fechar depende de três coisas: quanto o fornecedor ganha em antecipar, se o valor paga o custo da operação e quanto ele precisa de caixa. Cada fornecedor recebe uma nota de 0 a 100, com a taxa da tabela e os motivos.</p></div>
  <div class="stats pf-fx">${FX_ORD.map(k => `<button type="button" class="stat fx-${k}" data-act="pfFx" data-v="${k}" aria-pressed="${u.pfFx === k}"><div class="k">${FAIXAS[k][0]}</div><div class="v">${fN(tot[k].n)}</div><div class="s">${k === 'fora' ? 'fornecedores excluídos' : `${kBRL(tot[k].v)} no prazo · receita ${kBRL(tot[k].r)}`}</div></button>`).join('')}</div>
  <div class="pf-grid">
    <div class="box"><div class="box-h"><p class="eyebrow">Filtro recomendado</p><button class="btn gold sm" type="button" data-act="pfUsar">Ver na lista de leads</button></div>
      <p class="hint" style="margin-bottom:var(--s3)">Pontos de cada critério. Perfil ideal: 75 pontos ou mais, com prazo e valor dentro da faixa. Bom potencial: 55 a 74.</p>
      ${crit.map(([pts, t, m, b]) => `<div class="crit"><span class="crit-p">${pts}</span><div><b>${t}</b><p>${esc(m)}</p>${b ? `<small>${esc(b)}</small>` : ''}</div></div>`).join('')}
      <div class="row" style="margin-top:var(--s3)"><button class="link" type="button" data-act="pfPadrao">Voltar aos valores recomendados</button></div></div>
    <div class="box"><p class="eyebrow">Fica fora</p><p class="hint" style="margin-bottom:var(--s2)">Mesmo com pagamento autorizado, estes não são clientes da antecipação.</p>
      ${['Empresa do grupo LCM', 'Pessoa física', ...EXCLUI.map(e => e[0]), 'Nada no prazo'].map(k => `<div class="kv"><span>${esc(k)}</span><span>${fN(exc[k] || 0)}</span></div>`).join('')}</div>
  </div>
  <div class="pf-bar"><div class="seg">${FX_ORD.map(k => `<button type="button" data-act="pfFx" data-v="${k}" aria-pressed="${u.pfFx === k}">${FAIXAS[k][0]}<span>${fN(tot[k].n)}</span></button>`).join('')}</div>
  <select class="inp" id="f_pfOrd" data-bind="ui.pfOrd" aria-label="Ordenar">${[['nota', 'Maior nota'], ['receita', 'Maior receita potencial'], ['valor', 'Maior valor no prazo'], ['nome', 'Nome A–Z']].map(([k, t]) => `<option value="${k}"${u.pfOrd === k ? ' selected' : ''}>${t}</option>`).join('')}</select></div>
  ${lista.length ? `<div class="scroll"><table class="tbl pf-tbl"><thead><tr><th class="n">Nota</th><th>Fornecedor</th><th class="n">Taxa</th><th class="n">No prazo</th><th class="n">Receita potencial</th><th>Motivos</th></tr></thead><tbody>${linhas}</tbody></table></div>
  ${lista.length > u.pfLim ? `<div class="mais"><button class="btn ghost sm" type="button" data-act="pfMais">Mostrar mais ${Math.min(60, lista.length - u.pfLim)} de ${fN(lista.length - u.pfLim)}</button></div>` : ''}`
  : `<div class="vazio"><strong>Nenhum fornecedor nesta faixa</strong>Ajuste os critérios acima.</div>`}</div>`;
}

/* ---------- minhas operações: uma linha por parcela, agrupada por processo ---------- */
function telaOps() {
  const u = S.ui, sel = u.opsSt === 'todas' ? Object.keys(PROP) : [u.opsSt], todas = [];
  porFornecedor().forEach(f => f.todas.forEach(l => { if (l._prop) todas.push(l); }));
  const linhas = todas.filter(l => sel.includes(l._prop.status)).sort((a, b) => a.fornecedor_razao.localeCompare(b.fornecedor_razao, 'pt-BR') || String(a.processo_numero).localeCompare(String(b.processo_numero), 'pt-BR', { numeric: true }) || a._parcN - b._parcN);
  let face = 0, des = 0, liq = 0, wt = 0; const forn = new Set(), procs = new Set();
  linhas.forEach(l => { forn.add(l._cnpj); procs.add(l._cnpj + '|' + l._proc); if (l._ok) { face += l.processo_valor; des += l._des; liq += l._liq; wt += l.processo_valor * l._taxa; } });
  const cont = k => todas.filter(l => k === 'todas' || l._prop.status === k).length;
  return `<div class="ops"><div><h1>Minhas operações</h1><p class="hint" style="margin-top:var(--s1)">Uma linha por parcela proposta, com o processo a que ela pertence, a margem negociada, o deságio da ANAX e o líquido do fornecedor.</p></div>
  <div class="seg">${[['negociando', 'Em negociação'], ['aceita', 'Aceitas'], ['recusada', 'Recusadas'], ['todas', 'Todas']].map(([k, t]) => `<button type="button" data-act="opsSt" data-v="${k}" aria-pressed="${u.opsSt === k}">${t}<span>${cont(k)}</span></button>`).join('')}</div>
  <div class="stats"><div class="stat"><div class="k">Parcelas</div><div class="v">${fN(linhas.length)}</div><div class="s">${plural(procs.size, 'processo', 'processos')} · ${plural(forn.size, 'fornecedor', 'fornecedores')}</div></div>
  <div class="stat"><div class="k">Valor de face</div><div class="v">${fK(face)}</div><div class="s">das parcelas listadas</div></div>
  <div class="stat hi"><div class="k">Deságio previsto</div><div class="v">${fK(des)}</div><div class="s">receita ANAX</div></div>
  <div class="stat"><div class="k">Margem média</div><div class="v">${face ? pct(wt / face) : '—'}</div><div class="s">ponderada pelo valor, a.m.</div></div>
  <div class="stat"><div class="k">Líquido</div><div class="v">${fK(liq)}</div><div class="s">a pagar aos fornecedores</div></div></div>
  ${linhas.length ? `<div class="scroll"><table class="tbl"><thead><tr><th>Fornecedor</th><th>Processo · parcela</th><th>Pagamento</th><th class="n">Valor · margem</th><th class="n">Deságio · líquido</th><th>Proposta</th></tr></thead><tbody>
  ${linhas.map(l => { const pr = l._prop, st = PROP[pr.status], id = esc(l.lead_id); return `<tr data-act="abrirLead" data-c="${l._cnpj}" tabindex="0">
  <td><b>${esc(l.fornecedor_razao)}</b><small>${esc(l.fornecedor_cnpj)}</small></td>
  <td><b>${esc(l.processo_numero)} · ${esc(l.processo_parcela || '—')}</b><small class="clamp" title="${onde(l.processo_empresa, l.processo_obra)}">${esc(l.processo_obra || l.processo_empresa || '')}</small></td>
  <td>${fData(l.processo_pagamento)}<small>${l.dias_pagamento != null ? 'em ' + l.dias_pagamento + ' dias' : ''}</small></td>
  <td class="n">${brl(l.processo_valor)}<small>${pct(l._taxa)} a.m.</small></td>
  <td class="n"><b>${l._ok ? brl(l._des) : '—'}</b><small>${l._ok ? 'líquido ' + brl(l._liq) : 'fora do prazo'}</small></td>
  <td>${tag({ negociando: 'Em negociação', aceita: 'Aceita', recusada: 'Recusada' }[pr.status], st[1])}<small>${esc(pr.atualizado_por || pr.criado_por || '')}${pr.atualizado_em ? ' · ' + fTS(pr.atualizado_em) : ''}</small>
  <div class="acoes">${pr.status === 'negociando' ? `<button class="btn ghost xs" type="button" data-act="propSt" data-id="${id}" data-s="aceita">Aceita</button><button class="btn bad xs" type="button" data-act="propSt" data-id="${id}" data-s="recusada">Recusada</button>` : `<button class="btn ghost xs" type="button" data-act="propSt" data-id="${id}" data-s="negociando">Reabrir</button>`}</div></td></tr>`; }).join('')}
  </tbody><tfoot><tr><td colspan="3">${plural(linhas.length, 'parcela', 'parcelas')}</td><td class="n">${brl(face)}<small>média ${face ? pct(wt / face) : '—'} a.m.</small></td><td class="n">${brl(des)}<small>líquido ${brl(liq)}</small></td><td></td></tr></tfoot></table></div>`
  : `<div class="vazio"><strong>Nenhuma parcela ${{ negociando: 'em negociação', aceita: 'aceita', recusada: 'recusada', todas: 'com proposta' }[u.opsSt]}</strong>Na aba Leads, abra um fornecedor e use “Propor” na parcela do processo.</div>`}</div>`;
}

/* ---------- janela de proposta ---------- */
function modalHTML() {
  const M = S.modal; if (!M) return '';
  const f = porFornecedor().get(M.cnpj); if (!f) return '';
  const ids = Object.keys(M.itens), varias = ids.length > 1, nSel = ids.filter(id => M.itens[id].on).length;
  const grupos = processos(f.todas.filter(l => l.lead_id in M.itens));
  let tFace = 0, tDes = 0;
  const lista = grupos.map(p => `<div class="mgrp"><div class="mproc"><b>Processo ${esc(p.numero)}</b><span title="${onde(p.empresa, p.obra)}">${onde(p.empresa, p.obra)}</span></div>` + p.ps.map(l => {
    const it = M.itens[l.lead_id], v = parseBR(it.margem), ok = v > 0 && v <= 20, c = ok ? calc(l.processo_valor, l.dias_pagamento, v) : null, idc = 'f_m_' + l.lead_id.replace(/\W/g, '_');
    if (it.on && c) { tFace += l.processo_valor; tDes += c.desc; }
    return `<div class="mi${it.on ? ' on' : ''}" data-act="mItem" data-id="${esc(l.lead_id)}">
    <input type="checkbox" tabindex="-1" aria-hidden="true"${it.on ? ' checked' : ''}>
    <div class="mi-a"><b>Parcela ${esc(l.processo_parcela || '—')} · ${brl(l.processo_valor)}</b><span>pagamento ${fData(l.processo_pagamento)} · em ${l.dias_pagamento} d · NF ${esc(l.nf_numero || '—')}</span></div>
    <div class="mi-m" data-act="noop"><input class="inp" id="${idc}" data-bind="modal.itens.${esc(l.lead_id)}.margem" data-live="1" inputmode="decimal" value="${esc(it.margem)}" aria-label="Margem da ${esc(rotulo(l))}"${it.on ? '' : ' disabled'}><span>% a.m.</span></div>
    <div class="mi-p">${it.on ? (c ? `deságio <b>${brl(c.desc)}</b><br>líquido ${brl(c.liq)}` : '<span class="err">margem inválida</span>') : 'fora da proposta'}</div></div>`; }).join('') + '</div>').join('');
  return `<div class="veu" data-act="modalX"><div class="modal" role="dialog" aria-modal="true" aria-labelledby="mt" data-act="noop">
  <div class="modal-h"><h3 id="mt">${M.para ? 'Mover para Em negociação' : M.so ? 'Proposta da parcela' : 'Nova proposta'}</h3><p>${esc(f.nome)} · taxa da tabela ${pct(f.tabela)} a.m. </p></div>
  <div class="modal-b">
  ${varias ? `<div class="aplicar"><label class="hint" for="f_modal_todas">Margem para as marcadas</label><input class="inp" id="f_modal_todas" data-bind="modal.todas" inputmode="decimal" value="${esc(M.todas)}"><span class="hint">% a.m.</span><button class="btn ghost sm" type="button" data-act="mTodas">Aplicar</button><span class="spacer"></span><button class="link" type="button" data-act="mSel">${nSel === ids.length ? 'Desmarcar todas' : 'Marcar todas'}</button></div>` : ''}
  <div class="mlista">${lista}</div>
  ${campo('modal.obs', 'Observação (opcional)', { area: true, ph: 'Condições combinadas, prazo, quem aprovou…' })}
  ${M.err ? `<div class="err">${esc(M.err)}</div>` : ''}</div>
  <div class="modal-f"><span class="hint">${plural(nSel, 'parcela', 'parcelas')} · ${brl(tFace)} · deságio ${brl(tDes)}</span><button class="btn ghost" type="button" data-act="modalX">Cancelar</button><button class="btn gold" type="button" data-act="modalOk"${nSel ? '' : ' disabled'}>Salvar proposta</button></div></div></div>`;
}

function avisoSQL() {
  const fbe = ((S.meta || {}).firebase || {}).erro;
  if (fbe) return `<div class="alerta"><b>Firebase ainda não está pronto.</b><span>Por enquanto o painel só consulta, sem gravar. ${esc(fbe).slice(0, 220)}</span></div>`;
  const q = (S.meta || {}).sql || {};
  if (!q.configurado || !q.erro) return '';
  return `<div class="alerta"><b>SQL Server indisponível.</b><span>O que você registrar agora fica num arquivo temporário e pode se perder quando o app reiniciar. ${esc(String(q.erro).split(/ Erro:| \('|\. \(/)[0]).slice(0, 200)}</span><button class="btn ghost xs" type="button" data-act="janela" data-v="base">Ver conexão</button></div>`;
}
function blocoSQL() {
  const m = S.meta || {}, q = m.sql || {}, t = m.teste_sql;
  const falha = q.erro || q.erro_uau;
  const st = !q.configurado ? ['Não configurado', 'plain'] : falha ? ['Com problema', 'bad'] : S.rows.length ? ['Conectado', 'ok'] : ['Configurado', 'gold'];
  return `<div class="box sqlbox"><div class="box-h"><p class="eyebrow">SQL Server</p>${tag(st[0], st[1])}</div>
  ${q.configurado ? `<p class="hint">${esc(q.resumo)}</p>${q.erro_uau && !t ? `<p class="hint err-t">${esc(q.erro_uau)}</p>` : ''}` : `<p class="hint">Preencha a seção [sql] nos Secrets do app (servidor, porta, banco, usuario, senha).</p>`}
  ${t ? `<ul class="teste">${t.linhas.map(l => `<li>${esc(l)}</li>`).join('')}${t.ip ? `<li>IP de saída deste app: <b>${esc(t.ip)}</b>${cp(t.ip)}</li>` : ''}</ul><p class="hint">Teste feito em ${fTS(t.quando)}.</p>` : ''}
  <div class="row" style="margin-top:var(--s2)"><button class="btn ghost sm" type="button" data-act="testarSql"${S.testando ? ' disabled' : ''}>${S.testando ? 'Testando…' : 'Testar conexão'}</button></div></div>`;
}

/* ---------- janelas do topo: base de dados, taxas e nome ---------- */
const LS_NOME = 'anax-leads-nome';
let nomeLocal = ''; try { nomeLocal = localStorage.getItem(LS_NOME) || ''; } catch (e) {}
const CAMPOS_TAXA = [['taxaBase', 'Taxa base', '% a.m.'], ['ajPorte.pequeno', 'Ajuste porte pequeno', 'p.p.'], ['ajPorte.medio', 'Ajuste porte médio', 'p.p.'],
  ['ajPorte.grande', 'Ajuste porte grande', 'p.p.'], ['ajScore.medio', 'Ajuste de risco', 'p.p.'], ['taxaMinima', 'Taxa mínima', '% a.m.'],
  ['faixaPequenoAte', 'Porte pequeno até', 'R$ em aberto'], ['faixaMedioAte', 'Porte médio até', 'R$ em aberto'], ['prazoMax', 'Prazo máximo', 'dias']];
function baseOpcoes() {
  const c = S.carregando;
  return `<div class="fontes">
  <div class="fonte"><b>Consultar o UAU</b><p>Roda o leads.sql no SQL Server e traz as parcelas aprovadas, com fornecedor, processo e NF.</p>
  <button class="btn gold sm" type="button" data-act="carregarUau"${c ? ' disabled' : ''}>${c === 'uau' ? 'Consultando o UAU…' : 'Consultar agora'}</button></div>
  <label class="fonte" for="f_planilha"><b>Enviar planilha</b><p>Excel ou CSV salvo com o resultado do leads.sql no SSMS.</p>
  <span class="btn ghost sm${c ? ' off' : ''}">${c === 'planilha' ? 'Lendo a planilha…' : 'Escolher arquivo'}</span><input type="file" id="f_planilha" data-file="planilha" accept=".xlsx,.xls,.csv"${c ? ' disabled' : ''} hidden></label></div>`;
}
function abrirJanela(tipo) {
  if (tipo === 'taxas') { const p = S.params, v = {}; CAMPOS_TAXA.forEach(([k]) => { v[k] = String(getPath(p, k) ?? '').replace('.', ','); }); S.janela = { tipo, v, err: '' }; }
  else if (tipo === 'nome') S.janela = { tipo, nome: (S.meta.login && S.meta.login.nome) || S.usuario || nomeLocal || '', err: '' };
  else S.janela = { tipo, err: '' };
  render();
  const i = document.querySelector('.janela input:not([type=file])'); if (i) i.focus();
}
function taxasDoForm() {
  const v = S.janela.v, p = JSON.parse(JSON.stringify(S.params));
  for (const [k, lb] of CAMPOS_TAXA) { const n = parseBR(v[k]); if (!isFinite(n)) return [null, `${lb}: use um número.`]; setPath(p, k, n); }
  if (p.taxaBase <= 0 || p.taxaBase > 20 || p.taxaMinima < 0 || p.taxaMinima > 20) return [null, 'Taxas entre 0 e 20% a.m.'];
  if (p.faixaPequenoAte >= p.faixaMedioAte) return [null, 'O porte pequeno precisa terminar antes do médio.'];
  if (p.prazoMax < 1 || p.prazoMax > 720) return [null, 'Prazo máximo entre 1 e 720 dias.'];
  p.prazoMax = Math.round(p.prazoMax);
  return [p, ''];
}
function janelaHTML() {
  const J = S.janela; if (!J) return '';
  const m = S.meta || {};
  let tit, sub, corpo, rod;
  if (J.tipo === 'base') {
    tit = 'Base de dados';
    sub = S.rows.length ? `Agora: ${esc(m.fonte || '')}${m.carregado ? ' · carregada em ' + fTS(m.carregado) : ''} · ${fN(S.rows.length)} parcelas` : 'Nenhuma base carregada ainda.';
    corpo = baseOpcoes() + blocoSQL() + `<p class="hint">${esc(m.armazenamento || '')}. ${RO() ? 'Por enquanto o painel só consulta o UAU.' : 'Etapas, propostas, notas e documentos ficam guardados e voltam quando a base é recarregada.'}</p>`;
    rod = `<span class="hint"></span><button class="btn ghost" type="button" data-act="janelaX">Fechar</button>`;
  } else if (J.tipo === 'taxas') {
    const [p] = taxasDoForm();
    tit = 'Tabela de taxas da antecipação';
    sub = (RO() ? 'Modo consulta: vale só para esta sessão, nada é salvo. ' : 'Vale para toda a equipe. ') + 'A taxa de cada fornecedor = taxa base + ajuste do porte + ajuste de risco, nunca abaixo da mínima.';
    corpo = `<div class="taxas">${CAMPOS_TAXA.map(([k, lb, un]) => `<div class="fld"><label for="f_tx_${k.replace('.', '_')}">${esc(lb)}</label><div class="un"><input class="inp" id="f_tx_${k.replace('.', '_')}" data-bind="janela.v.${k}" data-live="1" inputmode="decimal" value="${esc(J.v[k])}"><span>${esc(un)}</span></div></div>`).join('')}</div>
    ${p ? `<div class="box tx-ex">${['pequeno', 'medio', 'grande'].map(pt => `<div><span>${{ pequeno: 'Porte pequeno', medio: 'Porte médio', grande: 'Porte grande' }[pt]}</span><b>${pct(Math.max(p.taxaMinima, r2(p.taxaBase + p.ajPorte[pt] + p.ajScore.medio)))} a.m.</b></div>`).join('')}</div>` : ''}`;
    rod = `<button class="link" type="button" data-act="taxasPadrao">Voltar ao padrão</button><span class="spacer"></span><button class="btn ghost" type="button" data-act="janelaX">Cancelar</button><button class="btn gold" type="button" data-act="taxasOk">${RO() ? 'Aplicar' : 'Salvar taxas'}</button>`;
  } else {
    tit = 'Seu nome'; sub = 'Aparece nas notas, nas propostas e no resumo do dia. ' + ((S.meta.firebase || {}).ligado ? 'Fica guardado na sua conta do Firebase.' : 'Fica guardado neste navegador.');
    corpo = campo('janela.nome', 'Nome', { ph: 'Ex.: iasmin.fernandes' });
    rod = `<span class="spacer"></span><button class="btn ghost" type="button" data-act="janelaX">Cancelar</button><button class="btn gold" type="button" data-act="nomeOk">Salvar</button>`;
  }
  return `<div class="veu" data-act="janelaX"><div class="modal janela j-${J.tipo}" role="dialog" aria-modal="true" aria-labelledby="jt" data-act="noop">
  <div class="modal-h"><h3 id="jt">${tit}</h3><p>${sub}</p></div><div class="modal-b">${corpo}${J.err ? `<div class="err">${esc(J.err)}</div>` : ''}</div>
  <div class="modal-f">${rod}</div></div></div>`;
}
function enviarPlanilha(f) {
  if (!f) return;
  if (!/\.(xlsx|xls|csv)$/i.test(f.name)) return toast('Use um arquivo .xlsx, .xls ou .csv.', 'bad');
  if (f.size > 50 * 1048576) return toast('Planilha acima de 50 MB.', 'bad');
  const r = new FileReader();
  r.onload = () => { S.carregando = 'planilha'; evento('planilha', { nome: f.name, b64: String(r.result).split(',')[1] || '' }); render(); };
  r.onerror = () => toast('Não consegui ler o arquivo.', 'bad');
  r.readAsDataURL(f);
}
function telaInicial() {
  return `<div class="inicio"><div class="inicio-c"><p class="eyebrow">ANAX · Comercial</p><h1>Painel de leads</h1>
  <p class="hint">Fornecedores com pagamentos já aprovados no UAU, para oferecer a antecipação. Carregue a base para começar.</p>
  ${baseOpcoes()}
  ${(S.meta.sql || {}).configurado ? blocoSQL() : ''}
  ${S.meta.login ? `<p class="hint inicio-n">Conectado como <b>${esc(S.meta.login.nome)}</b> · <button class="link" type="button" data-act="sair">Sair</button></p>`
    : `<p class="hint inicio-n">Você aparece nas notas como <b>${esc(S.usuario || '—')}</b> · <button class="link" type="button" data-act="janela" data-v="nome">alterar</button></p>`}</div></div>`;
}

/* altura: o painel ocupa a janela do navegador, sem rolar a página */
let altOuvindo = false;
function ajustaAltura() {
  let h = 860;
  try {
    const fe = window.frameElement;
    if (fe) {
      h = Math.max(560, Math.round(window.parent.innerHeight - fe.getBoundingClientRect().top - 10));
      if (!altOuvindo) { altOuvindo = true; let t = 0; window.parent.addEventListener('resize', () => { clearTimeout(t); t = setTimeout(ajustaAltura, 120); }); }
    }
  } catch (e) { /* iframe de outra origem: altura fixa */ }
  if (h !== S.alt) { S.alt = h; STL.height(h); }
}

/* ---------- divisor entre a lista e o detalhe: arrastar, setas do teclado, duplo clique volta ao padrão ---------- */
const ESQ_MIN = 22, ESQ_MAX = 70, ESQ_PADRAO = 40;
function limitaEsq(pctv, split) {
  const w = split ? split.getBoundingClientRect().width : 1000;
  const minPx = 260 / w * 100, maxPx = 100 - 460 / w * 100;  // lista com pelo menos 260 px, detalhe com pelo menos 460 px
  return Math.round(Math.min(Math.max(pctv, ESQ_MIN, minPx), ESQ_MAX, maxPx) * 10) / 10;
}
function aplicaEsq(split, v) {
  split.style.setProperty('--esq', v + '%');
  const d = split.querySelector('.divisor'); if (d) d.setAttribute('aria-valuenow', Math.round(v));
}
let arrasto = null;
document.addEventListener('pointerdown', e => {
  const d = e.target.closest && e.target.closest('.divisor'); if (!d || e.button !== 0) return;
  e.preventDefault();
  arrasto = { split: d.parentElement, id: e.pointerId };
  d.setPointerCapture(e.pointerId); d.classList.add('ativo'); document.body.classList.add('arrastando');
});
document.addEventListener('pointermove', e => {
  if (!arrasto || e.pointerId !== arrasto.id) return;
  const r = arrasto.split.getBoundingClientRect();
  S.ui.esq = limitaEsq((e.clientX - r.left) / r.width * 100, arrasto.split);
  aplicaEsq(arrasto.split, S.ui.esq);
});
const fimArrasto = e => {
  if (!arrasto || (e.pointerId != null && e.pointerId !== arrasto.id)) return;
  const d = arrasto.split.querySelector('.divisor'); if (d) d.classList.remove('ativo');
  document.body.classList.remove('arrastando'); arrasto = null; salvarUI();
};
document.addEventListener('pointerup', fimArrasto);
document.addEventListener('pointercancel', fimArrasto);
document.addEventListener('dblclick', e => {
  const d = e.target.closest && e.target.closest('.divisor'); if (!d) return;
  S.ui.esq = null; d.parentElement.style.removeProperty('--esq'); d.setAttribute('aria-valuenow', ESQ_PADRAO); salvarUI();
});
document.addEventListener('keydown', e => {
  if (!e.target.matches || !e.target.matches('.divisor')) return;
  const passo = e.shiftKey ? 10 : 2, atual = S.ui.esq || ESQ_PADRAO;
  const novo = { ArrowLeft: atual - passo, ArrowRight: atual + passo, Home: ESQ_MIN, End: ESQ_MAX }[e.key];
  if (novo == null) return;
  e.preventDefault();
  S.ui.esq = limitaEsq(novo, e.target.parentElement); aplicaEsq(e.target.parentElement, S.ui.esq); salvarUI();
});

/* ---------- render ---------- */
function render() {
  const ae = document.activeElement, fid = ae && ae.id, ss = ae && ae.selectionStart, se = ae && ae.selectionEnd;
  const sc = ['.lista', '.det', '.ops', '.modal-b'].map(s => { const e = document.querySelector(s); return e ? e.scrollTop : 0; });
  if (!S.rows.length) { $('#app').innerHTML = avisoSQL() + telaInicial() + janelaHTML(); ajustaVeu(); return; }
  document.body.classList.toggle('ro', RO());
  if (RO()) { if (S.ui.aba === 'ops') S.ui.aba = 'leads'; if (!['resumo', 'processos'].includes(S.ui.tab)) S.ui.tab = 'resumo'; if (S.ui.etapa !== 'todas') S.ui.etapa = 'todas'; }
  $('#app').innerHTML = topo() + (S.ui.aba === 'ops' ? telaOps() : S.ui.aba === 'perfil' ? telaPerfil() : telaLeads()) + modalHTML() + janelaHTML();
  ajustaVeu();
  ['.lista', '.det', '.ops', '.modal-b'].forEach((s, i) => { const e = document.querySelector(s); if (e) e.scrollTop = sc[i]; });
  if (fid) { const el = document.getElementById(fid); if (el) { try { el.focus({ preventScroll: true }); if (ss != null && el.setSelectionRange && /text|search/.test(el.type || '')) el.setSelectionRange(ss, se); } catch (e) {} } }
  salvarUI();
}

/* a janela de proposta ocupa só a parte do painel que está visível na página do Streamlit */
let veuOuvindo = false;
function ajustaVeu() {
  const v = document.querySelector('.veu'); if (!v) return;
  try {
    const fe = window.frameElement; if (!fe) return;
    const r = fe.getBoundingClientRect(), H = window.parent.innerHeight;
    const top = Math.max(0, -r.top), bot = Math.min(r.height, H - r.top);
    if (bot - top > 240) { v.style.top = top + 'px'; v.style.height = (bot - top) + 'px'; v.style.bottom = 'auto'; }
    if (!veuOuvindo) { veuOuvindo = true; window.parent.addEventListener('scroll', ajustaVeu, true); window.parent.addEventListener('resize', ajustaVeu); }
  } catch (e) { /* iframe de outra origem: usa a área toda */ }
}

/* ---------- eventos da tela ---------- */
const ACT = {
  noop: () => {},
  copy: a => copy(a.dataset.t),
  aba: a => { S.ui.aba = a.dataset.v; render(); },
  sel: a => { if (S.ui.sel !== a.dataset.c) { S.ui.sel = a.dataset.c; S.form = null; } render(); },
  tab: a => { S.ui.tab = a.dataset.v; render(); const d = document.querySelector('.det'); if (d) d.scrollTop = 0; },
  etapa: a => mudarEtapa(S.ui.sel, a.dataset.v),
  proposta: () => abrirProposta(S.ui.sel, null, null),
  propor: a => abrirProposta(S.ui.sel, a.dataset.id, null),
  propSt: (a, e) => { e.stopPropagation(); statusProposta(a.dataset.id, a.dataset.s || null); },
  mItem: a => { const it = S.modal.itens[a.dataset.id]; if (Object.keys(S.modal.itens).length < 2) return; it.on = !it.on; S.modal.err = ''; render(); },
  mTodas: () => { const M = S.modal; Object.values(M.itens).forEach(i => { if (i.on) i.margem = M.todas; }); render(); },
  mSel: () => { const M = S.modal, todas = Object.values(M.itens).every(i => i.on); Object.values(M.itens).forEach(i => { i.on = !todas; }); render(); },
  modalOk: () => salvarProposta(),
  modalX: (a, e) => { if (e.target !== a && !a.matches('button')) return; S.modal = null; render(); },
  etapaF: a => { S.ui.etapa = a.dataset.v; S.ui.lim = 80; render(); },
  filtros: () => { S.ui.filtros = !S.ui.filtros; render(); },
  fac: a => { const k = a.dataset.k, v = a.dataset.v, s = new Set(S.ui.facets[k] || []); s.has(v) ? s.delete(v) : s.add(v); S.ui.facets[k] = [...s]; S.ui.lim = 80; render(); },
  internos: () => { S.ui.ocultarInternos = !S.ui.ocultarInternos; render(); },
  rdNovo: () => { S.ui.rd = { id: 'r' + Date.now(), key: 'processo_valor', _k: 'processo_valor', op: 'gte', v1: '', v2: '', vals: [] }; render(); },
  rdX: () => { S.ui.rd = null; render(); },
  rdVal: a => { const d = S.ui.rd, s = new Set(d.vals); s.has(a.dataset.v) ? s.delete(a.dataset.v) : s.add(a.dataset.v); d.vals = [...s]; render(); },
  rdOk: () => { const d = S.ui.rd, t = CF[d.key].type; const ok = t === 'enum' ? d.vals.length : d.op === 'entre' ? String(d.v1).trim() && String(d.v2).trim() : String(d.v1).trim(); if (!ok) return toast('Preencha a condição.', 'bad'); S.ui.rules.push({ id: d.id, key: d.key, op: d.op, v1: d.v1, v2: d.v2, vals: d.vals.slice() }); S.ui.rd = null; render(); },
  rm: a => { const k = a.dataset.k, u = S.ui; if (k === 'perfil') u.perfilF = 'todos'; else if (k === 'q') u.q = ''; else if (k.startsWith('f:')) u.facets[k.slice(2)] = []; else u.rules = u.rules.filter(r => r.id !== k.slice(2)); render(); },
  limpar: () => { Object.assign(S.ui, { q: '', facets: {}, rules: [], etapa: 'todas', perfilF: 'todos', lim: 80, rd: null }); render(); },
  mais: () => { S.ui.lim += 80; render(); },
  opsSt: a => { S.ui.opsSt = a.dataset.v; render(); },
  resumo: () => { evento('resumo', {}); },
  janela: a => abrirJanela(a.dataset.v),
  janelaX: (a, e) => { if (e.target !== a && !a.matches('button')) return; S.janela = null; render(); },
  carregarUau: () => { S.carregando = 'uau'; evento('carregar_uau', {}); render(); },
  testarSql: () => { S.testando = true; evento('testar_sql', {}); render(); },
  sair: () => { evento('sair', {}); },
  taxasPadrao: () => { CAMPOS_TAXA.forEach(([k]) => { S.janela.v[k] = String(getPath(DEF, k)).replace('.', ','); }); S.janela.err = ''; render(); },
  taxasOk: () => { const [p, err] = taxasDoForm(); if (!p) { S.janela.err = err; render(); return; } evento('params', { params: p }); S.janela = null; toast(RO() ? 'Aplicando as taxas…' : 'Salvando a tabela de taxas…'); render(); },
  nomeOk: () => { const n = String(S.janela.nome || '').trim().slice(0, 80); if (!n) { S.janela.err = 'Escreva seu nome.'; render(); return; }
    try { localStorage.setItem(LS_NOME, n); } catch (e) {} nomeLocal = n; S.usuario = n; evento('usuario', { nome: n }); S.janela = null; toast('Nome salvo.', 'ok'); render(); },
  pfFx: a => { S.ui.pfFx = a.dataset.v; S.ui.pfLim = 60; render(); },
  pfMais: () => { S.ui.pfLim += 60; render(); },
  pfPadrao: () => { S.ui.perfil = { ...PERFIL_DEF }; invalida(); render(); toast('Critérios recomendados restaurados.', 'ok'); },
  pfUsar: () => { Object.assign(S.ui, { aba: 'leads', perfilF: S.ui.pfFx === 'fora' ? 'fora' : S.ui.pfFx === 'ideal' ? 'ideal' : S.ui.pfFx, ordem: 'perfil', etapa: 'todas', q: '', lim: 80, sel: null }); render(); },
  abrirLead: a => { Object.assign(S.ui, { aba: 'leads', sel: a.dataset.c, tab: 'resumo', etapa: 'todas', q: '' }); S.form = null; render(); },
  notaAdd: () => { const t = String(S.ui.nota || '').trim(); if (!t) return toast('Escreva a anotação.', 'bad'); evento('nota_add', { cnpj: S.ui.sel, texto: t }); S.ui.nota = ''; toast('Salvando anotação…'); render(); },
  notaDel: a => { evento('nota_del', { nota_id: a.dataset.id, cnpj: S.ui.sel }); toast('Excluindo…'); },
  docBaixar: a => { evento('doc_baixar', { doc_id: a.dataset.id }); toast('Preparando o arquivo…'); },
  docDel: a => { evento('doc_del', { doc_id: a.dataset.id, cnpj: S.ui.sel }); toast('Excluindo…'); },
  dadosSalvar: () => { const c = S.ui.sel, f = porFornecedor().get(c), campos = {};
    EDITAVEIS.forEach(([k, , uau]) => { const v = String(S.form[k] || '').trim(); const orig = uau ? String(f.base[uau] || '').trim() : ''; campos[k] = v && v !== orig ? v : null; });
    if (campos.email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(campos.email)) return toast('E-mail inválido.', 'bad');
    evento('dados', { cnpj: c, nome: f.nome, campos }); toast('Salvando dados…'); },
  dadosUau: () => { const c = S.ui.sel, campos = {}; EDITAVEIS.forEach(([k, , uau]) => { campos[k] = uau ? null : (crmDe(c)[k] || null); }); S.form = null; evento('dados', { cnpj: c, nome: porFornecedor().get(c).nome, campos }); toast('Voltando aos dados do UAU…'); },
};
document.addEventListener('click', e => { const a = e.target.closest('[data-act]'); if (!a) return; const f = ACT[a.dataset.act]; if (f) f(a, e); });
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && (S.modal || S.janela)) { S.modal = null; S.janela = null; render(); return; }
  if (e.key === 'Enter' && S.janela && S.janela.tipo === 'nome' && e.target.id === 'f_janela_nome') { ACT.nomeOk(); return; }
  if (e.key === 'Enter' && e.target.matches && e.target.matches('.lrow,tr[data-act]')) { const f = ACT[e.target.dataset.act]; if (f) f(e.target, e); }
  if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && e.target.matches && e.target.matches('.lrow')) { e.preventDefault(); const n = e.key === 'ArrowDown' ? e.target.nextElementSibling : e.target.previousElementSibling; if (n && n.matches('.lrow')) { S.ui.sel = n.dataset.c; S.form = null; render(); const x = document.querySelector('.lrow.on'); if (x) { x.focus(); x.scrollIntoView({ block: 'nearest' }); } } }
});
document.addEventListener('input', e => { const t = e.target, b = t.dataset && t.dataset.bind; if (!b || b.startsWith('ui.perfil.')) return; setPath(S, b, t.value); if (b === 'ui.q') S.ui.lim = 80; if (t.dataset.live) render(); });
document.addEventListener('change', e => {
  const t = e.target;
  if (t.dataset && t.dataset.file === 'docs') { const fl = Array.from(t.files || []); t.value = ''; enviarDocs(fl); return; }
  if (t.dataset && t.dataset.file === 'planilha') { const f = (t.files || [])[0]; t.value = ''; enviarPlanilha(f); return; }
  if (t.dataset && t.dataset.bind && t.tagName === 'SELECT') { setPath(S, t.dataset.bind, t.value); if (t.dataset.bind === 'ui.perfilF') { S.ui.lim = 80; } render(); }
  if (t.dataset && t.dataset.bind && t.dataset.bind.startsWith('ui.perfil.')) { const n = Number(t.value); if (!(n >= 0)) return toast('Use um número.', 'bad'); setPath(S, t.dataset.bind, n); invalida(); render(); }
});
document.addEventListener('dragover', e => { const d = e.target.closest && e.target.closest('[data-drop]'); if (d) { e.preventDefault(); d.classList.add('over'); } });
document.addEventListener('dragleave', e => { const d = e.target.closest && e.target.closest('[data-drop]'); if (d) d.classList.remove('over'); });
document.addEventListener('drop', e => { const d = e.target.closest && e.target.closest('[data-drop]'); if (d) { e.preventDefault(); d.classList.remove('over'); enviarDocs(Array.from(e.dataTransfer.files || [])); } });

/* ---------- recebe do Python ---------- */
function receber(a) {
  const pa = a.params || {};
  S.params = Object.assign({}, DEF, pa, { ajPorte: Object.assign({}, DEF.ajPorte, pa.ajPorte), ajScore: Object.assign({}, DEF.ajScore, pa.ajScore) });
  S.crm = a.crm || {}; S.propostas = a.propostas || {}; S.notas = a.notas || {}; S.docs = a.docs || {}; S.meta = a.meta || {}; S.usuario = a.usuario || '';
  Object.keys(S.pend).forEach(k => { if ((S.crm[k] || {}).etapa === S.pend[k]) delete S.pend[k]; });
  Object.keys(S.pendP).forEach(k => { const p = S.pendP[k], sv = S.propostas[k]; if ((!p.status && !sv) || (sv && p.status === sv.status && (p.margem == null || Math.abs(Number(sv.margem) - Number(p.margem)) < 1e-6))) delete S.pendP[k]; });
  ajustaAltura();
  const av = S.meta.aviso;
  if (av && av.token !== S.avisoVisto) { S.avisoVisto = av.token; S.carregando = null; toast(av.texto, av.tipo === 'erro' ? 'bad' : 'ok'); }
  if (S.meta.teste_sql && S.meta.teste_sql.quando !== S.testeVisto) { S.testeVisto = S.meta.teste_sql.quando; S.testando = false; }
  if (S.meta.login) S.nomeEnviado = true;
  if (!S.nomeEnviado) { S.nomeEnviado = true; if (nomeLocal && nomeLocal !== S.usuario) { S.usuario = nomeLocal; evento('usuario', { nome: nomeLocal, inicio: true }); } }
  if (a.dados && a.dados.versao !== S.versao) { S.versao = a.dados.versao; S.rows = prepara(a.dados); S.ui.sel = null; S.form = null; S.carregando = null; if (S.janela && S.janela.tipo === 'base') S.janela = null; }
  else if (!a.dados) { S.rows = []; S.versao = null; }
  if (S.form && S.form._c) { const cr = S.crm[S.form._c] || {}; if (cr.atualizado_em !== S.form._v) S.form = null; }
  invalida();
  if (a.download && a.download.token && a.download.token !== S.dlVisto) { S.dlVisto = a.download.token; baixar(a.download); }
  render();
  if (S.form && S.form._c) S.form._v = (S.crm[S.form._c] || {}).atualizado_em;
}
window.addEventListener('message', e => { const d = e.data; if (d && d.type === 'streamlit:render') receber(d.args || {}); });
STL.ready();
STL.height(S.alt);
ajustaAltura();
})();
