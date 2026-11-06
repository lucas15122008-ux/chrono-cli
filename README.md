# chrono

IA local no terminal do Mac, rodando no [Ollama](https://ollama.com). Conversa em português e também:
- lê e organiza seus arquivos, sempre perguntando antes de mudar qualquer coisa;
- lê PDF, Word e planilhas e faz contas nas planilhas;
- tem **agentes** e **skills** que você mesmo cria e ajusta.

Nada sai do seu computador.

```
╭────────────────────────────────────────────────────────────╮
│ ◆ chrono — IA local no seu Mac                             │
│ agente   geral · assistente para qualquer assunto          │
│ modelo   ornith-1.5:9b · 9B · Q4 · lê imagens              │
│ memória  7,9 GB na GPU · conversa até 65 mil tokens        │
│ conversa nova · raciocínio desligado · ferramentas ligadas │
╰────────────────────────────────────────────────────────────╯
você ›
```

## O que precisa

- macOS (feito e testado num MacBook M4 com 16 GB)
- Python 3.9 ou mais novo (o que já vem no Mac serve)
- [Ollama](https://ollama.com) rodando, com um modelo que use ferramentas. O padrão é o `ornith-1.5:9b`:
  ```bash
  ollama pull ornith-1.5:9b
  ```
- As bibliotecas de Python (só a `rich` é obrigatória; as outras são para PDF e Excel):
  ```bash
  pip3 install --user rich pypdf openpyxl xlrd
  ```
- Opcional: as ferramentas de linha de comando do Xcode (`xcode-select --install`). Com elas, o chrono lê PDFs escaneados usando o leitor de texto do próprio macOS.

## Instalar

```bash
git clone https://github.com/lucas15122008-ux/chrono-cli.git
cd chrono-cli
mkdir -p ~/.local/bin
ln -s "$PWD/chrono.py" ~/.local/bin/chrono
```

Se o comando `chrono` não for encontrado, coloque `~/.local/bin` no PATH, adicionando `export PATH="$HOME/.local/bin:$PATH"` ao `~/.zshrc`.

## Usar

```bash
chrono                                   # abre o chat
chrono "qual a diferença entre óleo 5W30 e 10W40?" # pergunta rápida sem precisar de abrir o chat, mas carrega modelo
chrono -c "e para motor flex?"           # continua a última conversa
cat pedido.txt | chrono "resuma"         # usa um texto como contexto
chrono -i foto.jpg "que peça é essa?"    # manda uma imagem
chrono -a atendente                      # abre com um agente
chrono -s conferir-pedidos "pedido.pdf"  # liga uma skill
chrono -m outro-modelo -p                # outro modelo, com raciocínio
chrono --agentes                         # lista os agentes
chrono --skills                          # lista as skills
chrono --modelos                         # lista os modelos baixados
```

### Comandos do chat

| Comando | O que faz |
|---|---|
| `/agente` | menu com as setas para trocar de agente (`/agente nome` troca direto) |
| `/agente novo NOME` · `/agente editar` | cria ou abre um agente no TextEdit |
| `/skill` | menu com as setas para ligar e desligar skills (`/skill nome` liga direto) |
| `/skill desligar [nome]` · `/skill editar NOME` | desliga uma skill (ou todas) ou abre uma no TextEdit |
| `/modelo [nome]` | mostra ou troca o modelo |
| `/pensar` · `/ferramentas` | liga ou desliga o raciocínio e o acesso aos arquivos |
| `/imagem ARQUIVO` | anexa uma imagem à próxima mensagem |
| `/nova` · `/ajuda` · `/sair` | conversa nova, ajuda, sair (ou Ctrl+D) |

Para colar várias linhas, comece e termine com uma linha só com `"""`.

## Ferramentas

O modelo pode, sozinho:
- listar pastas, procurar arquivos (pelo Spotlight) e procurar texto;
- ler textos, PDF, Word e planilhas;
- ver imagens;
- fazer contas em planilhas: soma, média, contagem, com filtro e agrupamento.

Antes de qualquer mudança, o chrono mostra o que vai fazer e pergunta (s/n/t). Isso vale para:
- escrever arquivos, criar pastas, mover;
- mandar para a Lixeira;
- criar e editar planilhas.

As regras de segurança:
- "Apagar" sempre manda para a Lixeira; nada é apagado de vez.
- Antes de editar uma planilha, uma cópia vai para a Lixeira.
- O chrono não roda comandos no Terminal e não acessa a internet.

## Agentes

O agente define **quem** conversa: as instruções, o modelo, o raciocínio e as ferramentas. Cada agente é um arquivo de texto em `~/.chrono/agentes/`. Na primeira vez, o chrono cria três: `geral`, `atendente` (respostas para clientes do Mercado Livre) e `planilhas`.

```
descrição: rascunha respostas para clientes do Mercado Livre
modelo: ornith-1.5:9b
raciocínio: desligado
ferramentas: só leitura

Você ajuda a responder perguntas de clientes no Mercado Livre...
```

As configurações vêm no começo do arquivo, todas opcionais. Depois de uma linha em branco vêm as instruções. Linhas que começam com `#` são comentários.

## Skills

A skill é uma **receita** para uma tarefa: o passo a passo que vai junto de cada mensagem enquanto ela estiver ligada. Só você liga uma skill, e ela vale até o fim da conversa. Cada skill é uma pasta em `~/.chrono/skills/NOME/` com um `SKILL.md`, no mesmo formato das skills do Claude:

```
---
name: conferir-pedidos
description: confere um pedido de fornecedor contra a planilha de preços
---

1. Leia o PDF do pedido com ler_arquivo.
2. ...
```

A pasta pode ter outros arquivos de apoio, como um modelo de planilha. A **skill-creator** já vem pronta: ligue com `/skill skill-creator` e diga que skill você quer. Ela te entrevista, escreve a receita e salva depois do seu "s".

## Onde ficam as coisas

| Caminho | O quê |
|---|---|
| `~/.chrono/config.json` | servidor do Ollama, modelo, agente padrão |
| `~/.chrono/agentes/` | os agentes |
| `~/.chrono/skills/` | as skills |
| `~/.chrono/conversas/` | as conversas salvas |

## Testes

```bash
python3 -m unittest discover -s tests
```

Os testes usam um Ollama de mentira e pastas temporárias. Não precisam do modelo e não mexem nos seus arquivos.


### O Chrono ainda está em Beta, tem erros e muitas funcionalidades faltando!!!