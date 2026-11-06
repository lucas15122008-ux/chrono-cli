"""Contas, criação e edição de planilhas do Excel, para as ferramentas do chrono.

As contas são feitas aqui, em Python, e não pelo modelo: um modelo pequeno erraria ao somar
milhares de preços de cabeça. A leitura das planilhas vem do documentos.py.
"""
import ast
import re
import zipfile
from datetime import datetime

import documentos


class ErroPlanilha(Exception):
    """Pedido que não deu para atender (coluna que não existe, filtro que não entendi...)."""


OPERACOES = {"soma": "soma", "media": "média", "contagem": "contagem", "maior": "maior", "menor": "menor"}
MAX_GRUPOS = 50


def numero(texto):
    """Número de uma célula em texto ("R$ 1.234,56", "89,9", "1.5"), ou None se não for número."""
    limpo = str(texto).replace("R$", "").replace(" ", "").replace(" ", "").strip()
    if not limpo:
        return None
    if "," in limpo:  # jeito brasileiro: ponto separa milhar, vírgula separa decimal
        limpo = limpo.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", limpo):  # 1.234 é mil duzentos e trinta e quatro
        limpo = limpo.replace(".", "")
    try:
        return float(limpo)
    except ValueError:
        return None


def formatar(valor):
    """Número no jeito brasileiro: 1.234,56 (inteiros sem casas decimais)."""
    if float(valor).is_integer():
        return f"{int(valor):,}".replace(",", ".")
    return f"{valor:,.2f}".replace(",", "x").replace(".", ",").replace("x", ".")


def _coluna(cabecalho, nome):
    """Índice da coluna pelo nome no cabeçalho (sem ligar para acentos) ou pela letra (D)."""
    alvo = documentos.normalizar(str(nome).strip())
    for indice, titulo in enumerate(cabecalho):
        if documentos.normalizar(titulo) == alvo:
            return indice
    if re.fullmatch(r"[a-z]{1,2}", alvo):
        indice = 0
        for letra in alvo:
            indice = indice * 26 + ord(letra) - ord("a") + 1
        if indice - 1 < len(cabecalho):
            return indice - 1
    raise ErroPlanilha(f"não existe a coluna {nome}; as colunas são: {', '.join(cabecalho)}")


CONDICAO = re.compile(r"^(.+?)\s*(>=|<=|!=|=|>|<|n[ãa]o\s+cont[ée]m|cont[ée]m)\s*(.+)$", re.IGNORECASE)


def _filtro(cabecalho, texto):
    """Função que diz se uma linha passa no filtro ("Marca = Bosch e Preço > 100")."""
    if not texto:
        return lambda valores: True
    condicoes = []
    for parte in re.split(r"\s+e\s+", texto.strip(), flags=re.IGNORECASE):
        achado = CONDICAO.match(parte.strip())
        if not achado:
            raise ErroPlanilha(f'não entendi o filtro "{parte.strip()}"; use por exemplo: Marca = Bosch, '
                               f"Preço > 100, Descrição contém pastilha")
        coluna, operador, valor = achado.groups()
        condicoes.append((_coluna(cabecalho, coluna), " ".join(documentos.normalizar(operador).split()),
                          valor.strip().strip("\"'")))

    def passa(valores):
        return all(_compara(valores[i] if i < len(valores) else "", operador, valor)
                   for i, operador, valor in condicoes)
    return passa


