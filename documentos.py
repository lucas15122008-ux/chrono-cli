"""Leitura de documentos que não são texto puro: PDF (inclusive escaneado), Word e planilhas.

As bibliotecas pypdf, openpyxl e xlrd só são carregadas quando um desses arquivos aparece,
para o chrono continuar abrindo rápido. Páginas de PDF sem texto (escaneadas) passam pelo
leitor de texto do próprio macOS, num programinha em Swift (ocr.swift) compilado na primeira vez.
Word, RTF e afins são lidos pelo textutil, que já vem no Mac.
"""
import json
import logging
import subprocess
import unicodedata
from datetime import date, datetime
from pathlib import Path

PROGRAMA_OCR = Path.home() / ".chrono" / "bin" / "chrono-ocr"
FONTE_OCR = Path(__file__).resolve().with_name("ocr.swift")

LIMITE = 20000  # caracteres devolvidos de uma vez
MAX_PAGINAS_IMAGEM = 20  # páginas escaneadas lidas por vez (cada uma leva 1 ou 2 segundos)
PREVIA_LINHAS = 20  # linhas de cada aba no resumo de uma planilha
LINHAS_POR_VEZ = 200  # linhas de planilha por vez quando o modelo pede para continuar
MAX_ABAS_NA_PREVIA = 10

PDF = {".pdf"}
WORD = {".docx", ".doc", ".rtf", ".rtfd", ".odt", ".html", ".htm", ".webarchive"}
PLANILHA = {".xlsx", ".xlsm", ".xls"}


class ErroDocumento(Exception):
    """Documento que não deu para ler (protegido, quebrado, aba que não existe...)."""


class FaltaBiblioteca(ErroDocumento):
    def __init__(self, nome, para):
        super().__init__(f"para ler {para}, falta a biblioteca {nome}: rode pip3 install --user {nome}")
        self.nome = nome


def tipo(caminho):
    """"pdf", "word", "planilha", ou None para o que não é documento."""
    extensao = Path(caminho).suffix.lower()
    for nome, extensoes in (("pdf", PDF), ("word", WORD), ("planilha", PLANILHA)):
        if extensao in extensoes:
            return nome
    return None


def normalizar(texto):
    """Minúsculas e sem acentos, para "orcamento" achar "Orçamento"."""
    sem_acento = unicodedata.normalize("NFD", texto)
    return "".join(c for c in sem_acento if unicodedata.category(c) != "Mn").casefold()


def _importar(nome, para):
    try:
        return __import__(nome)
    except ImportError:
        raise FaltaBiblioteca(nome, para)


# PDF

def _abrir_pdf(caminho):
    pypdf = _importar("pypdf", "PDF")
    logging.getLogger("pypdf").setLevel(logging.ERROR)  # avisos técnicos bagunçariam a tela do chat
    try:
        leitor = pypdf.PdfReader(str(caminho))
        if leitor.is_encrypted and not leitor.decrypt(""):
            raise ErroDocumento("este PDF é protegido por senha.")
        len(leitor.pages)
    except ErroDocumento:
        raise
    except Exception:
        raise ErroDocumento("não consegui abrir este PDF (o arquivo parece quebrado).")
    return leitor


