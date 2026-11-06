# chrono com agentes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user pick a customizable agent (instructions + model + reasoning + tools) before talking to chrono, with each agent kept as a plain-text file in `~/.chrono/agentes/`.

**Architecture:** A new module `agentes.py` reads, validates, lists and creates agent files and knows nothing about the screen or Ollama. `chrono.py` gains `Conversa.usar_agente()`, the `-a/--agente` and `--agentes` options, the `/agente` command, an "agente" row in the header and the agent name in saved conversations.

**Tech Stack:** system Python 3.9.6 (`/usr/bin/python3`), rich 15, stdlib (`subprocess` only for the fixed `open -e`), `unittest`, the existing fake Ollama server and pty harness.

**Spec:** `docs/2026-11-04-chrono-agentes-design.md`

## Global Constraints

- Python 3.9: no `match`, no `X | Y` at runtime (use `Optional[...]`).
- No new dependency. The only program chrono runs for this feature is `open -e <file>`, as an argument list, never a shell, never chosen by the model.
- `chrono` with no options must behave exactly like today (same instructions, model, reasoning and tools).
- All user-facing text in Brazilian Portuguese. Agent errors always name the agent, the line (when there is one) and what is valid there; they never surface as a Python traceback.
- Never overwrite an agent file: the three ready-made agents are created only when `~/.chrono/agentes/` does not exist; `/agente novo` refuses an existing name.
- Change tools keep asking for confirmation; a "só leitura" agent is offered only the read tools.
- New test modules import `limpeza` right after the `sys.path` lines (temp folder deleted at the end of the run).
- Run tests with `caffeinate -i /usr/bin/python3 -m unittest discover -s tests` from the project root. The folder is not a git repo: no commit steps.

## Review Focus

1. The user saves an agent in TextEdit as rich text (`{\rtf1…`): clear error telling them to use Formatar › Converter em Texto Simples, no garbage instructions → Task 1 `test_arquivo_rtf_avisa`.
2. File with a UTF-8 BOM or Windows line endings (edited elsewhere): parsed like any other file → Task 1 `test_bom_e_crlf`.
3. File named `Atendente.txt` and the user types `-a atendente` (or `ATENDENTE`): found → Task 1 `test_carregar_ignora_maiusculas`.
4. One broken agent file: `/agente` and `--agentes` still list all agents, marking the broken one with its error → Task 1 `test_listar_mostra_erro_sem_quebrar` and Task 3 `test_lista_com_agente_quebrado`.
5. The default agent (`geral.txt`) has a mistake and the user just types `chrono`: chrono warns in red and opens with the `config.json` settings instead of refusing to start → Task 2 `test_agente_padrao_quebrado_avisa_e_abre`.

---

### Task 1: `agentes.py` — read, validate, list and create agents

**Files:**
- Create: `agentes.py`, `tests/test_agentes.py`

**Interfaces:**
- Produces: `class ErroAgente(Exception)`.
- Produces: `@dataclass Agente` with `nome: str`, `instrucoes: str`, `descricao: str = ""`, `modelo: Optional[str] = None`, `pensar: Optional[bool] = None`, `ferramentas: Optional[str] = None` (`"ligadas" | "desligadas" | "leitura"`), `arquivo: Optional[Path] = None`. `None` means "use the chrono default".
- Produces: `ler(texto: str, nome: str) -> Agente` — parses file text.
- Produces: `carregar(pasta: Path, nome: str) -> Agente` — finds `<nome>.txt` ignoring case and accents (via `documentos.normalizar`), reads it as UTF-8 (`utf-8-sig`), returns `ler(...)` with `arquivo` set.
- Produces: `listar(pasta: Path) -> list[tuple[str, str]]` — `(nome, descrição)` for every `*.txt`, sorted by name; for a broken file the second item is `"⚠ " + str(erro)`; missing folder → `[]`.
- Produces: `criar_prontos(pasta: Path, sistema: str) -> bool` — only when `pasta` does not exist: creates it with `geral.txt`, `atendente.txt`, `planilhas.txt`; returns whether it created them.
- Produces: `criar_novo(pasta: Path, nome: str) -> Path` — validates the name, refuses an existing one, writes the template, returns the path.
- Produces: `RESERVADOS = ("novo", "editar")`.