def _compara(celula, operador, valor):
    if operador == "contem":
        return documentos.normalizar(valor) in documentos.normalizar(celula)
    if operador == "nao contem":
        return documentos.normalizar(valor) not in documentos.normalizar(celula)
    a, b = numero(celula), numero(valor)
    if operador in ("=", "!="):
        igual = a == b if a is not None and b is not None else documentos.normalizar(celula) == documentos.normalizar(valor)
        return igual if operador == "=" else not igual
    if a is None or b is None:
        return False
    return {">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b}[operador]


def _aba(abas, aba):
    if aba is None:
        if not abas:
            raise ErroPlanilha("a planilha não tem abas.")
        return next(iter(abas))
    real = next((nome for nome in abas if documentos.normalizar(nome) == documentos.normalizar(aba)), None)
    if real is None:
        raise ErroPlanilha(f"não existe a aba {aba}; as abas são: {', '.join(abas)}")
    return real


def _plural(n, palavra="linha"):
    return f"{n} {palavra}{'s' if n != 1 else ''}"


def _resultado(operacao, numeros):
    if operacao == "soma":
        return sum(numeros)
    if operacao == "média":
        return sum(numeros) / len(numeros)
    return max(numeros) if operacao == "maior" else min(numeros)


def calcular(caminho, operacao, coluna=None, filtro=None, agrupar_por=None, aba=None):
    """Faz a conta pedida numa aba e devolve a frase com o resultado."""
    op = OPERACOES.get(documentos.normalizar(str(operacao or "")).strip())
    if op is None:
        raise ErroPlanilha(f"operação desconhecida: {operacao}; use soma, média, contagem, maior ou menor")
    abas = documentos.ler_abas(caminho)
    linhas = abas[_aba(abas, aba)]
    if not linhas:
        raise ErroPlanilha("a aba está vazia.")
    cabecalho, dados = linhas[0][1], linhas[1:]
    if op != "contagem" and not coluna:
        raise ErroPlanilha(f"diga a coluna para a {op}; as colunas são: {', '.join(cabecalho)}")
    indice = _coluna(cabecalho, coluna) if coluna else None
    passa = _filtro(cabecalho, filtro)
    escolhidas = [(n, v) for n, v in dados if passa(v)]

    if op == "contagem":
        titulo = "contagem"
    elif op in ("soma", "média"):
        titulo = f"{op} de {cabecalho[indice]}"
    else:
        titulo = f"{op} {cabecalho[indice]}"
    if agrupar_por:
        return _agrupado(op, titulo, cabecalho, indice, _coluna(cabecalho, agrupar_por), escolhidas)
    if filtro:
        titulo += f" onde {filtro}"
    if not escolhidas and filtro:
        return f"{titulo}: nenhuma linha bate com o filtro"
    if op == "contagem":
        return f"{titulo}: {_plural(len(escolhidas))}"

    com_numero = [(numero(v[indice]) if indice < len(v) else None, n, v) for n, v in escolhidas]
    validos = [(x, n, v) for x, n, v in com_numero if x is not None]
    sem_numero = len(com_numero) - len(validos)
    if not validos:
        return f"{titulo}: nenhuma linha tem número em {cabecalho[indice]}"
    if op in ("maior", "menor"):
        escolha = max if op == "maior" else min
        valor, n, v = escolha(validos, key=lambda item: item[0])
        return f"{titulo}: {formatar(valor)} — linha {n}: {' | '.join(v)}"
    total = _resultado(op, [x for x, _, _ in validos])
    contagem = (f"{len(validos)} linhas com número; {sem_numero} sem número" if sem_numero
                else _plural(len(validos)))
    return f"{titulo}: {formatar(total)} ({contagem})"


def _agrupado(op, titulo, cabecalho, indice, grupo, escolhidas):
    grupos = {}
    for _, valores in escolhidas:
        chave = valores[grupo] if grupo < len(valores) and valores[grupo] else "(vazio)"
        grupos.setdefault(chave, []).append(valores)
    resultados = []
    for chave, membros in grupos.items():
        if op == "contagem":
            resultados.append((len(membros), f"{chave}: {len(membros)}"))
            continue
        numeros = [x for x in (numero(v[indice]) if indice < len(v) else None for v in membros) if x is not None]
        if numeros:
            valor = _resultado(op, numeros)
            resultados.append((valor, f"{chave}: {formatar(valor)} ({_plural(len(numeros))})"))
    resultados.sort(key=lambda item: -item[0])  # estável: empates ficam na ordem em que aparecem
    linhas = [texto for _, texto in resultados[:MAX_GRUPOS]]
    if len(resultados) > MAX_GRUPOS:
        linhas.append(f"… e mais {len(resultados) - MAX_GRUPOS} grupos")
    return f"{titulo} por {cabecalho[grupo]} ({_plural(len(resultados), 'grupo')}):\n" + "\n".join(linhas)


# Criar planilhas

def _celula(texto):
    """Valor de uma célula escrita pelo modelo: fórmula, número, data ou texto.

    Códigos com zero à esquerda (0123) ficam texto, para o zero não sumir.
    """
    limpo = str(texto).strip()
    if not limpo:
        return None
    if limpo.startswith("="):
        return limpo
    if re.fullmatch(r"0\d+", limpo):
        return limpo
    data = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", limpo)
    if data:
        dia, mes, ano = (int(x) for x in data.groups())
        try:
            return datetime(ano, mes, dia)
        except ValueError:
            return limpo
    valor = numero(limpo)
    if valor is None:
        return limpo
    return int(valor) if valor.is_integer() and "," not in limpo else valor


SEPARADOR_MARKDOWN = re.compile(r"\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?")


def _celulas(linha):
    if "|" in linha:
        linha = linha.strip()
        linha = linha[1:] if linha.startswith("|") else linha
        linha = linha[:-1] if linha.endswith("|") else linha
        return linha.split("|")
    for separador in ("\t", ";"):
        if separador in linha:
            return linha.split(separador)
    return [linha]


def tabela(conteudo):
    """A tabela que o modelo escreveu (células separadas por |, ; ou tab; Markdown também) em linhas de valores."""
    linhas = []
    for linha in str(conteudo).splitlines():
        if not linha.strip() or SEPARADOR_MARKDOWN.fullmatch(linha.strip()):
            continue
        linhas.append([_celula(c) for c in _celulas(linha)])
    if not linhas:
        raise ErroPlanilha("a tabela está vazia.")
    return linhas


def previa(linhas, maximo=10):
    texto = "\n".join(f"{i}: {' | '.join(documentos._valor(v) for v in linha)}"
                      for i, linha in enumerate(linhas[:maximo], 1))
    return texto + (f"\n… (+{len(linhas) - maximo} linhas)" if len(linhas) > maximo else "")


def criar(destino, linhas, aba=None):
    """Grava uma planilha .xlsx nova: cabeçalho em negrito, congelado no topo, colunas com largura boa."""
    openpyxl = documentos._importar("openpyxl", "planilhas do Excel")
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter
    livro = openpyxl.Workbook()
    folha = livro.active
    folha.title = re.sub(r"[\[\]:*?/\\]", "", aba or "Planilha1")[:31] or "Planilha1"
    for linha in linhas:
        folha.append(linha)
    for celula in folha[1]:
        celula.font = Font(bold=True)
    for linha in folha.iter_rows(min_row=2):
        for celula in linha:
            if isinstance(celula.value, datetime):
                celula.number_format = "dd/mm/yyyy"
    folha.freeze_panes = "A2"
    for indice in range(1, max(len(l) for l in linhas) + 1):
        maior = max((len(documentos._valor(l[indice - 1])) for l in linhas if indice - 1 < len(l)), default=0)
        folha.column_dimensions[get_column_letter(indice)].width = max(10, min(50, maior + 2))
    livro.save(destino)


# Editar planilhas

CONTA_PROIBIDA = "a conta só pode usar números, colunas entre colchetes (como [Preço]) e + - * /"
PECAS_PERMITIDAS = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name, ast.Load,
                    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub, ast.UAdd)
