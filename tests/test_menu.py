import io
import os
import pty
import select
import sys
import threading
import time
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import limpeza  # noqa: E402,F401  (pasta temporária apagada no fim da rodada)
import menu as m  # noqa: E402
from rich.console import Console  # noqa: E402

TITULO = "Escolha o agente   ↑↓ escolher · Enter trocar · e editar · Esc sair"


class TestTeclas(unittest.TestCase):
    def setUp(self):
        self.ler, self.escrever = os.pipe()
        self.addCleanup(os.close, self.ler)
        self.addCleanup(os.close, self.escrever)

    def teclas(self, *pedacos):
        for pedaco in pedacos:
            os.write(self.escrever, pedaco)

    def test_setas_enter_e_letras(self):
        entradas = [b"\x1b[A", b"\x1b[B", b"\x1bOB", b"\r", b"\n", b"E"]
        lidas = []
        for entrada in entradas:
            self.teclas(entrada)
            lidas.append(m.ler_tecla(self.ler))
        self.assertEqual(lidas, ["cima", "baixo", "baixo", "enter", "enter", "e"])

    def test_esc_sozinho(self):
        self.teclas(b"\x1b")
        self.assertEqual(m.ler_tecla(self.ler), "esc")
        self.teclas(b"\x04")
        self.assertEqual(m.ler_tecla(self.ler), "esc")

    def test_seta_em_pedacos(self):
        # O terminal pode entregar o Esc antes do resto da sequência da seta.
        self.teclas(b"\x1b")
        threading.Thread(target=lambda: (time.sleep(0.01), self.teclas(b"[B"))).start()
        self.assertEqual(m.ler_tecla(self.ler), "baixo")

    def test_sequencia_desconhecida(self):
        self.teclas(b"\x1b[5~", b"\r")
        self.assertEqual(m.ler_tecla(self.ler), "")
        self.assertEqual(m.ler_tecla(self.ler), "enter")


def desenhar(menu, largura):
    console = Console(file=io.StringIO(), width=largura, color_system=None)
    console.print(menu)
    return console.file.getvalue().rstrip("\n").split("\n")


class TestMenu(unittest.TestCase):
    def test_mover_da_volta(self):
        menu = m.Menu("t", [m.Item("a"), m.Item("b"), m.Item("c")], posicao=0)
        menu.mover(-1)
        self.assertEqual(menu.item().rotulo, "c")
        menu.mover(1)
        self.assertEqual(menu.item().rotulo, "a")

    def test_menu_desenha_a_escolha(self):
        menu = m.Menu(TITULO, [m.Item("geral", "assistente para qualquer assunto", marca="●"),
                               m.Item("atendente", "rascunha respostas")], posicao=1)
        linhas = desenhar(menu, 100)
        self.assertEqual(linhas[0].rstrip(), TITULO)
        self.assertRegex(linhas[1], r"^  ● geral\s+assistente para qualquer assunto")
        self.assertRegex(linhas[2], r"^▸   atendente\s+rascunha respostas")

    def test_detalhe_longo_mantem_as_marcas(self):
        # Um erro comprido no detalhe apertava as outras colunas até sumir com o ▸ e o ●.
        menu = m.Menu(TITULO, [m.Item("geral", "assistente", marca="●"), m.Item("quebrado", "⚠ " + "erro " * 30),
                               m.Item("+ criar agente novo")], posicao=0)
        linhas = desenhar(menu, 100)
        self.assertRegex(linhas[1], r"^▸ ● geral\s+assistente")
        self.assertRegex(linhas[2], r"^    quebrado\s+⚠ erro")
        self.assertTrue(linhas[2].rstrip().endswith("…"))
        self.assertTrue(linhas[3].startswith("    + criar agente novo"))
        self.assertTrue(all(len(linha) <= 100 for linha in linhas))

    def test_menu_estreito_nao_quebra_linha(self):
        menu = m.Menu(TITULO, [m.Item("geral", "x" * 150), m.Item("planilhas", "curta")])
        linhas = desenhar(menu, 40)
        self.assertEqual(len(linhas), 3)
        self.assertTrue(all(len(linha) <= 40 for linha in linhas), linhas)
        self.assertTrue(linhas[1].rstrip().endswith("…"))


