# chrono com ferramentas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let chrono's model use nine file tools on the Mac through Ollama's native tool calling, asking the user before every change.

**Architecture:** A new module `ferramentas.py` holds the tool definitions (MCP-compatible JSON Schema), path resolution and the implementations; it knows nothing about the screen and receives a `confirmar` callback. `chrono.py` gains a multi-round loop in `Conversa._transmitir` (model asks for tools → run → send results → repeat, max 10 rounds), a `Confirmador` (s/n/t), and two new Exibidor methods for action lines and questions.

**Tech Stack:** system Python 3.9.6, rich 15, stdlib (`subprocess` only for the fixed programs `mdfind` and `sips`), `unittest`, the existing fake Ollama server extended with scripted rounds.

**Spec:** `docs/2026-11-02-chrono-ferramentas-design.md`

## Global Constraints

- Python 3.9 (no `match`, no `X | Y` at runtime; `from __future__ import annotations` if using such hints).
- No new dependency. No tool runs a command chosen by the model; only the fixed programs `mdfind` (Spotlight) and `sips` (image conversion) are called, with argument lists, never a shell.
- Read tools never ask; change tools always ask through `confirmar`; only "s"/"sim" (or "t"/"todas", which also approves the rest of the same question) approve.
- "Apagar" = move to `~/.Trash`; nothing is ever deleted for real.
- Max 10 tool rounds per question; `ler_arquivo` max 20 000 characters; lists and searches max 100 items.
- When stdin is not a terminal, change tools are refused automatically.
- `chrono.py` imports `ferramentas` from its own folder (works through the `~/.local/bin/chrono` symlink because Python resolves it); tests add the project root to `sys.path`.
- All user-facing and model-facing text in Brazilian Portuguese.
- The folder is not a git repo: no commit steps.

## Review Focus

1. Model sends a Portuguese folder name for a path that must be created (`~/Documentos/novo.txt`): the translated existing prefix is used (`~/Documents/novo.txt`) → test in Task 1 (`test_traduz_prefixo_para_caminho_novo`).
2. Model sends `arguments` as a JSON string instead of an object, or an unknown tool name: the model gets a readable error result, no traceback → test in Task 3 (`test_argumentos_em_texto_e_ferramenta_desconhecida`).
3. A tool fails on the Mac (no permission, file vanished): result text tells the model, screen shows a short line, chat continues → test in Task 1 (`test_erro_de_permissao_vira_resultado`).
4. `mover` onto an existing file or `mandar_para_lixeira` with a name already in the Trash: never overwrites → tests in Task 2 (`test_mover_nao_sobrescreve`, `test_lixeira_nome_unico`).
5. Ctrl+C while the confirmation question is on screen: counts as "não", the question ends, echo and terminal state are restored → pty test in Task 4 (`test_ctrl_c_na_confirmacao`).

---

### Task 1: `ferramentas.py` — definitions, paths and read tools

**Files:**
- Create: `ferramentas.py`, `tests/test_ferramentas.py`

**Interfaces:**
- Produces: `Resultado` (dataclass: `texto: str` for the model, `resumo: str` for the screen line, `imagens: list` of base64 strings, default empty, `alterou: bool = False`).
- Produces: `resolver_caminho(caminho: str, base: Path, casa: Path = Path.home()) -> Path` — expands `~`, makes relative paths relative to `base`, then walks the components and replaces a component that doesn't exist by its real name when that one exists: `Documentos→Documents`, `Mesa→Desktop`, `Área de Trabalho→Desktop`, `Imagens→Pictures`, `Músicas→Music`, `Filmes→Movies`.
- Produces: `definicoes(alterar: bool = True) -> list[dict]` in Ollama/MCP format `{"type": "function", "function": {"name", "description", "parameters": {"type": "object", "properties", "required"}}}`; every path parameter description says the real folder names are in English (`~/Documents`, `~/Desktop`, `~/Downloads`, `~/Pictures`).
- Produces: `executar(nome: str, argumentos, confirmar, base: Path) -> Resultado` — `argumentos` may be a dict or a JSON string; unknown name or bad arguments → `Resultado` with an error text, never an exception.
- Produces: `abreviar(caminho: Path) -> str` (home shown as `~`) for screen lines and questions.

- [ ] **Step 1: Write the failing tests** (temp folders as `casa`/`base`)

