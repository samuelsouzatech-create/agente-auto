# Áudios da bancada

Os arquivos de áudio desta pasta NÃO vão para o Git. Para criá-los:

    .venv-teste\Scripts\python scripts\gerar_audios_bancada.py

Ele gera, com voz sintética do Gemini (alguns centavos de dólar):

1. `pergunta_preco.wav`: "Oi, boa tarde! Queria saber quanto tá o Corolla que vocês têm aí."
2. `troca.wav`: "Ô, eu tenho um Gol 2015, com uns cem mil quilômetros. Vocês pegam ele na troca pelo Onix?"
3. `desconto.wav`: "Gostei do HB20, mas tá caro. Se eu pagar à vista, você faz por quarenta e oito mil?"
4. `inaudivel.wav`: 4 segundos de chiado, sem fala (gerado sem custo).

Se preferir voz de gente de verdade, grave você mesmo as 3 frases acima (no celular, em .ogg,
.mp3 ou .wav) e salve com o mesmo nome. Não use áudio de cliente real.
Se um arquivo faltar, o roteiro sai com AVISO "áudio ausente".
