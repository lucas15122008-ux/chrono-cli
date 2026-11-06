# chrono com skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user turn on skills (folders with a `SKILL.md`) for the whole conversation with `/skill`, `-s` or an arrow menu, and ship a ready-made skill-creator that writes new skills through a `criar_skill` tool that asks first.

**Architecture:** A new module `skills.py` reads, validates, lists and creates skills and implements the `criar_skill` tool; it knows nothing about the screen. `menu.py` gains a toggle mode (Enter flips ✓ and the menu stays open). `chrono.py` keeps the active skills on `Conversa.skills`, appends one block per skill to the system prompt of each request (not to the history), offers `criar_skill` only while skill-creator is on, and adds the commands, the prompt indicator and save/restore.

**Tech Stack:** system Python 3.9.6, rich 15, stdlib, `unittest`, fake Ollama, pty harness, fake `open` in PATH.

**Spec:** `docs/2026-11-05-chrono-skills-design.md`

## Global Constraints

- No new dependency; Python 3.9. All visible and model-facing text in Brazilian Portuguese.
- Only the user turns skills on; the model never does. A skill's instructions never bypass confirmations; `criar_skill` is a change tool (asks, refused without a keyboard, refused for "só leitura" agents).
- `SKILL.md` limit: 20 000 characters. Reserved names: `desligar`, `editar`. Names: `[\w-]+`, looked up ignoring case and accents (`documentos.normalizar`).
- The skill-creator is created only when `~/.chrono/skills/` does not exist; nothing ever overwrites a skill without `confirmar(..., sempre_perguntar=True)`, and the old `SKILL.md` goes to `ferramentas.LIXEIRA` first.
- Errors never surface as a traceback. Run tests with `caffeinate -i /usr/bin/python3 -m unittest discover -s tests`. Not a git repo: no commits.

## Review Focus

1. A `SKILL.md` copied from a Claude skill (extra keys like `version:`, `argument-hint:`, quoted `description: "..."`) → parsed, extra keys ignored, quotes stripped → Task 1 `test_cabecalho_do_claude`.
2. The model calls `criar_skill` with `arguments` as a JSON string, with a missing field or a bad name → a readable error goes back to the model, no traceback → Task 1 `test_criar_skill_argumentos_ruins`.
3. `/skill Conferir-Pedidos` for folder `conferir-pedidos` → found → Task 1 `test_carregar_ignora_maiusculas`.
4. A skill on in a saved conversation whose folder was deleted → `chrono -c` warns in red and continues without it → Task 3 `test_continuar_skill_sumiu_avisa`.
5. `criar_skill` after the user deleted `~/.chrono/skills/` → creates the folder → Task 1 `test_criar_skill_sem_pasta`.

---

### Task 1: `skills.py`

**Files:** Create `skills.py`, `tests/test_skills.py`