```python
test_traduz_nome_existente:        resolver_caminho("~/Documentos/a.txt", base, casa) == casa/"Documents"/"a.txt"  (casa/Documents/a.txt exists)
test_traduz_prefixo_para_caminho_novo: resolver_caminho("~/Documentos/novo.txt", ...) == casa/"Documents"/"novo.txt"  (novo.txt doesn't exist)
test_relativo_usa_base:            resolver_caminho("x.txt", base, casa) == base/"x.txt"
test_listar_pasta:                 dirs end with "/", hidden entries skipped, sorted, resumo == "listando ~/…"
test_listar_pasta_limite:          150 files → 100 names + "… e mais 50"
test_ler_arquivo:                  texto contains the content; resumo == "lendo a.txt"
test_ler_arquivo_corta:            30 000 chars → first 20 000 + note "(arquivo cortado: mostrei 20000 de 30000 caracteres)"
test_ler_arquivo_binario:          file with b"\x00" → texto starts with "erro:" and says it's not text
test_erro_de_permissao_vira_resultado: chmod 000 file → texto starts with "erro:", no exception
test_buscar_texto:                 finds "pastilha" in 2 of 3 files, returns "arquivo:linha: trecho", case-insensitive, skips hidden dirs
test_buscar_arquivos:              mock subprocess.run → mdfind called as ["mdfind", "-name", "orc", "-onlyin", pasta]; output lines become the result (max 100)
test_ver_imagem_png:               Resultado.imagens has one base64 string; resumo == "abrindo foto.png"
test_ver_imagem_heic:              mock sips conversion called with an argument list; unsupported extension (.txt) → "erro:"
test_definicoes:                   9 tools; names exactly listar_pasta, ler_arquivo, buscar_arquivos, buscar_texto, ver_imagem, escrever_arquivo, criar_pasta, mover, mandar_para_lixeira; definicoes(alterar=False) has only the first 5
```

- [ ] **Step 2: Run, see them fail, implement, run, see them pass**

Run: `/usr/bin/python3 -m unittest discover -s tests`
Expected: all pass (old 41 + new).

### Task 2: Change tools with confirmation

**Files:**
- Modify: `ferramentas.py`, `tests/test_ferramentas.py`

**Interfaces:**
- Consumes: Task 1.
- Produces: `confirmar(pergunta: str, detalhe: str | None) -> bool` is the callback contract. `LIXEIRA = Path.home() / ".Trash"` is a module constant (tests replace it).
- Questions (exact copy): `Criar o arquivo {c}?`, `Substituir o arquivo {c}? Ele já existe.`, `Criar a pasta {c}?`, `Mover {origem} para {destino}?`, `Mandar {c} para a Lixeira?` (paths through `abreviar`). `escrever_arquivo` passes as `detalhe` the first 10 lines of the content plus `… (+N linhas)` when longer.
- Screen lines: approved → `criado …`, `pasta criada …`, `movido … → …`, `na Lixeira: …` with `alterou=True`; refused → `recusado: …` and the model gets `o usuário recusou: …`.

- [ ] **Step 1: Write the failing tests**

```python
test_escrever_pergunta_e_cria:       confirmar returns True → file has the content; question == "Criar o arquivo ~/…?"
test_escrever_recusado:              confirmar returns False → file not created; texto starts with "o usuário recusou"
test_escrever_avisa_substituir:      existing file → question ends with "Ele já existe."
test_criar_pasta / test_mover_para_pasta (destino is an existing folder → moves inside)
test_mover_nao_sobrescreve:          destino is an existing file → "erro:", origin untouched, confirmar never called
test_lixeira:                        file ends up in LIXEIRA
test_lixeira_nome_unico:             "a.txt" already in LIXEIRA → second one becomes "a 2.txt"
test_leitura_nunca_pergunta:         confirmar that raises AssertionError is passed to all 5 read tools
```

- [ ] **Step 2: Run, fail, implement, run, pass**

### Task 3: Tool loop in the conversation

**Files:**
- Modify: `chrono.py` (`Conversa`, new `Confirmador`, `somar_metricas`), `tests/fake_ollama.py`, `tests/test_chrono.py`