EXEMPLOS_DE_ALTERACAO = ("D5 = 99,90 · + 107 | Bateria | 450 · apagar linha 12 · "
                         "coluna Total = [Preço] * [Estoque]")


def _conta(expressao, cabecalho):
    """Função que calcula a expressão ("[Preço] * 1,1") para uma linha; só aceita contas simples.

    A expressão é conferida peça por peça antes: nada além de números, colunas e + - * /
    é executado, então o modelo não consegue rodar outra coisa disfarçada de conta.
    """
    colunas = {}

    def trocar(achado):
        indice = _coluna(cabecalho, achado.group(1))
        colunas[f"c{indice}"] = indice
        return f"c{indice}"

    texto = re.sub(r"\[([^\]]+)\]", trocar, expressao)
    texto = re.sub(r"(\d),(\d)", r"\1.\2", texto)  # 1,1 é um vírgula um
    try:
        arvore = ast.parse(texto.strip(), mode="eval")
    except SyntaxError:
        raise ErroPlanilha(CONTA_PROIBIDA)
    for peca in ast.walk(arvore):
        if (not isinstance(peca, PECAS_PERMITIDAS)
                or isinstance(peca, ast.Constant) and not isinstance(peca.value, (int, float))
                or isinstance(peca, ast.Name) and peca.id not in colunas):
            raise ErroPlanilha(CONTA_PROIBIDA)

    def avaliar(no, valores):
        if isinstance(no, ast.Expression):
            return avaliar(no.body, valores)
        if isinstance(no, ast.Constant):
            return float(no.value)
        if isinstance(no, ast.Name):
            return valores.get(colunas[no.id])
        if isinstance(no, ast.UnaryOp):
            valor = avaliar(no.operand, valores)
            return None if valor is None else (-valor if isinstance(no.op, ast.USub) else valor)
        a, b = avaliar(no.left, valores), avaliar(no.right, valores)
        if a is None or b is None:
            return None
        if isinstance(no.op, ast.Div):
            return a / b if b else None
        return {ast.Add: a + b, ast.Sub: a - b, ast.Mult: a * b}[type(no.op)]

    return lambda valores: avaliar(arvore, valores)


