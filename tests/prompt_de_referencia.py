"""SG1 (Maratona 4): o prompt de uma loja de carros, em várias situações, para provar que separar o
motor do pacote de veículos NÃO mudou nem uma letra do que o Léo recebe.

Gerado com o código de ANTES do SG1 (branch arrumacoes) e guardado em
tests/dados/prompt_veiculos_antes_do_sg1.json. O teste test_sg1_pacote_de_ramo.py monta tudo de
novo com o código de agora e compara. Sem banco: a loja é montada aqui, com a config padrão.
Para gerar de novo (só se o prompt mudar DE PROPÓSITO, com rodada de IA real):
    .venv-teste\\Scripts\\python -m tests.prompt_de_referencia
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ARQUIVO = Path(__file__).resolve().parent / "dados" / "prompt_veiculos_antes_do_sg1.json"
AGORA = datetime(2026, 11, 20, 10, 30, tzinfo=ZoneInfo("America/Recife"))       # sexta, aberta
AGORA_FECHADA = datetime(2026, 11, 22, 21, 0, tzinfo=ZoneInfo("America/Recife"))  # domingo à noite

SITUACOES = {
    "padrao": ({}, {}),
    "troca_sim": ({"aceita_troca": "sim", "endereco": "Rua A, 10", "cidade": "Recife"}, {}),
    "troca_nao": ({"aceita_troca": "nao"}, {}),
    "modulos_ligados": ({"modulos": {"agendamento": True, "fotos": True}}, {}),
    "modulos_desligados": ({"modulos": {"agendamento": False, "fotos": False}}, {}),
    "espera_meio_termo": ({}, {"em_espera": True}),
    "espera_conversar": ({"atendimento": {"aguardando_vendedor": "conversar"}}, {"em_espera": True}),
    "espera_quieta": ({"atendimento": {"aguardando_vendedor": "esperar"}}, {"em_espera": True}),
    "primeiro_contato_formal": ({"tom": "formal e respeitoso"}, {"primeiro_contato": True}),
    "cliente_da_casa": ({}, {"compras": [{"descricao": "Honda Civic 2019", "data": date(2025, 3, 1),
                                          "detalhe": "financiado em 48x"}]}),
    "retomada": ({}, {"retomada": {"texto": "Oi! O Civic que você viu continua aqui.",
                                   "enviado_em": datetime(2026, 11, 19, 15, 0, tzinfo=ZoneInfo("UTC"))}}),
    "recados": ({}, {"recados": [{"texto": "Feirão no sábado", "valido_ate": date(2026, 11, 21), "condicao": False}]}),
    "fechada": ({}, {"_agora": "fechada"}),
}


def _loja(custom: dict):
    from app import lojas
    return lojas.Loja(id=1, nome="Auto Referência", segmento="veiculos",
                      config=lojas._mesclar(lojas.PADROES, custom), versao_config=1, ativo=True)


def montar_todos() -> dict[str, str]:
    from app.core.montagem import ferramentas_da_loja, montar_prompt
    saida = {}
    for nome, (custom, extra) in SITUACOES.items():
        extra = dict(extra)
        agora = AGORA_FECHADA if extra.pop("_agora", None) == "fechada" else AGORA
        loja = _loja(custom)
        ferramentas = ferramentas_da_loja(loja, em_espera=bool(extra.get("em_espera")))
        prompt = montar_prompt(loja, ferramentas, agora, **extra)
        saida[nome] = json.dumps({"ferramentas": [f.name for f in ferramentas], "prompt": prompt},
                                 ensure_ascii=False)
    return saida


if __name__ == "__main__":
    import os
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    os.environ.setdefault("GOOGLE_API_KEY", "chave-falsa")
    ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
    ARQUIVO.write_text(json.dumps(montar_todos(), ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"gravado: {ARQUIVO.name} ({len(SITUACOES)} situações)")
