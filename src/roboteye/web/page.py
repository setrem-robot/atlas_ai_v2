"""A pagina de configuracao e conversa, num arquivo so.

Fica embutida como texto em vez de virar um arquivo estatico por um motivo
pratico: assim ela acompanha o pacote sem depender de como o projeto foi
instalado. Nao ha build, nao ha node_modules, nao ha nada a servir do disco.

A pagina e desenhada para o celular e para projecao: o centro e a conversa com a
Atlas; a configuracao fica recolhida em "Ajustes avancados", fora do caminho de
quem so quer mostrar o robo respondendo.
"""

from __future__ import annotations

PAGE = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Atlas</title>
<style>
  :root {
    --fundo:#090d14; --cartao:#141b26; --cartao2:#1b2432; --borda:#27313f;
    --texto:#eaf0f8; --fraco:#9aa8bc; --apagado:#64748b;
    --olho:#04c9fd; --olho-suave:#04c9fd1f; --olho-escuro:#04121a;
    --ok:#3ddc84; --erro:#ff6b6b; --aviso:#ffc857;
    --r:16px;
  }
  * { box-sizing:border-box; }
  html, body { height:100%; }
  body {
    margin:0;
    background:
      radial-gradient(70rem 36rem at 50% -16rem, #0d2434 0%, transparent 62%),
      var(--fundo);
    color:var(--texto);
    font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
    -webkit-font-smoothing:antialiased;
  }
  .wrap { max-width:44rem; margin:0 auto; padding:0 16px env(safe-area-inset-bottom); }

  /* ---------- olhos da Atlas ---------- */
  .olhos { display:inline-flex; gap:.34em; flex:none; }
  .olhos i {
    width:.62em; height:.9em; border-radius:.22em; background:var(--olho);
    box-shadow:0 0 .7em #04c9fd80; animation:piscar 5.4s infinite;
  }
  .olhos i:last-child { animation-delay:.08s; }
  @keyframes piscar { 0%,92%,100%{transform:scaleY(1)} 95%{transform:scaleY(.1)} }
  @media (prefers-reduced-motion:reduce){ .olhos i{animation:none} }

  /* ---------- login ---------- */
  #entrada { max-width:21rem; margin:17vh auto 0; text-align:center; }
  #entrada .marca { font-size:30px; display:flex; justify-content:center; align-items:center; gap:14px; }
  #entrada h1 { font-size:26px; margin:14px 0 2px; letter-spacing:-.02em; }
  #entrada .sub { color:var(--fraco); font-size:14px; margin:0 0 20px; }
  #pin {
    width:100%; padding:14px; text-align:center; font-size:28px; letter-spacing:.34em;
    background:#0b1119; color:var(--texto); border:1px solid var(--borda); border-radius:12px;
  }
  #entrada button { width:100%; margin-top:12px; }

  /* ---------- cabecalho ---------- */
  .topo {
    display:flex; align-items:center; gap:13px; padding:20px 0 14px;
    position:sticky; top:0; z-index:5;
    background:linear-gradient(var(--fundo) 72%, transparent);
  }
  .topo .marca { font-size:22px; display:flex; align-items:center; gap:11px; }
  .topo h1 { font-size:20px; margin:0; font-weight:650; letter-spacing:-.02em; }
  .topo h1 small { display:block; font-size:12px; color:var(--apagado); font-weight:500; letter-spacing:.02em; }
  .vivo {
    margin-left:auto; display:inline-flex; align-items:center; gap:7px;
    font-size:12px; color:var(--fraco); background:var(--cartao); border:1px solid var(--borda);
    padding:6px 11px; border-radius:999px;
  }
  .vivo b { width:8px; height:8px; border-radius:50%; background:var(--ok); box-shadow:0 0 0 0 #3ddc8466; animation:pulso 2.4s infinite; }
  @keyframes pulso { 0%{box-shadow:0 0 0 0 #3ddc8455} 70%{box-shadow:0 0 0 7px #3ddc8400} 100%{box-shadow:0 0 0 0 #3ddc8400} }

  /* ---------- conversa (o centro) ---------- */
  .chat {
    background:linear-gradient(var(--cartao2),var(--cartao));
    border:1px solid var(--borda); border-radius:var(--r);
    padding:14px; box-shadow:0 20px 50px -30px #000;
  }
  .falas {
    height:clamp(280px, 58vh, 640px); overflow-y:auto; padding:4px 4px 2px;
    display:flex; flex-direction:column; gap:12px; scroll-behavior:smooth;
  }
  .falas::-webkit-scrollbar { width:7px; }
  .falas::-webkit-scrollbar-thumb { background:#2b3747; border-radius:9px; }
  .vazio { margin:auto; text-align:center; color:var(--apagado); font-size:14px; padding:20px; }

  .msg { display:flex; align-items:flex-end; gap:9px; max-width:86%; }
  .msg .av { flex:none; width:30px; height:30px; border-radius:9px;
    background:var(--olho-suave); border:1px solid #04c9fd33;
    display:grid; place-items:center; }
  .msg .av .olhos i { width:5px; height:8px; }
  .bolha {
    padding:10px 14px; border-radius:15px; font-size:15.5px; line-height:1.45;
    white-space:pre-wrap; word-break:break-word;
  }
  .msg.ela { align-self:flex-start; }
  .msg.ela .bolha {
    background:var(--cartao2); border:1px solid var(--borda);
    border-bottom-left-radius:5px; color:var(--texto);
  }
  .msg.eu { align-self:flex-end; flex-direction:row-reverse; }
  .msg.eu .bolha {
    background:linear-gradient(160deg,#17d3ff,#04b6ec); color:var(--olho-escuro);
    font-weight:550; border-bottom-right-radius:5px;
  }
  .msg.err .bolha { background:#2a1414; border:1px solid #5a2a2a; color:var(--erro); }
  .pensando .bolha { padding:13px 15px; }
  .dots { display:inline-flex; gap:5px; }
  .dots b { width:7px; height:7px; border-radius:50%; background:var(--olho); opacity:.5; animation:salta 1.1s infinite; }
  .dots b:nth-child(2){ animation-delay:.16s; } .dots b:nth-child(3){ animation-delay:.32s; }
  @keyframes salta { 0%,80%,100%{transform:translateY(0);opacity:.4} 40%{transform:translateY(-5px);opacity:1} }

  .barra { display:flex; gap:9px; margin-top:12px; align-items:center; }
  .barra input {
    flex:1; padding:14px 16px; font-size:16px; background:#0b1119; color:var(--texto);
    border:1px solid var(--borda); border-radius:999px;
  }
  .barra input::placeholder { color:var(--apagado); }
  .enviar {
    flex:none; width:50px; height:50px; border-radius:50%; border:0; cursor:pointer;
    background:var(--olho); color:var(--olho-escuro); font-size:22px; line-height:1;
    display:grid; place-items:center;
  }
  .enviar:active { transform:scale(.94); }
  .dica-chat { font-size:12px; color:var(--apagado); margin:9px 2px 0; text-align:center; }

  /* ---------- avancado (recolhido) ---------- */
  details.av {
    margin:16px 0 40px; border:1px solid var(--borda); border-radius:14px;
    background:var(--cartao); overflow:hidden;
  }
  details.av > summary {
    list-style:none; cursor:pointer; padding:14px 16px; font-size:13px; color:var(--fraco);
    display:flex; align-items:center; gap:9px; font-weight:600;
  }
  details.av > summary::-webkit-details-marker { display:none; }
  details.av > summary::before {
    content:"⚙"; font-size:14px; opacity:.7;
  }
  details.av > summary::after { content:"▾"; margin-left:auto; transition:transform .2s; }
  details.av[open] > summary::after { transform:rotate(180deg); }
  details.av > summary + * { margin-top:0; }
  .corpo-av { padding:0 14px 14px; }

  fieldset { border:1px solid var(--borda); border-radius:12px; background:#0f1620; padding:13px 14px 15px; margin:0 0 12px; }
  legend { padding:0 7px; font-size:11px; color:var(--apagado); text-transform:uppercase; letter-spacing:.11em; font-weight:600; }
  label { display:block; margin:12px 0 4px; font-size:13px; color:var(--fraco); }
  input, select {
    width:100%; padding:11px 12px; font-size:16px; background:#0a1017; color:var(--texto);
    border:1px solid var(--borda); border-radius:9px;
  }
  input:focus, select:focus, button:focus-visible, .barra input:focus { outline:2px solid var(--olho); outline-offset:-1px; }
  button {
    padding:11px 17px; font-size:15px; font-weight:600; cursor:pointer;
    background:var(--olho); color:var(--olho-escuro); border:0; border-radius:10px;
  }
  button:active { transform:translateY(1px); }
  button.leve { background:transparent; color:var(--texto); border:1px solid var(--borda); }
  button:disabled { opacity:.5; cursor:progress; }
  .linha { display:flex; gap:8px; align-items:center; } .linha input { flex:1; }
  .aviso { font-size:13px; margin-top:8px; white-space:pre-wrap; }
  .ok{color:var(--ok)} .ruim{color:var(--erro)} .neutro{color:var(--fraco)}
  .dica { font-size:12px; color:var(--fraco); margin-top:6px; }

  .painel { display:grid; grid-template-columns:repeat(auto-fit,minmax(8.2rem,1fr)); gap:9px; }
  .medida { background:#0a1017; border:1px solid var(--borda); border-radius:10px; padding:10px 11px; position:relative; overflow:hidden; }
  .medida::before { content:""; position:absolute; inset:0 0 auto 0; height:2px; background:#33405280; }
  .medida.bom::before{background:var(--ok)} .medida.alerta::before{background:var(--aviso)}
  .medida .rot { display:block; font-size:10.5px; letter-spacing:.09em; text-transform:uppercase; color:var(--apagado); font-weight:600; }
  .medida .val { font-size:19px; font-weight:650; font-variant-numeric:tabular-nums; margin-top:2px; }
  .medida .sub { font-size:11.5px; color:var(--fraco); }
  .medida.alerta .val{color:var(--aviso)} .medida.bom .val{color:var(--ok)}

  .controle { display:flex; gap:15px; align-items:center; }
  .cruz { display:grid; grid-template-columns:repeat(3,30px); grid-template-rows:repeat(3,30px); gap:3px; flex:none; }
  .seta { display:grid; place-items:center; font-size:12px; background:#0a1017; border:1px solid var(--borda); border-radius:7px; color:var(--apagado); }
  .seta.cima{grid-area:1/2} .seta.esq{grid-area:2/1} .seta.meio{grid-area:2/2;font-size:9px} .seta.dir{grid-area:2/3} .seta.baixo{grid-area:3/2}
  .seta.aceso { background:var(--olho); border-color:var(--olho); color:var(--olho-escuro); box-shadow:0 0 14px #04c9fd55; }
  .seta.parada { background:#2a3140; border-color:#3a4356; color:var(--texto); }
  .controle-lado .rot { display:block; font-size:10.5px; letter-spacing:.09em; text-transform:uppercase; color:var(--apagado); font-weight:600; }
  .agora { font-size:24px; font-weight:650; margin-top:1px; } .agora.vivo { color:var(--olho); }
  .fita { display:flex; gap:4px; margin-top:12px; height:20px; overflow:hidden; }
  .fita span { flex:none; width:20px; display:grid; place-items:center; font-size:9px; border-radius:5px; background:#0a1017; border:1px solid var(--borda); color:var(--fraco); }
  .rodape-av { display:flex; flex-direction:column; gap:8px; }
  .rodape-av button { width:100%; }
</style>
</head>
<body>

<!-- ============ LOGIN ============ -->
<div id="entrada" class="wrap">
  <div class="marca"><span class="olhos"><i></i><i></i></span></div>
  <h1>Atlas</h1>
  <p class="sub">Converse com o robô</p>
  <input id="pin" type="tel" inputmode="numeric" maxlength="6" placeholder="PIN">
  <p class="aviso" id="erroPin"></p>
  <button onclick="entrar()">Entrar</button>
</div>

<!-- ============ CONTEUDO ============ -->
<main id="conteudo" class="wrap" hidden>
  <header class="topo">
    <span class="marca"><span class="olhos"><i></i><i></i></span></span>
    <h1>Atlas<small>robô da SETREM</small></h1>
    <span class="vivo"><b></b>no ar</span>
  </header>

  <!-- CONVERSA: o centro -->
  <section class="chat" id="blocoConversa" style="display:none">
    <div id="falas" class="falas"><div class="vazio">Pergunte algo e a Atlas responde falando.</div></div>
    <form class="barra" onsubmit="conversar(); return false;">
      <input id="msg" placeholder="Escreva uma pergunta…" autocomplete="off">
      <button class="enviar" type="submit" aria-label="Enviar">&#10148;</button>
    </form>
    <p class="aviso" id="resConversa" style="text-align:center"></p>
    <p class="dica-chat">Ex.: “Qual é o seu nome?” · “O que é a SETREM?” · “Quem te construiu?”</p>
  </section>

  <!-- AJUSTES AVANCADOS: recolhido -->
  <details class="av">
    <summary>Ajustes avançados</summary>
    <div class="corpo-av">

      <fieldset>
        <legend>O robô agora</legend>
        <div id="estadoRobo" class="painel">carregando…</div>
        <p class="dica" id="versaoRobo"></p>
      </fieldset>

      <fieldset>
        <legend>Inteligência</legend>
        <label for="ROBOTEYE_OLLAMA_HOST">Endereço da máquina com a IA</label>
        <div class="linha">
          <input id="ROBOTEYE_OLLAMA_HOST" placeholder="192.168.1.50:11434">
          <button class="leve" onclick="testarIA()">Testar</button>
        </div>
        <p class="dica">IP e porta onde o Ollama roda. Teste antes de salvar.</p>
        <p class="aviso" id="resIA"></p>
        <label for="ROBOTEYE_LLM_MODEL">Modelo</label>
        <input id="ROBOTEYE_LLM_MODEL" list="modelos" placeholder="gemma3:1b">
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
        <div style="margin-top:12px"><button class="leve" onclick="testarVoz()">Falar uma frase</button></div>
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
        <legend>Escuta</legend>
        <label for="ROBOTEYE_HEARING_MODEL_SIZE">Reconhecimento de fala</label>
        <select id="ROBOTEYE_HEARING_MODEL_SIZE">
          <option value="tiny">rápido (tiny) — ~0,9 s</option>
          <option value="base">preciso (base) — ~1,9 s</option>
          <option value="small">mais preciso (small) — pesado no Pi</option>
        </select>
        <p class="dica">Quanto o robô demora para entender, e o quanto acerta. Trocar baixa o modelo novo na primeira vez.</p>
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
        <p class="dica">Traz a versão publicada e reinicia o robô. Se não subir, volta sozinho para a anterior.</p>
        <button class="leve" onclick="atualizar()">Atualizar o robô</button>
        <p class="aviso" id="resAtualizar"></p>
      </fieldset>

      <p class="aviso" id="resSalvar"></p>
      <div class="rodape-av">
        <button onclick="salvar()">Salvar</button>
        <button class="leve" onclick="reiniciar()">Salvar e reiniciar o robô</button>
      </div>
    </div>
  </details>
</main>

<script>
let PIN = "";
let PENSANDO = false;
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
function mostrar(id, texto, classe) { const el = $(id); el.textContent = texto; el.className = "aviso " + (classe || "neutro"); }

async function entrar() {
  PIN = $("pin").value.trim();
  try { await carregar(); $("entrada").hidden = true; $("conteudo").hidden = false; }
  catch (e) { mostrar("erroPin", e.message, "ruim"); }
}

async function carregar() {
  const estado = await api("/api/state");
  const voz = $("ROBOTEYE_VOICE"); voz.innerHTML = "";
  for (const v of estado.vozes) {
    const o = document.createElement("option");
    o.value = v.key; o.textContent = v.descricao + (v.online ? "  (nuvem)" : "");
    voz.append(o);
  }
  const persona = $("ROBOTEYE_PERSONA"); persona.innerHTML = "";
  for (const p of estado.personas) { const o = document.createElement("option"); o.value = p; o.textContent = p; persona.append(o); }
  pintarFalas(estado.conversa);
  $("blocoAtualizar").style.display = estado.atualizacao && estado.atualizacao.disponivel ? "" : "none";
  if (!window._relogioConversa) window._relogioConversa = setInterval(atualizarConversa, 3000);
  atualizarPainel();
  if (!window._relogioPainel) window._relogioPainel = setInterval(atualizarPainel, 6000);
  if (!window._relogioControle) window._relogioControle = setInterval(async () => {
    try { pintarControle((await api("/api/robo")).controle); } catch (e) {}
  }, 2000);
  for (const campo of CAMPOS) { if (estado.config[campo]) $(campo).value = estado.config[campo]; }
}

/* ---------- conversa ---------- */
function balaoOlhos() { const d = document.createElement("div"); d.className = "av"; d.innerHTML = '<span class="olhos"><i></i><i></i></span>'; return d; }
function balao(quem, texto) {
  const linha = document.createElement("div");
  linha.className = "msg " + (quem === "voce" ? "eu" : quem === "erro" ? "err" : "ela");
  if (quem !== "voce" && quem !== "erro") linha.appendChild(balaoOlhos());
  const bolha = document.createElement("div"); bolha.className = "bolha"; bolha.textContent = texto;
  linha.appendChild(bolha);
  return linha;
}
function balaoPensando() {
  const l = document.createElement("div"); l.className = "msg ela pensando";
  l.appendChild(balaoOlhos());
  const b = document.createElement("div"); b.className = "bolha";
  b.innerHTML = '<span class="dots"><b></b><b></b><b></b></span>';
  l.appendChild(b); return l;
}
function pintarFalas(conversa) {
  const bloco = $("blocoConversa");
  bloco.style.display = conversa && conversa.disponivel ? "" : "none";
  if (!conversa || !conversa.disponivel) return;
  const alvo = $("falas"); const falas = conversa.falas || [];
  alvo.innerHTML = "";
  if (!falas.length && !PENSANDO) { alvo.innerHTML = '<div class="vazio">Pergunte algo e a Atlas responde falando.</div>'; return; }
  for (const fala of falas) alvo.appendChild(balao(fala.quem, fala.texto));
  const ultimo = falas[falas.length - 1];
  if (PENSANDO && (!ultimo || ultimo.quem === "voce")) alvo.appendChild(balaoPensando());
  else PENSANDO = false;
  alvo.scrollTop = alvo.scrollHeight;
}
async function conversar() {
  const campo = $("msg"); const texto = campo.value.trim();
  if (!texto) return;
  campo.value = ""; PENSANDO = true;
  const alvo = $("falas");
  if (alvo.querySelector(".vazio")) alvo.innerHTML = "";
  alvo.appendChild(balao("voce", texto));
  alvo.appendChild(balaoPensando());
  alvo.scrollTop = alvo.scrollHeight;
  mostrar("resConversa", "", "");
  try { await api("/api/conversar", {texto}); pollRapido(); }
  catch (e) { PENSANDO = false; mostrar("resConversa", e.message, "ruim"); atualizarConversa(); }
}
function pollRapido() {
  let n = 0; clearInterval(window._rapido);
  window._rapido = setInterval(async () => {
    n++; await atualizarConversa();
    if (!PENSANDO || n > 60) clearInterval(window._rapido);
  }, 900);
}
async function atualizarConversa() {
  try { const estado = await api("/api/state"); pintarFalas(estado.conversa); } catch (e) {}
}

/* ---------- painel / status ---------- */
function medida(rotulo, valor, sub, estado) {
  const classe = estado ? " " + estado : "";
  const rodape = sub ? `<span class="sub">${sub}</span>` : "";
  return `<div class="medida${classe}"><span class="rot">${rotulo}</span><span class="val">${valor}</span>${rodape}</div>`;
}
function duracao(s) {
  if (s === null || s === undefined) return "?";
  if (s < 60) return s + " s";
  const min = Math.floor(s/60)%60, h = Math.floor(s/3600)%24, d = Math.floor(s/86400);
  if (d) return `${d} d ${h} h`; if (h) return `${h} h ${min} min`; return `${min} min`;
}
const SETAS = {frente:"▲", tras:"▼", esquerda:"◀", direita:"▶", parar:"■"};
function pintarControle(c) {
  const atual = c && c.atual;
  for (const seta of document.querySelectorAll(".seta")) {
    const desta = seta.dataset.dir === atual;
    seta.classList.toggle("aceso", desta && atual !== "parar");
    seta.classList.toggle("parada", desta && atual === "parar");
  }
  const rotulo = $("comandoAtual"); if (!rotulo) return;
  rotulo.textContent = atual ? atual : "—"; rotulo.classList.toggle("vivo", !!atual && atual !== "parar");
  $("comandoDica").textContent = !c || !c.total ? "esperando o celular" : (c.recebendo ? "recebendo agora" : "último há instantes");
  $("fitaComandos").innerHTML = (c && c.ultimos || [])
    .map((u,i) => `<span style="opacity:${(1-i*0.075).toFixed(2)}">${SETAS[u.direcao]||"?"}</span>`).join("");
}
async function atualizarPainel() {
  let r; try { r = await api("/api/robo"); } catch (e) { return; }
  const partes = [];
  if (r.temperatura !== null) {
    const quente = r.temperatura >= r.temperatura_alerta;
    partes.push(medida("Temperatura", r.temperatura.toFixed(1) + " °C", quente ? "acima do limite" : "ok", quente ? "alerta" : "bom"));
  }
  if (r.memoria) partes.push(medida("Memória livre", (r.memoria.livre_mb/1024).toFixed(1) + " GB", `de ${(r.memoria.total_mb/1024).toFixed(1)} GB`));
  if (r.disco) { const ap = r.disco.livre_gb <= r.disco.minimo_gb; partes.push(medida("Cartão livre", r.disco.livre_gb.toFixed(1) + " GB", `de ${r.disco.total_gb} GB`, ap ? "alerta" : "")); }
  if (r.carga !== null) partes.push(medida("Carga", r.carga.toFixed(2), "último minuto"));
  partes.push(medida("Ligado há", duracao(r.ligado_ha), ""));
  const bt = r.bluetooth || {};
  partes.push(medida("Celular", bt.conectado ? "conectado" : "não", bt.aparelhos && bt.aparelhos.length ? bt.aparelhos[0] : "pelo bluetooth", bt.conectado ? "bom" : ""));
  for (const [nome, estado] of Object.entries(r.servicos || {})) {
    const vivo = estado === "active";
    const rot = nome.replace("roboteye-ble", "bluetooth do app").replace("roboteye", "face e voz");
    partes.push(medida(rot, vivo ? "de pé" : estado, "", vivo ? "bom" : "alerta"));
  }
  pintarControle(r.controle);
  $("estadoRobo").innerHTML = partes.join("");
  $("versaoRobo").textContent = r.versao ? `versão: ${r.versao.commit} — ${r.versao.titulo} (${r.versao.quando})` : "";
}

/* ---------- acoes de ajuste ---------- */
async function atualizar() {
  if (!confirm("Buscar a versão publicada e reiniciar o robô?")) return;
  mostrar("resAtualizar", "procurando...", "");
  try { await api("/api/atualizar", {}); mostrar("resAtualizar", "atualizando… a página volta em instantes", ""); }
  catch (e) { mostrar("resAtualizar", e.message, "erro"); }
}
async function testarIA() {
  mostrar("resIA", "testando...", "neutro");
  try {
    const r = await api("/api/test/llm", {host: $("ROBOTEYE_OLLAMA_HOST").value});
    if (!r.ok) { mostrar("resIA", "sem resposta: " + r.erro, "ruim"); return; }
    mostrar("resIA", `respondeu em ${r.ms} ms — ${r.modelos.length} modelo(s)`, "ok");
    $("modelos").innerHTML = "";
    for (const m of r.modelos) { const o = document.createElement("option"); o.value = m; $("modelos").append(o); }
    if (r.modelos.length && !$("ROBOTEYE_LLM_MODEL").value) $("ROBOTEYE_LLM_MODEL").value = r.modelos[0];
  } catch (e) { mostrar("resIA", e.message, "ruim"); }
}
async function testarVoz() {
  mostrar("resVoz", "falando...", "neutro");
  try { const r = await api("/api/test/voice", {}); mostrar("resVoz", r.ok ? `falou com a voz ${r.voz}` : "nao saiu audio", r.ok ? "ok" : "ruim"); }
  catch (e) { mostrar("resVoz", e.message, "ruim"); }
}
function coletar() { const dados = {}; for (const campo of CAMPOS) dados[campo] = $(campo).value.trim(); return dados; }
async function salvar() {
  mostrar("resSalvar", "salvando...", "neutro");
  try { await api("/api/config", coletar()); mostrar("resSalvar", "salvo. reinicie o robo para valer.", "ok"); return true; }
  catch (e) { mostrar("resSalvar", e.message, "ruim"); return false; }
}
async function reiniciar() {
  if (!(await salvar())) return;
  mostrar("resSalvar", "reiniciando...", "neutro");
  try { const r = await api("/api/restart", {}); mostrar("resSalvar", r.ok ? "reiniciado." : ("nao reiniciou: " + r.erro), r.ok ? "ok" : "ruim"); }
  catch (e) { mostrar("resSalvar", e.message, "ruim"); }
}
$("pin").addEventListener("keydown", (e) => { if (e.key === "Enter") entrar(); });
</script>
</body>
</html>
"""