File rules (the algorithm the tests pin):
1. Lines whose first non-space character is `#` are comments and are ignored everywhere (they keep their line numbers for errors).
2. After skipping leading blank lines, the **first block** is the run of non-blank lines up to the first blank line.
3. A block line is a setting when it matches `nome: valor` and `normalizar(nome)` is one of `descricao`, `modelo`, `raciocinio`, `ferramentas`.
4. No setting in the first block → the whole (comment-free) text is the instructions.
5. At least one setting → every line of the block must be a setting with a non-empty value; the instructions are what comes after the block.
6. Values, compared with `normalizar`: raciocínio `ligado|sim` → `True`, `desligado|nao` → `False`; ferramentas `ligadas|ligado|sim` → `"ligadas"`, `desligadas|desligado|nao` → `"desligadas"`, `so leitura|leitura` → `"leitura"`. `descrição` and `modelo` keep the text as written.
7. Text starting with `{\rtf` → `ErroAgente`. Empty instructions → `ErroAgente`.

Error copy (exact):
- unknown setting: `linha 2 do agente atendente: não conheço "modlo"; as configurações são: descrição, modelo, raciocínio, ferramentas`
- line in a settings block that is not a setting: `linha 3 do agente atendente: "Seja curto." não é uma configuração; separe as instruções das configurações com uma linha em branco`
- bad value: `linha 4 do agente atendente: ferramentas: talvez — use ligadas, desligadas ou só leitura` (raciocínio: `— use ligado ou desligado`; empty value: same message with nothing after the colon)
- no instructions: `o agente atendente não tem instruções: escreva o que ele deve fazer depois das configurações, separado por uma linha em branco`
- rich text: `o agente atendente foi salvo como texto formatado; no TextEdit, use Formatar › Converter em Texto Simples e salve de novo`
- not found: `não existe o agente vendas; os agentes são: atendente, geral, planilhas` (empty folder: `ainda não há agentes em ~/.chrono/agentes`)
- bad name (`criar_novo`): `o nome do agente só pode ter letras, números, - e _ (sem espaços)`; reserved: `"novo" é um comando; escolha outro nome`; existing: `já existe o agente atendente; para mudar, use /agente editar atendente`

Ready-made agents: the exact texts in the spec section "Os três agentes prontos"; `geral.txt` is `"descrição: assistente para qualquer assunto\n\n" + sistema + "\n"`.

Template written by `criar_novo` (exact, `NOME` replaced):
```
# Agente NOME. Linhas que começam com # são comentários: o chrono ignora.
# Configurações (todas opcionais; apague a linha para usar o padrão do chrono):
#   modelo: um modelo do Ollama (veja os instalados com: chrono --modelos)
#   raciocínio: ligado ou desligado
#   ferramentas: ligadas, desligadas ou só leitura
descrição: para que serve este agente, numa frase
raciocínio: desligado
ferramentas: ligadas

Escreva aqui as instruções: quem o agente é, o que ele faz e como deve responder.
Responda sempre em português do Brasil.
```

- [ ] **Step 1: Write the failing tests** (`tests/test_agentes.py`, a temp `pasta` per test)

