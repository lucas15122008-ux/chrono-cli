"""Agentes do chrono: cada um é um arquivo de texto em ~/.chrono/agentes/.

O arquivo começa com as configurações (uma por linha, "nome: valor") e, depois de uma linha em
branco, vêm as instruções, que viram o prompt de sistema. Linhas que começam com # são
comentários. Este módulo só lê, valida e cria os arquivos: não sabe nada da tela nem do Ollama.
"""
import difflib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from documentos import normalizar

RESERVADOS = ("novo", "editar")

# Nome da configuração sem acento → como aparece nas mensagens.
CONFIGURACOES = {"descricao": "descrição", "modelo": "modelo", "raciocinio": "raciocínio",
                 "ferramentas": "ferramentas"}
LISTA_CONFIGURACOES = "as configurações são: " + ", ".join(CONFIGURACOES.values())
APELIDOS = {"pensar": "raciocinio", "ferramenta": "ferramentas"}  # "pensar" é o nome no config.json

PENSAR = {"ligado": True, "sim": True, "desligado": False, "nao": False}
FERRAMENTAS = {"ligadas": "ligadas", "ligado": "ligadas", "sim": "ligadas",
               "desligadas": "desligadas", "desligado": "desligadas", "nao": "desligadas",
               "so leitura": "leitura", "leitura": "leitura"}
VALORES_VALIDOS = {"raciocinio": "use ligado ou desligado",
                   "ferramentas": "use ligadas, desligadas ou só leitura",
                   "modelo": "escreva o nome de um modelo do Ollama",
                   "descricao": "escreva uma frase dizendo para que serve o agente"}

MODELO_NOVO = """\
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
"""

ATENDENTE = """\
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
"""

PLANILHAS = """\
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
"""


class ErroAgente(Exception):
    pass


@dataclass
class Agente:
    nome: str
    instrucoes: str
    descricao: str = ""
    modelo: Optional[str] = None
    pensar: Optional[bool] = None
    ferramentas: Optional[str] = None  # "ligadas", "desligadas" ou "leitura"; None = o padrão
    arquivo: Optional[Path] = None


def _configuracao(linha):
    """("nome sem acento", "valor") se a linha tem cara de "nome: valor"; senão None."""
    achou = re.match(r"\s*([^:]+?)\s*:\s*(.*?)\s*$", linha)
    if not achou or len(achou.group(1).split()) > 2:
        return None
    chave = normalizar(achou.group(1))
    return APELIDOS.get(chave, chave), achou.group(2)


def _desconhecida(onde, linha, chave):
    """Erro de configuração que não existe, sugerindo a parecida ("modlo" → modelo)."""
    parecidas = difflib.get_close_matches(chave, list(CONFIGURACOES) + list(APELIDOS), n=1, cutoff=0.8)
    sugestao = f" (quis dizer {CONFIGURACOES[APELIDOS.get(parecidas[0], parecidas[0])]}?)" if parecidas else ""
    return ErroAgente(f'{onde}: não conheço "{linha.split(":")[0].strip()}"; {LISTA_CONFIGURACOES}{sugestao}')


def _parece_configuracao(chave, valor):
    """Uma linha das instruções que só pode ser uma configuração perdida depois da linha em branco."""
    if chave == "raciocinio":
        return normalizar(valor) in PENSAR
    if chave == "ferramentas":
        return normalizar(valor) in FERRAMENTAS
    return chave == "modelo" and bool(valor) and " " not in valor


def ler(texto, nome):
    """Lê o texto de um arquivo de agente. Erros viram ErroAgente com a linha e o que vale ali."""
    texto = texto.lstrip("﻿")
    if texto.lstrip().startswith("{\\rtf"):
        raise ErroAgente(f"o agente {nome} foi salvo como texto formatado; no TextEdit, use Formatar › "
                         "Converter em Texto Simples e salve de novo")
    linhas = [(n, linha.rstrip()) for n, linha in enumerate(texto.splitlines(), 1)
              if not linha.lstrip().startswith("#")]
    while linhas and not linhas[0][1].strip():
        del linhas[0]
    tamanho = next((i for i, (_, linha) in enumerate(linhas) if not linha.strip()), len(linhas))
    bloco = linhas[:tamanho]
    conhecidas = [_configuracao(linha) for _, linha in bloco]
    if not any(c and c[0] in CONFIGURACOES for c in conhecidas):
        # Sem configuração certa, o arquivo é todo instrução ("Atenção: ..."), a não ser que o
        # bloco tenha uma configuração escrita errado, que não pode ser ignorada em silêncio.
        for (numero, linha), configuracao in zip(bloco, conhecidas):
            if configuracao and difflib.get_close_matches(configuracao[0], list(CONFIGURACOES), n=1, cutoff=0.8):
                raise _desconhecida(f"linha {numero} do agente {nome}", linha, configuracao[0])
        return Agente(nome=nome, instrucoes=_juntar(linhas, nome))

    agente = Agente(nome=nome, instrucoes="")
    for (numero, linha), configuracao in zip(bloco, conhecidas):
        onde = f"linha {numero} do agente {nome}"
        if configuracao is None:
            raise ErroAgente(f'{onde}: "{linha.strip()}" não é uma configuração; separe as instruções '
                             "das configurações com uma linha em branco")
        chave, valor = configuracao
        if chave not in CONFIGURACOES:
            raise _desconhecida(onde, linha, chave)
        escolhido = {"raciocinio": PENSAR, "ferramentas": FERRAMENTAS}.get(chave)
        if not valor or (escolhido is not None and normalizar(valor) not in escolhido):
            mostrado = f" {valor}" if valor else ""
            raise ErroAgente(f"{onde}: {CONFIGURACOES[chave]}:{mostrado} — {VALORES_VALIDOS[chave]}")
        if chave == "descricao":
            agente.descricao = valor
        elif chave == "modelo":
            agente.modelo = valor
        elif chave == "raciocinio":
            agente.pensar = PENSAR[normalizar(valor)]
        else:
            agente.ferramentas = FERRAMENTAS[normalizar(valor)]
    depois = [(n, linha) for n, linha in linhas[tamanho:] if linha.strip()][:1]
    for numero, linha in depois:
        configuracao = _configuracao(linha)
        if configuracao and _parece_configuracao(*configuracao):
            raise ErroAgente(f"linha {numero} do agente {nome}: as configurações ficam juntas no começo, "
                             "sem linha em branco entre elas")
    agente.instrucoes = _juntar(linhas[tamanho:], nome)
    return agente


