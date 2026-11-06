"""Emulador mínimo de terminal com histórico de rolagem.

Serve para ver o que fica na tela de verdade depois dos redesenhos da rich: o cursor
não consegue subir além do topo da tela, então o que rolou para o histórico não se apaga.
"""
import re

ESCAPE = re.compile(r"\x1b\[([0-9;?]*)([A-Za-z])|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


class Tela:
    def __init__(self, altura, largura):
        self.altura = altura
        self.largura = largura
        self.linhas = [""]  # histórico + tela
        self.y = 0
        self.x = 0
        self.quebra_pendente = False

    def _topo(self):
        return max(0, len(self.linhas) - self.altura)

    def _descer(self):
        self.y += 1
        if self.y == len(self.linhas):
            self.linhas.append("")

    def escrever(self, texto):
        i = 0
        while i < len(texto):
            m = ESCAPE.match(texto, i)
            if m:
                self._controle(m.group(1), m.group(2))
                i = m.end()
                continue
            ch = texto[i]
            i += 1
            if ch == "\r":
                self.x, self.quebra_pendente = 0, False
            elif ch == "\n":
                self._descer()
                self.quebra_pendente = False
            elif ch >= " ":
                if self.quebra_pendente:
                    self._descer()
                    self.x, self.quebra_pendente = 0, False
                linha = self.linhas[self.y].ljust(self.x)
                self.linhas[self.y] = linha[:self.x] + ch + linha[self.x + 1:]
                if self.x == self.largura - 1:
                    self.quebra_pendente = True
                else:
                    self.x += 1
        return self

    def _controle(self, args, cmd):
        if cmd is None:  # sequências OSC (links, título da janela)
            return
        n = int(args) if args.isdigit() else 1
        if cmd == "A":
            self.y = max(self._topo(), self.y - n)
        elif cmd == "B":
            self.y = min(len(self.linhas) - 1, self.y + n)
        elif cmd == "G":
            self.x = n - 1
        elif cmd == "K":
            self.linhas[self.y] = "" if args == "2" else self.linhas[self.y][:self.x]
        if cmd in "ABG":
            self.quebra_pendente = False

    def texto(self):
        return [linha.rstrip() for linha in self.linhas]