# Roda o menu num terminal falso, num processo filho, e diz se o terminal voltou como estava.
FILHO = r"""
import sys, termios
sys.path.insert(0, RAIZ)
import menu as m
from rich.console import Console
def estado():
    atributos = termios.tcgetattr(0)
    atributos[3] &= ~termios.PENDIN  # o próprio macOS liga esse bit ao voltar ao modo normal
    return atributos
antes = estado()
r = m.escolher(Console(force_terminal=True), m.Menu("t", [m.Item("a"), m.Item("b")]))
print("RESULTADO", r and (r[0], r[1].rotulo), "TERMINAL", "IGUAL" if estado() == antes else "DIFERENTE")
"""


# O modo de ligar e desligar: Enter alterna o ✓ e o menu continua aberto (FECHAR: Enter em "b" fecha).
FILHO_ALTERNAR = r"""
import sys
sys.path.insert(0, RAIZ)
import menu as m
from rich.console import Console
itens = [m.Item("a"), m.Item("b")]
def alternar(item):
    if FECHAR and item.rotulo == "b":
        return True
    item.marca = "✓" if item.marca != "✓" else " "
    return False
r = m.escolher(Console(force_terminal=True), m.Menu("t", itens), alternar=alternar)
print("MARCAS", [i.marca for i in itens], "RESULTADO", r and (r[0], r[1].rotulo))
"""


def rodar_menu_no_terminal(tecla, script=FILHO):
    teclas = tecla if isinstance(tecla, list) else [tecla]
    pid, fd = pty.fork()
    if pid == 0:
        os.execv(sys.executable, [sys.executable, "-c", f"RAIZ = {str(RAIZ)!r}\n" + script])
    saida, enviada, fim = b"", False, time.time() + 10
    while time.time() < fim:
        pronto, _, _ = select.select([fd], [], [], 0.1)
        if pronto:
            try:
                dados = os.read(fd, 4096)
            except OSError:
                break
            if not dados:
                break
            saida += dados
        if not enviada and b"\x1b[?25l" in saida:  # o menu já está na tela
            for cada in teclas:
                time.sleep(0.15)
                os.write(fd, cada)
            enviada = True
    os.waitpid(pid, 0)
    os.close(fd)
    return saida.decode("utf-8", "replace")


class TestTerminalVolta(unittest.TestCase):
    def test_terminal_volta_como_estava(self):
        for tecla, esperado in ((b"\x1b", "None"), (b"\r", "('enter', 'a')"), (b"\x03", "None")):
            with self.subTest(tecla=tecla):
                saida = rodar_menu_no_terminal(tecla)
                self.assertIn(f"RESULTADO {esperado} TERMINAL IGUAL", saida)
                self.assertIn("\x1b[?25h", saida)  # o cursor aparece de novo


class TestAlternar(unittest.TestCase):
    def test_enter_alterna_e_o_menu_continua(self):
        saida = rodar_menu_no_terminal([b"\r", b"\x1b[B", b"\r", b"\x1b"], "FECHAR = False\n" + FILHO_ALTERNAR)
        self.assertIn("MARCAS ['✓', '✓'] RESULTADO None", saida)

    def test_alternar_pode_fechar(self):
        saida = rodar_menu_no_terminal([b"\r", b"\x1b[B", b"\r"], "FECHAR = True\n" + FILHO_ALTERNAR)
        self.assertIn("MARCAS ['✓', ' '] RESULTADO ('enter', 'b')", saida)


if __name__ == "__main__":
    unittest.main()
