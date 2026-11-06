"""Ferramentas do chrono: o que o modelo pode fazer com os arquivos do Mac.

Cada ferramenta tem nome, descrição e parâmetros no formato do Ollama, que é o mesmo do MCP.
As de leitura nunca perguntam; as que alteram chamam confirmar() antes e só agem com um sim.
Nenhuma roda comando escolhido pelo modelo: só os programas fixos mdfind (busca do Spotlight)
e sips (conversão de imagens), sempre com a lista de argumentos montada aqui.
"""
import base64
import codecs
import errno
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import documentos
import planilhas

CASA = Path.home().resolve()  # resolvida, como os caminhos que resolver_caminho devolve
LIXEIRA = CASA / ".Trash"

MAX_CARACTERES = 20000
LIMITE_LEITURA = MAX_CARACTERES * 4  # bytes lidos de um arquivo, no máximo
MAX_ITENS = 100
MAX_IMAGEM = 5_000_000  # imagens maiores são reduzidas pelo sips antes de ir para o modelo

# O Finder mostra os nomes traduzidos, mas no disco as pastas têm o nome em inglês.
TRADUCOES = {
    "Documentos": "Documents",
    "Mesa": "Desktop",
    "Área de Trabalho": "Desktop",
    "Imagens": "Pictures",
    "Músicas": "Music",
    "Filmes": "Movies",
}
AJUDA_CAMINHO = ("Caminho no Mac. As pastas do usuário têm o nome em inglês: ~/Documents (Documentos), "
                 "~/Desktop (Mesa), ~/Downloads, ~/Pictures (Imagens).")

IMAGENS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
CONVERTER = {".heic", ".heif", ".tif", ".tiff"}  # o modelo não lê esses: o sips converte para jpg
# PDF, Word e planilhas são lidos pelo documentos.py; estes ainda não.
NAO_LE = {".pptx": "do PowerPoint", ".ppt": "do PowerPoint", ".numbers": "do Numbers", ".pages": "do Pages",
          ".key": "do Keynote", ".zip": "compactado"}
MAX_DOCUMENTO_NA_BUSCA = 5_000_000  # na busca por pasta, documentos maiores são pulados (demoram a abrir)
MAX_TEXTO_POR_LINHAS = 20_000_000  # ler a partir de uma linha carrega o arquivo inteiro


# Erros do sistema em português, para o modelo (e o usuário) entenderem.
ERROS_DO_SISTEMA = {
    errno.ENOENT: "não existe",
    errno.EEXIST: "já existe",
    errno.ENOTDIR: "não é uma pasta",
    errno.EISDIR: "é uma pasta",
    errno.ENOTEMPTY: "não está vazia",
    errno.ENOSPC: "não coube: o disco está cheio",
    errno.EBUSY: "está em uso",
    errno.ENAMETOOLONG: "tem um nome longo demais",
    errno.EROFS: "está num disco que só deixa ler",
    errno.EXDEV: "está em outro disco",
}


@dataclass
class Resultado:
    texto: str  # vai para o modelo
    resumo: str  # vira a linha cinza na tela
    imagens: list = field(default_factory=list)
    alterou: bool = False


class Erro(Exception):
    """Problema que vira resultado para o modelo, com uma linha curta para a tela."""

    def __init__(self, texto, resumo):
        super().__init__(texto)
        self.resumo = resumo


def abreviar(caminho):
    """Caminho para mostrar, com a pasta do usuário como ~."""
    caminho = Path(caminho)
    if caminho == CASA:
        return "~"
    try:
        return "~/" + str(caminho.relative_to(CASA))
    except ValueError:
        return str(caminho)


def resolver_caminho(caminho, base):
    """Caminho de verdade para o que o modelo pediu: ~ é a pasta do usuário, relativo parte de base.

    Uma pasta com nome traduzido que não existe (Documentos) vira a de nome real (Documents),
    se essa existir; assim funciona até para arquivos que ainda vão ser criados. "." e ".." são
    resolvidos de verdade: "~/Documents/Clientes/.." é ~/Documents, nunca um item chamado "..".
    O último nome não é seguido se for um atalho, para quem chama decidir o que fazer com ele.
    """
    texto = str(caminho).strip()
    if texto == "~" or texto.startswith("~/"):
        bruto = CASA / texto[2:]
    else:
        bruto = Path(texto)
        if not bruto.is_absolute():
            bruto = Path(base) / bruto
    atual = Path(bruto.parts[0])
    for parte in bruto.parts[1:]:
        candidato = atual / parte
        real = TRADUCOES.get(parte)
        if real and not candidato.exists() and (atual / real).exists():
            candidato = atual / real
        atual = candidato
    if atual.name in ("", ".", ".."):
        return atual.resolve()
    return atual.parent.resolve() / atual.name


