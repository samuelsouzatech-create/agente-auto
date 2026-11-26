"""
SE0 (Maratona Segurança), item 4: todo arquivo de texto do repositório é UTF-8 válido.

Reprova:
- arquivo que não decodifica como UTF-8 (ex.: gravado em Windows-1252 pelo PowerShell 5.1);
- arquivo com "acento quebrado" (mojibake): o texto UTF-8 que foi lido como Windows-1252/1250 e
  gravado de novo ("DecisÃ£o", "DecisĂµes"). Os pedaços procurados estão escritos com \\u para
  este próprio arquivo não reprovar.
"""
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
EXTENSOES = (".md", ".py", ".sql", ".json", ".yaml", ".yml", ".txt", ".toml", ".cfg", ".ini",
             ".sh", ".ps1", ".example", ".csv", ".html", ".css", ".js", ".ts", ".tsx")
NOMES = ("Caddyfile", "Dockerfile", ".gitignore", ".dockerignore", ".gitattributes")
PASTAS_FORA = (".venv", ".venv-teste", "node_modules", ".git", "logs", "dados", "fotos", "__pycache__")

# "Ã" + segundo byte de ç ã é á ê ó í õ ú à  (UTF-8 lido como Windows-1252)
# "Ă" + o mesmo (UTF-8 lido como Windows-1250, o caso do "DecisĂµes")
_SEGUNDOS = ("§", "£", "©", "¡", "ª", "³", "­", "µ", "º", " ")
QUEBRADOS = tuple("Ã" + s for s in _SEGUNDOS) + tuple("Ă" + s for s in _SEGUNDOS) + ("�",)


def arquivos_de_texto() -> list[Path]:
    try:
        saida = subprocess.run(["git", "ls-files", "-z"], cwd=RAIZ, capture_output=True, check=True).stdout
        nomes = [n for n in saida.decode("utf-8").split("\0") if n]
        caminhos = [RAIZ / n for n in nomes]
    except (OSError, subprocess.CalledProcessError):        # sem git: varre a pasta
        caminhos = [p for p in RAIZ.rglob("*") if p.is_file()
                    and not any(parte in PASTAS_FORA for parte in p.relative_to(RAIZ).parts)]
    return sorted(p for p in caminhos if p.is_file() and (p.suffix in EXTENSOES or p.name in NOMES))


def problema(caminho: Path) -> str | None:
    bruto = caminho.read_bytes()
    try:
        texto = bruto.decode("utf-8")
    except UnicodeDecodeError as erro:
        return f"não é UTF-8 (byte {erro.start})"
    for pedaco in QUEBRADOS:
        if pedaco in texto:
            linha = texto[:texto.index(pedaco)].count("\n") + 1
            return f"acento quebrado {pedaco!r} na linha {linha}"
    return None


def test_todo_arquivo_de_texto_e_utf8_valido():
    arquivos = arquivos_de_texto()
    assert len(arquivos) > 100
    ruins = [f"{p.relative_to(RAIZ).as_posix()}: {m}" for p in arquivos if (m := problema(p))]
    assert not ruins, "Regrave em UTF-8 (sem mudar o texto):\n" + "\n".join(ruins)


def test_o_teste_pega_os_defeitos(tmp_path):
    bom = tmp_path / "bom.md"
    bom.write_text("Decisões e não", encoding="utf-8")
    assert problema(bom) is None
    ansi = tmp_path / "ansi.md"
    ansi.write_bytes("Decisões".encode("cp1252"))
    assert "não é UTF-8" in problema(ansi)
    for codigo in ("cp1252", "cp1250"):
        quebrado = tmp_path / f"{codigo}.md"
        quebrado.write_text("Decisões".encode("utf-8").decode(codigo), encoding="utf-8")
        assert "acento quebrado" in problema(quebrado)
