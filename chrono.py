#!/usr/bin/env python3
"""chrono: conversa com uma IA local (Ollama) pelo terminal."""

import argparse
import base64
import json
import re
import subprocess
import sys
import termios
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import agentes
import ferramentas
import skills

try:
    import readline  # setas e histórico do que você digita no chat
except ImportError:
    readline = None

try:
    from rich import box
    from rich.console import Console, Group
    from rich.live import Live
    from rich.markdown import Heading, Markdown
    from rich.panel import Panel
    from rich.segment import Segment
    from rich.spinner import Spinner
    from rich.style import Style
    from rich.table import Table
    from rich.text import Text
except ImportError:  # sem a rich, só a saída simples (arquivo ou pipe) funciona
    Console = None
else:
    class Titulo(Heading):
        """Título sempre à esquerda (a rich centraliza o título principal)."""
        LEVEL_ALIGN = {}

    class Formatado(Markdown):
        """Markdown da rich com os títulos à esquerda e o endereço dos links à mostra.

        Link clicável esconde o endereço, e nem todo terminal sabe abrir esse tipo de link.
        """
        elements = {**Markdown.elements, "heading_open": Titulo}

        def __init__(self, texto, **opcoes):
            opcoes.setdefault("hyperlinks", False)
            super().__init__(texto, **opcoes)

# Cores do painel.
AZUL = "#bfddf3"    # barrinha da resposta
LILAS = "#AFA9EC"   # marca "chrono"
VERDE = "#5DCAA5"   # "você ›"
CINZA = "#888780"   # detalhes
AMBAR = "#EF9F27"   # animação de espera
BORDA = "#5F5E5A"   # caixa do cabeçalho

PASTA = Path.home() / ".chrono"
CONFIG = PASTA / "config.json"
CONVERSAS = PASTA / "conversas"
DIGITADOS = PASTA / "digitados"
PASTA_AGENTES = PASTA / "agentes"
PASTA_SKILLS = PASTA / "skills"

PADRAO = {
    "modelo": "ornith-1.5:9b",
    "sistema": (
        "Você é um assistente útil que roda no terminal do usuário. "
        "Responda sempre em português do Brasil, de forma clara e direta. "
        "Evite tabelas e formatação pesada."
    ),
    "pensar": False,
    "servidor": "http://localhost:11434",
    "agente": "geral",
}

EXEMPLOS = """exemplos:
  chrono                                   abre o chat
  chrono "qual a diferença entre óleo 5W30 e 10W40?"
  chrono -c "e para motor flex?"           continua a última conversa
  cat pedido.txt | chrono "resuma"         usa um texto como contexto
  chrono -i foto.jpg "que peça é essa?"    manda uma imagem
  chrono -a atendente                      abre o chat com o agente atendente
  chrono --agentes                         lista os agentes
  chrono -s conferir-pedidos "pedido.pdf"  liga uma skill (pode repetir o -s)
  chrono --skills                          lista as skills

Os agentes ficam em ~/.chrono/agentes/ (um arquivo de texto cada, para editar no TextEdit).
O servidor e o agente padrão ficam em ~/.chrono/config.json.
As skills ficam em ~/.chrono/skills/ (uma pasta com um SKILL.md cada).
As conversas ficam salvas em ~/.chrono/conversas/."""

AJUDA_CHAT = """Comandos:
  /nova              começa uma conversa nova
  /agente [nome]     mostra os agentes ou troca de agente (começa conversa nova)
  /agente novo NOME  cria um agente e abre no TextEdit
  /agente editar     abre o agente atual no TextEdit (ou: /agente editar NOME)
  /skill [nome]      mostra as skills ou liga uma (vale para a conversa toda)
  /skill desligar [nome]  desliga uma skill (ou todas)
  /skill editar NOME abre a skill no TextEdit
  /modelo [nome]     mostra ou troca o modelo
  /pensar            liga/desliga o raciocínio antes da resposta
  /ferramentas       liga/desliga o acesso aos arquivos do Mac
  /imagem ARQUIVO    anexa uma imagem à próxima mensagem
  /sair              sai (ou Ctrl+D)
Para colar várias linhas, comece e termine com uma linha só com \"\"\"."""


class ErroIA(Exception):
    pass


def cor(codigo, texto, fluxo=sys.stdout):
    return f"\033[{codigo}m{texto}\033[0m" if fluxo.isatty() else texto


