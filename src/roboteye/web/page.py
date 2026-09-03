"""A pagina de configuracao, num arquivo so.

Fica embutida como texto em vez de virar um arquivo estatico por um motivo
pratico: assim ela acompanha o pacote sem depender de como o projeto foi
instalado. Nao ha build, nao ha node_modules, nao ha nada a servir do disco.

A pagina e desenhada para o celular, que e de onde ela sera aberta — alguem em
pe na frente do robo, sem teclado.
"""

from __future__ import annotations

PAGE = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RobotEye</title>
<style>
  :root {
    /* O ciano e a cor dos olhos da Atlas; o fundo puxa levemente para ele, em
       vez de um cinza neutro qualquer. */
    --fundo: #090d13; --cartao: #131923; --cartao-alto: #1a212d;
    --borda: #232c3a; --borda-forte: #33405280;
    --texto: #e8edf5; --fraco: #93a1b5; --apagado: #66748a;
    --olho: #04c9fd; --olho-fundo: #04c9fd14;
    --ok: #3ddc84; --erro: #ff6b6b; --aviso: #ffc857;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 0 0 56px;
    background:
      radial-gradient(90rem 40rem at 50% -18rem, #0c2130 0%, transparent 65%),
      var(--fundo);
    color: var(--texto);
    font: 16px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  main, #entrada { max-width: 34rem; margin: 0 auto; padding: 0 14px; }

  /* --- cabecalho: os olhos da Atlas --- */
  .capa { padding: 26px 0 20px; display: flex; align-items: center; gap: 13px; }
  .olhos { display: flex; gap: 7px; flex: none; }
  .olhos i {
    width: 15px; height: 21px; border-radius: 5px; background: var(--olho);
    box-shadow: 0 0 16px #04c9fd66;
    animation: piscar 5.5s infinite;
  }
  .olhos i:last-child { animation-delay: .07s; }
  @keyframes piscar {
    0%, 92%, 100% { transform: scaleY(1); }
    95% { transform: scaleY(.12); }
  }
  @media (prefers-reduced-motion: reduce) { .olhos i { animation: none; } }

  h1 { font-size: 21px; margin: 0; letter-spacing: -.02em; font-weight: 650; }
  h1 span { color: var(--olho); }
  .sub { color: var(--fraco); font-size: 13px; margin: 1px 0 0; }

  fieldset {
    border: 1px solid var(--borda); border-radius: 14px;
    background: linear-gradient(var(--cartao-alto), var(--cartao));
    padding: 15px 15px 17px; margin: 0 0 13px;
  }
  legend {
    padding: 0 7px; font-size: 11px; color: var(--apagado); text-transform: uppercase;
    letter-spacing: .11em; font-weight: 600;
  }
  label { display: block; margin: 12px 0 4px; font-size: 13px; color: var(--fraco); }
  input, select {
    width: 100%; padding: 11px 12px; font-size: 16px;
    background: #0a0f16; color: var(--texto);
    border: 1px solid var(--borda); border-radius: 9px;
  }
  input:focus, select:focus, button:focus-visible {
    outline: 2px solid var(--olho); outline-offset: -1px;
  }
  button {
    padding: 11px 17px; font-size: 15px; font-weight: 600; cursor: pointer;
    background: var(--olho); color: #04121a; border: 0; border-radius: 9px;
  }
  button:active { transform: translateY(1px); }
  button.leve { background: transparent; color: var(--texto); border: 1px solid var(--borda); }
  button:disabled { opacity: .5; cursor: progress; }
  .linha { display: flex; gap: 8px; align-items: center; }
  .linha input { flex: 1; }
  .aviso { font-size: 13px; margin-top: 8px; white-space: pre-wrap; }
  .ok { color: var(--ok); } .ruim { color: var(--erro); } .neutro { color: var(--fraco); }
  .rodape { position: sticky; bottom: 0; padding: 12px 0 0;
            background: linear-gradient(transparent, var(--fundo) 30%); }
  .rodape button { width: 100%; }
  .painel {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(8.4rem, 1fr)); gap: 9px;
  }
  .medida {
    background: #0a0f16; border: 1px solid var(--borda); border-radius: 10px;
    padding: 10px 11px; position: relative; overflow: hidden;
  }
  /* Uma faixa fina na borda de cima carrega o estado; a cor do numero sozinha
     e dificil de ver de relance, que e como este painel e lido. */
  .medida::before {
    content: ""; position: absolute; inset: 0 0 auto 0; height: 2px;
    background: var(--borda-forte);
  }
  .medida.bom::before { background: var(--ok); }
  .medida.alerta::before { background: var(--aviso); }
  .medida .rot {
    display: block; font-size: 10.5px; letter-spacing: .09em;
    text-transform: uppercase; color: var(--apagado); font-weight: 600;
  }
  .medida .val {
    font-size: 19px; font-weight: 650; font-variant-numeric: tabular-nums;
    letter-spacing: -.01em; margin-top: 2px;
  }
  .medida .sub { font-size: 11.5px; color: var(--fraco); }
  .medida.alerta .val { color: var(--aviso); }
  .medida.bom .val { color: var(--ok); }
  /* --- controle --- */
  .controle { display: flex; gap: 15px; align-items: center; }
  .cruz {
    display: grid; grid-template-columns: repeat(3, 30px); grid-template-rows: repeat(3, 30px);
    gap: 3px; flex: none;
  }
  .seta {
    display: grid; place-items: center; font-size: 12px;
    background: #0a0f16; border: 1px solid var(--borda); border-radius: 7px;
    color: var(--apagado); transition: none;
  }
  .seta.cima  { grid-area: 1 / 2; }
  .seta.esq   { grid-area: 2 / 1; }
  .seta.meio  { grid-area: 2 / 2; font-size: 9px; }
  .seta.dir   { grid-area: 2 / 3; }
  .seta.baixo { grid-area: 3 / 2; }
  .seta.aceso {
    background: var(--olho); border-color: var(--olho); color: #04121a;
    box-shadow: 0 0 14px #04c9fd55;
  }
  .seta.parada { background: #2a3140; border-color: #3a4356; color: var(--texto); }
  .controle-lado { min-width: 0; }
  .controle-lado .rot {
    display: block; font-size: 10.5px; letter-spacing: .09em;
    text-transform: uppercase; color: var(--apagado); font-weight: 600;
  }
  .agora { font-size: 25px; font-weight: 650; letter-spacing: -.02em; margin-top: 1px; }
  .agora.vivo { color: var(--olho); }
  /* A fita e o rastro dos ultimos comandos: o mais novo entra pela esquerda e
     os antigos vao apagando, para se ver o ritmo do toque sem ler texto. */
  .fita { display: flex; gap: 4px; margin-top: 12px; height: 20px; overflow: hidden; }
  .fita span {
    flex: none; width: 20px; display: grid; place-items: center; font-size: 9px;
    border-radius: 5px; background: #0a0f16; border: 1px solid var(--borda);
    color: var(--fraco);
  }

  .falas { max-height: 200px; overflow-y: auto; margin-bottom: 11px;
           display: flex; flex-direction: column; gap: 7px; }
  .falas p {
    margin: 0; line-height: 1.4; font-size: 14.5px;
    background: #0a0f16; border: 1px solid var(--borda);
    border-radius: 10px; padding: 7px 10px;
  }
  .falas .quem {
    display: block; color: var(--apagado); font-size: 10px; font-weight: 600;
    text-transform: uppercase; letter-spacing: .09em; margin-bottom: 1px;
  }
.dica { font-size: 12px; color: var(--fraco); margin-top: 6px; }
  #entrada { max-width: 320px; margin: 60px auto; text-align: center; }
</style>
</head>
<body>

<div id="entrada">
  <div class="capa" style="justify-content:center">
    <div class="olhos"><i></i><i></i></div>
    <div><h1>Atlas</h1><p class="sub">painel do robô</p></div>
  </div>
  <p class="sub" style="margin-bottom:14px">Informe o PIN mostrado no terminal do robô.</p>
  <input id="pin" type="tel" inputmode="numeric" maxlength="6" placeholder="000000"
         style="text-align:center; font-size:26px; letter-spacing:.3em">
  <p class="aviso" id="erroPin"></p>
  <button style="margin-top:12px; width:100%" onclick="entrar()">Entrar</button>
</div>

<main id="conteudo" hidden>
  <div class="capa">
    <div class="olhos"><i></i><i></i></div>
    <div><h1>Atlas</h1><p class="sub">painel do robô</p></div>
  </div>

  <fieldset>
    <legend>Inteligência</legend>
    <label for="ROBOTEYE_OLLAMA_HOST">Endereço da máquina com a IA</label>
    <div class="linha">
      <input id="ROBOTEYE_OLLAMA_HOST" placeholder="192.168.1.50:11434">
      <button class="leve" onclick="testarIA()">Testar</button>
    </div>
    <p class="dica">IP e porta da máquina onde o Ollama roda. Teste antes de salvar.</p>
    <p class="aviso" id="resIA"></p>

    <label for="ROBOTEYE_LLM_MODEL">Modelo</label>
    <input id="ROBOTEYE_LLM_MODEL" list="modelos" placeholder="qwen3:8b">
    <datalist id="modelos"></datalist>

    <label for="ROBOTEYE_PERSONA">Personalidade</label>
    <select id="ROBOTEYE_PERSONA"></select>
  </fieldset>

  <fieldset>
    <legend>Voz</legend>
    <label for="ROBOTEYE_VOICE">Voz</label>
    <select id="ROBOTEYE_VOICE"></select>

    <label for="ROBOTEYE_VOICE_FALLBACK">Reserva quando faltar internet</label>
    <input id="ROBOTEYE_VOICE_FALLBACK" placeholder="auto">
    <p class="dica">auto, off, ou o nome de uma voz local.</p>

    <label for="ROBOTEYE_VOICE_GAIN">Volume</label>
    <input id="ROBOTEYE_VOICE_GAIN" placeholder="1.0">

    <div style="margin-top:12px">
      <button class="leve" onclick="testarVoz()">Falar uma frase</button>
    </div>
    <p class="aviso" id="resVoz"></p>
  </fieldset>

  <fieldset id="blocoControle">
    <legend>Controle</legend>
    <div class="controle">
      <div class="cruz">
        <span class="seta cima" data-dir="frente">&#9650;</span>
        <span class="seta esq" data-dir="esquerda">&#9664;</span>
        <span class="seta meio" data-dir="parar">&#9632;</span>
        <span class="seta dir" data-dir="direita">&#9654;</span>
        <span class="seta baixo" data-dir="tras">&#9660;</span>
      </div>
      <div class="controle-lado">
        <span class="rot">Comando agora</span>
        <div class="agora" id="comandoAtual">—</div>
        <p class="dica" id="comandoDica">esperando o celular</p>
      </div>
    </div>
    <div class="fita" id="fitaComandos"></div>
  </fieldset>

  <fieldset>
    <legend>O robô agora</legend>
    <div id="estadoRobo" class="painel">carregando…</div>
    <p class="dica" id="versaoRobo"></p>
  </fieldset>

  <fieldset id="blocoConversa" style="display:none">
    <legend>Conversar</legend>
    <div id="falas" class="falas"></div>
    <input id="msg" placeholder="Digite e a Atlas responde falando"
           onkeydown="if(event.key==='Enter') conversar()">
    <div style="margin-top:12px">
      <button class="leve" onclick="conversar()">Enviar</button>
    </div>
    <p class="aviso" id="resConversa"></p>
  </fieldset>

  <fieldset>
    <legend>Escuta</legend>
    <label for="ROBOTEYE_HEARING_MODEL_SIZE">Reconhecimento de fala</label>
    <select id="ROBOTEYE_HEARING_MODEL_SIZE">
      <option value="tiny">rápido (tiny) — ~0,9 s</option>
      <option value="base">preciso (base) — ~1,9 s</option>
      <option value="small">mais preciso (small) — pesado no Pi</option>
    </select>
    <p class="dica">
      Quanto o robô demora para entender o que você falou, e o quanto ele acerta.
      O <b>base</b> pontua melhor e erra menos com voz de criança; o <b>tiny</b>
      responde um segundo antes. Trocar aqui baixa o modelo novo na primeira vez.
    </p>
  </fieldset>

  <fieldset>
    <legend>Face</legend>
    <label for="ROBOTEYE_EYE_COLOR">Cor dos olhos</label>
    <input id="ROBOTEYE_EYE_COLOR" placeholder="#04C9FD">
    <label for="ROBOTEYE_FACE_QUALITY">Qualidade do desenho</label>
    <select id="ROBOTEYE_FACE_QUALITY">
      <option value="auto">auto</option><option value="low">baixa</option>
      <option value="medium">média</option><option value="high">alta</option>
    </select>
    <label for="ROBOTEYE_FACE_FULLSCREEN">Tela cheia</label>
    <select id="ROBOTEYE_FACE_FULLSCREEN">
      <option value="true">sim</option><option value="false">não</option>
    </select>
  </fieldset>

  <fieldset id="blocoAtualizar" style="display:none">
    <legend>Versão</legend>
    <p class="dica">
      Traz a versão publicada e reinicia o robô. Se a nova versão não subir, ele
      volta sozinho para a anterior. Espera a Atlas terminar de falar.
    </p>
    <button class="leve" onclick="atualizar()">Atualizar o robô</button>
    <p class="aviso" id="resAtualizar"></p>
  </fieldset>

  <p class="aviso" id="resSalvar"></p>
  <div class="rodape">
    <button onclick="salvar()">Salvar</button>
    <button class="leve" style="width:100%; margin-top:8px" onclick="reiniciar()">
      Salvar e reiniciar o robô
    </button>
  </div>
</main>

<script>
let PIN = "";
const $ = (id) => document.getElementById(id);
const CAMPOS = ["ROBOTEYE_OLLAMA_HOST","ROBOTEYE_LLM_MODEL","ROBOTEYE_PERSONA","ROBOTEYE_VOICE",
                "ROBOTEYE_VOICE_FALLBACK","ROBOTEYE_VOICE_GAIN","ROBOTEYE_HEARING_MODEL_SIZE",
                "ROBOTEYE_EYE_COLOR","ROBOTEYE_FACE_QUALITY","ROBOTEYE_FACE_FULLSCREEN"];

async function api(rota, corpo) {
  const r = await fetch(rota, {
    method: corpo === undefined ? "GET" : "POST",
    headers: {"X-Pin": PIN, "Content-Type": "application/json"},
    body: corpo === undefined ? undefined : JSON.stringify(corpo),
  });
  const dados = await r.json().catch(() => ({erro: "resposta ilegivel"}));
  if (!r.ok) throw new Error(dados.erro || ("erro " + r.status));
  return dados;
}

function mostrar(id, texto, classe) {
  const el = $(id);
  el.textContent = texto;
  el.className = "aviso " + (classe || "neutro");
}

async function entrar() {
  PIN = $("pin").value.trim();
  try {
    await carregar();
    $("entrada").hidden = true;
    $("conteudo").hidden = false;
  } catch (e) {
    mostrar("erroPin", e.message, "ruim");
  }
}

async function carregar() {
  const estado = await api("/api/state");

  const voz = $("ROBOTEYE_VOICE");
  voz.innerHTML = "";
  for (const v of estado.vozes) {
    const o = document.createElement("option");
    o.value = v.key;
    o.textContent = v.descricao + (v.online ? "  (nuvem)" : "");
    voz.append(o);
  }
  const persona = $("ROBOTEYE_PERSONA");
  persona.innerHTML = "";
  for (const p of estado.personas) {
    const o = document.createElement("option");
    o.value = p; o.textContent = p;
    persona.append(o);
  }
  pintarFalas(estado.conversa);
  $("blocoAtualizar").style.display =
    estado.atualizacao && estado.atualizacao.disponivel ? "" : "none";
  // O robo pode ser interpelado de mais de um lugar (aqui e pelo SSH); manter a
  // pagina olhando faz ela mostrar tambem o que nao passou por ela.
  if (!window._relogioConversa) {
    window._relogioConversa = setInterval(atualizarConversa, 4000);
  }
  atualizarPainel();
  if (!window._relogioPainel) {
    window._relogioPainel = setInterval(atualizarPainel, 5000);
  }
  // O direcional so tem graca se acompanhar o dedo: 700 ms e o intervalo em
  // que a seta acende junto com o toque, sem pesar no robo.
  if (!window._relogioControle) {
    window._relogioControle = setInterval(async () => {
      try { pintarControle((await api("/api/robo")).controle); } catch (e) { /* sem drama */ }
    }, 700);
  }
  for (const campo of CAMPOS) {
    if (estado.config[campo]) $(campo).value = estado.config[campo];
  }
}

function pintarFalas(conversa) {
  $("blocoConversa").style.display = conversa && conversa.disponivel ? "" : "none";
  if (!conversa || !conversa.disponivel) return;
  const alvo = $("falas");
  alvo.innerHTML = "";
  for (const fala of conversa.falas) {
    const p = document.createElement("p");
    const quem = document.createElement("span");
    quem.className = "quem";
    quem.textContent = fala.quem + " ";
    p.appendChild(quem);
    p.appendChild(document.createTextNode(fala.texto));
    alvo.appendChild(p);
  }
  alvo.scrollTop = alvo.scrollHeight;
}

async function conversar() {
  const campo = $("msg");
  const texto = campo.value.trim();
  if (!texto) return;
  mostrar("resConversa", "enviando...", "");
  try {
    await api("/api/conversar", {texto});
    campo.value = "";
    mostrar("resConversa", "", "");
    // A resposta sai pela voz; a pagina so mostra o que ja foi dito. Uma espera
    // curta e o suficiente para a primeira frase ja aparecer junto.
    setTimeout(atualizarConversa, 1200);
  } catch (e) {
    mostrar("resConversa", e.message, "erro");
  }
}

function medida(rotulo, valor, sub, estado) {
  const classe = estado ? " " + estado : "";
  const rodape = sub ? `<span class="sub">${sub}</span>` : "";
  return `<div class="medida${classe}"><span class="rot">${rotulo}</span>` +
         `<span class="val">${valor}</span>${rodape}</div>`;
}

function duracao(s) {
  if (s === null || s === undefined) return "?";
  if (s < 60) return s + " s";
  const min = Math.floor(s / 60) % 60, h = Math.floor(s / 3600) % 24, d = Math.floor(s / 86400);
  if (d) return `${d} d ${h} h`;
  if (h) return `${h} h ${min} min`;
  return `${min} min`;
}

const SETAS = {frente: "\u25b2", tras: "\u25bc", esquerda: "\u25c0",
               direita: "\u25b6", parar: "\u25a0"};

function pintarControle(c) {
  const atual = c && c.atual;
  for (const seta of document.querySelectorAll(".seta")) {
    const desta = seta.dataset.dir === atual;
    seta.classList.toggle("aceso", desta && atual !== "parar");
    seta.classList.toggle("parada", desta && atual === "parar");
  }

  const rotulo = $("comandoAtual");
  rotulo.textContent = atual ? atual : "—";
  rotulo.classList.toggle("vivo", !!atual && atual !== "parar");

  $("comandoDica").textContent = !c || !c.total
    ? "esperando o celular"
    : (c.recebendo ? "recebendo agora" : "último há instantes");

  // A fita mostra o rastro: o mais novo na esquerda, os antigos apagando.
  $("fitaComandos").innerHTML = (c && c.ultimos || [])
    .map((u, i) => `<span style="opacity:${(1 - i * 0.075).toFixed(2)}">` +
                   `${SETAS[u.direcao] || "?"}</span>`)
    .join("");
}

async function atualizarPainel() {
  let r;
  try { r = await api("/api/robo"); } catch (e) { return; }

  const partes = [];
  if (r.temperatura !== null) {
    // Sem ventoinha, o Pi reduz a frequência acima do limite — e a resposta da
    // Atlas fica mais lenta sem nada no log dizendo por quê.
    const quente = r.temperatura >= r.temperatura_alerta;
    partes.push(medida("Temperatura", r.temperatura.toFixed(1) + " °C",
      quente ? "acima do limite" : "ok", quente ? "alerta" : "bom"));
  }
  if (r.memoria) {
    partes.push(medida("Memória livre", (r.memoria.livre_mb / 1024).toFixed(1) + " GB",
      `de ${(r.memoria.total_mb / 1024).toFixed(1)} GB`));
  }
  if (r.disco) {
    const apertado = r.disco.livre_gb <= r.disco.minimo_gb;
    partes.push(medida("Cartão livre", r.disco.livre_gb.toFixed(1) + " GB",
      `de ${r.disco.total_gb} GB`, apertado ? "alerta" : ""));
  }
  if (r.carga !== null) partes.push(medida("Carga", r.carga.toFixed(2), "último minuto"));
  partes.push(medida("Ligado há", duracao(r.ligado_ha), ""));

  const bt = r.bluetooth || {};
  partes.push(medida("Celular", bt.conectado ? "conectado" : "não",
    bt.aparelhos && bt.aparelhos.length ? bt.aparelhos[0] : "pelo bluetooth",
    bt.conectado ? "bom" : ""));

  for (const [nome, estado] of Object.entries(r.servicos || {})) {
    const vivo = estado === "active";
    const rotulo = nome.replace("roboteye-ble", "bluetooth do app")
                       .replace("roboteye", "face e voz");
    partes.push(medida(rotulo,
      vivo ? "de pé" : estado, "", vivo ? "bom" : "alerta"));
  }

  pintarControle(r.controle);
  $("estadoRobo").innerHTML = partes.join("");
  $("versaoRobo").textContent = r.versao
    ? `versão: ${r.versao.commit} — ${r.versao.titulo} (${r.versao.quando})` : "";
}

async function atualizarConversa() {
  try {
    const estado = await api("/api/state");
    pintarFalas(estado.conversa);
  } catch (e) { /* a pagina continua util sem isso */ }
}

async function atualizar() {
  if (!confirm("Buscar a versão publicada e reiniciar o robô?")) return;
  mostrar("resAtualizar", "procurando...", "");
  try {
    await api("/api/atualizar", {});
    // A resposta é só o aceite: quem reinicia o robô é o systemd, e este mesmo
    // processo vai embora junto. A página fica sem resposta por alguns segundos
    // e volta — dizer isso evita que pareça travada.
    mostrar("resAtualizar", "atualizando… a página volta em instantes", "");
  } catch (e) {
    mostrar("resAtualizar", e.message, "erro");
  }
}

async function testarIA() {
  mostrar("resIA", "testando...", "neutro");
  try {
    const r = await api("/api/test/llm", {host: $("ROBOTEYE_OLLAMA_HOST").value});
    if (!r.ok) { mostrar("resIA", "sem resposta: " + r.erro, "ruim"); return; }
    mostrar("resIA", `respondeu em ${r.ms} ms — ${r.modelos.length} modelo(s)`, "ok");
    $("modelos").innerHTML = "";
    for (const m of r.modelos) {
      const o = document.createElement("option"); o.value = m;
      $("modelos").append(o);
    }
    if (r.modelos.length && !$("ROBOTEYE_LLM_MODEL").value) {
      $("ROBOTEYE_LLM_MODEL").value = r.modelos[0];
    }
  } catch (e) { mostrar("resIA", e.message, "ruim"); }
}

async function testarVoz() {
  mostrar("resVoz", "falando...", "neutro");
  try {
    const r = await api("/api/test/voice", {});
    mostrar("resVoz", r.ok ? `falou com a voz ${r.voz}` : "nao saiu audio", r.ok ? "ok" : "ruim");
  } catch (e) { mostrar("resVoz", e.message, "ruim"); }
}

function coletar() {
  const dados = {};
  for (const campo of CAMPOS) dados[campo] = $(campo).value.trim();
  return dados;
}

async function salvar() {
  mostrar("resSalvar", "salvando...", "neutro");
  try {
    await api("/api/config", coletar());
    mostrar("resSalvar", "salvo. reinicie o robo para valer.", "ok");
    return true;
  } catch (e) { mostrar("resSalvar", e.message, "ruim"); return false; }
}

async function reiniciar() {
  if (!(await salvar())) return;
  mostrar("resSalvar", "reiniciando...", "neutro");
  try {
    const r = await api("/api/restart", {});
    mostrar("resSalvar", r.ok ? "reiniciado." : ("nao reiniciou: " + r.erro), r.ok ? "ok" : "ruim");
  } catch (e) { mostrar("resSalvar", e.message, "ruim"); }
}

$("pin").addEventListener("keydown", (e) => { if (e.key === "Enter") entrar(); });
</script>
</body>
</html>
"""