def _existente(caminho, base):
    alvo = resolver_caminho(caminho, base)
    if not alvo.exists():
        raise Erro(f"{abreviar(alvo)} não existe.", f"não achei {alvo.name or abreviar(alvo)}")
    return alvo


def _arquivo_comum(alvo):
    """Recusa pastas e arquivos especiais (como /dev/zero ou canos), que travariam a leitura."""
    if alvo.is_dir():
        raise Erro(f"{abreviar(alvo)} é uma pasta; use listar_pasta.", f"{alvo.name} é uma pasta")
    if not stat.S_ISREG(alvo.stat().st_mode):
        raise Erro(f"{abreviar(alvo)} não é um arquivo comum.", f"{alvo.name} não é um arquivo comum")


def _limitar(itens, total=None):
    total = len(itens) if total is None else total
    if total > MAX_ITENS:
        itens = itens[:MAX_ITENS] + [f"… e mais {total - MAX_ITENS}"]
    return "\n".join(itens)


def fmt_tamanho(n_bytes):
    if n_bytes < 1000:
        return f"{n_bytes} B"
    if n_bytes < 1_000_000:
        return f"{round(n_bytes / 1000)} KB"
    if n_bytes < 1_000_000_000:
        return f"{n_bytes / 1e6:.1f} MB".replace(".", ",")
    return f"{n_bytes / 1e9:.1f} GB".replace(".", ",")


def _detalhes(caminho):
    """"(2 KB · 30/10 10:11)", "(30/10 10:11)" para pastas, ou None se não der para ver."""
    try:
        info = caminho.stat()
    except (OSError, ValueError):
        return None
    quando = datetime.fromtimestamp(info.st_mtime).strftime("%d/%m %H:%M")
    if stat.S_ISDIR(info.st_mode):
        return f"({quando})"
    return f"({fmt_tamanho(info.st_size)} · {quando})"


def _data(caminho):
    try:
        return caminho.stat().st_mtime
    except (OSError, ValueError):
        return 0


def _decodificar(dados):
    """Texto do arquivo, ou None se não for texto. Tenta UTF-8, UTF-16 (com BOM) e o cp1252 do Windows."""
    if dados.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return dados.decode("utf-16", errors="replace")
    if b"\x00" in dados[:8192]:
        return None
    try:
        return dados.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        if e.start >= len(dados) - 3:  # só a última letra foi cortada pelo limite de leitura
            return dados[:e.start].decode("utf-8-sig", errors="replace")
        return dados.decode("cp1252", errors="replace")


# Ferramentas de leitura: nunca perguntam.

def listar_pasta(caminho, base, confirmar, ordem="nome"):
    pasta = _existente(caminho, base)
    if not pasta.is_dir():
        raise Erro(f"{abreviar(pasta)} não é uma pasta.", f"{pasta.name} não é uma pasta")
    entradas = [e for e in pasta.iterdir() if not e.name.startswith(".")]
    if ordem == "data":
        entradas.sort(key=_data, reverse=True)
    else:
        entradas.sort(key=lambda e: e.name.lower())
    itens = []
    for entrada in entradas[:MAX_ITENS]:
        nome = entrada.name + ("/" if entrada.is_dir() else "")
        detalhes = _detalhes(entrada)
        itens.append(f"{nome}  {detalhes}" if detalhes else nome)
    return Resultado(_limitar(itens, len(entradas)) or "(pasta vazia)", f"listando {abreviar(pasta)}")


def _numero(valor, nome):
    """Número de página ou linha vindo do modelo ("4", 4 ou "página 4"); sem valor, 1."""
    if valor is None:
        return 1
    achado = re.search(r"\d+", str(valor))
    if not achado or int(achado.group()) < 1:
        raise Erro(f'{nome} precisa ser um número (por exemplo "3").', f"{nome} inválido")
    return int(achado.group())


def _recusar_formato(arquivo):
    tipo = NAO_LE.get(arquivo.suffix.lower())
    if tipo:
        raise Erro(f"{arquivo.name} é um arquivo {tipo}, e eu ainda não leio esse formato.",
                   f"{arquivo.name}: formato que ainda não leio")


def _texto_inteiro(arquivo):
    if arquivo.stat().st_size > MAX_TEXTO_POR_LINHAS:
        raise Erro(f"{arquivo.name} é grande demais ({fmt_tamanho(arquivo.stat().st_size)}) para ler por linhas.",
                   f"{arquivo.name} é grande demais")
    texto = _decodificar(arquivo.read_bytes())
    if texto is None:
        raise Erro(f"{abreviar(arquivo)} não é um arquivo de texto.", f"{arquivo.name} não é texto")
    return texto