def _avisos(caminho):
    """O que a biblioteca perde ao salvar (ela não guarda gráficos, imagens nem macros)."""
    try:
        nomes = zipfile.ZipFile(caminho).namelist()
    except (OSError, zipfile.BadZipFile):
        return []
    perdas = [nome for pedaco, nome in (("xl/charts/", "gráficos"), ("xl/media/", "imagens"),
                                        ("xl/pivotTables/", "tabelas dinâmicas"), ("vbaProject", "macros"))
              if any(pedaco in n for n in nomes)]
    return [f"atenção: esta planilha tem {', '.join(perdas)}, que se perdem ao salvar por aqui"] if perdas else []


class Edicao:
    """Alterações numa aba, conferidas uma a uma; nada é gravado até aplicar().

    As ferramentas usam as operações separadas (mudar_onde, nova_coluna, nova_linha, apagar_onde):
    no teste real, uma minilinguagem num campo só confundia o modelo, que errava linha e coluna.
    """

    def __init__(self, caminho, aba=None):
        if str(caminho).lower().endswith(".xls"):
            raise ErroPlanilha("não edito planilhas .xls (formato antigo); posso criar uma cópia em .xlsx com "
                               "criar_planilha.")
        openpyxl = documentos._importar("openpyxl", "planilhas do Excel")
        try:
            livro = openpyxl.load_workbook(caminho)  # com as fórmulas, para elas continuarem fórmulas
            valores_livro = openpyxl.load_workbook(caminho, data_only=True)  # com os resultados, para as contas
        except Exception:
            raise ErroPlanilha("não consegui abrir esta planilha (pode estar protegida ou quebrada).")
        nomes = [f.title for f in livro.worksheets]
        nome = nomes[0] if aba is None else next(
            (n for n in nomes if documentos.normalizar(n) == documentos.normalizar(aba)), None)
        if nome is None:
            raise ErroPlanilha(f"não existe a aba {aba}; as abas são: {', '.join(nomes)}")
        self.caminho, self.livro, self.nome = caminho, livro, nome
        self.folha, self.valores = livro[nome], valores_livro[nome]
        self.total = max((r for r in range(1, self.folha.max_row + 1)
                          if any(c.value is not None for c in self.folha[r])), default=0)
        self.cabecalho = [documentos._valor(c.value) for c in self.folha[1]] if self.total else []
        while self.cabecalho and self.cabecalho[-1] == "":
            self.cabecalho.pop()
        self.passos, self.apagar, self.descricao = [], [], []
        self.avisos = _avisos(caminho)
        self.linhas_novas = self.colunas_novas = 0

    def _conteudo(self, r):
        celulas = [documentos._valor(c.value) for c in self.folha[r]]
        while celulas and celulas[-1] == "":
            celulas.pop()
        return " | ".join(celulas)

    def _linhas_onde(self, filtro):
        passa = _filtro(self.cabecalho, filtro)
        alvos = [r for r in range(2, self.total + 1)
                 if passa([documentos._valor(self.valores.cell(row=r, column=i + 1).value)
                           for i in range(len(self.cabecalho))])]
        if not alvos:
            raise ErroPlanilha(f"nenhuma linha bate com o filtro {filtro}")
        return alvos

    def mudar_onde(self, coluna, valor, filtro):
        """Muda a coluna nas linhas que batem com o filtro, sem o modelo precisar acertar o número da linha."""
        texto = str(valor).strip()
        if re.search(r"\[[^\]]+\]", texto):
            raise ErroPlanilha("um valor não pode ter colunas entre colchetes; para calcular a partir de outras "
                               "colunas, use adicionar_coluna")
        if not texto.startswith("=") and re.fullmatch(r"[\d.,\s]+([*/+][\d.,\s]+)+", texto):
            raise ErroPlanilha("o valor parece uma conta; escreva o resultado (como 142,41) ou uma fórmula do Excel "
                               "começando com =")
        indice = _coluna(self.cabecalho, coluna)
        for r in self._linhas_onde(filtro):
            antigo = documentos._valor(self.folha.cell(row=r, column=indice + 1).value) or "(vazia)"
            self.descricao.append(f"{self.cabecalho[indice]} na linha {r}: {antigo} → {texto} ({self._conteudo(r)})")
            self.passos.append(lambda r=r, indice=indice, novo=_celula(texto):
                               self.folha.cell(row=r, column=indice + 1, value=novo))

    def definir_celula(self, referencia, valor):
        if re.search(r"\[[^\]]+\]", valor):
            # No teste real, o modelo escreveu "C4 = [Preço] * 0,95" e o texto foi gravado por cima de um preço.
            raise ErroPlanilha(f"uma célula recebe um valor ou uma fórmula do Excel (começando com =); para "
                               f"calcular a partir de outras colunas, crie uma coluna nova, assim: "
                               f"coluna Nome da coluna = {valor.strip()}")
        referencia = referencia.upper()
        linha = int(re.sub(r"\D", "", referencia))
        antigo = documentos._valor(self.folha[referencia].value) or "(vazia)"
        onde_fica = f"linha {linha}: {self._conteudo(linha)}" if linha <= self.total else "linha nova"
        # A linha inteira na confirmação deixa à vista quando o modelo erra a linha.
        self.descricao.append(f"{referencia}: {antigo} → {valor.strip()} ({onde_fica})")
        self.passos.append(lambda novo=_celula(valor): self.folha.__setitem__(referencia, novo))

    def nova_coluna(self, titulo, expressao):
        titulo = str(titulo).strip()
        existente = next((c for c in self.cabecalho if documentos.normalizar(c) == documentos.normalizar(titulo)), None)
        if existente:
            raise ErroPlanilha(f"já existe a coluna {existente}; escolha outro nome")
        from openpyxl.utils import get_column_letter
        conta = _conta(expressao, self.cabecalho)
        self.colunas_novas += 1
        indice = len(self.cabecalho) + self.colunas_novas
        resultados = {}
        for r in range(2, self.total + 1):
            linha = {i: numero(documentos._valor(self.valores.cell(row=r, column=i + 1).value))
                     for i in range(len(self.cabecalho))}
            resultados[r] = conta(linha)
        calculados = sum(1 for v in resultados.values() if v is not None)
        vazias = len(resultados) - calculados
        texto = f"coluna nova {get_column_letter(indice)} ({titulo}): {calculados} valores calculados"
        if vazias:
            texto += (f"; {vazias} linha{'s' if vazias != 1 else ''} sem número "
                      f"{'ficaram vazias' if vazias != 1 else 'ficou vazia'}")
        self.descricao.append(texto)
        aviso = ("a coluna nova guarda valores fixos, calculados agora (não é fórmula do Excel): se a coluna de "
                 "origem mudar depois, ela não muda")
        if aviso not in self.avisos:
            self.avisos.append(aviso)

        def passo():
            self.folha.cell(row=1, column=indice, value=titulo)
            for r, v in resultados.items():
                self.folha.cell(row=r, column=indice, value=v)
        self.passos.append(passo)

    def nova_linha(self, celulas):
        textos = [str(c).strip() for c in celulas]
        if any(re.search(r"\[[^\]]+\]", t) for t in textos):
            raise ErroPlanilha("esta linha parece uma conta; para uma coluna calculada, use adicionar_coluna")
        while textos and textos[-1] == "":
            textos.pop()
        if self.cabecalho and len(textos) > len(self.cabecalho):
            raise ErroPlanilha(f"a planilha tem {len(self.cabecalho)} colunas ({', '.join(self.cabecalho)}), mas a "
                               f"linha tem {len(textos)} valores")
        valores = [_celula(t) for t in textos]
        self.linhas_novas += 1
        numero_linha = self.total + self.linhas_novas
        self.descricao.append(f"linha nova {numero_linha}: {' | '.join(documentos._valor(v) for v in valores)}")

        def passo():
            for j, v in enumerate(valores, 1):
                self.folha.cell(row=numero_linha, column=j, value=v)
        self.passos.append(passo)

    def apagar_linha(self, numero_linha):
        if not 1 <= numero_linha <= self.total:
            raise ErroPlanilha(f"a aba {self.nome} tem só {self.total} linhas.")
        self.descricao.append(f"apagar linha {numero_linha}: {self._conteudo(numero_linha)}")
        self.apagar.append(numero_linha)

    def apagar_onde(self, filtro):
        for r in self._linhas_onde(filtro):
            self.apagar_linha(r)

    def aplicar(self):
        for passo in self.passos:
            passo()
        for numero_linha in sorted(set(self.apagar), reverse=True):  # de baixo para cima: a numeração de antes vale
            self.folha.delete_rows(numero_linha)
        self.livro.save(self.caminho)


