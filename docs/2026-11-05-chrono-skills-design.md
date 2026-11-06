# chrono com skills: desenho

Data: 2026-11-05 · Tamanho: projeto pequeno (um módulo novo, comandos, um menu e uma ferramenta)

## Por quê

O Lucas quer **skills no chrono**: receitas para tarefas específicas (o passo a passo de como fazer algo) que ele mesmo cria do zero, pensadas para o que o chrono consegue fazer. Ele também quer que o chrono **ajude a criar as skills**, com uma skill pronta chamada **skill-creator**.

Agente e skill são coisas diferentes: o agente é *quem* conversa (instruções gerais, modelo, ferramentas) e é escolhido antes de começar; a skill é *uma receita* que se liga por cima de qualquer agente.

## Objetivos

- Cada skill é uma pasta em `~/.chrono/skills/NOME/` com um `SKILL.md` (o mesmo formato das skills do Claude que o Lucas já conhece) e, se ele quiser, outros arquivos de apoio (exemplos, modelos de planilha).
- **Só o Lucas liga uma skill** (escolha dele: o modelo não liga sozinho).
- Uma skill ligada **vale para a conversa inteira**: não precisa chamar de novo a cada mensagem. Dá para ligar mais de uma.
- `/skill` abre um menu com as setas para ligar e desligar; `/skill NOME` liga direto.
- O prompt mostra o que está ligado: `você · conferir-pedidos ›`.
- Conversa nova (`/nova` ou troca de agente) começa sem skills.
- A **skill-creator** vem pronta: entrevista o Lucas, mostra a receita e salva com o "s" dele, numa ferramenta própria que confere o formato e nunca sobrescreve sem perguntar.

## Fora do escopo (por enquanto)

- O modelo escolher e ligar skills sozinho (decisão do Lucas).
- Reaproveitar as skills do Claude em `~/.claude/skills` (o Lucas vai criar as do chrono do zero).
- Skills que rodam programas ou acessam a internet: uma skill só dá instruções; o que o modelo pode fazer continua limitado às ferramentas do chrono.
- Restringir quais skills cada agente pode usar.

## Não pode acontecer (mesmo que "funcione")

- Uma skill ligada sem o Lucas perceber: o prompt sempre mostra as skills ligadas.
- Uma skill passar por cima das regras do chrono: alterações continuam pedindo confirmação, e nenhuma skill faz o modelo rodar comandos.
- A skill-creator gravar ou sobrescrever uma skill sem mostrar o que vai gravar e receber um "s".
- Um `SKILL.md` com erro derrubar o chrono ou aparecer como erro do Python.

## Caminhos considerados

**Quem liga a skill:**

| Caminho | Ganha | Perde |
|---|---|---|
| O modelo sozinho e o Lucas também | Igual ao Claude | O modelo de 9B às vezes esquece ou liga sem precisar |
| **Só o Lucas** (escolhido) | Totalmente previsível | Precisa lembrar de ligar (resolvido por ficar ligada a conversa toda) |
| Só o modelo | Nada para lembrar | Menos controle quando o modelo erra |

**Formato:** pasta com `SKILL.md` (escolhido, mesmo formato do Claude, permite arquivos de apoio) em vez de um `.txt` solto como os agentes.

**Como a skill-creator salva:** uma ferramenta própria, `criar_skill` (escolhido: confere nome e formato), em vez de o modelo escrever o arquivo "na mão" com `escrever_arquivo` (um modelo de 9B erra mais o formato).

## Como funciona

### O arquivo da skill

`~/.chrono/skills/conferir-pedidos/SKILL.md`:

```
---
name: conferir-pedidos
description: confere um pedido de fornecedor contra a planilha de preços
---

1. Peça o PDF do pedido e a planilha de preços, se o usuário não disse quais são.
2. ...
```

- **Nome:** o nome da pasta (letras, números, `-` e `_`). Como nos agentes, maiúsculas e acentos não importam ao chamar. O `name:` do cabeçalho é opcional; se existir e for diferente da pasta, vale a pasta.
- **Descrição:** `description:` no cabeçalho, uma frase. Opcional, mas aparece no menu e na lista.
- **Instruções:** tudo depois do cabeçalho. Obrigatório.
- **Sem cabeçalho** (`---` no começo), o arquivo inteiro são as instruções.
- **Arquivos de apoio:** os outros arquivos da pasta. Quando a skill está ligada, o chrono diz ao modelo onde está a pasta e quais arquivos ela tem, para ele ler com as ferramentas de leitura (precisa das ferramentas ligadas).
- **Erros, em português:**
  - pasta sem `SKILL.md`;
  - cabeçalho aberto e não fechado;
  - skill sem instruções;
  - arquivo que não é texto em UTF-8;
  - `SKILL.md` maior que 20 000 caracteres: "a skill X é grande demais (N caracteres); o limite é 20000".

### Ligar e desligar

- `/skill NOME` liga a skill. Se ela já estava ligada, lê o arquivo de novo (vale como "recarregar") e avisa.
- `/skill desligar NOME` desliga uma skill; `/skill desligar` desliga todas.
- `/skill` abre o menu (com terminal de verdade; sem terminal, imprime a lista):
  ```
  Skills   ↑↓ escolher · Enter liga/desliga · e editar · Esc sair
  ▸ ✓ conferir-pedidos   confere um pedido de fornecedor contra a planilha de preços
      skill-creator      ajuda a criar uma skill nova para o chrono
      + criar skill nova
  ```
  - Enter liga ou desliga a skill destacada e **o menu continua aberto**, para ligar várias de uma vez.
  - **e** abre o `SKILL.md` destacado no TextEdit.
  - **"+ criar skill nova"** liga a skill-creator e fecha o menu, com o aviso "A skill-creator está ligada: diga que skill você quer criar.".
  - **Esc** fecha. Ao fechar, uma linha cinza diz quais skills estão ligadas ("Skills ligadas: a, b" ou "Nenhuma skill ligada.").
  - Uma skill com erro aparece com ⚠; Enter nela mostra o erro e não liga.