def ler_arquivo(caminho, base, confirmar, a_partir_de=None, aba=None):
    arquivo = _existente(caminho, base)
    _arquivo_comum(arquivo)
    inicio = _numero(a_partir_de, "a_partir_de")
    tipo_documento = documentos.tipo(arquivo)
    if tipo_documento == "pdf":
        return Resultado(documentos.ler_pdf(arquivo, inicio, MAX_CARACTERES), f"lendo {arquivo.name}")
    if tipo_documento == "planilha":
        # Sem a_partir_de, a planilha abre num resumo; com ele, numa página de linhas.
        pagina = None if a_partir_de is None else inicio
        return Resultado(documentos.ler_planilha(arquivo, aba, pagina, MAX_CARACTERES), f"lendo {arquivo.name}")
    if tipo_documento == "word":
        return Resultado(documentos.ler_word(arquivo, MAX_CARACTERES), f"lendo {arquivo.name}")
    _recusar_formato(arquivo)
    if inicio > 1:
        return Resultado(_ler_a_partir_da_linha(arquivo, inicio), f"lendo {arquivo.name}")
    tamanho = arquivo.stat().st_size
    with arquivo.open("rb") as entrada:
        dados = entrada.read(LIMITE_LEITURA)
    texto = _decodificar(dados)
    if texto is None:
        raise Erro(f"{abreviar(arquivo)} não é um arquivo de texto.", f"{arquivo.name} não é texto")
    if tamanho > LIMITE_LEITURA:
        texto = (texto[:MAX_CARACTERES] + f"\n(arquivo cortado: mostrei {MAX_CARACTERES} caracteres "
                 f"de um arquivo de {fmt_tamanho(tamanho)})")
    elif len(texto) > MAX_CARACTERES:
        texto = (texto[:MAX_CARACTERES]
                 + f"\n(arquivo cortado: mostrei {MAX_CARACTERES} de {len(texto)} caracteres)")
    return Resultado(texto, f"lendo {arquivo.name}")


def _ler_a_partir_da_linha(arquivo, inicio):
    linhas = _texto_inteiro(arquivo).splitlines()
    if inicio > len(linhas):
        raise Erro(f"o arquivo tem só {len(linhas)} linhas.", f"{arquivo.name} tem só {len(linhas)} linhas")
    partes, tamanho, ultima = [], 0, inicio - 1
    for numero in range(inicio, len(linhas) + 1):
        linha = linhas[numero - 1]
        if partes and tamanho + len(linha) + 1 > MAX_CARACTERES:
            break
        partes.append(linha[:MAX_CARACTERES])
        tamanho += len(linha) + 1
        ultima = numero
    texto = f"(a partir da linha {inicio})\n" + "\n".join(partes)
    if ultima < len(linhas):
        texto += f"\n(mostrei as linhas {inicio} a {ultima} de {len(linhas)}; para continuar, use a_partir_de={ultima + 1})"
    return texto


def buscar_no_arquivo(caminho, texto, base, confirmar):
    arquivo = _existente(caminho, base)
    _arquivo_comum(arquivo)
    if documentos.tipo(arquivo):
        achados = documentos.buscar(arquivo, texto)
    else:
        _recusar_formato(arquivo)
        procurado = documentos.normalizar(texto)
        achados = [f"linha {numero}: {linha.strip()[:200]}"
                   for numero, linha in enumerate(_texto_inteiro(arquivo).splitlines(), 1)
                   if procurado in documentos.normalizar(linha)]
    return Resultado(_limitar(achados) or "nada encontrado", f'procurando "{texto}" em {arquivo.name}')


