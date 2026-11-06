# chrono: menu de agentes com as setas — desenho curto

Data: 2026-11-05 · Tamanho: mudança pequena (um menu no `/agente`) · Aprovado pelo Lucas ("isso mesmo, pode fazer")

## Por quê

O Lucas quer escolher o agente **navegando com as setas do teclado** em vez de digitar o nome: no chat, `/agente` abre um menu, ↑/↓ escolhem, Enter troca.

## Como fica

```
Escolha o agente   ↑↓ escolher · Enter trocar · e editar · Esc sair
  ● geral       assistente para qualquer assunto
▸   atendente   rascunha respostas para clientes do Mercado Livre
    planilhas   lê, organiza e faz contas em planilhas e documentos
    + criar agente novo
```

- `/agente` (sem nada depois) abre o menu, já parado no agente atual (o do ●); a linha escolhida fica em lilás.
- **↑/↓** andam (do fim volta para o começo e vice-versa). **Enter** troca de agente, igual ao `/agente NOME` de hoje (conversa nova, cabeçalho de novo). **Esc**, **Ctrl+C** ou **Ctrl+D** fecham sem mudar nada.
- **e** abre o agente destacado no TextEdit, igual ao `/agente editar NOME`.
- **"+ criar agente novo"** pergunta o nome e faz o mesmo que `/agente novo NOME`.
- Agente com erro aparece com ⚠ e o erro; Enter nele mostra o erro e fica o agente atual (como `/agente NOME` com um arquivo quebrado). "e" nele abre o arquivo para consertar.
- O menu some depois da escolha. Com Esc fica uma linha cinza com o agente que continua ativo.
- `/agente NOME`, `/agente novo NOME` e `/agente editar [NOME]` continuam iguais.
- Sem terminal de verdade (a tela não é um terminal), `/agente` imprime a lista como hoje.

## Caminhos considerados

| Caminho | Ganha | Perde |
|---|---|---|
| **Menu feito no chrono, com a rich e o controle do teclado do Python** (escolhido) | Nada para instalar; mesmo visual do resto; testável no terminal falso dos testes | Ler as setas à mão (códigos de escape) |
| Biblioteca pronta (questionary, prompt_toolkit, simple-term-menu) | Menu pronto | Mais coisa para instalar; a maior é pesada e pode brigar com o readline que o chrono usa para ler o que se digita; visual diferente |

**Escolha:** o menu feito no chrono (minha proposta, aprovada pelo Lucas junto com o desenho).

## Fora do escopo

- Menu no `/modelo` (dá para reaproveitar depois, se o Lucas gostar).
- Busca digitando dentro do menu, rolagem para listas maiores que a tela.

## Não pode acontecer

- O terminal ficar sem eco ou "quebrado" depois do menu (inclusive com Ctrl+C no meio).
- O que se digitou antes de o menu abrir escolher alguma coisa sozinho.
- Os testes abrirem o TextEdit de verdade.

## Depois da revisão

- **Enter no agente atual (●) com uma conversa em andamento não apaga a conversa:** o chrono avisa "Você já está no agente X; a conversa continua" e diz que, para recarregar o arquivo dele, é `/agente X`. Com a conversa vazia, Enter recarrega como antes.
- **O nome do agente novo é digitado num campo do próprio menu** (Enter cria, Esc desiste, Backspace apaga, acentos funcionam). No readline do Mac, o Esc se juntava à tecla seguinte e "Esc + vendas" criava "endas". Desistir mostra "Nenhum agente criado.".
- **Num terminal "dumb"** (onde a rich não desenha ao vivo), `/agente` imprime a lista em vez do menu.