**Interfaces:**
- Consumes: `ferramentas.definicoes`, `ferramentas.executar` (Tasks 1–2).
- Produces: `FakeOllama.rodadas: list` — when not empty, each `/api/chat` call pops the first item: `{"tool_calls": [{"function": {"name", "arguments"}}]}` or `{"respostas": [...]}`; `fake.pedidos` keeps every request body.
- Produces: `Conversa.ferramentas: bool` (default: `"tools" in recursos`); `Confirmador(exibidor)` callable with `.todas`; `somar_metricas(lista: list[dict]) -> dict` (sums `total_duration`, `eval_count`, `eval_duration`; `prompt_eval_count` from the last).
- Produces: Exibidor interface gains `acao(resumo: str, alterou: bool)` and `perguntar(pergunta: str, detalhe: str | None) -> str` (returns what the user typed; `ExibidorSimples.perguntar` returns `""`, and so does any Exibidor when stdin is not a terminal).
- Loop rules: send `tools` only when `conversa.ferramentas`; append the assistant message with its `tool_calls`; for each call append `{"role": "tool", "tool_name": nome, "content": r.texto}` plus `"images"` when present; after 10 rounds with tool calls, call `exibidor.acao("limite de 10 rodadas de ferramenta", False)` and make one last request without `tools`. `fim` gets `somar_metricas` of all rounds and the last round's context.

- [ ] **Step 1: Write the failing tests** (with `Gravador` extended with `acao`/`perguntar`)

```python
test_rodada_de_ferramenta:        rodadas = [tool_calls ler_arquivo(tmp/a.txt), respostas ["Resumo"]] → answer "Resumo"; 2nd request has a "tool" message containing a.txt's text; Gravador saw ("acao", "lendo a.txt", False) before the texts
test_metricas_somadas:            two rounds → fim gets eval_count 128
test_limite_de_rodadas:           11 tool rounds scripted → exactly 10 executed, then a request without "tools", acao "limite de 10 rodadas de ferramenta"
test_argumentos_em_texto_e_ferramenta_desconhecida: arguments as JSON string works; name "formatar_disco" → tool message starts with "erro:"
test_confirmador_t_aprova_o_resto: perguntar answers "t" once → three escrever_arquivo calls, perguntar called once
test_sem_teclado_recusa:          ExibidorSimples → escrever_arquivo refused, file not created
test_ferramentas_desligadas:      conversa.ferramentas = False → request has no "tools"
test_historico_guarda_ferramentas: saved JSON contains the assistant tool_calls and the tool message
```

- [ ] **Step 2: Run, fail, implement, run, pass (old tests too)**

### Task 4: Screen, chat command and header

**Files:**
- Modify: `chrono.py` (`ExibidorRico.acao/perguntar`, `cabecalho`, `abrir`, `comando`, `AJUDA_CHAT`), `tests/test_chrono.py`

**Interfaces:**
- Consumes: Task 3.
- `ExibidorRico.acao`: gray line `◇ {resumo}` (or `◆ {resumo}` when `alterou`), printed above the live area.
- `ExibidorRico.perguntar`: stops the live area (echo back on), prints `detalhe` (if any) in gray with the bar, asks `? {pergunta} (s/n/t) ` in amber `#EF9F27` with `input()`, restarts the spinner, returns the answer; Ctrl+C or EOF there returns `""` (= no).
- Header row: `conversa {…} · raciocínio {…} · ferramentas {ligadas|desligadas|indisponíveis}`.
- `/ferramentas` toggles `conversa.ferramentas` (gray line `Ferramentas ligadas.`/`desligadas.`; `indisponíveis` message when the model can't); `AJUDA_CHAT` gets `  /ferramentas       liga/desliga o acesso aos arquivos do Mac`.

- [ ] **Step 1: Write the failing tests**

```python
test_acao_aparece_em_cinza:        ExibidorRico on a test console → line "◇ lendo a.txt" before "▎ chrono"
test_cabecalho_ferramentas:        "ferramentas ligadas" in the header
test_comando_ferramentas:          comando(conv, "/ferramentas", ...) flips conv.ferramentas
pty test_confirmacao_sim:          fake asks escrever_arquivo(home/x.txt); user types "s" → file exists; screen has "? Criar o arquivo" and "◆ criado"
pty test_confirmacao_nao:          user types "n" → file absent; screen has "◇ recusado"
pty test_ctrl_c_na_confirmacao:    Ctrl+C at the question → file absent, chat prompt returns, typed text after it is echoed
```

- [ ] **Step 2: Run, fail, implement, run, pass**

### Task 5: Real model and final review

- [ ] **Step 1:** `/usr/bin/python3 -m unittest discover -s tests` three times → all OK each time.
- [ ] **Step 2:** In a temp folder with a few files, pty-driven chat with `qwen3.5:9b`: "o que tem nesta pasta?", "resuma o arquivo X", "crie um arquivo resumo.txt com isso" answered "s", "mande Y para a lixeira" answered "n". Check the screen lines, the file, and that nothing outside the temp folder changed.
- [ ] **Step 3:** Open `chrono` in the user's Terminal panel.