```python
test_le_configuracoes_e_instrucoes:  ler("descrição: x\nmodelo: m:1\nraciocínio: ligado\nferramentas: só leitura\n\nFaça y.\nE z.", "a")
                                     == Agente(nome="a", descricao="x", modelo="m:1", pensar=True, ferramentas="leitura", instrucoes="Faça y.\nE z.")
test_sem_acento_e_maiusculas:        "Raciocinio: Desligado\nFERRAMENTAS: so leitura\n\nx" → pensar False, ferramentas "leitura"
test_sim_e_nao:                      "raciocínio: sim\nferramentas: não\n\nx" → pensar True, ferramentas "desligadas"
test_sem_configuracoes:              "Atenção: responda curto.\nSempre." → instrucoes == the whole text, every setting None
test_comentarios_ignorados:          template text from criar_novo parsed → descricao "para que serve este agente, numa frase", pensar False, ferramentas "ligadas", no "#" in instrucoes
test_configuracao_desconhecida:      "descrição: x\nmodlo: m\n\ny" → ErroAgente == 'linha 2 do agente a: não conheço "modlo"; as configurações são: descrição, modelo, raciocínio, ferramentas'
test_linha_que_nao_e_configuracao:   "ferramentas: ligadas\nSeja curto.\n\ny" → message with 'linha 2' and '"Seja curto." não é uma configuração'
test_valor_invalido:                 "ferramentas: talvez\n\ny" → 'linha 1 do agente a: ferramentas: talvez — use ligadas, desligadas ou só leitura'
test_sem_instrucoes:                 "descrição: x\n" → the no-instructions message
test_arquivo_rtf_avisa:              "{\\rtf1\\ansi ..." → the rich-text message
test_bom_e_crlf:                     "﻿descrição: x\r\n\r\nFaça y.\r\n" (written to a file, carregar) → descricao "x", instrucoes "Faça y."
test_carregar_ignora_maiusculas:     file Atendente.txt; carregar(pasta, "ATENDENTE").nome == "Atendente"
test_carregar_inexistente:           files a.txt, b.txt; carregar(pasta, "c") → 'não existe o agente c; os agentes são: a, b'
test_listar_mostra_erro_sem_quebrar: a.txt ok, b.txt with "modlo: x\ndescrição: y\n\nz" → [("a", "desc a"), ("b", "⚠ linha 1 do agente b: não conheço ...")]
test_criar_prontos:                  criar_prontos(pasta, "Sistema X.") is True; listar names == ["atendente", "geral", "planilhas"]; carregar geral.instrucoes == "Sistema X."; atendente.ferramentas == "leitura"; planilhas.ferramentas == "ligadas"
test_criar_prontos_nao_sobrescreve:  pasta exists with geral.txt edited → criar_prontos returns False and geral.txt unchanged, no other file created
test_criar_novo:                     path == pasta/"vendas.txt", content == template with NOME=vendas
test_criar_novo_recusa:              existing name → "já existe o agente ..."; "novo" → reserved message; "meu agente" → bad-name message; nothing written
```

- [ ] **Step 2: Run to verify they fail**

Run: `/usr/bin/python3 -m unittest discover -s tests -p "test_agentes.py" -v`
Expected: ERROR, `ModuleNotFoundError: No module named 'agentes'`

- [ ] **Step 3: Implement `agentes.py`** with the interfaces and rules above (names: letters incl. accents, digits, `-`, `_`: `re.fullmatch(r"[\w-]+", nome)`).

- [ ] **Step 4: Run to verify they pass**

Run: `/usr/bin/python3 -m unittest discover -s tests -p "test_agentes.py" -v`
Expected: all OK

---

### Task 2: agents in the conversation, the options and the header

**Files:**
- Modify: `chrono.py` (`PADRAO`, `Conversa`, `_rodada`, `cabecalho`, `abrir`, `main`, `EXEMPLOS`)
- Modify: `tests/fake_ollama.py` (a second working model)
- Test: `tests/test_chrono.py`

