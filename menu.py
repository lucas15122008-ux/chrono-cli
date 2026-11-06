"""Menu do chrono que se navega com as setas do teclado.

Não sabe nada de agentes: recebe os itens, mostra e devolve a escolha. Lê as teclas com o
terminal em modo "cbreak" (cada tecla chega na hora, sem eco) e sempre devolve o terminal como
estava, também com Ctrl+C.
"""
import codecs
import os
import select
import sys
import termios
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Optional, Tuple

from rich.live import Live
from rich.text import Text

# As mesmas cores do chrono.
AZUL = "#bfddf3"
CINZA = "#888780"
ERRO = "red"

SETAS = {b"[A": "cima", b"OA": "cima", b"[B": "baixo", b"OB": "baixo"}


def _mais(fd, espera):
    """O próximo byte, se ele chegar em até `espera` segundos; senão b""."""
    pronto, _, _ = select.select([fd], [], [], espera)
    return os.read(fd, 1) if pronto else b""


def ler_tecla(fd, espera=0.05):
    """Uma tecla: "cima", "baixo", "enter", "esc", uma letra (minúscula) ou "" (desconhecida)."""
    byte = os.read(fd, 1)
    if byte in (b"\r", b"\n"):
        return "enter"
    if byte in (b"", b"\x04"):  # fim da entrada ou Ctrl+D
        return "esc"
    if byte != b"\x1b":
        try:
            letra = byte.decode("ascii")
        except UnicodeDecodeError:
            return ""
        return letra.lower() if letra.isprintable() else ""
    sequencia = _sequencia(fd, espera)
    return "esc" if sequencia is None else SETAS.get(sequencia, "")


def _sequencia(fd, espera):
    """Depois de um Esc: None se ele veio sozinho; senão o resto da sequência (b"[A" numa seta).

    A sequência de uma seta pode chegar em pedaços, por isso espera um pouco por cada byte.
    """
    sequencia = _mais(fd, espera)
    if not sequencia:
        return None
    if sequencia in (b"[", b"O"):
        while True:
            byte = _mais(fd, espera)
            sequencia += byte
            if not byte or 0x40 <= byte[0] <= 0x7E:  # o último byte de uma sequência
                break
    return sequencia


@dataclass
class Item:
    rotulo: str
    detalhe: str = ""
    marca: str = " "  # a coluna do ● (o item atual)
    valor: object = None
    erro: bool = False  # o detalhe é uma mensagem de erro


class Menu:
    def __init__(self, titulo, itens, posicao=0):
        self.titulo = titulo
        self.itens = list(itens)
        self.posicao = posicao

    def mover(self, passo):
        self.posicao = (self.posicao + passo) % len(self.itens)

    def item(self):
        return self.itens[self.posicao]

    def __rich_console__(self, console, options):
        # Uma linha por item, montada à mão: numa tabela, um detalhe comprido (um erro) apertava
        # as outras colunas até sumir com o ▸ e o ●.
        nome, _, dica = self.titulo.partition("   ")
        yield Text.assemble((nome, LILAS), ("   " + dica if dica else "", CINZA),
                            no_wrap=True, overflow="ellipsis")
        largura = max(len(item.rotulo) for item in self.itens)
        espaco = max(options.max_width - largura - 5, 0)  # "▸ ● " antes e um espaço depois do nome
        for numero, item in enumerate(self.itens):
            escolhido = numero == self.posicao
            linha = Text(no_wrap=True, overflow="ellipsis")
            linha.append("▸ " if escolhido else "  ", style=LILAS)
            linha.append(item.marca + " ", style=LILAS)
            linha.append(item.rotulo.ljust(largura), style=f"bold {LILAS}" if escolhido else None)
            if item.detalhe and espaco:
                detalhe = Text(item.detalhe, style=ERRO if item.erro else CINZA)
                detalhe.truncate(espaco, overflow="ellipsis")
                linha.append(" ")
                linha.append(detalhe)
            yield linha


@contextmanager
def _teclado():
    """Terminal em modo "cbreak" (cada tecla na hora, sem eco); sempre volta como estava."""
    fd = sys.stdin.fileno()
    antes = termios.tcgetattr(fd)
    novo = list(antes)
    novo[3] &= ~(termios.ICANON | termios.ECHO | termios.ECHOCTL)  # Ctrl+C continua valendo
    novo[6] = list(antes[6])
    novo[6][termios.VMIN], novo[6][termios.VTIME] = 1, 0
    try:
        termios.tcflush(fd, termios.TCIFLUSH)  # o que foi digitado antes não conta
        termios.tcsetattr(fd, termios.TCSANOW, novo)
        yield fd
    finally:
        termios.tcsetattr(fd, termios.TCSANOW, antes)


def escolher(console, menu, teclas=(), alternar=None) -> Optional[Tuple[str, Item]]:
    """Mostra o menu até Enter (("enter", item)), uma das `teclas` ((tecla, item)) ou Esc (None).

    Com `alternar` (uma função que recebe o item), o Enter chama a função e o menu continua
    aberto, para ligar e desligar vários itens; se ela devolver True, o menu fecha.
    """
    try:
        with _teclado() as fd, Live(menu, console=console, transient=True, auto_refresh=False) as ao_vivo:
            while True:
                tecla = ler_tecla(fd)
                if tecla in ("cima", "baixo"):
                    menu.mover(-1 if tecla == "cima" else 1)
                    ao_vivo.update(menu, refresh=True)
                elif tecla == "enter":
                    if alternar is None or alternar(menu.item()):
                        return "enter", menu.item()
                    ao_vivo.update(menu, refresh=True)
                elif tecla in teclas:
                    return tecla, menu.item()
                elif tecla == "esc":
                    return None
    except KeyboardInterrupt:
        return None


class _Campo:
    def __init__(self, rotulo, dica):
        self.rotulo, self.dica, self.texto = rotulo, dica, ""

    def __rich__(self):
        return Text.assemble((self.rotulo + " ", LILAS), self.texto, ("▏", LILAS),
                             ("   " + self.dica if self.dica else "", CINZA), no_wrap=True, overflow="ellipsis")


def ler_texto(console, rotulo, dica="") -> Optional[str]:
    """Uma linha digitada; None com Esc, Ctrl+C ou Ctrl+D. Feito aqui, e não com o input(), porque
    no readline do Mac o Esc se junta à tecla seguinte (Esc e depois "vendas" virava "endas")."""
    campo = _Campo(rotulo, dica)
    decodificar = codecs.getincrementaldecoder("utf-8")(errors="ignore")
    try:
        with _teclado() as fd, Live(campo, console=console, transient=True, auto_refresh=False) as ao_vivo:
            while True:
                byte = os.read(fd, 1)
                if byte in (b"\r", b"\n"):
                    return campo.texto.strip()
                if byte == b"" or (byte == b"\x04" and not campo.texto):
                    return None
                if byte in (b"\x7f", b"\x08"):  # apagar
                    campo.texto = campo.texto[:-1]
                elif byte == b"\x15":  # Ctrl+U apaga tudo
                    campo.texto = ""
                elif byte == b"\x1b":
                    if _sequencia(fd, 0.05) is None:
                        return None
                    continue  # setas e outras teclas especiais não fazem nada aqui
                else:
                    letra = decodificar.decode(byte)
                    if not (letra and letra.isprintable()):
                        continue  # metade de uma letra com acento, ou um caractere de controle
                    campo.texto += letra
                ao_vivo.update(campo, refresh=True)
    except KeyboardInterrupt:
        return None