**Interfaces:**
- Produces: `class ErroSkill(Exception)`; `LIMITE = 20000`; `RESERVADOS = ("desligar", "editar")`.
- Produces: `@dataclass Skill(nome: str, instrucoes: str, descricao: str = "", pasta: Optional[Path] = None, apoio: List[str] = [])` (`apoio`: other non-hidden file names in the folder, sorted, without `SKILL.md`).
- Produces: `ler(texto: str, nome: str) -> Skill` — BOM stripped; if the first non-blank line is `---`, the header runs to the next `---` line (missing → error); header lines `chave: valor` with `name`/`description` (case-insensitive) used, surrounding quotes stripped, other keys ignored; body = instructions, stripped, required; over `LIMITE` → error.
- Produces: `carregar(pasta: Path, nome: str) -> Skill` (folder found ignoring case/accents; reads `SKILL.md` as `utf-8-sig`; sets `pasta`, `apoio`); `caminho(pasta, nome) -> Path` (the `SKILL.md` path without parsing); `existe(pasta, nome) -> bool`; `listar(pasta) -> List[Tuple[str, str]]` (`(nome, descrição)` sorted by `normalizar`, `"⚠ " + erro` for broken ones, `[]` for a missing folder); `criar_prontas(pasta: Path) -> bool` (only when `pasta` doesn't exist: creates `skill-creator/SKILL.md` from `SKILL_CREATOR`).
- Produces: `texto_para_o_modelo(skill: Skill) -> str`:
  ```
  # Skill ligada: NOME
  (DESCRIÇÃO)            ← only when there is one
  INSTRUÇÕES
  Arquivos de apoio desta skill, em ~/.chrono/skills/NOME: a.xlsx, b.txt   ← only when apoio
  ```
- Produces: `DEFINICAO_CRIAR_SKILL: dict` (Ollama/MCP format, name `criar_skill`, required `nome`, `descricao`, `instrucoes`) and `criar_skill(pasta: Path, argumentos, confirmar) -> ferramentas.Resultado` — `argumentos` dict or JSON string; validates; content `"---\nname: N\ndescription: D\n---\n\nINSTRUÇÕES\n"`; new → `confirmar(f"Criar a skill {N} em {abreviar(arquivo)}?", conteudo)`; existing → `confirmar(f"Substituir a skill {N}?", conteudo, sempre_perguntar=True)` then old `SKILL.md` copied to `_nome_livre(LIXEIRA / f"{N} SKILL (antes de substituir).md")`; refused → `Resultado("erro: o usuário não autorizou ...", f"skill {N} não criada")`; ok → `Resultado(f"skill criada em ...; para usar: /skill {N}", f"criada a skill {N}", alterou=True)`. Bad input → `Resultado` starting with `"erro:"`, never an exception.
- `SKILL_CREATOR`: the spec's five steps as instructions, with `description: ajuda a criar uma skill nova para o chrono`.

Error copy (exact): `não existe a skill X; as skills são: a, b` · `ainda não há skills em ~/.chrono/skills` · `a skill X não tem o arquivo SKILL.md` · `o cabeçalho da skill X começa com --- mas não termina com ---` · `a skill X não tem instruções: escreva o passo a passo depois do cabeçalho` · `a skill X não foi salva como texto em UTF-8; no TextEdit, salve de novo escolhendo a codificação Unicode (UTF-8)` · `a skill X é grande demais (N caracteres); o limite é 20000` · `o nome da skill só pode ter letras, números, - e _ (sem espaços)` · `"desligar" é um comando; escolha outro nome` · `falta a descrição: uma frase dizendo quando usar a skill` · `faltam as instruções da skill`.

- [ ] **Step 1: Tests** (`tests/test_skills.py`, temp folders; `ferramentas.LIXEIRA` patched)
```python
test_le_cabecalho_e_instrucoes      "---\nname: x\ndescription: faz y\n---\n\n1. passo" → Skill(nome="x", descricao="faz y", instrucoes="1. passo")
test_sem_cabecalho                  "1. passo" → descricao "", instrucoes "1. passo"
test_cabecalho_do_claude            'name: x\ndescription: "Faz y. Use quando z."\nversion: 4.7.0\nargument-hint: "[a]"' header → descricao "Faz y. Use quando z."
test_cabecalho_sem_fim              "---\nname: x\n1. passo" → the "não termina com ---" error
test_sem_instrucoes / test_grande_demais (20001 chars) / test_bom_e_crlf
test_carregar_ignora_maiusculas     folder conferir-pedidos; carregar(p, "Conferir-Pedidos").nome == "conferir-pedidos"; apoio == ["modelo.xlsx"]
test_carregar_inexistente / test_pasta_sem_skill_md / test_listar_mostra_erro / test_listar_pasta_que_nao_existe
test_criar_prontas / test_criar_prontas_nao_sobrescreve
test_texto_para_o_modelo            exact block above, with and without descricao/apoio
test_criar_skill_nova               confirmar answers yes → file content exact; question "Criar a skill vendas em …/vendas/SKILL.md?"; detail == content; Resultado.alterou
test_criar_skill_recusada           confirmar no → nothing written; texto starts with "erro:"
test_substituir_pergunta_sempre_e_guarda_a_antiga  existing skill → question "Substituir a skill vendas?" with sempre_perguntar=True; old content in LIXEIRA "vendas SKILL (antes de substituir).md"
test_criar_skill_argumentos_ruins   JSON string args work; missing descricao → "erro: falta a descrição…"; name "a b" → "erro: o nome…"; "editar" → reserved; nothing written
test_criar_skill_sem_pasta          pasta doesn't exist → created
```
- [ ] **Step 2:** `/usr/bin/python3 -m unittest discover -s tests -p "test_skills.py"` → ERROR `No module named 'skills'`
- [ ] **Step 3:** implement `skills.py`.
- [ ] **Step 4:** same command → all OK.

---

### Task 2: toggle mode in `menu.py`

**Files:** Modify `menu.py`; Test `tests/test_menu.py`

**Interfaces:**
- Produces: `escolher(console, menu, teclas=(), alternar=None)` — when `alternar` (a function `Item -> bool`) is given, Enter calls it: `True` closes and returns `("enter", item)`, `False` redraws and keeps the menu open. Without `alternar`, unchanged.

- [ ] **Step 1: Test** (in the pty child of `TestTerminalVolta`, add a second script variant): menu with items a, b; keys `\r`, `\x1b[B`, `\r`, `\x1b`; `alternar` flips `item.marca` between " " and "✓" and returns False → child prints the marks `["✓", "✓"]` and result `None`; a variant whose `alternar` returns True for "b" → result `('enter', 'b')`.
- [ ] **Step 2:** run `test_menu.py` → FAIL (`unexpected keyword argument 'alternar'`)
- [ ] **Step 3:** implement; **Step 4:** `test_menu.py` → OK.

---

### Task 3: skills in chrono

**Files:** Modify `chrono.py`; Test `tests/test_chrono.py`

**Interfaces:**
- Consumes: Task 1 (`carregar`, `caminho`, `listar`, `criar_prontas`, `texto_para_o_modelo`, `DEFINICAO_CRIAR_SKILL`, `criar_skill`, `ErroSkill`), Task 2 (`alternar`).
- Produces: `PASTA_SKILLS = PASTA / "skills"`; `Conversa.skills: list` (reset in `reiniciar`), `Conversa.skills_salvas: list` (from `carregar_ultima`), `ligar_skill(skill) -> bool` (True if it replaced one with the same name = reloaded), `desligar_skill(nome) -> bool`, `_criador_ligado() -> bool` (skill-creator on).
- `_rodada`: system content = agent instructions + tools notice (when tools) + `"\n\n" + texto_para_o_modelo(s)` for each active skill; when `com_ferramentas and _criador_ligado() and pode_alterar and not so_leitura`, append `DEFINICAO_CRIAR_SKILL` to the tools; `_usar_ferramenta`: name `criar_skill` while offered → `skills.criar_skill(PASTA_SKILLS, args, confirmar)`.
- `salvar`: `"skills": [s.nome for s in self.skills]`.
- `comando_skill(conversa, resto, console)`: `""` → `menu_de_skills` with a real terminal (same test as `/agente`), else the list (`✓` for active) and `Use: /skill NOME · desligar: /skill desligar [NOME] · editar: /skill editar NOME`; `desligar [NOME]`; `editar NOME`; `NOME` → `Skill X ligada.` / `Skill X recarregada.`, plus, for skill-creator without usable change tools: `A skill-creator precisa das ferramentas ligadas para salvar a skill; com este agente ela só consegue escrever o texto para você copiar.`; `ErroSkill` in red (capitalized).
- `menu_de_skills`: title `Skills   ↑↓ escolher · Enter liga/desliga · e editar · Esc sair`, items with marca `✓`, `+ criar skill nova` (turns skill-creator on and closes, then prints `A skill-creator está ligada: diga que skill você quer criar.`); on Esc prints `Skills ligadas: a, b` or `Nenhuma skill ligada.`.
- `/nova` and a successful agent switch print `Skills desligadas.` when skills were on.
- Prompt: `você · a, b ›` (rebuilt each loop in `chat`).
- `main`: `criar_prontas(PASTA_SKILLS)` (OSError ignored); `-s/--skill NOME` (append; missing/broken → exit 1 with the error); `--skills` prints the list; `-c` re-loads `skills_salvas` (missing/broken → red `Não liguei a skill X: <erro>`).
- `AJUDA_CHAT`: `/skill [nome]`, `/skill desligar [nome]`, `/skill editar NOME`; `EXEMPLOS`: `chrono -s conferir-pedidos "…"`, `chrono --skills`.

- [ ] **Step 1: Tests**
```python
# Conversa level
test_skill_vai_no_prompt_e_nao_no_historico   ligar_skill(x) → request system ends with texto_para_o_modelo(x); conv.mensagens[0] unchanged
test_criar_skill_so_com_a_skill_creator       without it: no "criar_skill" in tools; with it: present; with so_leitura: absent
test_criar_skill_pelo_modelo                  fake round calls criar_skill; Gravador answers "s" → SKILL.md written in a patched PASTA_SKILLS
test_nova_desliga_as_skills                   /nova → skills == [], output "Skills desligadas."
test_trocar_agente_desliga_as_skills
test_conversa_salva_as_skills
# Commands (StringIO console)
test_skill_liga_e_recarrega / test_skill_desligar / test_skill_inexistente / test_skill_editar_abre / test_lista_de_skills
test_skill_creator_sem_ferramentas_avisa       agent "desligadas" → warning text
# Program / pty
test_primeira_vez_cria_a_skill_creator         rodar(["oi"]) → skills/skill-creator/SKILL.md exists
test_opcao_s_liga_a_skill                      rodar(["-s", "x", "oi"]) → system contains "# Skill ligada: x"
test_opcao_s_inexistente                       exit 1, "Não existe a skill …"
test_continuar_volta_com_as_skills / test_continuar_skill_sumiu_avisa
test_listar_skills                             rodar(["--skills"])
test_prompt_mostra_as_skills                   pty: "/skill x" → "você · x ›"
test_menu_de_skills_liga_varias                pty: "/skill", Enter, ↓, Enter, Esc → "Skills ligadas: a, b"
test_menu_de_skills_criar_liga_o_criador       pty: navigate to "+ criar skill nova", Enter → "A skill-creator está ligada"
```
- [ ] **Step 2:** run the suite → the new tests FAIL.
- [ ] **Step 3:** implement; **Step 4:** whole suite → OK.

---

### Task 4: real check

- [ ] With Ornith in the pty: `/skill skill-creator`, ask for a small skill, answer its questions, approve the save with "s" → `~/.chrono/skills/NOME/SKILL.md` exists and is valid; `/skill NOME` and one question that uses it. Move the test skill and test conversations to the Trash afterwards.
