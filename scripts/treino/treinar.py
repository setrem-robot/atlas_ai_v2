#!/usr/bin/env python3
"""Treina a Atlas (LoRA sobre o Gemma 3 1B) na GPU do PC e exporta para o Pi.

O Pi não treina nada: ele só recebe o modelo pronto. Treinar aqui troca a
persona longa do prompt (~1000 tokens, que o Pi lê a cada conversa nova) por
pesos que já sabem quem ela é e como falar, e deixa no prompt só os fatos e a
data. Ver `dataset.py` para o que se ensina.

Ambiente (uma vez, no WSL, com a GPU visível em `nvidia-smi`):
    curl -LsSf https://astral.sh/uv/install.sh | sh
    uv venv -p 3.12 ~/atlas-treino
    VIRTUAL_ENV=~/atlas-treino uv pip install unsloth

Treino (~5 min numa RTX 4060), da raiz do repositório:
    python scripts/treino/dataset.py > /tmp/atlas-treino.jsonl
    ~/atlas-treino/bin/python scripts/treino/treinar.py /tmp/atlas-treino.jsonl
Sai `atlas-1b-gguf/` com o modelo em F16; `instalar-no-pi.sh` leva para o Pi e
quantiza lá em q4_K_M, o mesmo formato do gemma3:1b de hoje.
"""

from __future__ import annotations

import sys

from unsloth import FastModel  # importa antes do transformers, como o Unsloth pede
from unsloth.chat_templates import get_chat_template, train_on_responses_only
from datasets import load_dataset
from trl import SFTConfig, SFTTrainer

BASE = "unsloth/gemma-3-1b-it"
SAIDA = "atlas-1b-gguf"


def comoOOllamaMonta(mensagens: list[dict]) -> str:
    """O texto que o template do gemma3 no Ollama gera para estas mensagens.

    O template de chat do Unsloth junta o sistema dentro da primeira pergunta; o
    do Ollama faz dele um turno de usuário à parte. Treinar num formato e rodar
    no outro é mostrar ao modelo, no Pi, um prompt que ele nunca viu. Por isso o
    texto do treino é montado aqui, igual ao do Pi (`ollama show gemma3:1b
    --modelfile`). Sem o <bos>: a tokenização o acrescenta.
    Termina aberto no turno do modelo; no treino, a resposta e o <end_of_turn>
    vêm em seguida.
    """
    texto = ""
    for m in mensagens:
        if m["role"] in ("system", "user"):
            texto += f"<start_of_turn>user\n{m['content']}<end_of_turn>\n"
        else:
            return texto + f"<start_of_turn>model\n{m['content']}"
    return texto + "<start_of_turn>model\n"


assert comoOOllamaMonta(
    [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}, {"role": "assistant", "content": "A"}]
) == "<start_of_turn>user\nS<end_of_turn>\n<start_of_turn>user\nU<end_of_turn>\n<start_of_turn>model\nA"


def main(arquivo: str) -> int:
    model, tokenizer = FastModel.from_pretrained(
        model_name=BASE, max_seq_length=1024, load_in_4bit=False, full_finetuning=False
    )
    model = FastModel.get_peft_model(
        model,
        finetune_language_layers=True,
        finetune_attention_modules=True,
        finetune_mlp_modules=True,
        r=16,
        lora_alpha=16,
        lora_dropout=0,
        bias="none",
        random_state=7,
    )
    tokenizer = get_chat_template(tokenizer, chat_template="gemma-3")

    dados = load_dataset("json", data_files=arquivo, split="train")
    dados = dados.map(
        lambda lote: {"text": [comoOOllamaMonta(m) + "<end_of_turn>\n" for m in lote["messages"]]},
        batched=True,
    )
    separados = dados.train_test_split(test_size=0.05, seed=7)

    treino = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=separados["train"],
        eval_dataset=separados["test"],
        args=SFTConfig(
            dataset_text_field="text",
            per_device_train_batch_size=8,
            gradient_accumulation_steps=1,
            num_train_epochs=3,
            learning_rate=2e-4,
            warmup_steps=10,
            lr_scheduler_type="linear",
            logging_steps=10,
            eval_strategy="epoch",
            seed=7,
            output_dir="saida-treino",
            report_to="none",
        ),
    )
    # Só a resposta conta no erro: o modelo aprende a responder, não a
    # reescrever o prompt e a pergunta.
    treino = train_on_responses_only(
        treino,
        instruction_part="<start_of_turn>user\n",
        response_part="<start_of_turn>model\n",
    )
    treino.train()

    # Olhada rápida antes de exportar: perguntas que o modelo base errava.
    sistema = separados["test"][0]["messages"][0]["content"]
    for pergunta in ("quem é o coordenador do curso", "quem é o professor de cálculo", "o que é a lei de ohm"):
        mensagens = [{"role": "system", "content": sistema}, {"role": "user", "content": pergunta}]
        entrada = tokenizer(
            comoOOllamaMonta(mensagens), return_tensors="pt"
        ).input_ids.to(model.device)
        saida = model.generate(input_ids=entrada, max_new_tokens=60, do_sample=False)
        resposta = tokenizer.decode(saida[0][entrada.shape[1]:], skip_special_tokens=True)
        print(f"{pergunta} -> {resposta.strip()}")

    model.save_pretrained_gguf(SAIDA, tokenizer, quantization_method="F16")
    print(f"pronto: {SAIDA}/ — rode scripts/treino/instalar-no-pi.sh")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    raise SystemExit(main(sys.argv[1]))
