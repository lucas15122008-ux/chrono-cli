# chrono: desenho

Data: 2026-11-02 · Tamanho: mudança pequena (o mesmo programa do `ia`, com nome e visual novos)

## Por quê

O `ia` funciona, mas mostra texto puro: os asteriscos de negrito aparecem crus, a tela fica parada enquanto o modelo carrega e não dá para ver nada sobre o que está acontecendo. O Lucas quer **mais informação na tela** e um **visual mais caprichado**, no estilo do "painel B" que ele escolheu entre três telas de exemplo.

## Objetivos

- Trocar o nome de `ia` para **`chrono`**.
- Mostrar, ao abrir o chat, uma **caixa de cabeçalho** com os dados do modelo e da conversa.
- Mostrar uma **animação de espera** com os segundos contando.
- Mostrar cada resposta **marcada e formatada** (negrito, listas, títulos, código).
- Mostrar, depois de cada resposta, uma **linha de detalhes** com números reais.

## Fora do escopo

- Mudar o que o programa faz: os comandos (`/nova`, `/modelo`, `/pensar`, `/imagem`), as opções (`-c`, `-i`, `-p`, `-m`, `--modelos`) e a memória da conversa continuam iguais.
- Tela cheia estilo aplicativo (tipo editor de texto). O chrono continua sendo um chat que rola no terminal.

## Não pode acontecer (mesmo que "funcione")

- A resposta ficar mais lenta para aparecer por causa do visual.
- Texto repetido ou piscando na tela em respostas longas.
- Enfeites (cores, caixas) indo parar num arquivo quando a saída é redirecionada, como em `chrono "..." > resposta.txt`.

## Caminhos considerados

| Caminho | Ganha | Perde |
|---|---|---|
| **Biblioteca `rich`** (escolhido) | Caixas, animação e formatação prontas e bem-feitas; menos código; ajusta à largura da janela | Instalar uma vez (`pip3 install --user rich`); deixa de ser "um arquivo e pronto" |
| Só Python puro | Continua um arquivo só, sem instalar nada | Programa ~2x maior; formatação só no básico |

**Escolha do Lucas:** `rich`, porque o objetivo é ficar bonito e é ali que ela entrega mais.

## Como fica, decidido com o Lucas

**Nome.** O comando passa a ser `chrono`. O `ia` é removido de `~/.local/bin`. A configuração e as conversas salvas passam de `~/.ia` para `~/.chrono`.

**Caixa de cabeçalho** (só no chat):
- `◆ chrono — IA local no seu Mac`
- modelo: nome, tamanho (ex.: 9B), versão compactada (ex.: Q4), se lê imagens
- memória: quanto o modelo ocupa (ex.: 6,7 GB na GPU) e o tamanho máximo da conversa (ex.: 32 mil tokens)
- conversa: nova ou continuação; raciocínio ligado ou desligado

**Espera.** Animação `carregando o modelo… 1,2 s`, que vira `pensando… 8 s` com o raciocínio ligado e some quando chega a primeira palavra da resposta.

**Resposta.** Barrinha roxa à esquerda, rótulo `chrono` e texto formatado.

**Linha de detalhes** depois de cada resposta: tempo total, velocidade (tokens/s), tamanho da resposta (tokens) e quanto da conversa já foi usado (%).

**Pergunta rápida** (`chrono "pergunta"`): sem a caixa de cabeçalho, só a resposta formatada e a linha de detalhes. Quando a saída não vai para a tela (arquivo ou pipe), sai só o texto puro da resposta.

## Decisões minhas (para o Lucas conferir)

- **De onde vêm os números:** todos vêm do próprio Ollama. Os dados do modelo vêm de `/api/show`; memória e tamanho da conversa, de `/api/ps`; tempo, velocidade e tokens, do último pedaço da resposta de `/api/chat`.
- **Raciocínio ligado:** o texto do raciocínio deixa de ser mostrado. Aparece só `pensando… N s` na animação, e a linha de detalhes ganha "pensou N s". Fica mais limpo; se você quiser ver o raciocínio, dá para voltar.
- **Respostas longas:** cada parágrafo é formatado assim que termina de chegar, e só o parágrafo em andamento fica "ao vivo". Isso evita o texto repetido ou piscando quando a resposta passa do tamanho da tela.
- **Sem a `rich` instalada:** o chrono não quebra; mostra uma mensagem dizendo o comando para instalar.
- **Cores:** roxo para a marca e a resposta, verde-água para "você ›", cinza para detalhes, como no exemplo B.

## Deixado para quem constrói

- Espaçamentos, símbolos e os tons exatos das cores, desde que fiquem fiéis ao exemplo B.
- Como mostrar os erros dentro do visual novo, mantendo as mensagens em português que já existem.
