# chrono: menu de agentes com as setas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In the chat, `/agente` opens an arrow-key menu of agents (Enter switches, `e` edits, "+ criar agente novo" creates, Esc cancels).

**Architecture:** A new module `menu.py` holds a generic keyboard menu (key reading in cbreak mode, the menu state, a rich renderable and the `escolher` loop on a transient `Live`); it knows nothing about agents, so `/modelo` can reuse it later. `chrono.py` builds the agent items, calls `menu.escolher` from `comando_agente` when the screen is a real terminal, and dispatches the choice to the same code paths `/agente NOME`, `/agente novo NOME` and `/agente editar NOME` use.

**Tech Stack:** system Python 3.9.6, rich 15, stdlib `termios`/`select`/`os`, `unittest`, the pty harness `TerminalFalso` and the fake Ollama.

**Spec:** `docs/2026-11-05-chrono-menu-agentes-design.md`

## Global Constraints

- No new dependency. Python 3.9 (`Optional[...]`, no `match`).
- All visible text in Brazilian Portuguese; header line exactly `Escolha o agente   ↑↓ escolher · Enter trocar · e editar · Esc sair`; create item exactly `+ criar agente novo`.
- The terminal is always restored (echo, canonical mode) when the menu ends, also on Ctrl+C.
- Keys typed before the menu opens are discarded (`termios.tcflush(fd, TCIFLUSH)`).
- Without a real terminal (`not console.is_terminal or not sys.stdin.isatty()`), `/agente` prints the list exactly as today.
- Tests never open the real TextEdit: pty tests put a fake `open` script first in `PATH`.
- Run tests with `caffeinate -i /usr/bin/python3 -m unittest discover -s tests`. Not a git repo: no commit steps.

## Review Focus

1. Ctrl+C while the menu is open: menu closes, agent unchanged, typing echoes again → Task 2 `test_menu_ctrl_c_restaura_o_terminal`.
2. Enter typed together with `/agente` (typeahead) must not pick an item → Task 2 `test_menu_ignora_o_que_foi_digitado_antes`.
3. An arrow's escape sequence arriving split across reads (`\x1b` then `[B`) is still an arrow, while a lone Esc is Esc → Task 1 `test_seta_em_pedacos` and `test_esc_sozinho`.
4. Narrow terminal (40 columns): every menu line fits, long descriptions are cut with "…" instead of wrapping → Task 1 `test_menu_estreito_nao_quebra_linha`.
5. No agents at all (empty folder): the menu shows only "+ criar agente novo" and creating works → Task 2 `test_menu_sem_agentes_cria`.

---

### Task 1: `menu.py` — keys, state, drawing and the loop

**Files:**
- Create: `menu.py`, `tests/test_menu.py`

**Interfaces:**
- Produces: `ler_tecla(fd: int, espera: float = 0.05) -> str` — reads one key from `fd` (already in cbreak): `"cima"` (`\x1b[A`, `\x1bOA`), `"baixo"` (`\x1b[B`, `\x1bOB`), `"enter"` (`\r`, `\n`), `"esc"` (`\x1b` with nothing else within `espera` seconds, or `\x04` Ctrl+D), any other single printable character as itself lower-cased (`"e"`), `""` for an unknown sequence. Uses `select.select` to wait for the rest of an escape sequence.
- Produces: `@dataclass Item` with `rotulo: str`, `detalhe: str = ""`, `marca: str = " "` (the `●` column), `valor: object = None`, `erro: bool = False` (detail drawn as an error).
- Produces: `class Menu` with `__init__(self, titulo: str, itens: list, posicao: int = 0)`, `mover(self, passo: int) -> None` (wraps around), `item(self) -> Item`, and `__rich__()` — a grid: title line (title in LILAS, the rest in CINZA), then one row per item `"▸"`/`" "`, `marca`, `rotulo` (padded), `detalhe` (CINZA; ERRO red when `erro`); the selected row in LILAS bold; every column `no_wrap=True`, the detail `overflow="ellipsis"`.
- Produces: `escolher(console, menu: Menu, teclas: tuple = ()) -> Optional[Tuple[str, Item]]` — flushes typeahead, puts stdin in cbreak (no ICANON, no ECHO/ECHOCTL, ISIG kept), shows `menu` in a transient `Live` (auto_refresh off), loops on `ler_tecla`: `cima`/`baixo` move and redraw, `enter` → `("enter", item)`, a key in `teclas` → `(tecla, item)`, `esc` or `KeyboardInterrupt` → `None`; restores the saved termios in `finally`.

- [ ] **Step 1: Write the failing tests** (`tests/test_menu.py`; keys through `os.pipe()`, drawing through `Console(file=io.StringIO(), width=..., color_system=None)`)

```python
test_setas_enter_e_letras:      pipe gets b"\x1b[A", b"\x1b[B", b"\x1bOB", b"\r", b"\n", b"E" → "cima", "baixo", "baixo", "enter", "enter", "e" (one ler_tecla call each)
test_esc_sozinho:               b"\x1b" alone → "esc"; b"\x04" → "esc"
test_seta_em_pedacos:           write b"\x1b", then from a thread after 10 ms write b"[B" → "baixo"
test_sequencia_desconhecida:    b"\x1b[5~" → "" (and the next call reads the next key normally)
test_mover_da_volta:            Menu("t", [Item("a"), Item("b"), Item("c")], posicao=0): mover(-1) → item().rotulo == "c"; mover(1) → "a"
test_menu_desenha_a_escolha:    Menu with items geral(marca "●"), atendente, posicao=1 rendered at width 100 → lines: "Escolha…" title, "  ● geral …", "▸   atendente …"
test_menu_estreito_nao_quebra_linha: item with a 150-char detail at width 40 → every line len <= 40, 1 + len(itens) lines, the detail line ends with "…"
```