**Interfaces:**
- Consumes: Task 1 `Agente`, `ErroAgente`, `carregar`, `listar`, `criar_prontos`.
- Produces: `PASTA_AGENTES = PASTA / "agentes"`; `PADRAO["agente"] = "geral"`.
- Produces: `Conversa.agente: Optional[Agente]` (`None` = the `config.json` defaults) and `Conversa.so_leitura: bool = False`; `_rodada` passes `alterar=self.pode_alterar and not self.so_leitura` to `ferramentas.definicoes`.
- Produces: `Conversa.usar_agente(agente: Optional[Agente], nova_conversa: bool = True) -> None` — calls `trocar_modelo(agente.modelo or config["modelo"])` first (when `nova_conversa`; otherwise keeps `self.modelo` from the saved conversation), so an `ErroIA` leaves everything unchanged; then sets `self.agente`, `pensar` (agent value, else `config["pensar"]`), `ferramentas` (`False` for `"desligadas"`, otherwise what `trocar_modelo` set), `so_leitura` (`ferramentas == "leitura"`), and, when `nova_conversa`, `reiniciar()`.
- Produces: `reiniciar()` uses the agent's `instrucoes` when there is an agent, else `config["sistema"]`.
- Produces: `salvar()` writes `"agente": self.agente.nome if self.agente else None`; `carregar_ultima()` also sets `self.agente_salvo = dados.get("agente")`.
- Produces: `descrever_agente(conversa) -> str` — `"atendente · rascunha respostas para clientes do Mercado Livre"`, `"atendente"` without description, `"geral (padrão do config.json)"` when `agente is None`.
- Produces: `cabecalho(nome, show, ps, conversa, raciocinio, ferramentas, agente="")` — first row `("agente", agente)` when given; `abrir` passes `descrever_agente(conversa)` and shows ferramentas `"só leitura"` when `ferramentas and so_leitura`.
- Produces in `main`: `-a/--agente NOME`, `--agentes` (prints the list like `--modelos`, current default marked `●`); `criar_prontos(PASTA_AGENTES, config["sistema"])` before anything else; `-a` together with `-c` → `ErroIA("Use -a para começar com um agente ou -c para continuar a última conversa, não os dois.")`; `-m`/`-p` applied after the agent; `ErroAgente` caught next to `ErroIA` (exit 1, red message).
- Default agent: `config["agente"]`; missing file → `None`; broken file → red warning `Não usei o agente geral: <erro>` on stderr and `None`. An explicit `-a` with a missing or broken agent is an error (exit 1).
- `-c`: after `carregar_ultima()`, the agent named `agente_salvo or "geral"` is loaded if it exists and parses (otherwise `None`), then `usar_agente(agente, nova_conversa=False)`.
- `fake_ollama.py`: `OUTRO = "leve:4b"` accepted by `/api/show`, `/api/generate` and `/api/chat` like `MODELO`; the fake records the last `/api/chat` body (`self.pedidos` already exists; reuse it).

- [ ] **Step 1: Write the failing tests** (`tests/test_chrono.py`)

