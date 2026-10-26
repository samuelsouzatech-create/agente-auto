"""Cria uma 2ª loja de teste no loja.db real, para ver o multi-loja no Streamlit.
Rodar na raiz do projeto:  python scripts/criar_loja_teste.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import banco

LOJA_ID = 2
CONFIG = {
    "nome_agente": "Bia",
    "tom": "animado e descontraído, pode usar emojis",
    "modulos": {"agendamento": False, "fotos": False},
    "financiamento": {"taxa_mensal": 0.025},
}
CARROS = [
    ("Jeep", "Renegade", 2021, 41000, "Cinza", "Automático", 99900.00),
    ("Fiat", "Argo", 2022, 18000, "Vermelho", "Manual", 72500.00),
]


def main():
    banco.criar_tabelas()
    conexao = banco.conectar()
    try:
        if conexao.execute("SELECT 1 FROM lojas WHERE id = ?", (LOJA_ID,)).fetchone():
            print("A loja 2 já existe. Nada a fazer.")
            return
        conexao.execute(
            "INSERT INTO lojas (id, nome, segmento, config) VALUES (?, ?, 'veiculos', ?)",
            (LOJA_ID, "Auto Center Teste", json.dumps(CONFIG, ensure_ascii=False)),
        )
        conexao.executemany(
            "INSERT INTO estoque (loja_id, marca, modelo, ano, km, cor, cambio, preco, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'disponivel')",
            [(LOJA_ID, *carro) for carro in CARROS],
        )
        conexao.commit()
    finally:
        conexao.close()
    print("Loja 2 'Auto Center Teste' criada: agente Bia, sem agendamento, sem fotos, taxa 2,5%.")


if __name__ == "__main__":
    main()
