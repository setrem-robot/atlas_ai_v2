#!/usr/bin/env python3
"""Treina a Atlas (LoRA sobre o Gemma 3 1B) na GPU do PC e exporta para o Pi.

O Pi não treina nada: ele só recebe o modelo pronto. Treinar aqui troca a
persona longa do prompt (~1000 tokens, que o Pi lê a cada conversa nova) por
pesos que já sabem quem ela é e como falar, e deixa no prompt só os fatos e a
data. Ver `dataset.py` para o que se ensina e `professor.py` para de onde vem
a maior parte dos exemplos.

Ambiente (uma vez, no WSL, com a GPU visível em `nvidia-smi`):
    curl -LsSf https://astral.sh/uv/install.sh | sh
    uv venv -p 3.12 ~/atlas-treino
    VIRTUAL_ENV=~/atlas-treino uv pip install unsloth

Treino (~1 h numa RTX 4060 com uns dez mil exemplos), com o professor fora da
GPU (`python scripts/treino/professor.py descarregar`):
    python scripts/treino/dataset.py > atlas-treino.jsonl
    ~/atlas-treino/bin/python scripts/treino/treinar.py atlas-treino.jsonl
Os checkpoints ficam em `saida-treino/`: se o treino cair no meio, rodar o
mesmo comando continua do último. Sai `atlas-1b/` em safetensors;
`instalar-no-pi.sh` converte para GGUF q4_K_M e leva para o Pi.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from unsloth import FastModel  # importa antes do transformers, como o Unsloth pede
from unsloth.chat_templates import get_chat_template, train_on_responses_only
from datasets import load_dataset
from trl import SFTConfig, SFTTrainer

#: ATLAS_BASE escolhe o modelo base: o Gemma 3 1B de sempre ou o Qwen2.5 1.5B,
#: que vai bem melhor em português (média PT 65,6 contra 54,2) com quase a
#: mesma velocidade no Pi. Cada um com o template que o Ollama dele monta, as
#: marcas de onde começa a resposta e o modelo que empresta o template no Pi.
BASES = {
    "gemma": {"hf": "unsloth/gemma-3-1b-it", "chat": "gemma-3", "ollama": "gemma3:1b",
              "usuario": "<start_of_turn>user\n", "modelo": "<start_of_turn>model\n", "fim": "<end_of_turn>\n"},
    "qwen": {"hf": "unsloth/Qwen2.5-1.5B-Instruct", "chat": "qwen-2.5", "ollama": "qwen2.5:1.5b",
             "usuario": "<|im_start|>user\n", "modelo": "<|im_start|>assistant\n", "fim": "<|im_end|>\n"},
}
ESCOLHA = os.environ.get("ATLAS_BASE", "gemma")
B = BASES[ESCOLHA]
BASE = B["hf"]
SAIDA = "atlas-1b"
CHECKPOINTS = "saida-treino"


def comoOOllamaMonta(mensagens: list[dict], base: str = ESCOLHA) -> str:
    """O texto que o template do gemma3 no Ollama gera para estas mensagens.

    O template de chat do Unsloth junta o sistema dentro da primeira pergunta; o
    do Ollama faz dele um turno de usuário à parte. Treinar num formato e rodar
    no outro é mostrar ao modelo, no Pi, um prompt que ele nunca viu. Por isso o
    texto do treino é montado aqui, igual ao do Pi (`ollama show gemma3:1b
    --modelfile`). Sem o <bos>: a tokenização o acrescenta.
    Termina aberto no turno do modelo; no treino, a última resposta e o
    <end_of_turn> vêm em seguida. As respostas anteriores (a memória da
    conversa) fecham o turno, como o Ollama faz.
    """
    if base == "qwen":
        return comoOOllamaMontaQwen(mensagens)
    texto = ""
    for i, m in enumerate(mensagens):
        if m["role"] in ("system", "user"):
            texto += f"<start_of_turn>user\n{m['content']}<end_of_turn>\n"
        elif i == len(mensagens) - 1:
            return texto + f"<start_of_turn>model\n{m['content']}"
        else:
            texto += f"<start_of_turn>model\n{m['content']}<end_of_turn>\n"
    return texto + "<start_of_turn>model\n"


def comoOOllamaMontaQwen(mensagens: list[dict]) -> str:
    """O mesmo, para o template do qwen2.5 no Ollama (`ollama show qwen2.5:1.5b
    --template`): o sistema vira um turno `system` próprio, e cada resposta
    anterior fecha com <|im_end|>."""
    texto = ""
    for i, m in enumerate(mensagens):
        if m["role"] == "system":
            texto += f"<|im_start|>system\n{m['content']}<|im_end|>\n"
        elif m["role"] == "user":
            texto += f"<|im_start|>user\n{m['content']}<|im_end|>\n"
        elif i == len(mensagens) - 1:
            return texto + f"<|im_start|>assistant\n{m['content']}"
        else:
            texto += f"<|im_start|>assistant\n{m['content']}<|im_end|>\n"
    return texto + "<|im_start|>assistant\n"


assert comoOOllamaMontaQwen(
    [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}, {"role": "assistant", "content": "A"},
     {"role": "user", "content": "V"}]
) == ("<|im_start|>system\nS<|im_end|>\n<|im_start|>user\nU<|im_end|>\n<|im_start|>assistant\nA<|im_end|>\n"
      "<|im_start|>user\nV<|im_end|>\n<|im_start|>assistant\n")
assert comoOOllamaMonta(
    [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}, {"role": "assistant", "content": "A"}], "gemma"
) == "<start_of_turn>user\nS<end_of_turn>\n<start_of_turn>user\nU<end_of_turn>\n<start_of_turn>model\nA"
assert comoOOllamaMonta(
    [{"role": "user", "content": "U"}, {"role": "assistant", "content": "A"}, {"role": "user", "content": "V"}], "gemma"
) == ("<start_of_turn>user\nU<end_of_turn>\n<start_of_turn>model\nA<end_of_turn>\n"
      "<start_of_turn>user\nV<end_of_turn>\n<start_of_turn>model\n")


def main(arquivo: str) -> int:
    model, tokenizer = FastModel.from_pretrained(
        model_name=BASE, max_seq_length=1024, load_in_4bit=False, full_finetuning=False
    )
    # Rank 32 em todas as camadas: com milhares de exemplos, o rank 16 do
    # primeiro treino ficava curto (errava a lei de Ohm que estava no dataset).
    model = FastModel.get_peft_model(
        model,
        finetune_language_layers=True,
        finetune_attention_modules=True,
        finetune_mlp_modules=True,
        r=32,
        lora_alpha=32,
        lora_dropout=0,
        bias="none",
        random_state=7,
    )
    tokenizer = get_chat_template(tokenizer, chat_template=B["chat"])

    dados = load_dataset("json", data_files=arquivo, split="train")
    dados = dados.map(
        lambda lote: {"text": [comoOOllamaMonta(m) + B["fim"] for m in lote["messages"]]},
        batched=True,
    )
    # A validação é separada pelo `dataset.py` por pergunta e por subtema, não
    # sorteada: paráfrase da mesma pergunta dos dois lados mediria decoreba.
    treinoDados = dados.filter(lambda e: e["parte"] == "treino")
    validacao = dados.filter(lambda e: e["parte"] == "validacao")
    print(f"{len(treinoDados)} exemplos de treino, {len(validacao)} de validação")

    passosPorEpoca = len(treinoDados) // 16
    treino = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=treinoDados,
        eval_dataset=validacao,
        args=SFTConfig(
            dataset_text_field="text",
            per_device_train_batch_size=8,
            gradient_accumulation_steps=2,
            num_train_epochs=3,
            learning_rate=1e-4,
            warmup_ratio=0.03,
            lr_scheduler_type="cosine",
            weight_decay=0.01,
            logging_steps=20,
            # Avalia e guarda duas vezes por época; no fim volta para o melhor
            # checkpoint pela eval_loss, e não para o último, que pode já ter
            # começado a decorar.
            eval_strategy="steps",
            eval_steps=max(passosPorEpoca // 2, 1),
            save_strategy="steps",
            save_steps=max(passosPorEpoca // 2, 1),
            save_total_limit=3,
            load_best_model_at_end=True,
            metric_for_best_model="eval_loss",
            greater_is_better=False,
            seed=7,
            output_dir=CHECKPOINTS,
            report_to="none",
        ),
    )
    # Só a resposta conta no erro: o modelo aprende a responder, não a
    # reescrever o prompt e a pergunta.
    treino = train_on_responses_only(
        treino,
        instruction_part=B["usuario"],
        response_part=B["modelo"],
    )
    retomar = any(Path(CHECKPOINTS).glob("checkpoint-*"))
    treino.train(resume_from_checkpoint=retomar or None)
    print(f"melhor checkpoint: {treino.state.best_model_checkpoint} (eval_loss {treino.state.best_metric:.3f})")

    # Olhada rápida antes de exportar: perguntas que o primeiro modelo errava.
    sistema = validacao[0]["messages"][0]["content"]
    for pergunta in ("quem é o coordenador do curso", "quem é o professor de cálculo", "o que é a lei de ohm",
                     "qual é o seu nome", "você gosta de música"):
        mensagens = [{"role": "system", "content": sistema}, {"role": "user", "content": pergunta}]
        entrada = tokenizer(comoOOllamaMonta(mensagens), return_tensors="pt").input_ids.to(model.device)
        saida = model.generate(input_ids=entrada, max_new_tokens=60, do_sample=False)
        resposta = tokenizer.decode(saida[0][entrada.shape[1]:], skip_special_tokens=True)
        print(f"{pergunta} -> {resposta.strip()}")

    # Safetensors em 16 bits, e não GGUF: o GGUF do Unsloth compila o llama.cpp
    # e pede `sudo apt`. O Ollama do PC importa safetensors do Gemma 3 direto e
    # quantiza na hora (`ollama create --quantize`), sem compilar nada.
    model.save_pretrained_merged(SAIDA, tokenizer, save_method="merged_16bit")
    print(f"pronto: {SAIDA}/ — rode scripts/treino/instalar-no-pi.sh")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    raise SystemExit(main(sys.argv[1]))
