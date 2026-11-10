"""Confere o contrato (C1): cada dado falso precisa obedecer ao openapi.yaml.

Uso, na raiz do repositório:
    python docs/api/conferir_mocks.py

Confere também que: nenhuma resposta ou pedido tem 'loja_id'; todo horário tem fuso; e cada rota tem ao
menos um dado falso de sucesso. Sai com código 1 se algo falhar (serve de teste no C2).
"""
import json
import os
import re
import sys

import yaml
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate as validar_openapi

AQUI = os.path.dirname(os.path.abspath(__file__))
PASTA = os.path.join(AQUI, "mocks")


def carregar():
    with open(os.path.join(AQUI, "openapi.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolver(doc, no):
    while isinstance(no, dict) and "$ref" in no and no["$ref"].startswith("#/components/responses/"):
        no = doc["components"]["responses"][no["$ref"].split("/")[-1]]
    return no


def esquema(doc, rota, metodo, status, tipo):
    op = doc["paths"][rota][metodo]
    if tipo == "pedido":
        corpo = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
    else:
        resp = resolver(doc, op["responses"][status])
        corpo = resp.get("content", {}).get("application/json", {}).get("schema")
    return corpo


def procurar_loja_id(valor, caminho="$"):
    achados = []
    if isinstance(valor, dict):
        for k, v in valor.items():
            if k == "loja_id":
                achados.append(f"{caminho}.{k}")
            achados += procurar_loja_id(v, f"{caminho}.{k}")
    elif isinstance(valor, list):
        for i, v in enumerate(valor):
            achados += procurar_loja_id(v, f"{caminho}[{i}]")
    return achados


def horarios_sem_fuso(valor, caminho="$"):
    ruins = []
    if isinstance(valor, dict):
        if set(valor) >= {"iso", "texto"} and not re.search(r"(Z|[+-]\d\d:\d\d)$", str(valor["iso"])):
            ruins.append(caminho)
        for k, v in valor.items():
            ruins += horarios_sem_fuso(v, f"{caminho}.{k}")
    elif isinstance(valor, list):
        for i, v in enumerate(valor):
            ruins += horarios_sem_fuso(v, f"{caminho}[{i}]")
    return ruins


def principal():
    doc = carregar()
    validar_openapi(doc)
    erros = []
    for c in procurar_loja_id(doc):
        erros.append(f"openapi.yaml tem a propriedade loja_id em {c}: nenhuma rota recebe a loja.")
    for rota, ops in doc["paths"].items():
        for op in ops.values():
            for par in op.get("parameters", []):
                if par.get("name") == "loja_id":
                    erros.append(f"{rota}: parâmetro loja_id não é permitido.")
    with open(os.path.join(PASTA, "_indice.json"), encoding="utf-8") as f:
        indice = json.load(f)
    papeis_ok = {"publico", "dono", "gestor", "vendedor", "vendedor_link"}
    for rota, ops in doc["paths"].items():
        for metodo, op in ops.items():
            papeis = op.get("x-papeis")
            if not papeis or not set(papeis) <= papeis_ok:
                erros.append(f"{metodo.upper()} {rota}: falta x-papeis ou tem papel desconhecido")
    cobertas = set()
    for arquivo, meta in sorted(indice.items()):
        with open(os.path.join(PASTA, arquivo), encoding="utf-8") as f:
            dado = json.load(f)
        rota, metodo, status, tipo = meta["rota"], meta["metodo"], meta["status"], meta["tipo"]
        if rota not in doc["paths"] or metodo not in doc["paths"][rota]:
            erros.append(f"{arquivo}: rota {metodo.upper()} {rota} não existe no contrato")
            continue
        if tipo == "resposta" and status not in doc["paths"][rota][metodo]["responses"]:
            erros.append(f"{arquivo}: o contrato não prevê a resposta {status} em {metodo.upper()} {rota}")
            continue
        if tipo == "resposta" and status.startswith("2"):
            cobertas.add((rota, metodo))
        corpo = esquema(doc, rota, metodo, status, tipo)
        if corpo is None:
            continue                         # 204 e afins: sem corpo
        validador = Draft202012Validator({"components": doc["components"], **corpo})
        for e in validador.iter_errors(dado):
            erros.append(f"{arquivo}: {'/'.join(str(p) for p in e.absolute_path) or '(raiz)'}: {e.message[:140]}")
        for c in procurar_loja_id(dado):
            erros.append(f"{arquivo}: tem loja_id em {c}")
        for c in horarios_sem_fuso(dado):
            erros.append(f"{arquivo}: horário sem fuso em {c}")
    for rota, ops in doc["paths"].items():
        for metodo, op in ops.items():
            sucesso = [s for s in op["responses"] if s.startswith("2")]
            tem_corpo = any(resolver(doc, op["responses"][s]).get("content") for s in sucesso)
            if tem_corpo and (rota, metodo) not in cobertas:
                erros.append(f"sem dado falso de sucesso para {metodo.upper()} {rota}")
    print(f"{len(indice)} dados falsos conferidos contra {sum(len(v) for v in doc['paths'].values())} operações.")
    if erros:
        print("\nPROBLEMAS:")
        for e in erros:
            print(" -", e)
        sys.exit(1)
    print("Tudo certo: todos obedecem ao contrato.")


if __name__ == "__main__":
    principal()
