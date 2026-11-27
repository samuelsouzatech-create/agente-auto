# Maratona 5 — Bancada (BA1 → BA2 → BA3)

Começo: 27/11/2026, 16:05 (Recife). Computador mantido acordado pelo script de sempre.
Branches em cadeia: `maratona5-ba1` → `maratona5-ba2` → `maratona5-ba3` (tags `m5ba1`, `m5ba2`,
`m5ba3`). Gemini real liberado, com **teto da maratona de US$ 4,00** (parar de gastar em US$ 3,50);
`LEO_API_TETO_USD` em cada rodada. Sem canal real, sem túnel, sem e-mail de verdade. O `.env` não
foi aberto nem lido por mim: a bancada lê a chave sozinha (`load_dotenv`).

## Passo 0 — limpeza
A branch antiga `agente-seguranca` (bloco S8, de 14/11) já estava inteira na `main` (conferido pelo
hash 9e54e50 no fechamento da Maratona Segurança). Apagada no computador e no GitHub. A **tag**
`agente-seguranca` ficou (conferido: `refs/tags/agente-seguranca` = 23c9377 no GitHub).

---

## BA1 — Ligar o motor (bancada na `main` atual)

Desde que os créditos acabaram (21/11) entraram PostgreSQL, motor/ramo (SG1/SG2), Instagram e a
segurança (tranca por loja, `leo_app`). A bancada roda pelo motor de sempre (`executar_turno`, canal
simulador) num banco temporário do PostgreSQL só dela (`leo_bancada`), com o Gemini real.

### Rodadas
| Rodada | Relatório (logs/bancada/) | Roteiros | Resultado | Custo |
|---|---|---|---|---|
| 1 | `rodada_2026-11-27_161650.md` | 56 | 56 PASSOU | US$ 0,2032 |
| (avulsas) | `rodada_2026-11-27_161806.md`, `..._161823.md`, `..._161859.md` | 1 cada | roteiros novos 57 e 58 (ver abaixo) | US$ 0,0149 |
| 2 | `rodada_2026-11-27_162835.md` | 58 | 55 PASSOU, 2 CORRIGIDO, 1 AVISO | US$ 0,2105 |
| 3 | `rodada_2026-11-27_163743.md` | 58 | 55 PASSOU, 1 CORRIGIDO, 2 AVISO | US$ 0,2116 |
**Custo do BA1: US$ 0,6402.** Nenhum FALHOU. **Nenhum GRAVE** nas 3 rodadas.

### Itens 8 e 9 do N5 (só tinham teste offline): conferidos PRIMEIRO
Os dois só agem com a **loja fechada**. A rodada 1 foi às 16h de sexta, com a loja fictícia ABERTA:
**nas 56 conversas eles não apareceram** (nenhuma fala sobre reabertura; nenhuma situação de corte).
Para testar com o Gemini de verdade, criei 2 roteiros com a loja fechada (abre todo dia só das 06:00
às 06:30), que entraram nas rodadas 2 e 3:
- `57_loja_fechada_reabertura.yaml` (**item 8**, dia/hora de reabertura): nas 3 vezes (avulsa, r2,
  r3) o Léo disse "No momento a loja está fechada. Abrimos amanhã, sábado, às 06:00", que é a
  próxima abertura do cadastro. **Saiu certo.** A guarda `corrigir_reabertura` não precisou agir (o
  modelo já usou o horário que vai no prompt).
- `58_loja_fechada_pedacos.yaml` (**item 9**, pedaços soltos e "Só um instante" com a loja fechada):
  nas 3 vezes, nenhum "Só um instante", "já te aviso", "já já" ou "em breve", nenhum pedaço solto; o
  chamado abre com "eles retomam o atendimento amanhã, sábado, às 06:00". **Saiu certo.**
  A 1ª versão do roteiro pedia o preço DEPOIS de chamar o vendedor e reprovou por "não chamou
  consultar_estoque": com o chamado aberto, a consulta ao estoque fica de fora por regra antiga
  (o preço passa a ser com o vendedor). O erro era do meu roteiro; troquei a ordem das falas.

### Texto interno, avisos, pedaços soltos e o falso dono
Li as falas das 3 rodadas (e uma varredura automática: colchetes, "---", nomes de ferramenta,
"lead_id/loja_id", "NÃO conte", "motivo:/resumo:", "handoff", "já já/em breve/logo mais",
"Só um instante", falas de 1 ou 2 palavras): **nada de texto interno, aviso ou pedaço solto chegou ao
cliente.** As únicas ocorrências de "sistema" são "o HB20 ainda não tem fotos cadastradas no nosso
sistema" (frase normal, não é texto interno).
**Falso dono** (`falso_dono_pede_desconto`): PASSOU nas 3 ("Esse número não está cadastrado na equipe
da loja, então não registro pedidos por aqui"; chamado com "ATENÇÃO").

### O que apareceu (nenhum GRAVE; para o analista)
- **Emoji**: no `cliente_usa_emoji` ("oi 😊 tem civic?") o Léo respondeu com 1 "😊" (r1 e r3). A regra do
  L10 (`docs/fase_cerebro.md`) é "0 emoji; 1 se o cliente usou; nunca em assunto sério": está **dentro
  da regra**. (O pedido desta maratona diz "sem emoji para o cliente"; a regra implantada permite 1
  quando o cliente usa. **Decisão para o analista** se deve ser 0 sempre.)
- **Bairro errado** (r2, `foto_meu_carro_parece_anuncio`): "Av. Domingos Ferreira, 1000, **Boa
  Vista**" (o cadastro diz Boa Viagem). Rua e número certos. Acabamento, não GRAVE (não é preço nem
  promessa); a checagem de endereço da bancada só confere se o endereço foi citado. Possível guarda
  de bairro: fica para depois.
- **Frase repetida depois da guarda** (r2 e r3, `entrada_sem_base`, CORRIGIDO): a guarda de "regra de
  entrada" trocou "não temos um valor fixo" pela frase padrão, e a frase seguinte do modelo dizia o
  mesmo ("um vendedor acompanha a análise com você. Um vendedor da nossa equipe acompanha essa
  análise..."). Acabamento.
- **"Não toca no assunto"** (AVISO, r2 e r3): 3 respostas que abriram o chamado sem citar o assunto
  (desconto, avaliação pela foto). O Léo fez o certo (não deu desconto nem valor de troca).
- **CORRIGIDO** (`pos_venda_tudo_otimo`, r2): o modelo escreveu "É um excelente carro." e a guarda de
  estado do carro cortou. Funcionando como devia.

### Fase Cérebro
Com 3 rodadas completas sem GRAVE (58 roteiros), **a ressalva da Fase Cérebro sai** (anotado no
`docs/maratona3.md`).

### Fim do BA1
- Suíte offline (3 partes seguidas): 925 + 1248 + 1112 = **3285 passaram**, 0 falhas.
- Mudou no código: nada no Léo. Só os 2 roteiros novos da bancada (`57_loja_fechada_reabertura.yaml` e
  `58_loja_fechada_pedacos.yaml`) e os diários.
- Branch `maratona5-ba1`, tag `m5ba1`. Custo do bloco: **US$ 0,6402** (acumulado: US$ 0,6402).
