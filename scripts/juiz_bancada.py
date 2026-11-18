"""
Juiz da bancada (L8): lê um relatório da bancada e dá nota de 1 a 5 a cada roteiro,
olhando três coisas: atendeu o cliente, naturalidade e seguiu as regras. Uma linha de
justificativa por roteiro. A nota SÓ INFORMA: não muda PASSOU/FALHOU.

Uso (gasta dinheiro: chama a IA uma vez por roteiro):
    .venv-teste\\Scripts\\python scripts\\juiz_bancada.py                 (o relatório mais novo)
    .venv-teste\\Scripts\\python scripts\\juiz_bancada.py logs\\bancada\\rodada_....md

Modelo: LEO_JUIZ_MODELO (padrão: o modelo já configurado do Léo).
Teto próprio: LEO_JUIZ_TETO_USD (padrão 0.30). Passou do teto, para e marca o resto "não avaliado".
Saída: logs/bancada/juiz_<nome do relatório>.md
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

PASTA = RAIZ / "logs" / "bancada"
TETO_PADRAO_USD = 0.30
LIMITE_SECAO = 6000          # o juiz recebe no máximo isto de cada roteiro

PROMPT_DO_JUIZ = """Você avalia um assistente de vendas de uma loja de carros (o "Léo").
Abaixo está um roteiro de teste: o que o cliente disse, o que o Léo respondeu, as
ferramentas e as checagens automáticas.

Dê UMA nota de 1 a 5 considerando juntas três coisas:
- atendeu o cliente (respondeu o que foi pedido, levou a um próximo passo);
- naturalidade (soa como um bom vendedor no WhatsApp, sem repetição nem cara de robô);
- seguiu as regras (não inventou preço, não prometeu o que só a equipe pode, chamou a equipe
  quando devia).
5 = excelente, 3 = aceitável com falhas, 1 = ruim.

Responda SÓ com JSON: {{"nota": <1 a 5>, "justificativa": "<uma frase curta>"}}

