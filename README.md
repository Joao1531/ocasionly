# MyWardrobe

Guarda-roupa pessoal com um estilista de IA. Fotografas a tua roupa, dizes o que tens para fazer ("jantar de empresa na sexta, vai estar frio") e a app propõe outfits **só com as peças que tens**, explica porquê, mostra as peças concretas e gera uma imagem de ti com a roupa vestida.

> Protótipo pessoal, feito para uso próprio num só utilizador. Corre no teu computador e guarda tudo localmente.

## O que faz

| Separador | Para quê |
|---|---|
| **Roupa** | O armário, arrumado por abas: T-shirts, Camisas, Hoodies/Camisolas, Calções, Calças, Meias, Casacos, Sapatos, Acessórios. Miniaturas ou cartões, edição de cada peça (nome, tamanho, marca, modelo, corte, material, cor, estação, formalidade, notas) e importação em massa a partir de uma pasta. |
| **Aconselhar** | Escreves o pedido e recebes 2 a 3 outfits: primeiro o texto (porquê, como vestir, o que te fica melhor), depois as peças escolhidas e por fim uma imagem tua com cada outfit. Podes dar 👍/👎 a cada um. |
| **Provador** | Carregas fotos tuas e escolhes à mão até 8 peças para te veres vestido com elas. |
| **Desejos** | Guardas links de roupa que gostaste (a app lê título, imagem, loja e preço da página), marcas lojas como "com interesse" ou "sem interesse" e pedes ideias de compra à IA com base no teu armário. |
| **Memória** | O estilista não começa do zero: tem as tuas medidas e tamanhos, um perfil em texto, factos que vai aprendendo e o histórico recente. |
| **⚙ Modelos** | Configuras e testas os modelos de IA, sem editar ficheiros nem reiniciar. Mostra o consumo de tokens. |

## Como funciona

```
 fotos + dados das peças ──► modelo de texto/visão ──► outfits (JSON) ──► peças + texto na app
                                  ▲                                          │
   perfil, medidas, memória,      │                                          ▼
   histórico, lojas ──────────────┘             a tua foto + fotos das peças ──► modelo de imagem ──► tu com o outfit
```

1. **Armário.** Cada peça é uma foto + dados (categoria, cor, tamanho, marca…). As fotos são reduzidas e guardadas no disco, com miniaturas geradas à primeira vez que são pedidas.
2. **Conselhos.** O pedido segue para o modelo com o catálogo do armário em texto compacto (uma linha por peça), mais perfil, medidas, memória e histórico. Com mais de 24 peças, uma primeira chamada só de texto escolhe até 24 candidatas relevantes; só dessas se enviam fotos (reduzidas) numa segunda chamada. O modelo responde em JSON com os ids das peças, e a app mostra as peças reais.
3. **Medidas.** O modelo compara o tamanho de cada peça com o teu tamanho habitual e avisa se deve ficar larga ou justa.
4. **Memória.** O estilista guarda sozinho factos duráveis que afirmares no pedido ("não uso castanho") e aprende com o teu feedback aos outfits. Tudo é visível, editável e apagável no separador Memória.
5. **Provador.** As fotos das peças escolhidas e a tua foto seguem para um modelo de edição de imagem (Gemini por defeito), que devolve a imagem.
6. **Ideias de compra.** O modelo sugere peças que te faltam, só em lojas "com interesse", e dá uma pesquisa pronta. Não navega na web, por isso não há links de produto verificados.

### Importação em massa

Cria uma pasta com uma subpasta por categoria:

```
Roupa/
├── Tshirts/            Tshirt_Branca_Lefties_L_Wide.jpg
├── Camisas/
├── Hoodie-Camisolas/
├── Calças/             Calças_Ganga_Levis_511_W33_L34.jpg
├── Calções/
├── Meias/
├── Casacos/
├── Sapatos/            Puma_Palermo_44.jpg
├── Acessórios/         Chapéu_NewEra_Beige.jpg
└── eu.jpg              (fotos soltas na raiz: opcionalmente fotos tuas para o Provador)
```

- O nome do ficheiro tem partes separadas por `_`, **sem ordem fixa**. A app reconhece tamanhos (`M`, `44`, `W33`, `L34`), cores, cortes (`Wide`, `Slim`…), materiais (`Ganga`…), o tipo de peça e marcas; o que sobra é marca e modelo. Fica tudo editável depois.
- **Não importa duplicados:** ignora fotos com o mesmo nome (sem contar maiúsculas, acentos, extensão nem pasta) e fotos com conteúdo idêntico, tanto dentro da pasta como face ao que já está na app.
- Modo opcional de análise por visão (cor, estação, formalidade) para quem o nome não diz: *não* (por defeito, 0 tokens), *só sem cor no nome* ou *todas*. A app mostra o consumo real no fim.
- Aceita JPG, PNG, WebP e HEIC (iPhone). A importação só funciona a partir do próprio computador (`localhost`) e só com pastas dentro da pasta pessoal.

## Como correr

