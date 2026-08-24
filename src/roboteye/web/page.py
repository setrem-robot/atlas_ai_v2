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
    --fundo: #0e1116; --cartao: #171b22; --borda: #262c36;
    --texto: #e6e9ef; --fraco: #9aa4b2; --olho: #04c9fd;
    --ok: #3ddc84; --erro: #ff6b6b; --aviso: #ffc857;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 16px 14px 48px;
    background: var(--fundo); color: var(--texto);
    font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
  }
  h1 { font-size: 20px; margin: 0 0 2px; }
  h1 span { color: var(--olho); }
  .sub { color: var(--fraco); font-size: 13px; margin-bottom: 20px; }
  fieldset {
    border: 1px solid var(--borda); border-radius: 12px;
    background: var(--cartao); padding: 14px; margin: 0 0 14px;
  }
  legend { padding: 0 6px; font-size: 13px; color: var(--fraco); text-transform: uppercase;
           letter-spacing: .06em; }
  label { display: block; margin: 12px 0 4px; font-size: 13px; color: var(--fraco); }
  input, select {
    width: 100%; padding: 11px 12px; font-size: 16px;
    background: #0e1116; color: var(--texto);
    border: 1px solid var(--borda); border-radius: 8px;
  }
  input:focus, select:focus { outline: 2px solid var(--olho); outline-offset: -1px; }
  button {
    padding: 11px 16px; font-size: 15px; font-weight: 600; cursor: pointer;
    background: var(--olho); color: #04121a; border: 0; border-radius: 8px;
  }
  button.leve { background: transparent; color: var(--texto); border: 1px solid var(--borda); }
  button:disabled { opacity: .5; cursor: progress; }
  .linha { display: flex; gap: 8px; align-items: center; }
  .linha input { flex: 1; }
  .aviso { font-size: 13px; margin-top: 8px; white-space: pre-wrap; }
  .ok { color: var(--ok); } .ruim { color: var(--erro); } .neutro { color: var(--fraco); }
  .rodape { position: sticky; bottom: 0; padding: 12px 0 0;
            background: linear-gradient(transparent, var(--fundo) 30%); }
  .rodape button { width: 100%; }
  .falas{max-height:190px;overflow-y:auto;margin-bottom:10px}
.falas p{margin:0 0 6px;line-height:1.35}
.falas .quem{opacity:.6;font-size:.8em;text-transform:uppercase;letter-spacing:.04em}
.dica { font-size: 12px; color: var(--fraco); margin-top: 6px; }
  #entrada { max-width: 320px; margin: 60px auto; text-align: center; }
</style>
</head>
<body>

<div id="entrada">
  <h1>Robot<span>Eye</span></h1>
  <p class="sub">Informe o PIN mostrado no terminal do robô.</p>
  <input id="pin" type="tel" inputmode="numeric" maxlength="6" placeholder="000000"
         style="text-align:center; font-size:26px; letter-spacing:.3em">
  <p class="aviso" id="erroPin"></p>
  <button style="margin-top:12px; width:100%" onclick="entrar()">Entrar</button>
</div>

<main id="painel" hidden>
  <h1>Robot<span>Eye</span></h1>
  <p class="sub">Configuração do robô</p>

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
                "ROBOTEYE_VOICE_FALLBACK","ROBOTEYE_VOICE_GAIN","ROBOTEYE_EYE_COLOR",
                "ROBOTEYE_FACE_QUALITY","ROBOTEYE_FACE_FULLSCREEN"];

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
    $("painel").hidden = false;
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
  // O robo pode ser interpelado de mais de um lugar (aqui e pelo SSH); manter a
  // pagina olhando faz ela mostrar tambem o que nao passou por ela.
  if (!window._relogioConversa) {
    window._relogioConversa = setInterval(atualizarConversa, 4000);
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

async function atualizarConversa() {
  try {
    const estado = await api("/api/state");
    pintarFalas(estado.conversa);
  } catch (e) { /* a pagina continua util sem isso */ }
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