- [ ] **Step 2: Run to verify they fail**

Run: `/usr/bin/python3 -m unittest discover -s tests -p "test_menu.py" -v`
Expected: ERROR `ModuleNotFoundError: No module named 'menu'`

- [ ] **Step 3: Implement `menu.py`** (colors: import nothing from chrono; define `LILAS`, `CINZA`, `ERRO` locally with the same values chrono uses).

- [ ] **Step 4: Run to verify they pass**

Run: `/usr/bin/python3 -m unittest discover -s tests -p "test_menu.py" -v`
Expected: all OK

---

### Task 2: `/agente` opens the menu

**Files:**
- Modify: `chrono.py` (`comando_agente`, split into helpers)
- Test: `tests/test_chrono.py`

**Interfaces:**
- Consumes: Task 1 `Item`, `Menu`, `escolher`.
- Produces in `chrono.py`:
  - `trocar_agente(conversa, nome: str, console) -> None` — today's `/agente NOME` branch (load, snapshot, `usar_agente`, `abrir`, restore on error).
  - `criar_agente(nome: str) -> None` and `editar_agente(conversa, nome: str) -> None` — today's `novo`/`editar` branches; `ErroAgente` still printed in red by `comando_agente`.
  - `menu_de_agentes(conversa, console) -> None` — items from `agentes.listar(PASTA_AGENTES)`: `Item(nome, descricao or erro, marca="●" if current, valor=nome, erro=descricao starts with "⚠")`, plus `Item("+ criar agente novo", valor=NOVO)`; starts on the current agent (else 0); `escolher(console, menu, teclas=("e",))`:
    - `("enter", agent)` → `trocar_agente`
    - `("e", agent)` → `editar_agente`
    - `("enter", NOVO)` → ask `Nome do agente novo:` with `ler_resposta(prompt_colorido(console, "Nome do agente novo:", LILAS))` (Ctrl+C/Ctrl+D or empty → nothing) then `criar_agente`
    - `("e", NOVO)` → nothing
    - `None` → gray `Continua com o agente {descrever_agente(conversa)}.`
  - `comando_agente`: empty `resto` and `console.is_terminal and sys.stdin.isatty()` → `menu_de_agentes`; otherwise exactly today's behavior.

- [ ] **Step 1: Write the failing tests** (pty: `TerminalFalso([], home, PATH=f"{fake_bin}:{os.environ['PATH']}")` where `fake_bin/open` is a `#!/bin/sh` script appending `"$@"` to a file; send keys with `os.write(t.fd, ...)`; agents are the three ready-made ones, alphabetical: atendente, geral, planilhas)

```python
test_menu_seta_e_enter_troca:        "/agente" → wait "Escolha o agente"; b"\x1b[B" (geral→planilhas); b"\r" → screen shows "planilhas · lê, organiza"; then "/agente" again opens on planilhas (●) — Esc
test_menu_esc_nao_troca:             "/agente", wait, b"\x1b" → "Continua com o agente geral · assistente para qualquer assunto."; header not printed again
test_menu_e_abre_no_textedit:        "/agente", b"\x1b[A" (geral→atendente), b"e" → fake open called with "-e" and the atendente.txt path
test_menu_cria_agente_novo:          "/agente", b"\x1b[A", b"\x1b[A" (→ "+ criar agente novo"), b"\r", wait "Nome do agente novo:", type "vendas" → agentes/vendas.txt exists, fake open got it
test_menu_agente_quebrado_mostra_erro: write agentes/quebrado.txt "modlo: x\n\nz"; menu shows "⚠"; navigate to it, Enter → red message with 'não conheço "modlo"'; then "/agente" opens with ● still on geral
test_menu_ctrl_c_restaura_o_terminal: "/agente", b"\x03" → menu gone, "você ›" again; type "/modelo" → "você › /modelo" visible (echo back)
test_menu_ignora_o_que_foi_digitado_antes: os.write(fd, b"/agente\r\r") in one write → wait "Escolha o agente"; after 0.5 s the agent is still geral (send Esc, screen has "Continua com o agente geral")
test_menu_sem_agentes_cria:          HOME whose agentes folder exists and is empty → "/agente" shows "+ criar agente novo" only; Enter, name "vendas" → vendas.txt created
test_lista_sem_terminal_igual_a_hoje: the existing TestComandoAgente.test_lista_com_agente_quebrado keeps passing (StringIO console → printed list)
```

- [ ] **Step 2: Run to verify they fail**

Run: `caffeinate -i /usr/bin/python3 -m unittest discover -s tests -p "test_chrono.py"`
Expected: the new pty tests FAIL (`não apareceu 'Escolha o agente'`); all others pass

- [ ] **Step 3: Implement** the helpers and the menu branch.

- [ ] **Step 4: Run the whole suite**

Run: `caffeinate -i /usr/bin/python3 -m unittest discover -s tests`
Expected: all OK

---

### Task 3: try it in a real terminal

- [ ] **Step 1:** Drive the real chrono (Ornith) in the pty: `/agente`, ↓, Enter → header of the new agent; `/agente`, Esc; check the screen and that the chat still echoes. Move any test conversation and agent to the Trash afterwards.