def carregar_config():
    PASTA.mkdir(exist_ok=True)
    if not CONFIG.exists():
        CONFIG.write_text(json.dumps(PADRAO, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    config = dict(PADRAO)
    try:
        config.update(json.loads(CONFIG.read_text(encoding="utf-8")))
    except ValueError as e:
        raise ErroIA(f"O arquivo {CONFIG} tem um erro: {e}")
    return config


def chamar(config, caminho, corpo=None):
    """Faz uma requisição ao Ollama e devolve a resposta aberta, para ler aos poucos."""
    req = urllib.request.Request(
        config["servidor"].rstrip("/") + caminho,
        data=json.dumps(corpo).encode() if corpo is not None else None,
        headers={"Content-Type": "application/json"},
    )
    try:
        return urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        try:
            detalhe = json.loads(e.read()).get("error", "")
        except ValueError:
            detalhe = ""
        if e.code == 404 and corpo and "model" in corpo:
            modelo = corpo["model"]
            raise ErroIA(f"O modelo '{modelo}' não está baixado. Rode: ollama pull {modelo}")
        raise ErroIA(f"O Ollama respondeu com erro: {detalhe or f'HTTP {e.code}'}")
    except urllib.error.URLError:
        raise ErroIA("Não consegui falar com o Ollama. Abra o app do Ollama ou rode: ollama serve")


def estado_ollama(config, modelo):
    """Entrada do modelo em /api/ps (memória, tamanho da conversa), ou None se não estiver carregado."""
    try:
        with chamar(config, "/api/ps") as r:
            modelos = json.load(r).get("models", [])
    except ErroIA:
        return None
    return next((m for m in modelos if mesmo_modelo(modelo, m.get("name", "")) or mesmo_modelo(modelo, m.get("model", ""))), None)


def mesmo_modelo(a, b):
    """Compara nomes de modelo; sem etiqueta, o Ollama entende ":latest" (llama3.2 = llama3.2:latest)."""
    def completo(nome):
        return nome if ":" in nome else nome + ":latest"
    return completo(a) == completo(b)


def carregar_modelo(config, modelo):
    """Deixa o modelo na memória: o cabeçalho mostra números reais e a 1ª resposta vem rápido."""
    with chamar(config, "/api/generate", {"model": modelo}) as r:
        r.read()


def listar_modelos(config):
    with chamar(config, "/api/tags") as r:
        return [m["name"] for m in json.load(r).get("models", [])]


def ler_imagem(caminho):
    try:
        return base64.b64encode(Path(caminho).expanduser().read_bytes()).decode()
    except FileNotFoundError:
        raise ErroIA(f"Imagem não encontrada: {caminho}")
    except OSError as e:
        raise ErroIA(f"Não consegui ler a imagem {caminho}: {e.strerror}")


# Formatação dos números que aparecem na tela (com vírgula, como no Brasil).

def fmt_decimal(valor, casas=1):
    return f"{valor:.{casas}f}".replace(".", ",")


def fmt_segundos(seg):
    return f"{fmt_decimal(seg)} s"


def fmt_gb(n_bytes):
    return f"{fmt_decimal(n_bytes / 1e9)} GB"


def fmt_mil(n):
    return f"{n // 1000} mil" if n >= 1000 else str(n)


def fmt_contexto(usado, total):
    pct = usado * 100 / total
    return "<1%" if pct < 1 else f"{round(pct)}%"


def resumo_modelo(nome, show, ps):
    """Linhas (rótulo, valor) do cabeçalho, a partir de /api/show e da entrada do modelo em /api/ps."""
    detalhes = show.get("details", {})
    partes = [nome]
    if detalhes.get("parameter_size"):
        partes.append(detalhes["parameter_size"].replace(".0B", "B").replace(".", ","))
    if detalhes.get("quantization_level"):
        partes.append(detalhes["quantization_level"].split("_")[0])
    if "vision" in show.get("capabilities", []):
        partes.append("lê imagens")
    if ps is None:
        memoria = "carrega na primeira pergunta"
    else:
        onde = "na GPU" if ps.get("size_vram", 0) >= ps["size"] else "(parte na CPU)"
        memoria = f"{fmt_gb(ps['size'])} {onde}"
        if ps.get("context_length"):
            memoria += f" · conversa até {fmt_mil(ps['context_length'])} tokens"
    return [("modelo", " · ".join(partes)), ("memória", memoria)]


def linha_detalhes(m, contexto_total, pensou):
    """Linha mostrada depois de cada resposta, a partir do último pedaço de /api/chat."""
    partes = [f"⏱ {fmt_segundos(m.get('total_duration', 0) / 1e9)}"]
    if m.get("eval_duration"):
        partes.append(f"⚡ {round(m['eval_count'] / (m['eval_duration'] / 1e9))} tokens/s")
    partes.append(f"✎ {m.get('eval_count', 0)} tokens")
    if contexto_total:
        usado = m.get("contexto_usado", m.get("prompt_eval_count", 0) + m.get("eval_count", 0))
        partes.append(f"▤ contexto {fmt_contexto(usado, contexto_total)}")
    if pensou is not None:
        partes.append(f"✦ pensou {fmt_segundos(pensou)}")
    return "   ".join(partes)


class Conversa:
    def __init__(self, config):
        self.config = config
        self.modelo = config["modelo"]
        self.recursos = set()
        self.pensar = config["pensar"]
        self.ferramentas = False
        self.pode_alterar = True  # sem teclado para confirmar, só as ferramentas de leitura são oferecidas
        self.so_leitura = False  # agente com "ferramentas: só leitura"
        self.skills_salvas = []  # nomes das skills ligadas na conversa carregada com -c
        self.agente = None  # None: instruções, modelo e raciocínio do config.json
        self.base = Path.cwd()  # caminhos relativos das ferramentas partem daqui
        self.reiniciar()

    def reiniciar(self):
        self.arquivo = None
        self.agente_salvo = None  # conversa nova: não herda o agente de uma conversa continuada
        sistema = self.agente.instrucoes if self.agente else self.config["sistema"]
        self.mensagens = [{"role": "system", "content": sistema}]
        self.skills = []  # conversa nova começa sem skills

    def ligar_skill(self, skill):
        """Liga a skill; se ela já estava ligada, troca pela versão lida agora e devolve True."""
        for i, ligada in enumerate(self.skills):
            if skills.normalizar(ligada.nome) == skills.normalizar(skill.nome):
                self.skills[i] = skill
                return True
        self.skills.append(skill)
        return False

    def desligar_skill(self, nome):
        antes = len(self.skills)
        self.skills = [s for s in self.skills if skills.normalizar(s.nome) != skills.normalizar(nome)]
        return len(self.skills) < antes

    def _criador_ligado(self):
        return any(skills.normalizar(s.nome) == "skill-creator" for s in self.skills)

    def _pode_criar_skill(self):
        """A ferramenta criar_skill só existe com a skill-creator ligada e podendo alterar arquivos."""
        return self._criador_ligado() and self.ferramentas and self.pode_alterar and not self.so_leitura

    def usar_agente(self, agente, nova_conversa=True, modelo=None):
        """Aplica o agente (None: o config.json). Se o modelo falhar, nada muda.

        Com nova_conversa=False (o -c), fica o histórico e o modelo da conversa salva; o
        modelo dado aqui (a opção -m) ganha do agente e da conversa.
        """
        if modelo is None:
            modelo = (agente and agente.modelo or self.config["modelo"]) if nova_conversa else self.modelo
        self.trocar_modelo(modelo)  # o erro sai daqui, antes de mudar qualquer outra coisa
        self.agente = agente
        escolha = agente.pensar if agente else None
        self.pensar = self.config["pensar"] if escolha is None else escolha
        self.ferramentas = "tools" in self.recursos and not self._sem_ferramentas()
        self.so_leitura = bool(agente) and agente.ferramentas == "leitura"
        if nova_conversa:
            self.reiniciar()

    def _proibida(self, nome):
        """Ferramenta que altera algo, pedida num agente só leitura (o modelo pode inventar uma)."""
        if not self.so_leitura:
            return False
        leitura = {d["function"]["name"] for d in ferramentas.definicoes(alterar=False)}
        todas = {d["function"]["name"] for d in ferramentas.definicoes(alterar=True)}
        return nome in todas - leitura

    def _sem_ferramentas(self):
        return bool(self.agente) and self.agente.ferramentas == "desligadas"

    def carregar_ultima(self):
        arquivos = sorted(CONVERSAS.glob("*.json"))
        if not arquivos:
            raise ErroIA("Ainda não há conversa salva para continuar.")
        dados = json.loads(arquivos[-1].read_text(encoding="utf-8"))
        self.arquivo = arquivos[-1]
        self.mensagens = dados["mensagens"]
        self.modelo = dados.get("modelo", self.modelo)
        self.agente_salvo = dados.get("agente")
        self.skills_salvas = dados.get("skills") or []

    def trocar_modelo(self, modelo):
        # Também confere se o modelo existe antes de trocar.
        with chamar(self.config, "/api/show", {"model": modelo}) as r:
            self.show = json.load(r)
        self.recursos = set(self.show.get("capabilities", []))
        self.modelo = modelo
        self.ferramentas = "tools" in self.recursos and not self._sem_ferramentas()

    def descricao(self):
        """"nova" ou "continuação de 02/11 20:31", tirado do nome do arquivo da conversa."""
        if self.arquivo is None:
            return "nova"
        try:
            quando = datetime.strptime(self.arquivo.stem[:17], "%Y-%m-%d_%H%M%S")
        except ValueError:  # arquivo com outro nome: usa a data da última modificação
            quando = datetime.fromtimestamp(self.arquivo.stat().st_mtime)
        return "continuação de " + quando.strftime("%d/%m %H:%M")

    def salvar(self):
        if self.arquivo is None:
            CONVERSAS.mkdir(parents=True, exist_ok=True)
            self.arquivo = CONVERSAS / (datetime.now().strftime("%Y-%m-%d_%H%M%S_%f") + ".json")
        # Com -c e o arquivo do agente indisponível, o nome continua guardado na conversa.
        dados = {"modelo": self.modelo, "agente": self.agente.nome if self.agente else self.agente_salvo,
                 "skills": [s.nome for s in self.skills], "mensagens": self.mensagens}
        self.arquivo.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")

    def perguntar(self, texto, imagens=(), exibidor=None):
        mensagem = {"role": "user", "content": texto}
        if imagens:
            if "vision" not in self.recursos:
                raise ErroIA(f"O modelo {self.modelo} não lê imagens.")
            mensagem["images"] = [ler_imagem(c) for c in imagens]
        inicio = len(self.mensagens)
        self.mensagens.append(mensagem)
        try:
            resposta = self._transmitir(exibidor or ExibidorSimples())
        except Exception:
            self._desfazer(inicio)
            raise
        if not resposta and len(self.mensagens) == inicio + 1:  # interrompida antes de qualquer coisa
            del self.mensagens[inicio:]
            return ""
        self.mensagens.append({"role": "assistant", "content": resposta})
        self.salvar()
        return resposta

    def _desfazer(self, inicio):
        """Depois de um erro, tira a pergunta do histórico.

        Se alguma ferramenta já tinha rodado, guarda até o último resultado dela (e uma nota do
        erro), para a conversa lembrar do que já foi feito no Mac.
        """
        feitas = [i for i in range(inicio, len(self.mensagens)) if self.mensagens[i]["role"] == "tool"]
        if not feitas:
            del self.mensagens[inicio:]
            return
        del self.mensagens[feitas[-1] + 1:]
        self.mensagens.append({"role": "assistant", "content": "(a resposta foi interrompida por um erro)"})
        self.salvar()

    def _transmitir(self, exibidor):
        """Manda a conversa ao modelo e entrega os pedaços ao exibidor conforme chegam.

        Quando o modelo pede ferramentas, roda cada uma, devolve os resultados e pergunta de novo,
        até ele responder só com texto; depois de LIMITE_RODADAS rodadas, pergunta sem ferramentas.
        Devolve o texto da última rodada. Guarda em self.metricas a soma das rodadas e em
        self.pensou quantos segundos o modelo raciocinou antes da primeira palavra.
        """
        self.metricas = None
        self.pensou = None
        self._comecou_a_pensar = None
        self._parcial = []
        rodadas = []
        confirmar = Confirmador(exibidor)
        exibidor.inicio()
        try:
            for rodada in range(LIMITE_RODADAS + 1):
                com_ferramentas = self.ferramentas and rodada < LIMITE_RODADAS
                texto, pedidos, metricas = self._rodada(exibidor, com_ferramentas)
                rodadas.append(metricas)
                if not (pedidos and com_ferramentas):
                    break
                self.mensagens.append({"role": "assistant", "content": texto, "tool_calls": pedidos})
                for pedido in pedidos:
                    self._usar_ferramenta(pedido, confirmar, exibidor)
                if rodada == LIMITE_RODADAS - 1:
                    exibidor.acao(f"limite de {LIMITE_RODADAS} rodadas de ferramenta", False)
        except KeyboardInterrupt:
            exibidor.interrompido()
            return "".join(self._parcial)
        except ErroIA:
            exibidor.fim(None, None, None)
            raise
        except OSError:
            exibidor.fim(None, None, None)
            raise ErroIA("A conexão com o Ollama caiu no meio da resposta.")
        except Exception:
            exibidor.fim(None, None, None)
            raise
        self.metricas = somar_metricas(rodadas)
        ps = estado_ollama(self.config, self.modelo)
        exibidor.fim(self.metricas, ps and ps.get("context_length"), self.pensou)
        return texto

    def _rodada(self, exibidor, com_ferramentas):
        """Uma ida e volta ao modelo. Devolve (texto, pedidos de ferramenta, métricas)."""
        mensagens = self.mensagens
        # Só no pedido, não no histórico: a pasta atual muda de uma vez para outra, e as skills
        # ligadas valem enquanto estiverem ligadas.
        extra = ""
        if com_ferramentas:
            modelo_do_contexto = CONTEXTO_LEITURA if self.so_leitura else CONTEXTO_FERRAMENTAS
            extra = modelo_do_contexto.format(pasta=ferramentas.abreviar(self.base))
        extra += "".join("\n\n" + skills.texto_para_o_modelo(s) for s in self.skills)
        if self._criador_ligado() and not self._pode_criar_skill():
            extra += SEM_CRIAR_SKILL  # senão o modelo chama uma ferramenta que não existe
        if extra and mensagens[0]["role"] == "system":
            mensagens = [dict(mensagens[0], content=mensagens[0]["content"] + extra)] + mensagens[1:]
        corpo = {"model": self.modelo, "messages": mensagens}
        if "thinking" in self.recursos:
            corpo["think"] = self.pensar
        if com_ferramentas:
            corpo["tools"] = ferramentas.definicoes(alterar=self.pode_alterar and not self.so_leitura,
                                                   imagens="vision" in self.recursos)
            if self._pode_criar_skill():
                corpo["tools"].append(skills.DEFINICAO_CRIAR_SKILL)
        ja_escreveu = bool(self._parcial)
        self._parcial = []
        pedidos = []
        metricas = None
        with chamar(self.config, "/api/chat", corpo) as r:
            for linha in r:
                pedaco = json.loads(linha)
                if "error" in pedaco:
                    raise ErroIA(f"O Ollama respondeu com erro: {pedaco['error']}")
                if pedaco.get("done"):
                    metricas = pedaco
                mensagem = pedaco.get("message", {})
                if mensagem.get("thinking"):
                    if self._comecou_a_pensar is None:
                        self._comecou_a_pensar = time.monotonic()
                    exibidor.pensando(mensagem["thinking"])
                pedidos += mensagem.get("tool_calls") or []
                texto = mensagem.get("content", "")
                if not self._parcial:
                    texto = texto.lstrip()
                if texto:
                    if self._comecou_a_pensar is not None and self.pensou is None:
                        self.pensou = time.monotonic() - self._comecou_a_pensar
                    if not self._parcial and ja_escreveu:
                        exibidor.texto("\n\n")  # separa do texto de uma rodada anterior
                    exibidor.texto(texto)
                    self._parcial.append(texto)
        return "".join(self._parcial), pedidos, metricas

    def _usar_ferramenta(self, pedido, confirmar, exibidor):
        funcao = pedido.get("function", {})
        nome = funcao.get("name", "")
        exibidor.usando_ferramentas()
        if nome == "criar_skill" and self._pode_criar_skill():
            resultado = skills.criar_skill(PASTA_SKILLS, funcao.get("arguments", {}), confirmar)
        elif self._proibida(nome):
            resultado = ferramentas.Resultado(
                texto=f"erro: este agente só pode ler arquivos; a ferramenta {nome} não está disponível.",
                resumo=f"{nome}: este agente só pode ler arquivos")
        else:
            resultado = ferramentas.executar(nome, funcao.get("arguments", {}), confirmar, self.base)
        exibidor.acao(resultado.resumo, resultado.alterou)
        mensagem = {"role": "tool", "tool_name": nome, "content": resultado.texto}
        if resultado.imagens:
            mensagem["images"] = resultado.imagens
        self.mensagens.append(mensagem)


LIMITE_RODADAS = 10

# Vai junto do prompt de sistema quando as ferramentas estão ligadas. Sem isso, no teste com o
# modelo real, ele pedia o caminho dos arquivos em vez de usar as ferramentas.
CONTEXTO_FERRAMENTAS = (
    "\n\nVocê tem ferramentas para ver e organizar os arquivos do Mac do usuário. "
    "A pasta atual, onde o chrono foi aberto, é {pasta}: quando o usuário falar de \"esta pasta\" "
    "ou citar um arquivo sem caminho, é dela que ele fala. Use as ferramentas por conta própria "
    "sempre que precisar, em vez de pedir caminhos ao usuário: liste a pasta ou procure o arquivo "
    "pelo nome. As alterações pedem confirmação ao usuário automaticamente, então não pergunte "
    "antes de chamar a ferramenta."
)

# Vai junto da skill-creator quando a ferramenta criar_skill não pode ser oferecida.
SEM_CRIAR_SKILL = (
    "\n\nA ferramenta criar_skill não está disponível agora: no fim, em vez de chamá-la, mostre o "
    "SKILL.md completo (o cabeçalho com name e description e as instruções) para o usuário copiar e "
    "salvar em ~/.chrono/skills/NOME/SKILL.md."
)

# A versão para agentes "ferramentas: só leitura": sem o convite para alterar arquivos.
CONTEXTO_LEITURA = (
    "\n\nVocê tem ferramentas para ver e ler os arquivos do Mac do usuário, mas não pode alterar nada: "
    "não crie, não mova, não apague e não mude arquivos. "
    "A pasta atual, onde o chrono foi aberto, é {pasta}: quando o usuário falar de \"esta pasta\" "
    "ou citar um arquivo sem caminho, é dela que ele fala. Use as ferramentas por conta própria "
    "sempre que precisar, em vez de pedir caminhos ao usuário: liste a pasta ou procure o arquivo "
    "pelo nome."
)


def somar_metricas(lista):
    """Junta as métricas das rodadas: tempos e tokens somados, o resto (contexto) da última."""
    lista = [m for m in lista if m]
    if not lista:
        return None
    total = dict(lista[-1])
    # A conversa inteira cabe no prompt da última rodada mais o que ela escreveu.
    total["contexto_usado"] = lista[-1].get("prompt_eval_count", 0) + lista[-1].get("eval_count", 0)
    for chave in ("total_duration", "eval_count", "eval_duration"):
        total[chave] = sum(m.get(chave, 0) for m in lista)
    return total


class Confirmador:
    """Pergunta antes de cada alteração; "t" (todas) aprova as restantes da mesma pergunta.

    Com sempre_perguntar (substituir um arquivo, que apaga o conteúdo antigo), pergunta mesmo
    depois de um "t".
    """

    def __init__(self, exibidor):
        self.exibidor = exibidor
        self.todas = False

    def __call__(self, pergunta, detalhe=None, sempre_perguntar=False):
        if self.todas and not sempre_perguntar:
            return True
        resposta = self.exibidor.perguntar(pergunta, detalhe).strip().lower()
        if resposta in ("t", "todas"):
            self.todas = True
            return True
        return resposta in ("s", "sim")


class ExibidorSimples:
    """Para quando a saída não vai para a tela (arquivo ou pipe): só o texto puro da resposta."""

    def inicio(self):
        pass

    def pensando(self, texto):
        pass

    def texto(self, pedaco):
        sys.stdout.write(pedaco)
        sys.stdout.flush()

    def fim(self, metricas, contexto_total, pensou):
        sys.stdout.write("\n")

    def acao(self, resumo, alterou):
        pass

    def usando_ferramentas(self):
        pass

    def perguntar(self, pergunta, detalhe):
        return ""  # sem tela para perguntar: as alterações são recusadas

    def interrompido(self):
        sys.stderr.write(cor("2", " [interrompido]", sys.stderr))
        sys.stderr.flush()
        sys.stdout.write("\n")


# Desenho com a rich.

def separar_blocos(texto):
    """Separa os blocos já terminados (parágrafos, listas, código) do trecho que ainda está chegando.

    Um bloco termina numa linha em branco, menos dentro de um bloco de código (```) e quando
    a linha seguinte vem recuada (continuação de um item de lista). Enquanto a linha seguinte
    não começou a chegar, o bloco fica em aberto.
    """
    blocos, atual, em_codigo = [], [], False
    todas = texto.split("\n")
    for i, linha in enumerate(todas[:-1]):  # a última linha pode ainda estar chegando
        if linha.strip().startswith("```"):
            em_codigo = not em_codigo
        if linha.strip() or em_codigo:
            atual.append(linha)
        elif atual:
            seguinte = todas[i + 1]
            if seguinte == "" or seguinte[0] in " \t":
                atual.append(linha)
            else:
                blocos.append("\n".join(atual).rstrip())
                atual = []
    return blocos, "\n".join(atual + todas[-1:])


def linha_vazia(linha):
    """Linha sem texto e sem fundo colorido (a margem de um bloco de código tem fundo e fica)."""
    return not "".join(s.text for s in linha).strip() and not any(s.style and s.style.bgcolor for s in linha)


class Barra:
    """Desenha qualquer conteúdo com uma barrinha colorida à esquerda.

    Pula as linhas vazias do começo (a rich põe uma antes de toda lista). Com separar=True,
    uma linha só com a barrinha vem antes, separando este bloco do anterior.
    """

    def __init__(self, conteudo, cor=AZUL, separar=False):
        self.conteudo = conteudo
        self.cor = cor
        self.separar = separar

    def __rich_console__(self, console, options):
        barra = Segment("▎ ", Style(color=self.cor))
        linhas = console.render_lines(self.conteudo, options.update_width(options.max_width - 2), pad=False)
        while linhas and linha_vazia(linhas[0]):
            linhas.pop(0)
        if self.separar:
            yield barra
            yield Segment.line()
        for linha in linhas:
            yield barra
            yield from linha
            yield Segment.line()


CONTROLES = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def limpar(texto):
    """Tira caracteres de controle (menos quebra de linha e tab) do que vai para a tela.

    Texto de arquivos ou do modelo com códigos do terminal poderia apagar linhas ou disfarçar
    a pergunta de confirmação.
    """
    return CONTROLES.sub("", texto)


def desligar_eco():
    """Desliga o eco do teclado enquanto algo é desenhado ao vivo e devolve o estado anterior.

    Sem isso, o que se digita (até o ^C e o Enter) empurra a parte ao vivo uma linha para
    baixo; o que rola para o histórico não se apaga e fica repetido.
    """
    try:
        fd = sys.stdin.fileno()
        antes = termios.tcgetattr(fd)
    except (OSError, ValueError, termios.error):  # a entrada não é um terminal
        return None
    novo = list(antes)
    novo[3] &= ~(termios.ECHO | termios.ECHOCTL)
    termios.tcsetattr(fd, termios.TCSANOW, novo)
    return antes


def religar_eco(antes):
    if antes is not None:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, antes)


class Cauda:
    """Mostra só as últimas linhas de um conteúdo, para o bloco em andamento caber na tela.

    Sem isso, a rich mostra o começo de um bloco maior que a tela e "..." no lugar do resto,
    e a resposta parece parada até o bloco terminar.
    """

    def __init__(self, conteudo):
        self.conteudo = conteudo

    def __rich_console__(self, console, options):
        linhas = console.render_lines(self.conteudo, options, pad=False)
        for linha in linhas[-max(1, console.size.height - 2):]:
            yield from linha
            yield Segment.line()


class Espera:
    """Animação de espera com os segundos contando: "carregando o modelo… 1,2 s"."""

    def __init__(self, fase="carregando o modelo"):
        self.fase = fase
        self.comeco = time.monotonic()
        self.spinner = Spinner("dots", style=AMBAR)

    def trocar(self, fase):
        self.fase = fase
        self.comeco = time.monotonic()

    def __rich_console__(self, console, options):
        segundos = fmt_segundos(time.monotonic() - self.comeco)
        self.spinner.text = Text(f"{self.fase}… {segundos}", style=AMBAR)
        yield self.spinner


class ExibidorRico:
    """Desenha a resposta no estilo do painel B.

    Cada bloco é formatado assim que termina de chegar e impresso uma vez só; só o bloco
    em andamento fica "ao vivo", assim respostas maiores que a tela não repetem nem piscam.
    """

    def __init__(self, console):
        self.console = console

    def inicio(self):
        self.resto = ""
        self.impressos = 0
        self._animar("carregando o modelo")

    def _animar(self, fase):
        self.espera = Espera(fase)
        self.eco = desligar_eco()
        self.ao_vivo = Live(self.espera, console=self.console, transient=True, refresh_per_second=10)
        self.ao_vivo.start()

    def pensando(self, texto):
        if self.espera.fase != "pensando":
            self.espera.trocar("pensando")

    def _fechar_texto(self):
        """O texto que anunciou a ação ("Vou ver a pasta.") sai inteiro antes dela."""
        if self.resto.strip():
            self.console.print(self._bloco(self.resto))
            self.impressos += 1
            self.resto = ""

    def usando_ferramentas(self):
        self._fechar_texto()
        self.espera.trocar("usando as ferramentas")
        if self.ao_vivo is not None:
            self.ao_vivo.update(self.espera)

    def acao(self, resumo, alterou):
        self._fechar_texto()
        simbolo, estilo = ("◆", LILAS) if alterou else ("◇", CINZA)
        self.console.print(Text(f"{simbolo} {limpar(resumo)}", style=estilo))
        self.espera.trocar("pensando")  # agora o modelo lê o resultado
        if self.ao_vivo is not None:
            self.ao_vivo.update(self.espera)

    def perguntar(self, pergunta, detalhe):
        """Pausa a animação, mostra a prévia e pergunta; Ctrl+C ou fim da entrada contam como não."""
        if not sys.stdin.isatty():
            return ""
        self._parar()
        if detalhe:
            self.console.print(Barra(Text(limpar(detalhe), style=CINZA), cor=CINZA))
        try:
            # O que foi digitado antes de a pergunta aparecer não pode respondê-la.
            termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
        except (OSError, ValueError, termios.error):
            pass
        if readline:  # a resposta ("s") não entra no histórico do que se digita no chat
            readline.set_auto_history(False)
        try:
            resposta = ler_resposta(prompt_colorido(self.console, f"? {limpar(pergunta)} (s/n/t)", AMBAR))
        except (KeyboardInterrupt, EOFError):
            self.console.print()
            resposta = ""
        finally:
            if readline:
                readline.set_auto_history(True)
        self._animar("pensando")
        return resposta

    def _bloco(self, texto):
        return Barra(Formatado(texto), separar=self.impressos > 0)

    def texto(self, pedaco):
        if self.impressos == 0 and not self.resto:
            self.console.print(Barra(Text("chrono", style=LILAS)))
        blocos, self.resto = separar_blocos(self.resto + limpar(pedaco))
        for bloco in blocos:
            self.console.print(self._bloco(bloco))
            self.impressos += 1
        self.ao_vivo.update(Cauda(self._bloco(self.resto)) if self.resto.strip() else Text(""))

    def _parar(self):
        if self.ao_vivo is None:  # já parado
            return
        # Esvazia a parte ao vivo antes de parar: o stop() redesenha tudo o que ela mostra,
        # e o que já rolou para o histórico não se apaga, ficando repetido.
        self.ao_vivo.update(Text(""), refresh=True)
        self.ao_vivo.stop()
        self.ao_vivo = None
        religar_eco(self.eco)
        if self.resto.strip():
            self.console.print(self._bloco(self.resto))
            self.impressos += 1
        self.resto = ""

    def fim(self, metricas, contexto_total, pensou):
        self._parar()
        if metricas:
            self.console.print(Text("  " + linha_detalhes(metricas, contexto_total, pensou), style=CINZA))

    def interrompido(self):
        self._parar()
        self.console.print(Text("  [interrompido]", style=CINZA))


def cabecalho(nome, show, ps, conversa, raciocinio, ferramentas, agente=""):
    """Caixa mostrada ao abrir o chat, com o agente e os dados do modelo e da conversa."""
    tabela = Table.grid(padding=(0, 1))
    tabela.add_column(style=CINZA, min_width=8, no_wrap=True)
    tabela.add_column()
    estado = f"{conversa} · raciocínio {raciocinio} · ferramentas {ferramentas}"
    linhas = [("agente", Text(agente))] if agente else []  # Text: colchetes no nome não viram estilo
    for rotulo, valor in linhas + resumo_modelo(nome, show, ps) + [("conversa", estado)]:
        tabela.add_row(rotulo, valor)
    titulo = Text.assemble(("◆ chrono", LILAS), (" — IA local no seu Mac", CINZA))
    return Panel(Group(titulo, tabela), box=box.ROUNDED, border_style=BORDA, expand=False)


def descrever_agente(conversa):
    """"atendente · rascunha respostas…", para o cabeçalho e o /agente."""
    agente = conversa.agente
    if agente is None and conversa.agente_salvo:
        return f"{conversa.agente_salvo} (arquivo do agente indisponível; usando o config.json)"
    if agente is None:
        return f"{conversa.config['agente']} (padrão do config.json)"
    return f"{agente.nome} · {agente.descricao}" if agente.descricao else agente.nome


def lista_de_agentes(atual):
    """Os agentes, um por linha, com a descrição; o atual marcado com ●."""
    lista = agentes.listar(PASTA_AGENTES)
    if not lista:
        return "Ainda não há agentes em ~/.chrono/agentes."
    largura = max(len(nome) for nome, _ in lista)
    marca = (lambda nome: "●" if atual and agentes.normalizar(nome) == agentes.normalizar(atual) else " ")
    return "\n".join(f"{marca(nome)} {nome.ljust(largura)}   {descricao}" for nome, descricao in lista)


def prompt_colorido(console, texto="você ›", cor=VERDE):
    """Prompt colorido ("você › " em verde), pronto para o input().

    O código da cor vai entre \\001 e \\002 para o readline não contá-lo como letras.
    Só vai o código que liga a cor: o readline do Mac escreve esses trechos todos antes
    do texto, então o que desliga a cor é escrito pelo ler_resposta, depois do Enter.
    """
    with console.capture() as captura:
        console.print(Text("x", style=cor), end="")
    liga = re.match(r"\x1b\[[0-9;]*m", captura.get())
    return (f"\001{liga.group()}\002" if liga else "") + texto + " "


def ler_resposta(prompt):
    """input() com o prompt colorido, desligando a cor depois (ela pinta também o que foi digitado)."""
    try:
        return input(prompt)
    finally:
        if sys.stdout.isatty():
            sys.stdout.write("\033[0m")
            sys.stdout.flush()


def ler_entrada(prompt):
    """Lê uma mensagem do chat; um bloco entre linhas com \"\"\" vira uma mensagem só."""
    linha = ler_resposta(prompt)
    if linha.strip() != '"""':
        return linha
    linhas = []
    while True:
        linha = input("")
        if linha.strip() == '"""':
            return "\n".join(linhas)
        linhas.append(linha)


def abrir(console, conversa):
    """Carrega o modelo (com a animação de espera) e mostra a caixa de cabeçalho."""
    eco = desligar_eco()
    try:
        with Live(Espera(), console=console, transient=True, refresh_per_second=10):
            carregar_modelo(conversa.config, conversa.modelo)
    finally:
        religar_eco(eco)
    if "thinking" not in conversa.recursos:
        raciocinio = "indisponível"
    else:
        raciocinio = "ligado" if conversa.pensar else "desligado"
    if "tools" not in conversa.recursos:
        estado_ferramentas = "indisponíveis"
    elif not conversa.ferramentas:
        estado_ferramentas = "desligadas"
    else:
        estado_ferramentas = "só leitura" if conversa.so_leitura else "ligadas"
    ps = estado_ollama(conversa.config, conversa.modelo)
    console.print(cabecalho(conversa.modelo, conversa.show, ps, conversa.descricao(), raciocinio,
                            estado_ferramentas, descrever_agente(conversa)))
    console.print(Text("/ajuda mostra os comandos · Ctrl+D sai", style=CINZA))


def comando(conversa, texto, pendentes, console):
    """Executa um comando do chat. Devolve False quando é para sair."""
    nome, _, resto = texto.partition(" ")
    resto = resto.strip()
    if nome in ("/sair", "/exit", "/quit"):
        return False
    if nome == "/ajuda":
        print(AJUDA_CHAT)
    elif nome == "/nova":
        tinha_skills = bool(conversa.skills)
        conversa.reiniciar()
        print(cor("2", "Conversa nova." + (" Skills desligadas." if tinha_skills else "")))
    elif nome == "/skill":
        comando_skill(conversa, resto, console)
    elif nome == "/agente":
        comando_agente(conversa, resto, console)
    elif nome == "/modelo":
        if not resto:
            print(cor("2", f"Modelo: {conversa.modelo}"))
            return True
        anterior = (conversa.modelo, conversa.show, conversa.recursos, conversa.ferramentas)
        try:
            conversa.trocar_modelo(resto)
            abrir(console, conversa)
        except (ErroIA, KeyboardInterrupt) as e:
            # O novo modelo não existe, não carregou ou a troca foi interrompida: fica o de antes.
            conversa.modelo, conversa.show, conversa.recursos, conversa.ferramentas = anterior
            print(cor("31", str(e)) if isinstance(e, ErroIA) else cor("2", "[interrompido]"))
            print(cor("2", f"Continua com {conversa.modelo}."))
    elif nome == "/ferramentas":
        if "tools" not in conversa.recursos:
            print(cor("2", f"O modelo {conversa.modelo} não sabe usar ferramentas."))
        else:
            conversa.ferramentas = not conversa.ferramentas
            print(cor("2", "Ferramentas " + ("ligadas." if conversa.ferramentas else "desligadas.")))
    elif nome == "/pensar":
        if "thinking" not in conversa.recursos:
            print(cor("2", f"O modelo {conversa.modelo} não tem modo de raciocínio."))
        else:
            conversa.pensar = not conversa.pensar
            print(cor("2", "Raciocínio " + ("ligado." if conversa.pensar else "desligado.")))
    elif nome == "/imagem":
        # Arrastar um arquivo para o Terminal cola o caminho com aspas ou "\ " nos espaços.
        caminho = resto.strip("'\"").replace("\\ ", " ")
        if not caminho:
            print("Use: /imagem caminho/da/foto.jpg")
        elif not Path(caminho).expanduser().is_file():
            print(cor("31", f"Arquivo não encontrado: {caminho}"))
        else:
            pendentes.append(caminho)
            print(cor("2", "Imagem anexada à próxima mensagem."))
    else:
        print(cor("31", f"Comando desconhecido: {nome}. Digite /ajuda."))
    return True


def abrir_no_textedit(caminho):
    """Abre o arquivo no TextEdit: um comando fixo do chrono, nunca escolhido pelo modelo."""
    try:
        abriu = subprocess.run(["open", "-e", str(caminho)], capture_output=True, check=False).returncode == 0
    except OSError:
        abriu = False
    if not abriu:
        print(f"Não consegui abrir o TextEdit; o arquivo está em {ferramentas.abreviar(caminho)}")


NOVO = object()  # o item "+ criar agente novo" do menu
TITULO_MENU = "Escolha o agente   ↑↓ escolher · Enter trocar · e editar · Esc sair"


def trocar_agente(conversa, nome, console):
    """/agente NOME: conversa nova com o agente; se o modelo dele falhar, fica o de antes."""
    atual = conversa.agente.nome if conversa.agente else None
    agente = agentes.carregar(PASTA_AGENTES, nome)
    estado = dict(vars(conversa))
    tinha_skills = bool(conversa.skills)
    try:
        conversa.usar_agente(agente)
        abrir(console, conversa)
        if tinha_skills:
            print(cor("2", "Skills desligadas."))
    except (ErroIA, KeyboardInterrupt) as e:
        # O modelo do agente não existe, não carregou ou a troca foi interrompida.
        vars(conversa).update(estado)
        print(cor("31", str(e)) if isinstance(e, ErroIA) else cor("2", "[interrompido]"))
        print(cor("2", f"Continua com o agente {atual or conversa.config['agente']}."))


def criar_agente(nome):
    arquivo = agentes.criar_novo(PASTA_AGENTES, nome)
    print(cor("2", f"Criei o agente {nome} em {ferramentas.abreviar(arquivo)}. "
                   f"Depois de salvar, use /agente {nome}."))
    abrir_no_textedit(arquivo)


def editar_agente(conversa, nome):
    if not nome and conversa.agente is None:
        print(f"O agente atual vem do config.json; para editar o {conversa.config['agente']}, "
              f"use /agente editar {conversa.config['agente']}.")
        return
    arquivo = agentes.caminho(PASTA_AGENTES, nome) if nome else conversa.agente.arquivo
    abrir_no_textedit(arquivo)
    print(cor("2", f"A mudança vale na próxima vez que você usar /agente {arquivo.stem}."))


def perguntar_nome_novo(console):
    """O nome do agente a criar; vazio se a pessoa desistir (Enter vazio, Esc, Ctrl+C ou Ctrl+D)."""
    import menu  # só aqui: precisa da rich, que a saída simples dispensa

    return menu.ler_texto(console, "Nome do agente novo:", "Enter cria · Esc desiste") or ""


def menu_de_agentes(conversa, console):
    """/agente no terminal: escolher com as setas, Enter troca, "e" edita, Esc sai."""
    import menu  # só aqui: o menu precisa da rich, que a saída simples dispensa

    atual = conversa.agente.nome if conversa.agente else None
    itens = []
    for nome, descricao in agentes.listar(PASTA_AGENTES):
        e_o_atual = atual is not None and agentes.normalizar(nome) == agentes.normalizar(atual)
        itens.append(menu.Item(nome, descricao, marca="●" if e_o_atual else " ", valor=nome,
                               erro=descricao.startswith("⚠")))
    posicao = next((i for i, item in enumerate(itens) if item.marca == "●"), 0)
    itens.append(menu.Item("+ criar agente novo", valor=NOVO))
    escolha = menu.escolher(console, menu.Menu(TITULO_MENU, itens, posicao), teclas=("e",))
    if escolha is None:
        print(cor("2", f"Continua com o agente {descrever_agente(conversa)}."))
        return
    tecla, item = escolha
    if item.valor is NOVO:
        if tecla != "enter":
            return
        nome = perguntar_nome_novo(console)
        if nome:
            criar_agente(nome)
        else:
            print(cor("2", "Nenhum agente criado."))
    elif tecla == "e":
        editar_agente(conversa, item.valor)
    elif item.marca == "●" and len(conversa.mensagens) > 1:
        # Enter no agente atual não apaga a conversa; recarregar o arquivo é com /agente NOME.
        print(cor("2", f"Você já está no agente {item.valor}; a conversa continua. "
                       f"Para recarregar o arquivo dele, use /agente {item.valor}."))
    else:
        trocar_agente(conversa, item.valor, console)


def texto_do_prompt(conversa):
    """ "você ›", ou "você · a, b ›" com skills ligadas, para nunca ficar uma ligada sem perceber."""
    if not conversa.skills:
        return "você ›"
    return "você · " + ", ".join(s.nome for s in conversa.skills) + " ›"


AVISO_CRIADOR = ("A skill-creator precisa das ferramentas ligadas para salvar a skill; com este agente ela "
                 "só consegue escrever o texto para você copiar.")


def ligar_skill(conversa, nome):
    skill = skills.carregar(PASTA_SKILLS, nome)
    recarregada = conversa.ligar_skill(skill)
    print(cor("2", f"Skill {skill.nome} {'recarregada' if recarregada else 'ligada'}."))
    if skills.normalizar(skill.nome) == "skill-creator" and not conversa._pode_criar_skill():
        print(cor("2", AVISO_CRIADOR))
    return skill


def lista_de_skills(ligadas):
    """As skills, uma por linha, com a descrição; as ligadas marcadas com ✓."""
    lista = skills.listar(PASTA_SKILLS)
    if not lista:
        return "Ainda não há skills em ~/.chrono/skills."
    largura = max(len(nome) for nome, _ in lista)
    ligadas = {skills.normalizar(nome) for nome in ligadas}
    return "\n".join(f"{'✓' if skills.normalizar(nome) in ligadas else ' '} {nome.ljust(largura)}   {descricao}"
                     for nome, descricao in lista)


def menu_de_skills(conversa, console):
    """/skill no terminal: Enter liga e desliga (o menu continua aberto), "e" edita, Esc sai."""
    import menu  # só aqui: precisa da rich, que a saída simples dispensa

    ligadas = {skills.normalizar(s.nome) for s in conversa.skills}
    criador_antes = conversa._criador_ligado()
    itens = [menu.Item(nome, descricao, marca="✓" if skills.normalizar(nome) in ligadas else " ", valor=nome,
                       erro=descricao.startswith("⚠")) for nome, descricao in skills.listar(PASTA_SKILLS)]
    itens.append(menu.Item("+ criar skill nova", valor=NOVO))
    avisos = []

    def alternar(item):
        if item.valor is NOVO:
            return True
        if item.marca == "✓":
            conversa.desligar_skill(item.valor)
            item.marca = " "
            return False
        try:
            skill = skills.carregar(PASTA_SKILLS, item.valor)
        except skills.ErroSkill as e:
            avisos.append(maiuscula(str(e)))
            return False
        conversa.ligar_skill(skill)
        item.marca = "✓"
        return False

    titulo = "Skills   ↑↓ escolher · Enter liga/desliga · e editar · Esc sair"
    escolha = menu.escolher(console, menu.Menu(titulo, itens), teclas=("e",), alternar=alternar)
    for aviso in avisos:
        print(cor("31", aviso))
    if escolha and escolha[1].valor is NOVO and escolha[0] == "enter":
        ligar_skill(conversa, "skill-creator")
        print(cor("2", "A skill-creator está ligada: diga que skill você quer criar."))
        return
    if escolha and escolha[1].valor is not NOVO:  # "e": abrir no TextEdit
        editar_skill(escolha[1].valor)
    nomes = ", ".join(s.nome for s in conversa.skills)
    print(cor("2", f"Skills ligadas: {nomes}" if nomes else "Nenhuma skill ligada."))
    if conversa._criador_ligado() and not criador_antes and not conversa._pode_criar_skill():
        print(cor("2", AVISO_CRIADOR))


def editar_skill(nome):
    arquivo = skills.caminho(PASTA_SKILLS, nome)
    abrir_no_textedit(arquivo)
    print(cor("2", f"A mudança vale na próxima vez que você ligar a skill (/skill {arquivo.parent.name})."))


def comando_skill(conversa, resto, console):
    """/skill (o menu), /skill NOME, /skill desligar [NOME] e /skill editar NOME."""
    acao, _, nome = resto.partition(" ")
    nome = nome.strip()
    try:
        if not resto and console.is_terminal and not console.is_dumb_terminal and sys.stdin.isatty():
            menu_de_skills(conversa, console)
        elif not resto:
            print(lista_de_skills(s.nome for s in conversa.skills))
            print(cor("2", "Use: /skill NOME · desligar: /skill desligar [NOME] · editar: /skill editar NOME"))
        elif acao == "desligar" and nome:
            print(cor("2", f"Skill {nome} desligada." if conversa.desligar_skill(nome) else f"Não há skill {nome} ligada."))
        elif acao == "desligar":
            print(cor("2", "Skills desligadas." if conversa.skills else "Nenhuma skill estava ligada."))
            conversa.skills = []
        elif acao == "editar":
            if nome:
                editar_skill(nome)
            else:
                print("Use: /skill editar NOME")
        else:
            ligar_skill(conversa, resto)
    except skills.ErroSkill as e:
        print(cor("31", maiuscula(str(e))))


def comando_agente(conversa, resto, console):
    """/agente (o menu), /agente NOME, /agente novo NOME e /agente editar [NOME]."""
    acao, _, nome = resto.partition(" ")
    nome = nome.strip()
    try:
        # Num terminal "dumb" a rich não desenha a parte ao vivo: o menu ficaria invisível.
        if not resto and console.is_terminal and not console.is_dumb_terminal and sys.stdin.isatty():
            menu_de_agentes(conversa, console)
        elif not resto:  # sem terminal de verdade: a lista, como antes
            print(f"Agente: {descrever_agente(conversa)}")
            print(lista_de_agentes(conversa.agente.nome if conversa.agente else None))
            print(cor("2", "Trocar: /agente NOME · criar: /agente novo NOME · editar: /agente editar [NOME]"))
        elif acao == "novo":
            if nome:
                criar_agente(nome)
            else:
                print("Use: /agente novo NOME")
        elif acao == "editar":
            editar_agente(conversa, nome)
        else:
            trocar_agente(conversa, resto, console)
    except agentes.ErroAgente as e:
        print(cor("31", maiuscula(str(e))))


def chat(conversa, imagens, console):
    if readline:
        readline.set_history_length(1000)
        try:
            readline.read_history_file(str(DIGITADOS))
        except OSError:
            pass
    abrir(console, conversa)
    exibidor = ExibidorRico(console)
    pendentes = list(imagens)
    while True:
        try:
            texto = ler_entrada(prompt_colorido(console, texto_do_prompt(conversa))).strip()
        except KeyboardInterrupt:
            print()
            continue
        except EOFError:
            print()
            break
        if not texto:
            continue
        if texto.startswith("/"):
            if not comando(conversa, texto, pendentes, console):
                break
            continue
        print()
        try:
            conversa.perguntar(texto, pendentes, exibidor)
        except ErroIA as e:
            print(cor("31", str(e)))
            if pendentes:
                print(cor("2", "A imagem foi descartada; anexe de novo com /imagem."))
        pendentes.clear()
        print()
    if readline:
        try:
            readline.write_history_file(str(DIGITADOS))
        except OSError:
            pass


def maiuscula(texto):
    return texto[:1].upper() + texto[1:]


def agente_ou_aviso(nome):
    """O agente NOME. Sem o arquivo, None (o config.json, como antes); com erro, avisa e None."""
    if not agentes.existe(PASTA_AGENTES, nome):
        return None
    try:
        return agentes.carregar(PASTA_AGENTES, nome)
    except agentes.ErroAgente as e:
        sys.stderr.write(cor("31", f"Não usei o agente {nome}: {e}", sys.stderr) + "\n")
        return None


def main():
    p = argparse.ArgumentParser(
        prog="chrono",
        description="Conversa com uma IA local (Ollama) pelo terminal.",
        epilog=EXEMPLOS,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    p.add_argument("pergunta", nargs="*", help="pergunta rápida; sem ela, abre o chat")
    p.add_argument("-c", "--continuar", action="store_true", help="continua a última conversa")
    p.add_argument("-a", "--agente", metavar="NOME", help="agente a usar (veja com --agentes)")
    p.add_argument("-m", "--modelo", help="modelo do Ollama a usar desta vez")
    p.add_argument("-i", "--imagem", action="append", default=[], metavar="ARQUIVO",
                   help="anexa uma imagem (pode repetir)")
    p.add_argument("-p", "--pensar", action="store_true",
                   help="deixa o modelo raciocinar antes de responder (mais lento)")
    p.add_argument("--modelos", action="store_true", help="lista os modelos baixados")
    p.add_argument("--agentes", action="store_true", help="lista os agentes")
    p.add_argument("-s", "--skill", action="append", default=[], metavar="NOME",
                   help="liga uma skill (pode repetir)")
    p.add_argument("--skills", action="store_true", help="lista as skills")
    p.add_argument("-h", "--ajuda", action="help", help="mostra esta ajuda")
    args = p.parse_args()

    try:
        config = carregar_config()
        try:
            agentes.criar_prontos(PASTA_AGENTES, config["sistema"])
            skills.criar_prontas(PASTA_SKILLS)
        except OSError:
            pass  # sem os agentes e skills prontos, o chrono funciona com o config.json, como antes
        if args.modelos:
            print("\n".join(listar_modelos(config)))
            return 0
        if args.agentes:
            print(lista_de_agentes(config["agente"]))
            return 0
        if args.skills:
            print(lista_de_skills([]))
            return 0
        if args.agente and args.continuar:
            raise ErroIA("Use -a para começar com um agente ou -c para continuar a última conversa, não os dois.")

        pergunta = " ".join(args.pergunta)
        if not sys.stdin.isatty():
            pergunta = f"{pergunta}\n\n{sys.stdin.read()}"
        pergunta = pergunta.strip()

        # A rich só é necessária quando o chrono desenha na tela.
        na_tela = sys.stdout.isatty() or (not pergunta and sys.stdin.isatty())
        if na_tela and Console is None:
            sys.stderr.write("O chrono precisa da biblioteca rich. Instale com: pip3 install --user rich\n")
            return 1
        console = Console(highlight=False) if na_tela else None

        conversa = Conversa(config)
        if args.continuar:
            conversa.carregar_ultima()
            agente = agente_ou_aviso(conversa.agente_salvo or config["agente"])
            conversa.usar_agente(agente, nova_conversa=False, modelo=args.modelo)
        else:
            agente = agentes.carregar(PASTA_AGENTES, args.agente) if args.agente else agente_ou_aviso(config["agente"])
            conversa.usar_agente(agente, modelo=args.modelo)
        if args.pensar:
            conversa.pensar = True
        if args.continuar:
            for nome in conversa.skills_salvas:
                try:
                    conversa.ligar_skill(skills.carregar(PASTA_SKILLS, nome))
                except skills.ErroSkill as e:
                    sys.stderr.write(cor("31", f"Não liguei a skill {nome}: {e}", sys.stderr) + "\n")
        for nome in args.skill:
            conversa.ligar_skill(skills.carregar(PASTA_SKILLS, nome))
        conversa.pode_alterar = sys.stdin.isatty()
        if conversa.skills and pergunta:  # sem prompt na tela, o aviso é a única pista
            sys.stderr.write(cor("2", "Skills ligadas: " + ", ".join(s.nome for s in conversa.skills),
                                 sys.stderr) + "\n")
        if conversa._criador_ligado() and not conversa._pode_criar_skill():
            sys.stderr.write(cor("2", AVISO_CRIADOR, sys.stderr) + "\n")

        if pergunta:
            conversa.perguntar(pergunta, args.imagem, ExibidorRico(console) if sys.stdout.isatty() else None)
        elif not sys.stdin.isatty():
            raise ErroIA("Não recebi nada para perguntar.")
        else:
            chat(conversa, args.imagem, console)
    except (ErroIA, agentes.ErroAgente, skills.ErroSkill) as e:
        sys.stderr.write(cor("31", maiuscula(str(e)), sys.stderr) + "\n")
        return 1
    except KeyboardInterrupt:
        sys.stderr.write("\n")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
