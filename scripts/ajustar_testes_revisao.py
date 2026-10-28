"""Ajusta os testes antigos à revisão da Etapa 1 (loja obrigatória, envio por loja,
trava do runner) e acrescenta o teste do analista. Pode rodar mais de uma vez."""
import re
from pathlib import Path

TESTES = Path(__file__).resolve().parent.parent / "tests"

FAKES = [
    (r"async def resposta\(numero, texto, atraso=0\):", "async def resposta(numero, texto, atraso=0, **kw):"),
    (r"async def foto\(numero, url\):", "async def foto(numero, url, **kw):"),
    (r"async def marcar\(id_mensagem, digitando=False\):", "async def marcar(id_mensagem, digitando=False, **kw):"),
    (r'(wh\.processar_mensagem\((?:"[^"]*"|\w+),\s*(?:"[^"]*"|\w+))\)', r"\1, None, 1)"),
]

TESTE_DO_ANALISTA = '''def test_desativar_o_unico_canal_nao_volta_para_a_loja_1(loja_b):
    """Antes: sem canal ATIVO, tudo caía na loja 1 (isolamento furado)."""
    cadastrar_canal(LOJA_B, "whatsapp", "PNID_B")
    desativar_canal("whatsapp", "PNID_B")
    assert resolver_loja("whatsapp", "PNID_B") is None
    assert resolver_loja("whatsapp", "QUALQUER_OUTRO") is None


def test_recadastrar_move_o_canal_sem_duplicar'''

REGRAS = {
    "test_fase_2_robustez.py": FAKES,
    "test_etapa1_bloco3.py": FAKES + [
        (r'chave_redis\("buffer", None, "5581"\)', 'chave_redis("buffer", 1, "5581")'),
    ],
    "test_etapa1_bloco4.py": FAKES + [
        (r'tb\.processar_texto\("B", "tem civic\?"\)', 'tb.processar_texto("B", "tem civic?", loja_id=1)'),
    ],
    "test_comportamento_fluxos.py": [
        (r'\{"messages": historico, "lead_id": lead_id\}', '{"messages": historico, "lead_id": lead_id, "loja_id": 1}'),
    ],
    "test_etapa1_bloco7b.py": [
        (r'runner\.main\(\["--uma-vez"\]\)', 'runner.main(["--uma-vez", "--sem-trava"])'),
    ],
}

for nome, regras in REGRAS.items():
    caminho = TESTES / nome
    texto = caminho.read_text(encoding="utf-8")
    total = 0
    for padrao, novo in regras:
        texto, n = re.subn(padrao, novo, texto)
        total += n
    if nome == "test_etapa1_bloco3.py" and "test_desativar_o_unico_canal" not in texto:
        texto = texto.replace("def test_recadastrar_move_o_canal_sem_duplicar", TESTE_DO_ANALISTA, 1)
        total += 1
    caminho.write_text(texto, encoding="utf-8")
    print(f"{nome}: {total} ajuste(s)")