- `/skill editar NOME` abre o `SKILL.md` no TextEdit. A mudança vale na próxima vez que a skill for ligada (ou com `/skill NOME` de novo).
- **No Terminal:** `chrono -s NOME` (pode repetir) liga a skill naquela vez, também com pergunta rápida; `chrono --skills` lista as skills. Uma skill que não existe ou está com erro, em `-s` ou `/skill NOME`, dá erro em português com a lista das que existem (no `-s`, o chrono não abre).
- **Nomes reservados:** `desligar` e `editar`.

### Durante a conversa

- Em cada pedido ao modelo, o chrono junta ao prompt de sistema, depois das instruções do agente (e do aviso da pasta atual), um bloco por skill ligada:
  ```
  # Skill ligada: conferir-pedidos
  (confere um pedido de fornecedor contra a planilha de preços)
  <instruções>
  Arquivos de apoio desta skill, em ~/.chrono/skills/conferir-pedidos: modelo.xlsx
  ```
  Como no aviso da pasta, isso vai só no pedido, não no histórico.
- **O prompt** mostra as skills ligadas: `você · conferir-pedidos ›`, ou `você · a, b ›` com mais de uma.
- **Conversa nova:** `/nova` e a troca de agente desligam todas as skills e avisam em cinza ("Skills desligadas.") se havia alguma.
- **Conversas salvas** guardam os nomes das skills ligadas. O `chrono -c` liga de novo as que ainda existem, lendo o arquivo atual; uma que sumiu ou está com erro gera um aviso em vermelho e fica de fora.

### A skill-creator

- **Primeira vez:** se `~/.chrono/skills/` não existir, o chrono cria a pasta com a skill-creator dentro. Como os agentes prontos, ela é um arquivo normal, que o Lucas pode editar.
- **A ferramenta `criar_skill(nome, descricao, instrucoes)`** só é oferecida ao modelo enquanto a skill-creator está ligada, para manter curta a lista de ferramentas do modelo de 9B. Ela:
  - confere o nome (mesmas regras), a descrição e as instruções (não vazias);
  - **pergunta antes de gravar**, mostrando o `SKILL.md` inteiro: "Criar a skill X em ~/.chrono/skills/X/SKILL.md?";
  - se a skill já existir, pergunta "Substituir a skill X?" (sempre pergunta, mesmo depois de um "t") e manda o `SKILL.md` antigo para a Lixeira antes;
  - responde ao modelo "skill criada; para usar: /skill X".
- **Ao ligar a skill-creator** num agente sem ferramentas, ou só leitura, o chrono avisa: "A skill-creator precisa das ferramentas ligadas para salvar a skill; com este agente ela só consegue escrever o texto para você copiar."
- **As instruções da skill-creator** (texto pronto, em português) dizem ao modelo para:
  1. Entender a tarefa com uma pergunta por vez: o que a skill faz, quando usar, os passos, um exemplo de entrada e de resultado, que arquivos ela usa.
  2. Propor um nome curto (minúsculas e hífens) e uma descrição de uma frase dizendo quando usar.
  3. Escrever as instruções como passos numerados, diretos e em português, citando as ferramentas do chrono que cada passo usa (ler arquivos, buscar, fazer contas em planilhas, criar e mudar planilhas). Lembrar que o chrono não acessa a internet nem roda programas.
  4. Mostrar a skill inteira ao usuário e perguntar se pode salvar; ajustar o que ele pedir.
  5. Chamar `criar_skill` e, no fim, dizer como usar: `/skill nome`.

## Onde fica no código

- **`skills.py`** (novo):
  - ler e validar uma skill (nome, descrição, instruções, pasta, arquivos de apoio), listar, criar a skill-creator na primeira vez;
  - a definição e a execução da ferramenta `criar_skill`;
  - o texto da skill-creator e o erro `ErroSkill`.
- **`menu.py`:** um modo em que Enter alterna o ✓ e o menu continua aberto.
- **`chrono.py`:**
  - `Conversa.skills` (as ligadas), o bloco das skills em cada pedido e a ferramenta `criar_skill` quando a skill-creator está ligada;
  - `/skill` e `/skill desligar|editar`, o prompt com as skills, `-s` e `--skills`;
  - as skills na conversa salva e no `-c`, e o desligamento em `/nova` e na troca de agente;
  - `/ajuda` e `EXEMPLOS`.
- **Testes:** `tests/test_skills.py` e testes no `test_chrono.py`, como nos agentes (terminal falso, Ollama de mentira, `open` de mentira).

## Fica a critério de quem constrói

- O texto exato das mensagens e das instruções da skill-creator, seguindo os passos acima.
- A ordem da lista (sugestão: ordem alfabética).
- Se o prompt corta a lista de skills quando ela fica muito longa.

## Depois da revisão

- Na pergunta rápida (sem prompt na tela), o chrono escreve em cinza "Skills ligadas: …" quando `-c` religa skills da conversa ou `-s` liga alguma.
- O aviso da skill-creator sem poder salvar aparece também ao ligá-la pelo menu e com `-s`/`-c`; e o modelo recebe uma linha dizendo que a ferramenta `criar_skill` não está disponível e que, no fim, deve mostrar o SKILL.md completo para o usuário copiar.
- `criar_skill` confere o limite de 20 000 caracteres, nomes de até 64 caracteres e põe a descrição numa linha só.
- No menu, "e" em "+ criar skill nova" não liga a skill-creator.
