"""Skills do chrono: receitas em ~/.chrono/skills/NOME/SKILL.md que o usuário liga na conversa.

O SKILL.md tem o mesmo formato das skills do Claude: um cabeçalho entre linhas "---" com
"name" e "description" e, depois, as instruções. Este módulo lê, valida, lista e cria as
skills e faz a ferramenta criar_skill da skill-creator; não sabe nada da tela.
"""
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import ferramentas
from documentos import normalizar

LIMITE = 20000
LIMITE_NOME = 64
RESERVADOS = ("desligar", "editar")
ARQUIVO = "SKILL.md"

SKILL_CREATOR = """\
---
name: skill-creator
description: ajuda a criar uma skill nova para o chrono
---

Você está ajudando o usuário a criar uma skill para o chrono. Uma skill é uma receita: o passo a
passo de uma tarefa que se repete. Quando o usuário liga a skill (com /skill nome), estas
instruções vão junto de cada mensagem da conversa.

Siga estes passos, um de cada vez, conversando em português do Brasil:

1. Entenda a tarefa. Faça uma pergunta por vez e espere a resposta: o que a skill deve fazer;
   quando ela vai ser usada; quais são os passos, na ordem; um exemplo do que o usuário costuma
   pedir e do resultado que ele espera; e se ela usa algum arquivo (planilha, PDF, pasta). Não
   pergunte de novo o que o usuário já respondeu.
2. Proponha um nome curto, em minúsculas e com hífens (por exemplo: conferir-pedidos), e uma
   descrição de uma frase dizendo para que serve a skill.
3. Escreva as instruções como passos numerados, curtos e diretos, em português. Em cada passo,
   diga o que fazer e, quando fizer sentido, qual ferramenta do chrono usar: listar_pasta,
   buscar_arquivos, ler_arquivo, buscar_no_arquivo, calcular_na_planilha, criar_planilha,
   mudar_na_planilha, adicionar_linhas ou escrever_arquivo. Diga também como deve ser a resposta
   final (formato e tamanho). O chrono não acessa a internet nem roda programas: não escreva
   passos que dependam disso.
4. Mostre a skill inteira ao usuário (nome, descrição e instruções) e pergunte se ele quer mudar
   alguma coisa. Ajuste o que ele pedir e mostre de novo.
5. Quando ele disser que está bom, chame a ferramenta criar_skill com o nome, a descrição e as
   instruções. O chrono ainda pede a confirmação dele antes de gravar. Depois, diga como usar:
   /skill nome.
"""

DEFINICAO_CRIAR_SKILL = {
    "type": "function",
    "function": {
        "name": "criar_skill",
        "description": ("Salva uma skill nova do chrono em ~/.chrono/skills/NOME/SKILL.md. Use só depois de "
                        "o usuário aprovar o texto da skill. O chrono pede a confirmação dele antes de gravar."),
        "parameters": {
            "type": "object",
            "properties": {
                "nome": {"type": "string",
                         "description": "nome curto, em minúsculas e com hífens, por exemplo conferir-pedidos"},
                "descricao": {"type": "string", "description": "uma frase dizendo para que serve a skill"},
                "instrucoes": {"type": "string", "description": "o passo a passo da skill, em português"},
            },
            "required": ["nome", "descricao", "instrucoes"],
        },
    },
}


class ErroSkill(Exception):
    pass


@dataclass
class Skill:
    nome: str
    instrucoes: str
    descricao: str = ""
    pasta: Optional[Path] = None
    apoio: List[str] = field(default_factory=list)  # os outros arquivos da pasta


def _sem_aspas(valor):
    if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
        return valor[1:-1]
    return valor


def ler(texto, nome):
    """Lê o texto de um SKILL.md. Erros viram ErroSkill em português."""
    texto = texto.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    if len(texto) > LIMITE:
        raise ErroSkill(f"a skill {nome} é grande demais ({len(texto)} caracteres); o limite é {LIMITE}")
    linhas = texto.split("\n")
    inicio = next((i for i, linha in enumerate(linhas) if linha.strip()), len(linhas))
    descricao, corpo = "", linhas
    if inicio < len(linhas) and linhas[inicio].strip() == "---":
        fim = next((i for i in range(inicio + 1, len(linhas)) if linhas[i].strip() == "---"), None)
        if fim is None:
            raise ErroSkill(f"o cabeçalho da skill {nome} começa com --- mas não termina com ---")
        for linha in linhas[inicio + 1:fim]:
            chave, separador, valor = linha.partition(":")
            if separador and chave.strip().lower() == "description":
                descricao = _sem_aspas(valor.strip())
        corpo = linhas[fim + 1:]
    instrucoes = "\n".join(corpo).strip()
    if not instrucoes:
        raise ErroSkill(f"a skill {nome} não tem instruções: escreva o passo a passo depois do cabeçalho")
    return Skill(nome=nome, instrucoes=instrucoes, descricao=descricao)


def _pastas(pasta):
    if not pasta.is_dir():
        return []
    return sorted((p for p in pasta.iterdir() if p.is_dir() and not p.name.startswith(".")),
                  key=lambda p: normalizar(p.name))


def _achar(pasta, nome):
    return next((p for p in _pastas(pasta) if normalizar(p.name) == normalizar(nome)), None)


def existe(pasta, nome):
    return _achar(pasta, nome) is not None


def caminho(pasta, nome):
    """O SKILL.md da skill NOME (maiúsculas e acentos não importam), sem ler o que tem nele."""
    achada = _achar(pasta, nome)
    if achada is None:
        existentes = [p.name for p in _pastas(pasta)]
        if not existentes:
            raise ErroSkill("ainda não há skills em ~/.chrono/skills")
        raise ErroSkill(f"não existe a skill {nome}; as skills são: {', '.join(existentes)}")
    return achada / ARQUIVO


