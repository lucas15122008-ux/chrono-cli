# chrono com ferramentas: desenho

Data: 2026-11-02 · Tamanho: projeto pequeno (um ciclo novo no chrono, nove ferramentas e a confirmação)

## Por quê

O Lucas quer que o chrono **tenha acesso ao que ele tem no Mac** e **use ferramentas**: em vez de só conversar, encontrar, ler e organizar arquivos quando pedido em português ("resume o último orçamento que salvei em Documentos"). Toda alteração no Mac precisa de confirmação dele antes.

## Objetivos

- O modelo decide sozinho quando usar uma ferramenta, com o recurso nativo de ferramentas do Ollama.
- Ferramentas de leitura funcionam sem perguntar.
- Ferramentas que alteram algo **sempre perguntam antes**, mostrando exatamente o que vão fazer.
- Cada ação aparece na tela, no estilo do painel B, para o Lucas acompanhar.
- O formato das ferramentas é o mesmo do MCP (nome, descrição e parâmetros em JSON Schema), para um servidor MCP poder entrar depois sem refazer nada.

## Fora do escopo (por enquanto)

- **Rodar comandos no Terminal.** Decisão do Lucas: ainda não.
- **Servidor MCP.** Decisão do Lucas: fica para depois. Só o formato fica preparado.
- **PDF e planilhas do Excel.** Cada um precisa de uma biblioteca a mais; entram depois.
- **Internet:** nenhuma ferramenta acessa a rede.

## Não pode acontecer (mesmo que "funcione")

- Alterar, mover ou criar qualquer coisa sem um "s" do Lucas.
- Apagar um arquivo de vez: "apagar" sempre manda para a Lixeira.
- Ficar em loop chamando ferramentas sem parar.
- Encher a tela com o conteúdo de arquivos lidos: o resultado das ferramentas vai para o modelo, não para a tela.

## Caminhos considerados

| Caminho | Ganha | Perde |
|---|---|---|
| **Ferramentas nativas do Ollama, o modelo decide** (escolhido) | Pedido em português, o modelo acha e abre o que precisa; mesmo formato do MCP | O modelo de 9B às vezes escolhe a ferramenta errada ou erra um caminho; precisa de limite de rodadas |
| Só atalhos (`/ler`, `/pasta`) | Totalmente previsível | Não é "ter ferramentas": o Lucas faz o trabalho de achar os arquivos |
| Protocolo inventado em texto | Funciona com modelos sem ferramentas | Descartado: o qwen3.5:9b já sabe usar ferramentas |

**Escolha do Lucas:** ferramentas nativas, porque é o que ele descreveu e a confirmação protege as alterações.

## Como fica, decidido com o Lucas

**Ferramentas de leitura (sem perguntar):**

| Ferramenta | O que faz | Parâmetros |
|---|---|---|
| `listar_pasta` | lista o que tem numa pasta | `caminho` |
| `ler_arquivo` | lê um arquivo de texto (`.txt`, `.md`, `.csv`, código...) | `caminho` |
| `buscar_arquivos` | procura arquivos pelo nome no Mac inteiro (busca do Spotlight) | `nome`, `pasta` (opcional) |
| `buscar_texto` | procura um texto dentro dos arquivos de uma pasta | `texto`, `pasta` |
| `ver_imagem` | abre uma imagem do Mac para o modelo ver | `caminho` |

**Ferramentas que alteram (perguntam antes):**

| Ferramenta | O que faz | Parâmetros |
|---|---|---|
| `escrever_arquivo` | cria ou substitui um arquivo de texto | `caminho`, `conteudo` |
| `criar_pasta` | cria uma pasta | `caminho` |
| `mover` | move ou renomeia | `origem`, `destino` |
| `mandar_para_lixeira` | manda para a Lixeira (nunca apaga de vez) | `caminho` |

**Confirmação:** antes de cada alteração aparece a pergunta, por exemplo `? Mover "orcamento.pdf" para Documentos/Clientes? (s/n)`. Só "s" ou "sim" libera; qualquer outra resposta recusa, e o modelo recebe "o usuário recusou" para seguir sem aquilo.

**Sem rodar comandos:** nenhuma ferramenta executa comando escolhido pelo modelo.

## Decisões minhas (para o Lucas conferir)

- **Acesso:** o chrono lê o que o Lucas pode ler no Mac. Caminhos com `~` funcionam, e caminhos relativos partem da pasta onde o chrono foi aberto. Como tudo roda no Mac, nada lido sai do computador.
- **Nomes de pasta em português:** no teste com o modelo real, ele pediu `~/Documentos`, mas no Mac a pasta é `~/Documents` (o Finder só mostra o nome traduzido). A descrição das ferramentas diz ao modelo os nomes reais, e, quando um caminho não existe, o chrono troca os nomes traduzidos pelos reais: Documentos → Documents, Mesa e Área de Trabalho → Desktop, Imagens → Pictures, Músicas → Music, Filmes → Movies.
- **Na tela**, cada ação vira uma linha cinza antes da resposta: `◇ listando Documentos`, `◇ lendo pedido.txt`, `◇ procurando "orçamento"`. Alterações confirmadas aparecem como `◆ movido orcamento.pdf → Documentos/Clientes`; recusadas como `◇ recusado`.
- **Escrever arquivo:** a confirmação mostra as primeiras linhas do conteúdo e avisa em destaque quando vai **substituir** um arquivo que já existe.
- **Várias alterações numa resposta** (por exemplo, organizar 30 arquivos): cada uma pergunta. A resposta "t" (todas) aprova as alterações restantes **daquela pergunta**, depois de você ver a primeira.
- **Limites:** no máximo 10 rodadas de ferramenta por pergunta (depois disso o chrono avisa e para); `ler_arquivo` lê no máximo 20 mil caracteres e avisa quando cortou; listas e buscas mostram no máximo 100 itens; arquivos que não são texto são recusados com uma mensagem clara.
- **Sem teclado para responder:** quando a entrada não vem do teclado (`cat x | chrono "..."`), não dá para confirmar, então as ferramentas que alteram são recusadas automaticamente; as de leitura funcionam. A pergunta rápida no terminal (`chrono "..."`) pergunta normalmente.
- **Imagem:** `ver_imagem` manda a imagem junto do resultado da ferramenta (testado com o modelo real: ele abriu uma foto de teste e respondeu a cor certa).
- **Modelo sem ferramentas:** se o modelo escolhido não sabe usar ferramentas, o chrono segue como hoje, só conversando, e o cabeçalho avisa.
- **Cabeçalho:** a linha "conversa" ganha `· ferramentas ligadas` (ou `indisponíveis`).
- **Comando `/ferramentas`:** liga e desliga as ferramentas na conversa, para quando você quiser só bater papo sem o modelo sair procurando arquivo.
- **Linha de detalhes:** soma o tempo e os tokens de todas as rodadas da pergunta; o % de contexto é o da última rodada.
- **Histórico:** os pedidos de ferramenta e os resultados ficam salvos na conversa, para o `chrono -c` continuar com o contexto.

## Deixado para quem constrói

- O texto exato das descrições das ferramentas para o modelo (curto, em português, dizendo quando usar cada uma).
- Como detectar se um arquivo é texto.
- Os nomes únicos na Lixeira quando já existe um item com o mesmo nome.