ROTEIRO:
{secao}"""


@dataclass
class Avaliacao:
    roteiro: str
    status: str
    nota: int | None
    justificativa: str


_CABECALHO = re.compile(r"^## \d+\. (?P<nome>\S+) — (?P<status>.+)$", re.MULTILINE)


def secoes(relatorio: str) -> list[tuple[str, str, str]]:
    """[(nome, status, texto)] de cada roteiro do relatório (sem o resumo final)."""
    achados = list(_CABECALHO.finditer(relatorio))
    saida = []
    for i, m in enumerate(achados):
        fim = achados[i + 1].start() if i + 1 < len(achados) else relatorio.find("\n## Resumo", m.end())
        texto = relatorio[m.start(): fim if fim != -1 else len(relatorio)].strip()
        saida.append((m.group("nome"), m.group("status").strip(), texto))
    return saida


def ler_nota(resposta: str) -> tuple[int | None, str]:
    try:
        texto = resposta[resposta.index("{"): resposta.rindex("}") + 1]
        dados = json.loads(texto)
        nota = int(dados["nota"])
        if not 1 <= nota <= 5:
            raise ValueError
        return nota, " ".join(str(dados.get("justificativa") or "").split())[:200]
    except (ValueError, KeyError, TypeError):
        return None, "resposta do juiz ilegível"


def teto_do_juiz() -> float:
    try:
        return float(os.getenv("LEO_JUIZ_TETO_USD") or TETO_PADRAO_USD)
    except ValueError:
        return TETO_PADRAO_USD


def modelo_do_juiz() -> str:
    from app.config import MODELO_LLM
    return (os.getenv("LEO_JUIZ_MODELO") or "").strip() or MODELO_LLM


def chamar_ia(prompt: str, modelo: str):
    """(texto, tokens_entrada, tokens_saida). Só aqui o juiz fala com a IA."""
    from google import genai

    from app.config import GOOGLE_API_KEY
    cliente = genai.Client(api_key=GOOGLE_API_KEY)
    resposta = cliente.models.generate_content(
        model=modelo, contents=[prompt],
        config=genai.types.GenerateContentConfig(response_mime_type="application/json"))
    meta = getattr(resposta, "usage_metadata", None)
    return (resposta.text or "", int(getattr(meta, "prompt_token_count", 0) or 0),
            int(getattr(meta, "candidates_token_count", 0) or 0))


def julgar(relatorio: str, *, chamar=None, teto: float | None = None, modelo: str = "") -> tuple[list[Avaliacao], float]:
    from scripts.rodar_bancada import custo_usd
    chamar = chamar or (lambda prompt: chamar_ia(prompt, modelo or modelo_do_juiz()))
    teto = teto_do_juiz() if teto is None else teto
    entrada = saida = 0
    avaliacoes = []
    for nome, status, texto in secoes(relatorio):
        if custo_usd(entrada, saida) >= teto:
            avaliacoes.append(Avaliacao(nome, status, None, "não avaliado (teto do juiz)"))
            continue
        try:
            resposta, e, s = chamar(PROMPT_DO_JUIZ.format(secao=texto[:LIMITE_SECAO]))
        except Exception as erro:
            avaliacoes.append(Avaliacao(nome, status, None, f"erro do juiz: {type(erro).__name__}"))
            continue
        entrada, saida = entrada + e, saida + s
        nota, justificativa = ler_nota(resposta)
        avaliacoes.append(Avaliacao(nome, status, nota, justificativa))
    return avaliacoes, custo_usd(entrada, saida)


AVISO_MESMO_MODELO = "juiz = mesmo modelo do Léo (notas otimistas)"


def juiz_e_o_mesmo_modelo() -> bool:
    """L10: sem LEO_JUIZ_MODELO, o juiz usa o modelo do Léo (ele tende a se dar nota alta)."""
    return not (os.getenv("LEO_JUIZ_MODELO") or "").strip()


def montar(avaliacoes: list[Avaliacao], origem: str, custo: float, modelo: str,
           mesmo_modelo: bool = False) -> str:
    notas = [a.nota for a in avaliacoes if a.nota is not None]
    media = f"{sum(notas) / len(notas):.1f}" if notas else "—"
    linhas = [f"# Juiz da bancada — {origem}", "",
              f"Modelo: {modelo} · custo: US$ {custo:.4f} · média: {media} ({len(notas)} de "
              f"{len(avaliacoes)} roteiros avaliados). A nota só informa; não muda o resultado.", "",
              *([f"**Atenção: {AVISO_MESMO_MODELO}.** Defina LEO_JUIZ_MODELO para usar outro modelo.", ""]
                if mesmo_modelo else []),
              "| Roteiro | Resultado | Nota | Justificativa |", "|---|---|---|---|"]
    for a in avaliacoes:
        linhas.append(f"| {a.roteiro} | {a.status} | {a.nota if a.nota is not None else '—'} | "
                      f"{a.justificativa.replace('|', '/')} |")
    baixas = [a for a in avaliacoes if a.nota is not None and a.nota <= 2]
    if baixas:
        linhas += ["", "Notas 1–2 (olhar primeiro): " + ", ".join(a.roteiro for a in baixas)]
    return "\n".join(linhas) + "\n"


def mais_novo() -> Path:
    relatorios = sorted(PASTA.glob("rodada_*.md"))
    if not relatorios:
        raise SystemExit("Nenhum relatório em logs/bancada. Rode a bancada antes.")
    return relatorios[-1]


def main(argv=None) -> int:
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="Juiz da bancada do Léo (gasta dinheiro).")
    parser.add_argument("relatorio", nargs="?", help="relatório da bancada (padrão: o mais novo)")
    args = parser.parse_args(argv)
    caminho = Path(args.relatorio) if args.relatorio else mais_novo()
    modelo = modelo_do_juiz()
    avaliacoes, custo = julgar(caminho.read_text(encoding="utf-8"), modelo=modelo)
    destino = caminho.with_name(f"juiz_{caminho.stem}.md")
    destino.write_text(montar(avaliacoes, caminho.name, custo, modelo, juiz_e_o_mesmo_modelo()),
                       encoding="utf-8")
    print(f"Juiz: {destino} · custo US$ {custo:.4f} (teto US$ {teto_do_juiz():.2f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
