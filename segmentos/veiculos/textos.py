"""Textos fixos do ramo de veículos que entram no prompt do MOTOR (SG1, Maratona 4).

Saíram de app/core/montagem.py e de prompts/base.md sem mudar uma letra: o prompt de uma loja de
carros continua igual (tests/test_sg1_pacote_de_ramo.py compara com a foto de antes do SG1).
"""

# L5c: o que o Léo pode dizer sobre aceitar carro na troca (vem do cadastro da loja).
TEXTO_ACEITA_TROCA = {
    "sim": "- Troca: a loja aceita carro na troca (avaliação presencial, com um vendedor).",
    "nao": "- Troca: a loja NÃO aceita carro na troca. Se perguntarem, diga isso com educação.",
    "nao_informado": ("- Troca: não está cadastrado se a loja aceita carro na troca. Se perguntarem, "
                      "diga que vai confirmar com a equipe e chame acionar_handoff. Não diga que aceita."),
}


def linhas_da_identidade(valor_config) -> list[str]:
    """Gancho da camada IDENTIDADE (logo depois do endereço). valor_config(chave, padrao)."""
    return [TEXTO_ACEITA_TROCA.get(str(valor_config("aceita_troca", "nao_informado")),
                                   TEXTO_ACEITA_TROCA["nao_informado"])]


# Trechos marcados em prompts/base.md com {{ramo:<chave>}}.
TRECHOS_DO_PROMPT_BASE = {
    "nao_invente": "carro, preço, quilometragem",
    "exemplo_sem_foto": "um carro sem fotos",
    "o_item": "o carro",
    "fotos_do_cliente": '- Carro do cliente: comente o modelo aparente, a cor e o estado visível. Se ele quer dar na troca, use registrar_troca. A avaliação é presencial, com um vendedor: NUNCA dê valor nem faixa de preço pela foto.\n- Print de anúncio: procure o carro com consultar_estoque. Preço só o que a ferramenta devolver.',
}