def buscar_arquivos(nome, base, confirmar, pasta=None):
    comando = ["mdfind", "-name", nome]
    if pasta:
        comando += ["-onlyin", str(_existente(pasta, base))]
    try:
        saida = subprocess.run(comando, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        raise Erro("a busca do Spotlight demorou demais.", f'busca por "{nome}" demorou demais')
    achados = [Path(linha) for linha in saida.stdout.splitlines() if linha.strip()]
    achados.sort(key=_data, reverse=True)  # os mais novos primeiro: ajuda a achar "o último"
    itens = []
    for caminho in achados[:MAX_ITENS]:
        detalhes = _detalhes(caminho)
        itens.append(f"{caminho}  {detalhes}" if detalhes else str(caminho))
    return Resultado(_limitar(itens, len(achados)) or "nenhum arquivo encontrado", f'procurando arquivos "{nome}"')


def buscar_texto(texto, pasta, base, confirmar):
    raiz = _existente(pasta, base)
    procurado = documentos.normalizar(texto)
    achados = []
    for atual, pastas, arquivos in os.walk(raiz):
        pastas[:] = sorted(p for p in pastas if not p.startswith("."))
        for nome in sorted(arquivos):
            caminho = Path(atual) / nome
            if nome.startswith(".") or caminho.suffix.lower() in NAO_LE:
                continue
            try:
                info = caminho.stat()
                if not stat.S_ISREG(info.st_mode):
                    continue  # canos e arquivos especiais travariam
                if documentos.tipo(caminho):
                    if info.st_size <= MAX_DOCUMENTO_NA_BUSCA:
                        # Sem ler páginas escaneadas: demoraria segundos por página.
                        achados += [f"{caminho.relative_to(raiz)}: {achado}"
                                    for achado in documentos.buscar(caminho, texto, imagens=False)
                                    if not achado.startswith("aba ")]
                    continue
                if info.st_size > 2_000_000:
                    continue  # muito grandes demoram
                conteudo = _decodificar(caminho.read_bytes())
            except (OSError, documentos.ErroDocumento):
                continue
            if conteudo is None:
                continue
            for numero, linha in enumerate(conteudo.splitlines(), 1):
                if procurado in documentos.normalizar(linha):
                    achados.append(f"{caminho.relative_to(raiz)}:{numero}: {linha.strip()[:200]}")
        if len(achados) > MAX_ITENS * 5:  # já tem bem mais do que vai ser mostrado
            break
    return Resultado(_limitar(achados) or "nada encontrado", f'procurando "{texto}" em {abreviar(raiz)}')


def ver_imagem(caminho, base, confirmar):
    arquivo = _existente(caminho, base)
    _arquivo_comum(arquivo)
    extensao = arquivo.suffix.lower()
    if extensao not in IMAGENS | CONVERTER:
        raise Erro(f"{arquivo.name} não é uma imagem que eu consiga abrir (jpg, png, gif, webp, heic).",
                   f"{arquivo.name} não é imagem")
    if extensao in CONVERTER or arquivo.stat().st_size > MAX_IMAGEM:
        dados = _converter_para_jpeg(arquivo)
    else:
        dados = arquivo.read_bytes()
    return Resultado(f"imagem {arquivo.name} aberta; ela vem junto desta mensagem.", f"abrindo {arquivo.name}",
                     imagens=[base64.b64encode(dados).decode()])


def _converter_para_jpeg(arquivo):
    """jpg de no máximo 1600 px, feito pelo sips."""
    with tempfile.TemporaryDirectory() as pasta:
        destino = Path(pasta) / "imagem.jpg"
        try:
            subprocess.run(["sips", "-s", "format", "jpeg", "-Z", "1600", str(arquivo), "--out", str(destino)],
                           capture_output=True, timeout=60)
        except subprocess.TimeoutExpired:
            raise Erro(f"converter {arquivo.name} demorou demais.", f"não consegui abrir {arquivo.name}")
        if not destino.exists():
            raise Erro(f"não consegui converter {arquivo.name} para jpg.", f"não consegui abrir {arquivo.name}")
        return destino.read_bytes()


# Ferramentas que alteram: sempre perguntam antes, e nunca sobrescrevem nem apagam de vez.

def _recusado(acao):
    return Resultado(f"o usuário recusou: {acao}. Não tente de novo sem ele pedir.", f"recusado: {acao}")


def _previa(conteudo):
    """As 10 primeiras linhas, cada uma com até 200 caracteres (uma linha enorme não enche a tela)."""
    linhas = conteudo.splitlines()
    previa = "\n".join(linha if len(linha) <= 200 else linha[:200] + "…" for linha in linhas[:10])
    return previa + (f"\n… (+{len(linhas) - 10} linhas)" if len(linhas) > 10 else "")


def _pasta_existe(alvo):
    if not alvo.parent.is_dir():
        raise Erro(f"a pasta {abreviar(alvo.parent)} não existe; crie com criar_pasta antes.",
                   f"não achei a pasta {alvo.parent.name}")


def _nome_livre(alvo):
    """alvo, ou "nome 2.ext", "nome 3.ext"... se já existir (como o Finder faz na Lixeira)."""
    numero = 2
    livre = alvo
    while livre.exists():
        livre = alvo.with_name(f"{alvo.stem} {numero}{alvo.suffix}")
        numero += 1
    return livre


def escrever_arquivo(caminho, conteudo, base, confirmar):
    atalho = resolver_caminho(caminho, base)
    # Por um atalho, quem é escrito é o arquivo de destino: é ele que a pergunta precisa mostrar.
    arquivo = atalho.resolve() if atalho.is_symlink() else atalho
    if arquivo.is_dir():
        raise Erro(f"{abreviar(arquivo)} é uma pasta.", f"{arquivo.name} é uma pasta")
    _pasta_existe(arquivo)
    existe = arquivo.exists()
    nome = abreviar(arquivo) + (f" (pelo atalho {abreviar(atalho)})" if arquivo != atalho else "")
    pergunta = f"Substituir o arquivo {nome}? Ele já existe." if existe else f"Criar o arquivo {nome}?"
    # Substituir apaga o conteúdo antigo de vez, então pergunta mesmo depois de um "t" (todas).
    if not confirmar(pergunta, _previa(conteudo), sempre_perguntar=existe):
        return _recusado(f"escrever {abreviar(arquivo)}")
    arquivo.write_text(conteudo, encoding="utf-8")
    feito = "substituído" if existe else "criado"
    return Resultado(f"arquivo {abreviar(arquivo)} {feito}.", f"{feito} {abreviar(arquivo)}", alterou=True)


def criar_pasta(caminho, base, confirmar):
    pasta = resolver_caminho(caminho, base)
    if pasta.exists():
        raise Erro(f"{abreviar(pasta)} já existe.", f"{pasta.name} já existe")
    if not confirmar(f"Criar a pasta {abreviar(pasta)}?", None):
        return _recusado(f"criar a pasta {abreviar(pasta)}")
    pasta.mkdir(parents=True)
    return Resultado(f"pasta {abreviar(pasta)} criada.", f"pasta criada {abreviar(pasta)}", alterou=True)


def mover(origem, destino, base, confirmar):
    de = _existente(origem, base)
    para = resolver_caminho(destino, base)
    # No disco do Mac, nota.txt e Nota.txt são o mesmo item: trocar só maiúsculas é renomear.
    so_maiusculas = para.exists() and para.name != de.name and os.path.samefile(para, de)
    if para.is_dir() and not so_maiusculas:
        para = para / de.name
    if para.exists() and not so_maiusculas:
        raise Erro(f"{abreviar(para)} já existe; não vou sobrescrever.", f"{para.name} já existe")
    _pasta_existe(para)
    if not confirmar(f"Mover {abreviar(de)} para {abreviar(para)}?", None):
        return _recusado(f"mover {abreviar(de)}")
    shutil.move(str(de), str(para))
    return Resultado(f"{abreviar(de)} movido para {abreviar(para)}.", f"movido {abreviar(de)} → {abreviar(para)}",
                     alterou=True)


def mandar_para_lixeira(caminho, base, confirmar):
    alvo = _existente(caminho, base)
    if alvo in (CASA.resolve(), Path(alvo.anchor), LIXEIRA.resolve()):
        raise Erro(f"não vou mandar {abreviar(alvo)} inteira para a Lixeira.", f"recusado: {abreviar(alvo)}")
    if not confirmar(f"Mandar {abreviar(alvo)} para a Lixeira?", None):
        return _recusado(f"mandar {abreviar(alvo)} para a Lixeira")
    LIXEIRA.mkdir(exist_ok=True)
    shutil.move(str(alvo), str(_nome_livre(LIXEIRA / alvo.name)))
    return Resultado(f"{abreviar(alvo)} foi para a Lixeira (dá para recuperar de lá).", f"na Lixeira: {alvo.name}",
                     alterou=True)


# Planilhas: contas (leitura), criar e editar (perguntam antes).

def calcular_na_planilha(caminho, operacao, base, confirmar, coluna=None, filtro=None, agrupar_por=None, aba=None):
    arquivo = _existente(caminho, base)
    _arquivo_comum(arquivo)
    if documentos.tipo(arquivo) != "planilha":
        raise Erro(f"{arquivo.name} não é uma planilha do Excel.", f"{arquivo.name} não é planilha")
    resultado = planilhas.calcular(arquivo, operacao, coluna, filtro=filtro, agrupar_por=agrupar_por, aba=aba)
    return Resultado(resultado, f"calculando {operacao} em {arquivo.name}")


def criar_planilha(caminho, conteudo, base, confirmar, aba=None):
    atalho = resolver_caminho(caminho, base)
    arquivo = atalho.resolve() if atalho.is_symlink() else atalho
    if arquivo.suffix.lower() != ".xlsx":
        raise Erro("só crio planilhas .xlsx; use um nome terminado em .xlsx.", "só crio planilhas .xlsx")
    _pasta_existe(arquivo)
    linhas = planilhas.tabela(conteudo)
    existe = arquivo.exists()
    colunas = max(len(linha) for linha in linhas)
    pergunta = (f"Substituir a planilha {abreviar(arquivo)}? Ela já existe." if existe
                else f"Criar a planilha {abreviar(arquivo)} ({len(linhas)} linhas, {colunas} colunas)?")
    if not confirmar(pergunta, planilhas.previa(linhas), sempre_perguntar=existe):
        return _recusado(f"criar a planilha {abreviar(arquivo)}")
    planilhas.criar(arquivo, linhas, aba)
    return Resultado(f"planilha {abreviar(arquivo)} criada com {len(linhas)} linhas e {colunas} colunas.",
                     f"criada {abreviar(arquivo)}", alterou=True)


def _planilha_para_editar(caminho, base, aba):
    arquivo = _existente(caminho, base)
    _arquivo_comum(arquivo)
    if documentos.tipo(arquivo) != "planilha":
        raise Erro(f"{arquivo.name} não é uma planilha do Excel.", f"{arquivo.name} não é planilha")
    return arquivo, planilhas.Edicao(arquivo, aba)


def _confirmar_e_gravar(arquivo, edicao, confirmar):
    """Mostra o que vai mudar, pergunta, guarda a versão de agora na Lixeira e grava."""
    quantas = len(edicao.descricao)
    plural = "ões" if quantas != 1 else "ão"
    detalhe = "\n".join(edicao.descricao[:10])
    if quantas > 10:
        detalhe += f"\n… (+{quantas - 10} alterações)"
    detalhe += "".join(f"\n{aviso}" for aviso in edicao.avisos)
    detalhe += "\n(a versão de agora vai para a Lixeira, para dar para desfazer)"
    # Mexe no que já existe, então pergunta mesmo depois de um "t" (todas).
    if not confirmar(f"Alterar a planilha {abreviar(arquivo)}? ({quantas} alteraç{plural})", detalhe,
                     sempre_perguntar=True):
        return _recusado(f"alterar a planilha {abreviar(arquivo)}")
    LIXEIRA.mkdir(exist_ok=True)
    shutil.copy2(str(arquivo), str(_nome_livre(LIXEIRA / f"{arquivo.stem} (antes de editar){arquivo.suffix}")))
    edicao.aplicar()
    # O modelo recebe o que foi feito de verdade, para não inventar outro resumo.
    feito = "; ".join(edicao.descricao[:10]) + ("; …" if quantas > 10 else "")
    observacoes = "".join(f" Observação: {aviso}." for aviso in edicao.avisos)
    return Resultado(f"planilha {abreviar(arquivo)} alterada ({quantas} alteraç{plural}): {feito}.{observacoes} "
                     f"A versão anterior está na Lixeira.", f"alterada {abreviar(arquivo)}", alterou=True)


# No teste real, uma minilinguagem num campo só ("D5 = ...", "+ ...", "coluna X = ...") confundia o modelo,
# que errava linha e coluna; com uma ferramenta por operação e campos separados, ele acerta.

def mudar_na_planilha(caminho, coluna, valor, onde, base, confirmar, aba=None):
    arquivo, edicao = _planilha_para_editar(caminho, base, aba)
    edicao.mudar_onde(coluna, valor, onde)
    return _confirmar_e_gravar(arquivo, edicao, confirmar)


def adicionar_coluna(caminho, nome, conta, base, confirmar, aba=None):
    arquivo, edicao = _planilha_para_editar(caminho, base, aba)
    edicao.nova_coluna(nome, conta)
    return _confirmar_e_gravar(arquivo, edicao, confirmar)


def adicionar_linhas(caminho, linhas, base, confirmar, aba=None):
    arquivo, edicao = _planilha_para_editar(caminho, base, aba)
    for linha in str(linhas).splitlines():
        if linha.strip() and not planilhas.SEPARADOR_MARKDOWN.fullmatch(linha.strip()):
            edicao.nova_linha(planilhas._celulas(linha))
    if not edicao.descricao:
        raise Erro("nenhuma linha para adicionar.", "nenhuma linha para adicionar")
    return _confirmar_e_gravar(arquivo, edicao, confirmar)


def apagar_linhas(caminho, onde, base, confirmar, aba=None):
    arquivo, edicao = _planilha_para_editar(caminho, base, aba)
    edicao.apagar_onde(onde)
    return _confirmar_e_gravar(arquivo, edicao, confirmar)


@dataclass
class Ferramenta:
    nome: str
    descricao: str
    parametros: dict  # nome → descrição
    obrigatorios: list
    funcao: object
    altera: bool = False


FERRAMENTAS = [
    Ferramenta("listar_pasta", "Lista os arquivos e pastas dentro de uma pasta do Mac (sem os ocultos), "
               "com tamanho e data da última alteração.",
               {"caminho": AJUDA_CAMINHO,
                "ordem": 'Opcional: "data" mostra os mais novos primeiro (use para achar o último arquivo '
                         'salvo); o padrão é "nome".'},
               ["caminho"], listar_pasta),
    Ferramenta("ler_arquivo", "Lê um arquivo do Mac: texto (txt, md, csv, código), PDF (inclusive escaneado), "
               "Word e planilhas do Excel. Em arquivos grandes, diz como continuar a leitura.",
               {"caminho": AJUDA_CAMINHO,
                "a_partir_de": "Opcional: de onde continuar um arquivo grande, o número da página (PDF) ou da "
                               "linha (planilha e texto).",
                "aba": "Opcional, só para planilhas: o nome da aba a ler."},
               ["caminho"], ler_arquivo),
    Ferramenta("buscar_no_arquivo", "Procura um texto dentro de um arquivo (planilha, PDF, Word ou texto) e "
               "mostra só as linhas que batem. Use para achar um item numa tabela grande, como um preço.",
               {"caminho": AJUDA_CAMINHO, "texto": "O texto procurado (acentos e maiúsculas tanto faz)."},
               ["caminho", "texto"], buscar_no_arquivo),
    Ferramenta("calcular_na_planilha", "Faz uma conta exata numa planilha do Excel: soma, média, contagem, maior "
               "ou menor de uma coluna, com filtro e agrupamento. Use sempre que precisar de um total ou de um "
               "maior/menor valor, em vez de calcular de cabeça.",
               {"caminho": AJUDA_CAMINHO,
                "operacao": "soma, média, contagem, maior ou menor.",
                "coluna": "A coluna da conta, pelo nome do cabeçalho (como Preço) ou pela letra (como D). "
                          "Na contagem pode ficar vazia.",
                "filtro": "Opcional: só as linhas que batem, como: Marca = Bosch e Preço > 100. Também aceita "
                          "contém e não contém (Descrição contém pastilha).",
                "agrupar_por": "Opcional: uma coluna para dar o resultado por grupo, como Marca.",
                "aba": "Opcional: o nome da aba (o padrão é a primeira)."},
               ["caminho", "operacao"], calcular_na_planilha),
    Ferramenta("buscar_arquivos", "Procura arquivos pelo nome no Mac inteiro, com a busca do Spotlight; "
               "os mais novos vêm primeiro. Use quando não souber em que pasta o arquivo está.",
               {"nome": "Parte do nome do arquivo.",
                "pasta": "Opcional: procurar só dentro desta pasta. " + AJUDA_CAMINHO},
               ["nome"], buscar_arquivos),
    Ferramenta("buscar_texto", "Procura um texto dentro dos arquivos de texto de uma pasta e das subpastas.",
               {"texto": "O texto procurado (maiúsculas e minúsculas tanto faz).", "pasta": AJUDA_CAMINHO},
               ["texto", "pasta"], buscar_texto),
    Ferramenta("ver_imagem", "Abre uma imagem do Mac (jpg, png, heic...) para você ver o conteúdo.",
               {"caminho": AJUDA_CAMINHO}, ["caminho"], ver_imagem),
    Ferramenta("escrever_arquivo", "Cria um arquivo de texto ou substitui um que já existe. "
               "O usuário confirma antes.",
               {"caminho": AJUDA_CAMINHO, "conteudo": "O texto completo do arquivo."},
               ["caminho", "conteudo"], escrever_arquivo, altera=True),
    Ferramenta("criar_pasta", "Cria uma pasta. O usuário confirma antes.",
               {"caminho": AJUDA_CAMINHO}, ["caminho"], criar_pasta, altera=True),
    Ferramenta("mover", "Move ou renomeia um arquivo ou pasta. Se o destino for uma pasta que já existe, "
               "o item vai para dentro dela. Nunca sobrescreve. O usuário confirma antes.",
               {"origem": "O que mover. " + AJUDA_CAMINHO, "destino": "Para onde, ou o nome novo. " + AJUDA_CAMINHO},
               ["origem", "destino"], mover, altera=True),
    Ferramenta("mandar_para_lixeira", "Manda um arquivo ou pasta para a Lixeira; é assim que se apaga, e dá "
               "para recuperar. O usuário confirma antes.",
               {"caminho": AJUDA_CAMINHO}, ["caminho"], mandar_para_lixeira, altera=True),
    Ferramenta("criar_planilha", "Cria uma planilha do Excel (.xlsx) a partir de uma tabela. O usuário confirma "
               "antes.",
               {"caminho": "Onde salvar, terminando em .xlsx. " + AJUDA_CAMINHO,
                "conteudo": "A tabela: uma linha por linha, células separadas por |. A primeira linha é o "
                            "cabeçalho. Exemplo: Peça | Preço (nova linha) Vela NGK | 25,90",
                "aba": "Opcional: o nome da aba."},
               ["caminho", "conteudo"], criar_planilha, altera=True),
    Ferramenta("mudar_na_planilha", "Muda o valor de uma coluna nas linhas de uma planilha do Excel que batem com "
               "um filtro. Exemplo: coluna Preço, valor 149,90, onde Peça = disco. O usuário confirma antes, e a "
               "versão anterior vai para a Lixeira.",
               {"caminho": AJUDA_CAMINHO, "coluna": "A coluna a mudar, pelo nome do cabeçalho (como Preço).",
                "valor": "O valor novo, já calculado (como 149,90), ou uma fórmula do Excel começando com =.",
                "onde": "Quais linhas mudar, como: Peça = disco. Aceita =, >, <, contém e não contém, e junta "
                        "condições com e.",
                "aba": "Opcional: o nome da aba (o padrão é a primeira)."},
               ["caminho", "coluna", "valor", "onde"], mudar_na_planilha, altera=True),
    Ferramenta("adicionar_coluna", "Cria uma coluna nova numa planilha do Excel, calculada a partir de outras "
               "colunas, em todas as linhas. Exemplo: nome Preço com desconto, conta [Preço] * 0,95. O usuário "
               "confirma antes.",
               {"caminho": AJUDA_CAMINHO, "nome": "O nome da coluna nova.",
                "conta": "A conta, com as colunas entre colchetes e + - * /, como [Preço] * [Estoque].",
                "aba": "Opcional: o nome da aba (o padrão é a primeira)."},
               ["caminho", "nome", "conta"], adicionar_coluna, altera=True),
    Ferramenta("adicionar_linhas", "Adiciona linhas no fim de uma planilha do Excel. O usuário confirma antes.",
               {"caminho": AJUDA_CAMINHO,
                "linhas": "Uma linha por linha, com os valores na ordem das colunas, separados por |. "
                          "Exemplo: Bateria Moura | Moura | 450",
                "aba": "Opcional: o nome da aba (o padrão é a primeira)."},
               ["caminho", "linhas"], adicionar_linhas, altera=True),
    Ferramenta("apagar_linhas", "Apaga as linhas de uma planilha do Excel que batem com um filtro. O usuário "
               "confirma antes, e a versão anterior vai para a Lixeira.",
               {"caminho": AJUDA_CAMINHO, "onde": "Quais linhas apagar, como: Marca = NGK.",
                "aba": "Opcional: o nome da aba (o padrão é a primeira)."},
               ["caminho", "onde"], apagar_linhas, altera=True),
]


def definicoes(alterar=True, imagens=True):
    """As ferramentas no formato que o Ollama (e o MCP) entende.

    Sem alterar, só as de leitura; sem imagens (modelo que não lê imagem), sem ver_imagem.
    """
    return [{"type": "function",
             "function": {"name": f.nome, "description": f.descricao,
                          "parameters": {"type": "object",
                                         "properties": {p: {"type": "string", "description": d}
                                                        for p, d in f.parametros.items()},
                                         "required": f.obrigatorios}}}
            for f in FERRAMENTAS if (alterar or not f.altera) and (imagens or f.nome != "ver_imagem")]


def executar(nome, argumentos, confirmar, base):
    """Roda a ferramenta pedida pelo modelo. Qualquer problema vira um Resultado com "erro:"."""
    ferramenta = next((f for f in FERRAMENTAS if f.nome == nome), None)
    if ferramenta is None:
        return Resultado(f"erro: não existe a ferramenta {nome}.", f"ferramenta desconhecida: {nome}")
    if isinstance(argumentos, str):
        try:
            argumentos = json.loads(argumentos or "{}")
        except ValueError:
            argumentos = None
    if not isinstance(argumentos, dict):
        return Resultado("erro: os argumentos não vieram num formato válido.", f"{nome}: argumentos inválidos")
    faltando = [p for p in ferramenta.obrigatorios if not argumentos.get(p)]
    if faltando:
        return Resultado(f"erro: faltou {', '.join(faltando)}.", f"{nome}: faltou {', '.join(faltando)}")
    valores = {p: str(argumentos[p]) for p in ferramenta.parametros if argumentos.get(p)}
    try:
        return ferramenta.funcao(base=Path(base), confirmar=confirmar, **valores)
    except Erro as e:
        return Resultado(f"erro: {e}", e.resumo)
    except planilhas.ErroPlanilha as e:
        return Resultado(f"erro: {e}", f"{nome}: {str(e)[:60]}")
    except documentos.FaltaBiblioteca as e:
        return Resultado(f"erro: {e}.", f"falta a biblioteca {e.nome}")
    except documentos.ErroDocumento as e:
        return Resultado(f"erro: {e}", f"{nome}: {e}")
    except PermissionError as e:
        alvo = abreviar(e.filename) if e.filename else "esse item"
        return Resultado(f"erro: sem permissão para acessar {alvo}.", f"sem permissão: {Path(alvo).name}")
    except OSError as e:
        alvo = abreviar(e.filename) if e.filename else "o item"
        motivo = ERROS_DO_SISTEMA.get(e.errno, f"não pôde ser usado (o sistema recusou, código {e.errno})")
        return Resultado(f"erro: {alvo} {motivo}.", f"{nome}: falhou")
    except Exception as e:  # nada que o modelo peça pode derrubar o chat
        return Resultado(f"erro: não consegui usar {nome} ({e}).", f"{nome}: falhou")