def _juntar(linhas, nome):
    instrucoes = "\n".join(linha for _, linha in linhas).strip()
    if not instrucoes:
        raise ErroAgente(f"o agente {nome} não tem instruções: escreva o que ele deve fazer depois das "
                         "configurações, separado por uma linha em branco")
    return instrucoes


def _arquivos(pasta):
    if not pasta.is_dir():
        return []
    return sorted(pasta.glob("*.txt"), key=lambda p: normalizar(p.stem))


def _achar(pasta, nome):
    return next((p for p in _arquivos(pasta) if normalizar(p.stem) == normalizar(nome)), None)


def existe(pasta, nome):
    return _achar(pasta, nome) is not None


def caminho(pasta, nome):
    """O arquivo do agente NOME (maiúsculas e acentos não importam), sem ler o que tem nele."""
    arquivo = _achar(pasta, nome)
    if arquivo is None:
        existentes = [p.stem for p in _arquivos(pasta)]
        if not existentes:
            raise ErroAgente("ainda não há agentes em ~/.chrono/agentes")
        raise ErroAgente(f"não existe o agente {nome}; os agentes são: {', '.join(existentes)}")
    return arquivo


def carregar(pasta, nome):
    """O agente NOME, lido do arquivo NOME.txt da pasta."""
    arquivo = caminho(pasta, nome)
    try:
        texto = arquivo.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise ErroAgente(f"o agente {arquivo.stem} não foi salvo como texto em UTF-8; no TextEdit, "
                         "salve de novo escolhendo a codificação Unicode (UTF-8)")
    except OSError as e:
        raise ErroAgente(f"não consegui ler o agente {arquivo.stem}: {e.strerror or e}")
    agente = ler(texto, arquivo.stem)
    agente.arquivo = arquivo
    return agente


def listar(pasta) -> List[Tuple[str, str]]:
    """(nome, descrição) de cada agente; para um arquivo com erro, a descrição é o erro."""
    lista = []
    for arquivo in _arquivos(pasta):
        try:
            lista.append((arquivo.stem, carregar(pasta, arquivo.stem).descricao))
        except ErroAgente as e:
            lista.append((arquivo.stem, f"⚠ {e}"))
    return lista


def criar_prontos(pasta, sistema):
    """Na primeira vez (pasta ainda não existe), cria os agentes geral, atendente e planilhas."""
    if pasta.exists():
        return False
    pasta.mkdir(parents=True)
    geral = "descrição: assistente para qualquer assunto\n\n" + sistema.strip() + "\n"
    for nome, texto in (("geral", geral), ("atendente", ATENDENTE), ("planilhas", PLANILHAS)):
        (pasta / f"{nome}.txt").write_text(texto, encoding="utf-8")
    return True


def criar_novo(pasta, nome):
    """Cria NOME.txt a partir do modelo comentado. Nunca sobrescreve um agente que já existe."""
    if normalizar(nome) in RESERVADOS:
        raise ErroAgente(f'"{nome}" é um comando; escolha outro nome')
    if not re.fullmatch(r"[\w-]+", nome):
        raise ErroAgente("o nome do agente só pode ter letras, números, - e _ (sem espaços)")
    if _achar(pasta, nome) is not None:
        raise ErroAgente(f"já existe o agente {nome}; para mudar, use /agente editar {nome}")
    arquivo = pasta / f"{nome}.txt"
    try:
        pasta.mkdir(parents=True, exist_ok=True)
        arquivo.write_text(MODELO_NOVO.replace("NOME", nome), encoding="utf-8")
    except OSError as e:
        raise ErroAgente(f"não consegui criar o agente {nome}: {e.strerror or e}")
    return arquivo