def carregar(pasta, nome):
    arquivo = caminho(pasta, nome)
    nome = arquivo.parent.name
    if not arquivo.is_file():
        raise ErroSkill(f"a skill {nome} não tem o arquivo {ARQUIVO}")
    try:
        texto = arquivo.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise ErroSkill(f"a skill {nome} não foi salva como texto em UTF-8; no TextEdit, salve de novo "
                        "escolhendo a codificação Unicode (UTF-8)")
    except OSError as e:
        raise ErroSkill(f"não consegui ler a skill {nome}: {e.strerror or e}")
    skill = ler(texto, nome)
    skill.pasta = arquivo.parent
    skill.apoio = sorted(p.name for p in arquivo.parent.iterdir()
                         if p.is_file() and p.name != ARQUIVO and not p.name.startswith("."))
    return skill


def listar(pasta) -> List[Tuple[str, str]]:
    """(nome, descrição) de cada skill; para uma com erro, a descrição é o erro."""
    lista = []
    for achada in _pastas(pasta):
        try:
            lista.append((achada.name, carregar(pasta, achada.name).descricao))
        except ErroSkill as e:
            lista.append((achada.name, f"⚠ {e}"))
    return lista


def criar_prontas(pasta):
    """Na primeira vez (a pasta ainda não existe), cria a pasta com a skill-creator."""
    if pasta.exists():
        return False
    (pasta / "skill-creator").mkdir(parents=True)
    (pasta / "skill-creator" / ARQUIVO).write_text(SKILL_CREATOR, encoding="utf-8")
    return True


def texto_para_o_modelo(skill):
    """O bloco que vai junto do prompt de sistema enquanto a skill está ligada."""
    partes = [f"# Skill ligada: {skill.nome}"]
    if skill.descricao:
        partes.append(f"({skill.descricao})")
    partes.append(skill.instrucoes)
    if skill.apoio and skill.pasta:
        partes.append(f"Arquivos de apoio desta skill, em {ferramentas.abreviar(skill.pasta)}: "
                      + ", ".join(skill.apoio))
    return "\n".join(partes)


def _erro(mensagem, resumo):
    return ferramentas.Resultado(texto=f"erro: {mensagem}", resumo=resumo)


def criar_skill(pasta, argumentos, confirmar):
    """A ferramenta da skill-creator: confere, mostra e só grava com a confirmação do usuário."""
    if isinstance(argumentos, str):
        try:
            argumentos = json.loads(argumentos)
        except ValueError:
            argumentos = None
    if not isinstance(argumentos, dict):
        return _erro("não entendi os argumentos da ferramenta", "criar_skill: argumentos inválidos")
    nome, descricao, instrucoes = (str(argumentos.get(chave) or "").strip()
                                   for chave in ("nome", "descricao", "instrucoes"))
    descricao = " ".join(descricao.split())  # numa linha só: uma quebra estragaria o cabeçalho
    if normalizar(nome) in RESERVADOS:
        return _erro(f'"{nome}" é um comando; escolha outro nome', f"criar_skill: nome {nome} reservado")
    if not re.fullmatch(r"[\w-]+", nome):
        return _erro("o nome da skill só pode ter letras, números, - e _ (sem espaços)", "criar_skill: nome inválido")
    if len(nome) > LIMITE_NOME:
        return _erro(f"o nome da skill pode ter no máximo {LIMITE_NOME} caracteres", "criar_skill: nome comprido demais")
    if not descricao:
        return _erro("falta a descrição: uma frase dizendo quando usar a skill", "criar_skill: falta a descrição")
    if not instrucoes:
        return _erro("faltam as instruções da skill", "criar_skill: faltam as instruções")

    conteudo = f"---\nname: {nome}\ndescription: {descricao}\n---\n\n{instrucoes}\n"
    if len(conteudo) > LIMITE:
        return _erro(f"a skill fica grande demais ({len(conteudo)} caracteres); o limite é {LIMITE}: "
                     "deixe as instruções mais curtas", "criar_skill: skill grande demais")
    try:
        achada = _achar(pasta, nome)
        arquivo = (achada or pasta / nome) / ARQUIVO
        substituir = arquivo.exists()
    except OSError as e:
        return _erro(f"não consegui gravar a skill: {e.strerror or e}", f"skill {nome} não criada")
    if substituir:
        aprovado = confirmar(f"Substituir a skill {nome}?", conteudo, sempre_perguntar=True)
    else:
        aprovado = confirmar(f"Criar a skill {nome} em {ferramentas.abreviar(arquivo)}?", conteudo)
    if not aprovado:
        return _erro(f"o usuário não autorizou gravar a skill {nome}; pergunte o que ele quer mudar",
                     f"skill {nome} não criada")
    try:
        if substituir:
            ferramentas.LIXEIRA.mkdir(exist_ok=True)
            destino = ferramentas._nome_livre(ferramentas.LIXEIRA / f"{nome} SKILL (antes de substituir).md")
            shutil.copy2(str(arquivo), str(destino))
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_text(conteudo, encoding="utf-8")
    except OSError as e:
        return _erro(f"não consegui gravar a skill: {e.strerror or e}", f"skill {nome} não criada")
    feito = "substituída" if substituir else "criada"
    return ferramentas.Resultado(texto=f"skill {feito} em {ferramentas.abreviar(arquivo)}; para usar: /skill {nome}",
                                 resumo=f"{feito} a skill {nome}", alterou=True)