def preparar_edicao(caminho, alteracoes, aba=None):
    """Confere as alterações escritas numa minilinguagem (uma por linha) e devolve uma Edicao."""
    edicao = Edicao(caminho, aba)
    for linha in str(alteracoes).splitlines():
        linha = linha.strip()
        if not linha:
            continue
        onde = re.fullmatch(r"(?!coluna\s)(.+?)\s*=\s*(.+?)\s+onde\s+(.+)", linha, re.IGNORECASE)
        coluna = None if onde else re.fullmatch(r"coluna\s+(.+?)\s*=\s*(.+)", linha, re.IGNORECASE)
        celula = None if onde else re.fullmatch(r"([A-Za-z]{1,3}\d+)\s*=\s*(.*)", linha)
        if not (onde or coluna or celula):
            # "Preço com desconto = [Preço] * 0,95": no teste real, o modelo esquecia o "coluna" na frente.
            coluna = re.fullmatch(r"([^=\[\]+][^=\[\]]*?)\s*=\s*(.*\[[^\]]+\].*)", linha)
        nova = re.fullmatch(r"\+\s*(.+)", linha)
        apagada = re.fullmatch(r"apagar\s+linha\s+(\d+)", linha, re.IGNORECASE)
        if onde:
            edicao.mudar_onde(*onde.groups())
        elif coluna:
            edicao.nova_coluna(*coluna.groups())
        elif celula:
            edicao.definir_celula(*celula.groups())
        elif nova:
            edicao.nova_linha(_celulas(nova.group(1)))
        elif apagada:
            edicao.apagar_linha(int(apagada.group(1)))
        else:
            raise ErroPlanilha(f'não entendi a alteração "{linha}"; use por exemplo: {EXEMPLOS_DE_ALTERACAO}')
    if not edicao.descricao:
        raise ErroPlanilha(f"nenhuma alteração; use por exemplo: {EXEMPLOS_DE_ALTERACAO}")
    return edicao
