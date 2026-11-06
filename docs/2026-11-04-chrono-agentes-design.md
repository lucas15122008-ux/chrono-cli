# chrono com agentes: desenho

Data: 2026-11-04 · Tamanho: projeto pequeno (um módulo novo, uma opção, um comando e os testes)

## Por quê

O Lucas quer **agentes que ele possa customizar e que sirvam para diferentes coisas**. Por enquanto, a forma que ele escolheu é **trocar de agente antes de fazer algo**: cada agente é um ajudante com nome, instruções e configurações próprias, e o Lucas escolhe qual usar. A ideia de o chrono dividir uma tarefa e passar partes para outros agentes sozinho (os "subagentes") fica para depois.

## Objetivos

- Um agente junta, com um nome: **instruções** (o prompt de sistema), **modelo**, **raciocínio** (ligado ou desligado) e **ferramentas** (ligadas, desligadas ou só leitura), mais uma **descrição** curta.
- Cada agente é **um arquivo de texto** em `~/.chrono/agentes/`, que o Lucas abre e edita no TextEdit (escolha do Lucas, caminho A).
- Escolher o agente **ao abrir** (`chrono -a atendente`, também com pergunta rápida) ou **no meio do chat** (`/agente atendente`).
- Listar os agentes: `/agente` no chat e `chrono --agentes` no Terminal.
- Criar e editar sem procurar a pasta: `/agente novo NOME` e `/agente editar [NOME]` abrem o arquivo no TextEdit.
- Erro de digitação numa configuração aparece em português, dizendo a linha e o que vale ali, sem quebrar o chrono.
- Já vêm três agentes prontos: **geral**, **atendente** e **planilhas** (conteúdo abaixo).

## Fora do escopo (por enquanto)

- **Subagentes**: um agente chamar outro sozinho, ou o chrono dividir uma tarefa entre agentes.
- Ferramentas novas por agente (por exemplo, acesso ao Mercado Livre). Os agentes usam as ferramentas que já existem.
- Memória ou pasta própria por agente.
- Criar agentes com perguntas passo a passo no terminal (caminho C) ou dentro do `config.json` (caminho B).

## Não pode acontecer (mesmo que "funcione")

- `chrono` sozinho passar a se comportar diferente de hoje. O agente padrão "geral" é o chrono de hoje.
- Um erro num arquivo de agente aparecer como erro do Python (traceback) ou derrubar o chrono no meio de uma conversa.
- Uma configuração escrita errado ser ignorada em silêncio (por exemplo, "modlo: ..." fazer o agente usar outro modelo sem avisar).
- O chrono sobrescrever um agente que o Lucas editou. Os agentes prontos só são criados quando a pasta ainda não existe, e `/agente novo` recusa um nome que já existe.
- Agentes contornarem as regras das ferramentas: alterações continuam pedindo confirmação, e nada roda comandos escolhidos pelo modelo.

## Caminhos considerados

| Caminho | Ganha | Perde |
|---|---|---|
| **A. Um arquivo de texto por agente** (escolhido) | Fácil de abrir, ler e ajustar com calma no TextEdit; instruções longas ficam naturais | Precisa de uma regra simples para separar as configurações do texto e de avisos claros para erros |
| B. Tudo no `config.json` | Um arquivo só | JSON é chato de editar à mão (aspas, vírgulas, texto longo numa linha); uma vírgula quebra tudo |
| C. Só por comandos no chrono | Não precisa abrir arquivo | Escrever e corrigir instruções longas pelo terminal é desconfortável; mais código |

**Escolha do Lucas:** A.

## Como funciona

### O arquivo do agente

`~/.chrono/agentes/atendente.txt` (o nome do arquivo é o nome do agente; `.txt` para o TextEdit abrir direto):

```
descrição: rascunha respostas para clientes do Mercado Livre
modelo: ornith-1.5:9b
raciocínio: desligado
ferramentas: só leitura

Você ajuda a JR Auto Peças a responder clientes do Mercado Livre.
...
```