```python
# Conversa level (fake Ollama, temp CONVERSAS, as in TestConversa)
test_usar_agente_aplica_tudo:          Agente(modelo=OUTRO, pensar=True, ferramentas="leitura", instrucoes="Seja X.") → conv.modelo == OUTRO, conv.pensar True, conv.so_leitura True, conv.mensagens[0]["content"] == "Seja X."
test_so_leitura_nao_oferece_alteracoes: after the above, one question → tool names sent to the fake include "ler_arquivo" and not "escrever_arquivo"
test_ferramentas_desligadas:           Agente(ferramentas="desligadas") → conv.ferramentas False; no "tools" key in the request body
test_agente_com_modelo_inexistente_nao_troca: Agente(modelo="nao-existe") → ErroIA; conv.modelo, conv.agente and conv.mensagens unchanged
test_conversa_salva_o_agente:          after a question with agent "atendente", the saved JSON has "agente": "atendente"
test_cabecalho_mostra_agente:          cabecalho(..., agente="atendente · rascunha respostas") printed at width 100 contains "agente" and "atendente · rascunha respostas"

# Whole program (rodar / TerminalFalso with preparar_home)
test_primeira_vez_cria_os_agentes:     rodar(["oi"]) → HOME/.chrono/agentes has geral.txt, atendente.txt, planilhas.txt; geral.txt contains the PADRAO "sistema" text
test_chrono_sem_opcao_igual_a_hoje:    rodar(["oi"]) → system message sent == PADRAO["sistema"]; think False; tools present
test_opcao_a_usa_o_agente:             write agentes/curto.txt "modelo: leve:4b\n\nResponda curto."; rodar(["-a", "curto", "oi"]) → request model "leve:4b", system "Responda curto."
test_m_ganha_do_agente:                rodar(["-a", "curto", "-m", MODELO, "oi"]) → request model MODELO
test_agente_inexistente:               rodar(["-a", "vendas", "oi"]) → exit 1, stderr contains "não existe o agente vendas; os agentes são: atendente, geral, planilhas", no "Traceback"
test_agente_padrao_quebrado_avisa_e_abre: geral.txt = "modlo: x\ndescrição: y\n\nz"; rodar(["oi"]) → exit 0, stderr contains "Não usei o agente geral" and 'não conheço "modlo"', system sent == PADRAO["sistema"]
test_a_com_c_e_erro:                   rodar(["-a", "geral", "-c", "oi"]) → exit 1 with the "-a ... ou -c ..." message
test_continuar_volta_com_o_agente:     rodar(["-a", "atendente", "oi"]) then rodar(["-c", "e agora?"]) → second request has the atendente instructions as system message and no "escrever_arquivo" tool
test_listar_agentes:                   rodar(["--agentes"]) → exit 0, stdout has the three names with their descriptions and "●" on geral
test_chat_mostra_agente_no_cabecalho:  TerminalFalso(["-a", "atendente"]) → screen has "agente" and "atendente · rascunha respostas para clientes do Mercado Livre" and "ferramentas só leitura"
```

- [ ] **Step 2: Run to verify they fail**

Run: `caffeinate -i /usr/bin/python3 -m unittest discover -s tests -p "test_chrono.py"`
Expected: the new tests FAIL/ERROR (`usar_agente` / `-a` unknown); the old ones still pass

- [ ] **Step 3: Implement** the interfaces above in `chrono.py` and `OUTRO` in `fake_ollama.py`; add to `EXEMPLOS`:
```
  chrono -a atendente                      abre o chat com o agente atendente
  chrono --agentes                         lista os agentes
```
and change its last lines to say agents live in `~/.chrono/agentes/`.

- [ ] **Step 4: Run the whole suite**

Run: `caffeinate -i /usr/bin/python3 -m unittest discover -s tests`
Expected: all OK (231 old + the new ones)

---

### Task 3: the `/agente` command

**Files:**
- Modify: `chrono.py` (`comando`, `AJUDA_CHAT`, new `abrir_no_textedit`)
- Test: `tests/test_chrono.py`

**Interfaces:**
- Consumes: Task 1 `carregar`, `listar`, `criar_novo`, `ErroAgente`; Task 2 `usar_agente`, `abrir`, `descrever_agente`, `PASTA_AGENTES`.
- Produces: `abrir_no_textedit(caminho: Path) -> None` — `subprocess.run(["open", "-e", str(caminho)], check=False)`; if `open` fails, prints the file path instead.
- Produces in `comando`:
  - `/agente` → `Agente: <descrever_agente>` then the list from `listar`, current agent marked `●`, then the gray line `Trocar: /agente NOME · criar: /agente novo NOME · editar: /agente editar [NOME]`.
  - `/agente NOME` → `carregar`, then snapshot `estado = dict(vars(conversa))`, `usar_agente(agente)`, `abrir(console, conversa)`; on `ErroIA`/`KeyboardInterrupt` restore with `vars(conversa).update(estado)`, print the error (or `[interrompido]`) and `Continua com o agente X.`; on `ErroAgente` print it in red and change nothing.
  - `/agente novo NOME` → `criar_novo`, print `Criei o agente NOME em ~/.chrono/agentes/NOME.txt. Depois de salvar, use /agente NOME.`, then `abrir_no_textedit`.
  - `/agente editar [NOME]` → opens the current agent's file (or NOME's); if the current is `None`, prints `O agente atual vem do config.json; para editar o geral, use /agente editar geral.`; prints `A mudança vale na próxima vez que você usar /agente NOME.`
