"""Leitura segura de valores da configuração de uma loja.

A config é um dicionário com seções (ex.: {"modulos": {"fotos": True}}).
valor_config(config, "modulos.fotos") devolve True. Se a chave não existir,
devolve o padrão informado, sem quebrar.
"""


def valor_config(config: dict, caminho: str, padrao=None):
    if not isinstance(config, dict):
        return padrao
    # Aceita também chave "achatada" ("modulos.fotos": True), por segurança.
    if caminho in config:
        return config[caminho]
    atual = config
    for parte in caminho.split("."):
        if isinstance(atual, dict) and parte in atual:
            atual = atual[parte]
        else:
            return padrao
    return atual