- **Configurações:** o primeiro bloco do arquivo (até a primeira linha em branco), uma por linha, no formato `nome: valor`. Todas são opcionais; a que faltar vem do `config.json` (`modelo`, `pensar`) ou do padrão de hoje (ferramentas ligadas quando o modelo sabe usar).
- **Instruções:** todo o resto do arquivo. É exatamente o prompt de sistema que o modelo recebe; o chrono só acrescenta, como hoje, o aviso da pasta atual quando as ferramentas estão ligadas.
- **Arquivo sem configurações:** se nenhuma linha do primeiro bloco for uma configuração conhecida, o arquivo inteiro é instrução. Assim, um texto que começa com "Atenção: ..." não vira configuração.
- **Erros:** se o primeiro bloco tiver alguma configuração conhecida e alguma linha que não é, é erro: "linha 2 do agente atendente: não conheço "modlo"; as configurações são: descrição, modelo, raciocínio, ferramentas". Valor inválido também: "ferramentas: talvez — use ligadas, desligadas ou só leitura". Um agente sem instruções é erro também.
- **Leniência:** maiúsculas e acentos não importam nos nomes e valores (`raciocinio`, `so leitura`, `Ligado`). `sim`/`não` valem como ligado/desligado em raciocínio e ferramentas.
- **Depois da revisão:** `pensar` (o nome usado no `config.json`) vale como `raciocínio`, e `ferramenta` vale como `ferramentas`. Uma configuração escrita quase certo ("modlo") é erro mesmo sozinha no bloco, com a sugestão "(quis dizer modelo?)". Uma configuração perdida logo depois da linha em branco ("ferramentas: só leitura" já nas instruções) também é erro. Num agente "só leitura", o chrono recusa qualquer ferramenta que altera arquivos, mesmo que o modelo invente o pedido, e avisa o modelo de que ele não pode alterar nada.
- **Nome do agente:** letras, números, `-` e `_`, sem espaços. `novo` e `editar` são reservados para os comandos.

### Escolher o agente

- **Ao abrir:** `chrono -a atendente` (chat) ou `chrono -a atendente "pergunta"` (pergunta rápida). Sem `-a`, vale o agente padrão, `"agente"` no `config.json` (`"geral"` por padrão; a chave entra no `PADRAO`).
- **Opções do Terminal ganham do agente naquela vez:** `-m` troca o modelo e `-p` liga o raciocínio.
- **Agente que não existe** (`-a` ou `/agente` com um nome errado): erro em português com a lista dos agentes que existem.
- **Configuração que o modelo não tem:** raciocínio ligado num modelo sem raciocínio ou ferramentas num modelo sem ferramentas são ignorados, como hoje, e o cabeçalho mostra "indisponível".
- **No chat:** `/agente atendente` troca de agente e **começa uma conversa nova**, porque as instruções mudam. Carrega o modelo do agente (com a animação de espera) e mostra o cabeçalho de novo. Se o modelo não existir ou a troca for interrompida, fica o agente de antes, como no `/modelo`. Trocar para o mesmo agente recarrega o arquivo, então serve para aplicar uma edição.
- `/nova` começa uma conversa nova com o mesmo agente.
- `/ferramentas`, `/pensar` e `/modelo` continuam funcionando e valem até a próxima troca de agente. Com um agente "só leitura", `/ferramentas` liga e desliga, mas continua só leitura.

### Ver, criar e editar

- `/agente` (sem nome) mostra o agente atual e a lista, com a descrição de cada um. `chrono --agentes` mostra a mesma lista no Terminal.
- `/agente novo NOME` cria `NOME.txt` com um modelo de arquivo comentado em português (as quatro configurações e um parágrafo de instruções para trocar) e abre no TextEdit (`open -e`). Depois de salvar, `/agente NOME` passa a usá-lo.
- `/agente editar` abre o arquivo do agente atual no TextEdit; `/agente editar NOME`, o de outro. A mudança vale na próxima troca para o agente (`/agente NOME`) ou na próxima vez que o chrono abrir.
- Abrir o TextEdit é um comando fixo do chrono, não escolhido pelo modelo, então não conflita com "rodar comandos ainda não".

### O cabeçalho

Uma linha a mais na caixa do cabeçalho: `agente   atendente · rascunha respostas para clientes do Mercado Livre`.

### Conversas salvas