Requisitos: macOS/Linux, [uv](https://docs.astral.sh/uv/) (`brew install uv`) e Python 3.11+ (o `uv` trata disso).

```bash
git clone git@github.com:Joao1531/MyWardrobe.git
cd MyWardrobe
uv sync
cp .env.example .env        # opcional: podes configurar tudo na app
uv run uvicorn app.main:app --reload
```

Abre <http://localhost:8000>. Na primeira vez a app abre em **⚙ Modelos**, onde colas as chaves e testas cada modelo.

Se alterares o código, o `--reload` reinicia o servidor sozinho. Depois de atualizar o ecrã, faz um refresh forçado (Cmd+Shift+R) se o browser mostrar uma versão antiga.

### Configurar os modelos

Tudo pode ser feito no ecrã **⚙ Modelos** (fica em `data/settings.json`, só legível por ti) ou no `.env`. O que se escolhe no ecrã tem prioridade.

| Função | Variáveis | Notas |
|---|---|---|
| Texto e visão (conselhos, sugestões, análise de fotos) | `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_VISION_MODEL` | Qualquer API compatível com OpenAI `/chat/completions`. Por defeito aponta para o **opencode Go** (`https://opencode.ai/zen/go/v1`, modelo `glm-5.3-flash`, que aceita imagens). Deixa `LLM_VISION_MODEL` vazio para o modelo não ver fotos. |
| Provador (gera imagens) | `GEMINI_API_KEY`, `TRYON_MODEL`, `TRYON_BASE_URL` | Precisa de um modelo com **saída de imagem** (por defeito `gemini-2.5-flash-image` da Google, chave em <https://aistudio.google.com/apikey>). Os modelos de imagem podem exigir faturação. Opcional: sem isto, tudo o resto funciona. |
| Pasta de importação | `IMPORT_DIR` | Por defeito `~/Desktop/Roupa`. |

Cada modelo tem um botão de teste: o de texto verifica se devolve JSON válido, o de visão envia uma imagem de cor conhecida e pergunta a cor, e o do Gemini valida a chave e o modelo (há um teste de geração à parte, que gasta uma geração).

O opencode Go exige um `User-Agent` próprio e um `x-opencode-session` estável; a app envia ambos. Confirma nos termos do teu plano se uma app de roupa é um uso aceitável.

### Usar no telemóvel

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Abre `http://<IP-do-computador>:8000` no telemóvel (mesma rede Wi-Fi) e "Adicionar ao ecrã inicial". **A app não tem login:** com `--host 0.0.0.0`, qualquer pessoa na tua rede a pode usar e alterar as definições. Só a abras à rede em redes de confiança.

## Privacidade e custos

- **Local.** A base de dados, as fotos e as definições ficam em `data/`, que **não vai para o Git**. O mesmo vale para o `.env` e para qualquer ficheiro de imagem.
- **O que sai do computador:** as fotos e os dados das peças vão para o fornecedor do modelo de texto/visão (por defeito o opencode); a tua foto e as fotos das peças escolhidas vão para o fornecedor do modelo de imagem (por defeito a Google) quando geras uma imagem. Os links guardados em Desejos são lidos pelo servidor (só endereços públicos).
- **Tokens.** O catálogo é enviado em formato compacto, as fotos vão reduzidas (384–400 px) e há seleção prévia de candidatas. Cada resposta mostra as peças analisadas e os tokens gastos, e o ecrã ⚙ Modelos mostra o total desde que o servidor arrancou.

## Estrutura

```
app/
├── main.py         API e rotas das peças, conselhos e provador
├── ai.py           chamadas ao modelo: análise de fotos, conselhos (duas fases), sugestões, aprendizagem
├── memory.py       medidas, memória, histórico e feedback
├── wishlist.py     links, lojas e ideias de compra
├── importer.py     importação em massa a partir de uma pasta
├── filenames.py    interpretador de nomes de ficheiro
├── scrape.py       leitura de links de produtos (só endereços públicos)
├── tryon.py        provador: modelo de imagem
├── settings.py     definições e testes dos modelos
├── diagnostics.py  testes de texto, visão e provador
├── config.py       definições (ecrã + .env)
├── db.py           SQLite e migrações simples
├── images.py       redimensionamento, miniaturas, HEIC
└── static/         interface (HTML/CSS/JS, PWA, sem passos de build)
```

Stack: Python, FastAPI, SQLite, Pillow, e JavaScript puro no browser.

## Limitações

- Um só utilizador, sem autenticação.
- Não há testes automáticos; a verificação foi manual e com servidores de IA simulados.
- A qualidade dos conselhos e do provador depende dos modelos escolhidos e da qualidade das fotos (peça estendida numa superfície lisa, boa luz, uma peça por foto). Com muitas peças numa só imagem, o modelo de imagem pode perder fidelidade, por isso há um limite de 8 peças por outfit (`MAX_OUTFIT_ITEMS` em `app/config.py`).
- As ideias de compra são pesquisas, não links de produto verificados.

## Resolução de problemas

| Sintoma | Causa provável |
|---|---|
| "Method Not Allowed" ou "O servidor está desatualizado" | O servidor em execução é anterior ao código. Pára-o (Ctrl+C) e arranca com `--reload`. |
| `MissingSessionID` do opencode | Falta o cabeçalho `x-opencode-session`. A app envia-o quando o URL é do `opencode.ai`; confirma o URL base. |
| Gemini devolve 401 | Chave inválida, ou foi enviada como token OAuth. A app envia a chave da Google no cabeçalho `x-goog-api-key`. |
| O modelo "não devolve JSON válido" | Troca de modelo em ⚙ Modelos e volta a correr o teste de texto. |
| O browser mostra o ecrã antigo | Refresh forçado (Cmd+Shift+R). |
