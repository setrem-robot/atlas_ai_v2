# atlas_ai_v2 (RobotEye) — contexto para Claude Code

**Como o repositório funciona, ponta a ponta:**
[`COMO-FUNCIONA.md`](./COMO-FUNCIONA.md) — o caminho de uma pergunta desde o
microfone até a face, as peças uma a uma, e as decisões que explicam o desenho.

O orçamento de performance no Raspberry Pi 5 e as convenções de estilo deste
repositório estão em
**[`.claude/agents/roboteye-keeper.md`](./.claude/agents/roboteye-keeper.md)**
— leia aquilo primeiro para qualquer mudança de código. Este arquivo cobre
só o que falta: a relação (ou falta dela) com o resto do projeto do robô.

## Um ponto de contato com o `orquestrador`, e só um

O RobotEye (a "cara" da Atlas) e o `orquestrador` (o "corpo": motores, GPS,
Wi-Fi) continuam sendo dois programas separados. Mas **deixaram de ser
desacoplados**: a ponte Bluetooth trouxe um ponto de contato, e ele é o único.

- **`src/roboteye/ble/`** — o Pi anuncia o serviço BLE que era do ESP32 e
  publica o que chega do celular em `robo/comando/entrada`, o mesmo tópico que
  o `serial_ingestor` alimentava. Daí para a frente o caminho é todo do
  `orquestrador`: ele roteia para `robo/motores/comando`, e o serviço `motores`
  executa. O contrato desse tópico mora em `robo_common/topics.py`, no outro
  repositório — mudar o nome aqui sem mudar lá faz o robô aceitar comandos e
  não mover nada.
- **`src/roboteye/web/comandos.py`** — a página do celular assina o mesmo
  barramento só para *mostrar* o que o robô está obedecendo. Lê, não escreve.

Fora esses dois, `src/roboteye/` não conhece MQTT, serial nem GPIO — e a
`Assistant` de `core/assistant.py` continua sendo um "orquestrador" só no
sentido comum da palavra (liga LLM + memória + voz), sem relação com o
repositório de mesmo nome.

**Um broker só.** `scripts/setup-raspberry-pi.sh --bluetooth-app` instala o
Mosquitto pelo apt, e o `pi/docker-compose.yml` do `orquestrador` sobe outro na
mesma porta 1883. O segundo a subir falha com "Address already in use", e o
sintoma não parece de broker: o app conecta, os comandos chegam ao Pi e o robô
não se mexe — porque esta ponte publica com sucesso num broker que ninguém mais
escuta. Ver `../orquestrador/pi/mosquitto/apt/robo.conf.example`.

O que ainda **não** existe: o RobotEye reagir a `robo/telemetria/bateria`, ou
falar quando alguém publica em `robo/voz/falar`. Isso é trabalho novo. Veja
[`../orquestrador/MAPA-COMUNICACAO.md`](../orquestrador/MAPA-COMUNICACAO.md)
para o mapa completo do que existe hoje.

**E o outro lado da ponte não está instalado no robô.** Conferido por SSH: no
Pi rodam a face, esta ponte BLE e o Mosquitto — nenhum serviço do
`orquestrador`. Então o que esta ponte publica em `robo/comando/entrada` não é
consumido por ninguém, e o robô não anda por mais certo que este repositório
esteja. Antes de procurar defeito aqui, rode no Pi:

```bash
mosquitto_sub -h 127.0.0.1 -t 'robo/#' -v      # aperte uma direção no app
```

Se aparecer `robo/comando/entrada` e mais nada, o problema é do outro lado — a
§0 do mapa explica.

## Já fortemente orientado a objetos

Se for usar este projeto como exemplo de POO para a disciplina do curso,
os pontos mais fortes (com arquivo:linha) são:

- **Herança + polimorfismo clássicos**: `core/events.py::Event` (dataclass
  base, `frozen=True`) com 10 subclasses (`UserMessage`, `ThinkingStarted`,
  `AssistantReply`, `SpeechStarted`, `SpeechFinished`, `SpeechHeard`,
  `ListeningChanged`, `ErrorOccurred`, `Notice`, `Shutdown`); `EventBus.publish` despacha por `isinstance`. É o
  exemplo mais "de livro-texto" do projeto inteiro.
- **Factory Method**: `llm/factory.py::create_llm_client` e
  `speech/factory.py::create_tts_engine` escolhem a implementação concreta
  (`match backend: case "ollama"/"echo"` e `case "piper"/"kokoro"/"edge"/"null"`).
- **Decorator**: `speech/fallback.py::FallbackEngine` embrulha dois
  `TTSEngine` (primário + reserva) atrás da mesma interface.
- **Abstração via `typing.Protocol`** (não `abc.ABC`): `llm/base.py::LLMClient`
  e `speech/base.py::TTSEngine` — importante notar essa diferença se a
  disciplina exigir herança nominal clássica (`class X(Base):`); Protocol é
  "duck typing" estruturalmente tipado, não herança nominal.
- **Injeção de dependência + encapsulamento**: `core/assistant.py::Assistant`
  recebe todos os colaboradores (`llm`, `memory`, `speaker`, `bus`, `persona`)
  no `__init__`, guarda tudo como atributo privado, e implementa o protocolo
  de context manager (`__enter__`/`__exit__`).
- **Dataclasses `frozen=True, slots=True`** em todo `config.py`, com
  `from_env()` como construtor alternativo (classmethod).