- O arquivo da conversa guarda o nome do agente.
- `chrono -c` continua com o agente da conversa: o histórico, com as instruções de quando a conversa começou, e o modelo vêm da conversa salva (como hoje); raciocínio e ferramentas vêm do arquivo do agente, se ele ainda existir; se não existir, do `config.json`, como hoje.
- Conversas antigas, sem agente, continuam como hoje (aparecem como "geral").

### Primeira vez

Se `~/.chrono/agentes/` não existir, o chrono cria a pasta com os três agentes prontos. O "geral" usa o `sistema` do `config.json`, para manter qualquer ajuste que o Lucas já tenha feito. Se o arquivo do agente padrão for apagado depois, o chrono usa o `sistema`, o `modelo` e o `pensar` do `config.json`, como hoje, e o cabeçalho mostra "geral (padrão do config.json)".

### Os três agentes prontos

(Textos de atendente e planilhas ajustados depois do teste com o ornith-1.5:9b: o primeiro escrevia um comentário antes da resposta; o segundo procurava a planilha no Mac inteiro em vez da pasta atual.)

**geral.txt**
```
descrição: assistente para qualquer assunto

(o "sistema" do config.json; hoje: "Você é um assistente útil que roda no terminal do usuário.
Responda sempre em português do Brasil, de forma clara e direta. Evite tabelas e formatação pesada.")
```

**atendente.txt**
```
descrição: rascunha respostas para clientes do Mercado Livre
ferramentas: só leitura

Você ajuda a JR Auto Peças, loja de autopeças, a responder perguntas de clientes no Mercado Livre.
Sua resposta inteira é o texto que vai para o cliente, pronto para colar: comece direto pela
resposta, sem comentários antes ou depois, sem aspas, sem emojis e sem formatação.
Seja curto e educado, em português do Brasil.
Use apenas as informações que o usuário passar (anúncio, compatibilidade, estoque, prazo). Se
faltar alguma coisa para responder com certeza, não escreva a resposta: diga ao usuário o que falta.
Nunca prometa prazo, desconto ou compatibilidade que não esteja nessas informações.
Não coloque telefone, e-mail, endereço nem links na resposta: o Mercado Livre não permite. Se o
cliente pedir um contato, diga com gentileza, na própria resposta, que as dúvidas podem ser
tiradas por aqui mesmo.
```

**planilhas.txt**
```
descrição: lê, organiza e faz contas em planilhas e documentos
ferramentas: ligadas

Você é um assistente que roda no terminal do usuário e ajuda a ler, organizar e analisar
planilhas, tabelas e documentos.
Quando o usuário citar um arquivo sem caminho, comece pela pasta atual: use o nome do arquivo
direto nas ferramentas e só procure no resto do Mac se ele não estiver lá.
Para qualquer conta (soma, média, total, contagem), use a ferramenta calcular_na_planilha em vez
de calcular de cabeça.
Antes de mudar uma planilha, leia o cabeçalho para usar os nomes certos das colunas.
Responda em português do Brasil, de forma curta, dizendo de onde tirou cada número.
```

## Onde fica no código

- **`agentes.py`** (novo): ler e validar um arquivo de agente (o resultado tem nome, descrição, modelo, raciocínio, ferramentas e instruções), listar, criar os prontos, criar a partir do modelo e o erro `ErroAgente`.
- **`chrono.py`**:
  - a opção `-a/--agente` e o `--agentes`;
  - o comando `/agente`;
  - a `Conversa` sabe qual é o agente e aplica as configurações dele;
  - a linha do agente no cabeçalho, o agente na conversa salva e no `-c`;
  - `/ajuda`, `EXEMPLOS` e a chave `"agente"` no `PADRAO`.
- **Testes:** `tests/test_agentes.py` (ler, validar, listar, criar sem sobrescrever) e testes no `test_chrono.py` para `-a`, `/agente` (troca, nova conversa, erro mantém o anterior), cabeçalho, conversa salva com `-c`, e `/agente novo`/`editar` com o `open` simulado. Os testes usam a pasta temporária que se apaga sozinha (`tests/limpeza.py`).

## Fica a critério de quem constrói

- O texto exato do modelo de arquivo do `/agente novo` e das mensagens de erro, desde que em português e dizendo a linha e o que vale.
- Se o nome do agente é procurado ignorando acentos, além de maiúsculas.
- A ordem da lista (sugestão: o agente atual primeiro, depois em ordem alfabética).
