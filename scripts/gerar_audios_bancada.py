r"""Gera os áudios da bancada (M3): 3 falas com voz sintética do Gemini e 1 ruído (inaudível).

    .venv-teste\Scripts\python scripts\gerar_audios_bancada.py

Os arquivos ficam em bancada/audios/ (fora do Git). Custo: alguns centavos de dólar. Não imprime a chave."""
import os
import random
import struct
import sys
import wave
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PASTA = RAIZ / "bancada" / "audios"
PASTA.mkdir(parents=True, exist_ok=True)

FALAS = {
    "pergunta_preco.wav": "Oi, boa tarde! Queria saber quanto tá o Corolla que vocês têm aí.",
    "troca.wav": "Ô, eu tenho um Gol 2015, com uns cem mil quilômetros. Vocês pegam ele na troca pelo Onix?",
    "desconto.wav": "Gostei do HB20, mas tá caro. Se eu pagar à vista, você faz por quarenta e oito mil?",
}


def salvar_wav(caminho, pcm: bytes, taxa=24000):
    with wave.open(str(caminho), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes(pcm)


# Inaudível: 4 s de chiado baixo (sem fala nenhuma).
rng = random.Random(7)
ruido = b"".join(struct.pack("<h", rng.randint(-600, 600)) for _ in range(16000 * 4))
salvar_wav(PASTA / "inaudivel.wav", ruido, 16000)
print("inaudivel.wav: gerado (ruído)")

from dotenv import load_dotenv
load_dotenv(RAIZ / ".env")
chave = os.environ.get("GOOGLE_API_KEY", "")
if not chave or chave.startswith("chave-falsa"):
    print("sem chave real; TTS não gerado")
    sys.exit(2)
from google import genai
from google.genai import types

cliente = genai.Client(api_key=chave)
falhou = 0
for nome, texto in FALAS.items():
    try:
        r = cliente.models.generate_content(
            model="gemini-2.5-flash-preview-tts",
            contents=f"Fale em português do Brasil, com sotaque nordestino, de forma natural: {texto}",
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Kore")))))
        pcm = r.candidates[0].content.parts[0].inline_data.data
        salvar_wav(PASTA / nome, pcm)
        print(f"{nome}: gerado ({len(pcm) // 48000} s)")
    except Exception as e:
        falhou += 1
        print(f"{nome}: FALHOU ({type(e).__name__}: {str(e)[:160]})")
sys.exit(1 if falhou else 0)