- `AJUDA_CHAT` gains the line `  /agente [nome]     mostra os agentes ou troca de agente (começa conversa nova)` and `  /agente novo NOME  cria um agente e abre no TextEdit`.

- [ ] **Step 1: Write the failing tests** (`TestComandoAgente`, like `TestComandoModelo`, with `c.PASTA_AGENTES` patched to a temp folder holding the ready-made agents, and `c.abrir_no_textedit` replaced by a recorder)

```python
test_trocar_comeca_conversa_nova:     conv has 3 messages; comando("/agente atendente") → conv.agente.nome == "atendente", len(conv.mensagens) == 1, conv.mensagens[0]["content"] starts with "Você ajuda a JR Auto Peças"
test_trocar_para_o_mesmo_recarrega:   edit atendente.txt instructions on disk; comando("/agente atendente") again → new instructions in conv.mensagens[0]
test_nova_mantem_o_agente:            on "atendente" with 3 messages; comando("/nova") → conv.agente.nome == "atendente", conv.mensagens == [system with the atendente instructions]
test_agente_com_modelo_quebrado_mantem_o_anterior: agent file "modelo: grande:70b\n\nx" (QUEBRADO: show works, loading fails) → comando returns True; conv.agente.nome, conv.modelo and conv.mensagens unchanged; output has "Continua com o agente"
test_ctrl_c_na_troca_volta_ao_anterior: carregar_modelo raises KeyboardInterrupt → same as above
test_agente_quebrado_nao_troca:       comando("/agente quebrado") with a file that has 'modlo' → red message with 'não conheço "modlo"'; conv.agente unchanged
test_lista_com_agente_quebrado:       comando("/agente") output has "● geral", "atendente", "planilhas" with descriptions and the broken one with "⚠"
test_novo_cria_e_abre:                comando("/agente novo vendas") → PASTA_AGENTES/"vendas.txt" exists; recorder got that path; output has "/agente vendas"
test_novo_recusa_existente:           comando("/agente novo atendente") → message "já existe o agente atendente"; recorder not called
test_editar_abre_o_atual:             conv on "planilhas"; comando("/agente editar") → recorder got planilhas.txt; comando("/agente editar atendente") → atendente.txt
test_ajuda_lista_agente:              comando("/ajuda") output contains "/agente [nome]" and "/agente novo NOME"
```

- [ ] **Step 2: Run to verify they fail**

Run: `caffeinate -i /usr/bin/python3 -m unittest discover -s tests -p "test_chrono.py"`
Expected: the `TestComandoAgente` tests FAIL (`Comando desconhecido: /agente`)

- [ ] **Step 3: Implement** the command, `abrir_no_textedit` and the help lines.

- [ ] **Step 4: Run the whole suite**

Run: `caffeinate -i /usr/bin/python3 -m unittest discover -s tests`
Expected: all OK

---

### Task 4: try it with the real model

**Files:** none (manual check with Ollama and `ornith-1.5:9b`)

- [ ] **Step 1:** `chrono --agentes` → the three agents with descriptions; `~/.chrono/agentes/` created with the user's current `sistema` in `geral.txt`.
- [ ] **Step 2:** `chrono -a atendente "Cliente pergunta se o amortecedor dianteiro Cofap serve no Gol G5 2012. O anúncio diz Gol G5 2008 a 2013."` → a short, polite, ready-to-paste answer, no contact data, no emoji.
- [ ] **Step 3:** In the chat (pty driver): `/agente planilhas`, ask the average price of a test spreadsheet → header shows the agent, the model uses `calcular_na_planilha`; `/agente` lists; `/agente novo teste` opens TextEdit (then move `teste.txt` to the Trash).
- [ ] **Step 4:** `chrono "oi"` with no option → same behavior as before (geral).