def _programa_ocr():
    """O leitor de imagem compilado; compila (uns 6 segundos) se faltar ou se o ocr.swift mudou."""
    if PROGRAMA_OCR.exists() and PROGRAMA_OCR.stat().st_mtime >= FONTE_OCR.stat().st_mtime:
        return PROGRAMA_OCR
    PROGRAMA_OCR.parent.mkdir(parents=True, exist_ok=True)
    try:
        compilado = subprocess.run(["swiftc", "-O", str(FONTE_OCR), "-o", str(PROGRAMA_OCR)],
                                   capture_output=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        raise ErroDocumento("o compilador Swift do Mac não está disponível")
    if compilado.returncode != 0 or not PROGRAMA_OCR.exists():
        raise ErroDocumento("não consegui preparar o leitor de imagem do macOS")
    return PROGRAMA_OCR


def _ler_da_imagem(caminho, numero):
    programa = _programa_ocr()
    try:
        saida = subprocess.run([str(programa), str(caminho), str(numero)], capture_output=True, timeout=120)
        paginas = json.loads(saida.stdout.decode("utf-8") or "[]")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        raise ErroDocumento("o leitor de imagem do macOS não respondeu")
    return paginas[0]["texto"].strip() if paginas else ""


def _texto_da_pagina(leitor, caminho, numero, imagens_restantes):
    """(texto, lido_da_imagem). Página sem texto nenhum é escaneada: vai para o leitor de imagem."""
    try:
        texto = (leitor.pages[numero - 1].extract_text() or "").strip()
    except Exception:
        texto = ""
    if texto:
        return texto, False
    if imagens_restantes[0] <= 0:
        return f"(página escaneada; já li {MAX_PAGINAS_IMAGEM} páginas da imagem nesta vez)", False
    imagens_restantes[0] -= 1
    try:
        lido = _ler_da_imagem(caminho, numero)
    except ErroDocumento as e:
        return f"(página sem texto; não consegui ler a imagem: {e})", False
    return (lido, True) if lido else ("(página sem texto)", False)


def ler_pdf(caminho, a_partir_de=1, limite=LIMITE):
    leitor = _abrir_pdf(caminho)
    total = len(leitor.pages)
    if a_partir_de > total:
        raise ErroDocumento(f"o PDF tem só {total} página{'s' if total != 1 else ''}.")
    imagens_restantes = [MAX_PAGINAS_IMAGEM]
    partes, tamanho, ultima = [], 0, a_partir_de - 1
    for numero in range(a_partir_de, total + 1):
        texto, da_imagem = _texto_da_pagina(leitor, caminho, numero, imagens_restantes)
        bloco = f"=== página {numero}{' (lida da imagem)' if da_imagem else ''} ===\n{texto}"
        if partes and tamanho + len(bloco) > limite:
            break
        partes.append(bloco[:limite])
        tamanho += len(bloco) + 2
        ultima = numero
    resultado = "\n\n".join(partes)
    if ultima < total:
        resultado += (f"\n\n(mostrei as páginas {a_partir_de} a {ultima} de {total}; "
                      f"para continuar, use a_partir_de={ultima + 1})")
    return resultado


# Word, RTF e afins (pelo textutil do Mac)

def _texto_word(caminho):
    try:
        convertido = subprocess.run(["textutil", "-convert", "txt", "-stdout", "-encoding", "UTF-8", str(caminho)],
                                    capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        raise ErroDocumento("não consegui abrir este documento.")
    if convertido.returncode != 0:
        raise ErroDocumento("não consegui abrir este documento.")
    return convertido.stdout.decode("utf-8", errors="replace").strip()


def ler_word(caminho, limite=LIMITE):
    texto = _texto_word(caminho)
    if len(texto) > limite:
        texto = (texto[:limite] + f"\n(documento cortado: mostrei {limite} de {len(texto)} caracteres; "
                 f"use buscar_no_arquivo para achar trechos)")
    return texto


# Planilhas

def _valor(valor):
    """Célula como texto: números com vírgula, datas como 30/10/2026."""
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return "sim" if valor else "não"
    if isinstance(valor, datetime):
        return valor.strftime("%d/%m/%Y" if (valor.hour, valor.minute) == (0, 0) else "%d/%m/%Y %H:%M")
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    if isinstance(valor, float):
        return str(int(valor)) if valor.is_integer() else ("%.10g" % valor).replace(".", ",")
    return " ".join(str(valor).split())  # quebras de linha dentro da célula viram espaço


def _guardar(abas, nome, numero, valores):
    while valores and valores[-1] == "":
        valores.pop()
    if valores:
        abas[nome].append((numero, valores))


def ler_abas(caminho):
    """{nome da aba: [(número da linha, [células])]}, na ordem das abas e sem linhas vazias."""
    abas = {}
    if Path(caminho).suffix.lower() == ".xls":
        xlrd = _importar("xlrd", "planilhas .xls")
        try:
            livro = xlrd.open_workbook(str(caminho), on_demand=True)
            for nome in livro.sheet_names():
                aba = livro.sheet_by_name(nome)
                abas[nome] = []
                for i in range(aba.nrows):
                    valores = []
                    for celula in aba.row(i):
                        if celula.ctype == xlrd.XL_CELL_DATE:
                            valores.append(_valor(xlrd.xldate.xldate_as_datetime(celula.value, livro.datemode)))
                        elif celula.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                            valores.append("")
                        else:
                            valores.append(_valor(celula.value))
                    _guardar(abas, nome, i + 1, valores)
        except ErroDocumento:
            raise
        except Exception:
            raise ErroDocumento("não consegui abrir esta planilha.")
        return abas
    openpyxl = _importar("openpyxl", "planilhas do Excel")
    try:
        livro = openpyxl.load_workbook(str(caminho), read_only=True, data_only=True)
    except Exception:
        raise ErroDocumento("não consegui abrir esta planilha (pode estar protegida ou quebrada).")
    try:
        for aba in livro.worksheets:
            abas[aba.title] = []
            for numero, linha in enumerate(aba.iter_rows(values_only=True), 1):
                _guardar(abas, aba.title, numero, [_valor(v) for v in linha])
    finally:
        livro.close()
    return abas


def _linha(numero, valores):
    return f"{numero}: {' | '.join(valores)}"


def _trecho(nome, linhas, inicio, max_linhas, limite):
    """Linhas de uma aba a partir de inicio, até max_linhas ou o limite de caracteres, com o aviso de como continuar."""
    if linhas and inicio > linhas[-1][0]:
        raise ErroDocumento(f"a aba {nome} tem só {linhas[-1][0]} linhas.")
    bloco = [f"=== aba {nome} ({len(linhas)} linhas) ==="]
    if inicio > 1 and linhas and linhas[0][0] < inicio:
        bloco.append(_linha(*linhas[0]))  # o cabeçalho ajuda a entender as colunas
    tamanho = sum(len(b) + 1 for b in bloco)
    primeira = ultima = None
    mostradas = 0
    for numero, valores in linhas:
        if numero < inicio:
            continue
        linha = _linha(numero, valores)
        if mostradas and (mostradas >= max_linhas or tamanho + len(linha) + 1 > limite):
            bloco.append(f"(mostrei as linhas {primeira} a {ultima} de {linhas[-1][0]} da aba {nome}; para continuar, "
                         f'use aba="{nome}" e a_partir_de={ultima + 1}; para achar um item, use buscar_no_arquivo)')
            break
        bloco.append(linha)
        tamanho += len(linha) + 1
        primeira = numero if primeira is None else primeira
        ultima = numero
        mostradas += 1
    return "\n".join(bloco)


def ler_planilha(caminho, aba=None, a_partir_de=None, limite=LIMITE):
    """Sem a_partir_de, um resumo: as primeiras linhas de cada aba. Com a_partir_de, uma página de linhas.

    Entregar centenas de linhas de uma vez deixava o modelo minutos "lendo"; com o resumo ele
    vê as colunas e o tamanho, e pede mais (a_partir_de) ou procura (buscar_no_arquivo).
    """
    abas = ler_abas(caminho)
    if aba is not None:
        real = next((nome for nome in abas if normalizar(nome) == normalizar(aba)), None)
        if real is None:
            raise ErroDocumento(f"não existe a aba {aba}; as abas são: {', '.join(abas)}")
        escolhidas, texto = [real], ""
    else:
        escolhidas, texto = list(abas), f"abas: {', '.join(abas)}\n\n"
    if a_partir_de is not None:
        nome = escolhidas[0]
        return texto + _trecho(nome, abas[nome], a_partir_de, LINHAS_POR_VEZ, limite - len(texto))
    com_previa = escolhidas[:MAX_ABAS_NA_PREVIA]
    por_aba = (limite - len(texto)) // len(com_previa) if com_previa else limite
    blocos = [_trecho(nome, abas[nome], 1, PREVIA_LINHAS, por_aba) for nome in com_previa]
    sem_previa = escolhidas[MAX_ABAS_NA_PREVIA:]
    if sem_previa:
        blocos.append(f"(abas sem prévia: {', '.join(sem_previa)}; para ver uma delas, use aba=\"nome\")")
    return texto + "\n\n".join(blocos)


# Procurar dentro de um documento

def buscar(caminho, texto, imagens=True):
    """Linhas do documento que contêm o texto (sem ligar para acentos e maiúsculas).

    Com imagens=False, páginas escaneadas de PDF não são lidas (a busca por pasta fica rápida).
    """
    procurado = normalizar(texto)
    achados = []
    tipo_do_arquivo = tipo(caminho)
    if tipo_do_arquivo == "planilha":
        for nome, linhas in ler_abas(caminho).items():
            da_aba = [f"linha {_linha(n, v)}" for n, v in linhas[1:] if procurado in normalizar(" | ".join(v))]
            if da_aba:
                achados.append(f"aba {nome} — cabeçalho: {' | '.join(linhas[0][1])}")
                achados += da_aba
    elif tipo_do_arquivo == "pdf":
        leitor = _abrir_pdf(caminho)
        imagens_restantes = [MAX_PAGINAS_IMAGEM if imagens else 0]
        for numero in range(1, len(leitor.pages) + 1):
            conteudo, _ = _texto_da_pagina(leitor, caminho, numero, imagens_restantes)
            achados += [f"página {numero}: {l.strip()}" for l in conteudo.splitlines() if procurado in normalizar(l)]
    elif tipo_do_arquivo == "word":
        achados = [f"linha {n}: {l.strip()}" for n, l in enumerate(_texto_word(caminho).splitlines(), 1)
                   if procurado in normalizar(l)]
    return achados
