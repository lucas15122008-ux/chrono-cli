import contextlib
import fcntl
import importlib.util
import io
import json
import os
import pty
import re
import site
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from rich.console import Console
from rich.text import Text

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))  # o chrono importa o ferramentas.py da mesma pasta
sys.path.insert(0, str(Path(__file__).resolve().parent))
import limpeza  # noqa: E402,F401  (pasta temporária apagada no fim da rodada)
from fake_ollama import FINAL, MODELO, OUTRO, PS, QUEBRADO, SHOW, FakeOllama  # noqa: E402
from tela import Tela  # noqa: E402

_spec = importlib.util.spec_from_file_location("chrono", RAIZ / "chrono.py")
c = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(c)


def preparar_home(servidor):
    """HOME de teste com um config.json apontando para o servidor dado."""
    home = tempfile.mkdtemp(prefix="chrono-teste-")
    pasta = Path(home) / ".chrono"
    pasta.mkdir()
    (pasta / "config.json").write_text(json.dumps({"servidor": servidor}), encoding="utf-8")
    return home


def rodar(args, home, entrada=""):
    # PYTHONUSERBASE mantém a rich (instalada com --user) visível mesmo com outro HOME.
    env = dict(os.environ, HOME=home, PYTHONUSERBASE=site.getuserbase())
    return subprocess.run([sys.executable, str(RAIZ / "chrono.py"), *args], input=entrada,
                          capture_output=True, text=True, env=env, timeout=30)


class TestSaidaSimples(unittest.TestCase):
    def setUp(self):
        self.fake = FakeOllama().__enter__()
        self.home = preparar_home(self.fake.url)

    def tearDown(self):
        self.fake.__exit__()

    def test_saida_redirecionada_so_texto(self):
        self.fake.respostas = ["Brasília", "."]
        r = rodar(["Capital do Brasil?"], self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "Brasília.\n")
        self.assertNotIn("\x1b", r.stdout)

    def test_modelo_inexistente(self):
        r = rodar(["-m", "nao-existe", "oi"], self.home)
        self.assertEqual(r.returncode, 1)
        self.assertIn("ollama pull nao-existe", r.stderr)

    def test_ollama_fora_do_ar(self):
        r = rodar(["oi"], preparar_home("http://127.0.0.1:9"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("Não consegui falar com o Ollama", r.stderr)

    def test_pensamento_nao_vai_para_saida(self):
        self.fake.pensamentos = ["hmm, ", "17 vezes 23..."]
        self.fake.respostas = ["391"]
        r = rodar(["-p", "17*23?"], self.home)
        self.assertEqual(r.stdout, "391\n")
        self.assertEqual(r.stderr, "")


def pedido(nome, **argumentos):
    return {"function": {"name": nome, "arguments": argumentos}}


class TestFerramentasNaConversa(unittest.TestCase):
    def setUp(self):
        self.fake = FakeOllama().__enter__()
        self._conversas = c.CONVERSAS
        c.CONVERSAS = Path(tempfile.mkdtemp()) / "conversas"
        self.pasta = Path(tempfile.mkdtemp()).resolve()
        (self.pasta / "a.txt").write_text("pastilha cerâmica Cobreq", encoding="utf-8")
        self.conv = c.Conversa(dict(c.PADRAO, servidor=self.fake.url))
        self.conv.trocar_modelo(MODELO)
        self.conv.base = self.pasta
        # A casa e a Lixeira de verdade ficam fora dos testes.
        for nome, valor in (("CASA", self.pasta), ("LIXEIRA", self.pasta / ".Trash")):
            remendo = mock.patch.object(c.ferramentas, nome, valor)
            remendo.start()
            self.addCleanup(remendo.stop)

    def tearDown(self):
        c.CONVERSAS = self._conversas
        self.fake.__exit__()

    def mensagens_de_ferramenta(self, numero_do_pedido=-1):
        return [m for m in self.fake.pedidos[numero_do_pedido]["messages"] if m["role"] == "tool"]

    def test_ligadas_quando_o_modelo_sabe_usar(self):
        self.assertTrue(self.conv.ferramentas)

    def test_modelo_sabe_a_pasta_atual(self):
        # No teste real, sem isso o modelo pedia o caminho em vez de usar as ferramentas.
        self.conv.perguntar("o que tem nesta pasta?", exibidor=Gravador())
        sistema = self.fake.pedidos[0]["messages"][0]
        self.assertEqual(sistema["role"], "system")
        self.assertIn(f"A pasta atual, onde o chrono foi aberto, é {c.ferramentas.abreviar(self.pasta)}",
                      sistema["content"])
        self.assertNotIn("A pasta atual", self.conv.mensagens[0]["content"])  # não vai para o histórico

    def test_so_leitura_recusa_alteracao_nao_oferecida(self):
        # O modelo pode inventar uma ferramenta que não foi oferecida; um agente só leitura recusa.
        self.conv.so_leitura = True
        self.fake.rodadas = [{"tool_calls": [pedido("criar_pasta", caminho="nova")]}, {"respostas": ["ok"]}]
        gravador = Gravador(["s"])
        self.conv.perguntar("cria uma pasta", exibidor=gravador)
        self.assertFalse((self.pasta / "nova").exists())
        self.assertNotIn("perguntar", [ch[0] for ch in gravador.chamadas])
        self.assertIn("só pode ler", self.mensagens_de_ferramenta()[0]["content"])

    def test_so_leitura_avisa_o_modelo(self):
        self.conv.so_leitura = True
        self.conv.perguntar("oi", exibidor=Gravador())
        sistema = self.fake.pedidos[0]["messages"][0]["content"]
        self.assertIn("não pode alterar nada", sistema)
        self.assertNotIn("As alterações pedem confirmação", sistema)
        self.assertIn(f"A pasta atual, onde o chrono foi aberto, é {c.ferramentas.abreviar(self.pasta)}", sistema)

    def test_sem_ferramentas_sem_contexto_de_pasta(self):
        self.conv.ferramentas = False
        self.conv.perguntar("oi", exibidor=Gravador())
        self.assertNotIn("A pasta atual", self.fake.pedidos[0]["messages"][0]["content"])

    def test_rodada_de_ferramenta(self):
        self.fake.rodadas = [{"tool_calls": [pedido("ler_arquivo", caminho="a.txt")]}, {"respostas": ["Resumo"]}]
        g = Gravador()
        self.assertEqual(self.conv.perguntar("resuma a.txt", exibidor=g), "Resumo")
        self.assertIn("tools", self.fake.pedidos[0])
        segundo = self.fake.pedidos[1]["messages"]
        self.assertEqual(segundo[-1], {"role": "tool", "tool_name": "ler_arquivo", "content": "pastilha cerâmica Cobreq"})
        self.assertEqual(segundo[-2]["tool_calls"][0]["function"]["name"], "ler_arquivo")
        self.assertIn(("acao", "lendo a.txt", False), g.chamadas)
        tipos = [ch[0] for ch in g.chamadas]
        self.assertLess(tipos.index("acao"), tipos.index("texto"))

    def test_metricas_somadas(self):
        self.fake.rodadas = [{"tool_calls": [pedido("ler_arquivo", caminho="a.txt")]}, {"respostas": ["ok"]}]
        g = Gravador()
        self.conv.perguntar("resuma", exibidor=g)
        self.assertEqual(g.chamadas[-1], ("fim", 128, 32768, None))

    def test_limite_de_rodadas(self):
        self.fake.rodadas = [{"tool_calls": [pedido("listar_pasta", caminho=".")]} for _ in range(10)]
        self.fake.rodadas.append({"respostas": ["Pronto"]})
        g = Gravador()
        self.assertEqual(self.conv.perguntar("liste tudo", exibidor=g), "Pronto")
        self.assertEqual(len(self.fake.pedidos), 11)
        self.assertNotIn("tools", self.fake.pedidos[10])
        self.assertEqual(len(self.mensagens_de_ferramenta()), 10)
        self.assertIn(("acao", "limite de 10 rodadas de ferramenta", False), g.chamadas)

    def test_argumentos_em_texto_e_ferramenta_desconhecida(self):
        self.fake.rodadas = [{"tool_calls": [{"function": {"name": "ler_arquivo", "arguments": '{"caminho": "a.txt"}'}},
                                             pedido("formatar_disco")]},
                             {"respostas": ["ok"]}]
        self.conv.perguntar("faça", exibidor=Gravador())
        conteudos = [m["content"] for m in self.mensagens_de_ferramenta()]
        self.assertEqual(conteudos[0], "pastilha cerâmica Cobreq")
        self.assertTrue(conteudos[1].startswith("erro:"))

    def test_confirmador_t_aprova_o_resto(self):
        self.fake.rodadas = [{"tool_calls": [pedido("escrever_arquivo", caminho=f"n{i}.txt", conteudo="x")
                                             for i in range(3)]},
                             {"respostas": ["feito"]}]
        g = Gravador(respostas=["t"])
        self.conv.perguntar("crie três arquivos", exibidor=g)
        self.assertEqual(sorted(p.name for p in self.pasta.glob("n*.txt")), ["n0.txt", "n1.txt", "n2.txt"])
        self.assertEqual([ch[0] for ch in g.chamadas].count("perguntar"), 1)

    def test_resposta_n_recusa(self):
        self.fake.rodadas = [{"tool_calls": [pedido("escrever_arquivo", caminho="n.txt", conteudo="x")]},
                             {"respostas": ["ok"]}]
        self.conv.perguntar("crie", exibidor=Gravador(respostas=["n"]))
        self.assertFalse((self.pasta / "n.txt").exists())

    def test_sem_teclado_recusa(self):
        self.fake.rodadas = [{"tool_calls": [pedido("escrever_arquivo", caminho="n.txt", conteudo="x")]},
                             {"respostas": ["ok"]}]
        with contextlib.redirect_stdout(io.StringIO()):
            self.conv.perguntar("crie", exibidor=c.ExibidorSimples())
        self.assertFalse((self.pasta / "n.txt").exists())
        self.assertTrue(self.mensagens_de_ferramenta()[0]["content"].startswith("o usuário recusou"))

    def test_ferramentas_desligadas(self):
        self.conv.ferramentas = False
        self.conv.perguntar("oi", exibidor=Gravador())
        self.assertNotIn("tools", self.fake.pedidos[0])

    def test_historico_guarda_ferramentas(self):
        self.fake.rodadas = [{"tool_calls": [pedido("ler_arquivo", caminho="a.txt")]}, {"respostas": ["Resumo"]}]
        self.conv.perguntar("resuma", exibidor=Gravador())
        salvas = json.loads(self.conv.arquivo.read_text(encoding="utf-8"))["mensagens"]
        self.assertEqual([m["role"] for m in salvas], ["system", "user", "assistant", "tool", "assistant"])
        self.assertEqual(salvas[-1]["content"], "Resumo")

    def test_animacao_avisa_que_esta_usando_ferramentas(self):
        self.fake.rodadas = [{"tool_calls": [pedido("ler_arquivo", caminho="a.txt")]}, {"respostas": ["ok"]}]
        g = Gravador()
        self.conv.perguntar("resuma", exibidor=g)
        tipos = [ch[0] for ch in g.chamadas]
        self.assertLess(tipos.index("usando_ferramentas"), tipos.index("acao"))

    def test_ferramentas_oferecidas_conforme_o_que_da_para_fazer(self):
        self.conv.recursos.discard("vision")
        self.conv.pode_alterar = False  # sem teclado para confirmar
        self.conv.perguntar("oi", exibidor=Gravador())
        nomes = [d["function"]["name"] for d in self.fake.pedidos[0]["tools"]]
        self.assertEqual(nomes, ["listar_pasta", "ler_arquivo", "buscar_no_arquivo", "calcular_na_planilha",
                                 "buscar_arquivos", "buscar_texto"])

    def test_erro_depois_de_alterar_mantem_o_que_foi_feito(self):
        # Se uma rodada quebra depois de uma alteração aprovada, a conversa lembra da alteração.
        self.fake.rodadas = [{"tool_calls": [pedido("escrever_arquivo", caminho="n.txt", conteudo="x")]},
                             {"respostas": ["meio"], "quebrada": True}]
        with self.assertRaises(ValueError):
            self.conv.perguntar("crie n.txt", exibidor=Gravador(respostas=["s"]))
        self.assertTrue((self.pasta / "n.txt").exists())
        papeis = [m["role"] for m in self.conv.mensagens]
        self.assertEqual(papeis, ["system", "user", "assistant", "tool", "assistant"])
        self.assertEqual(self.conv.mensagens[-1]["content"], "(a resposta foi interrompida por um erro)")
        salvas = json.loads(self.conv.arquivo.read_text(encoding="utf-8"))["mensagens"]
        self.assertEqual(len(salvas), 5)

    def test_erro_desfaz_a_pergunta_inteira(self):
        self.fake.rodadas = [{"tool_calls": [pedido("ler_arquivo", caminho="a.txt")]}]
        self.fake.linha_quebrada = True  # a segunda rodada quebra no meio
        antes = list(self.conv.mensagens)
        with self.assertRaises(ValueError):
            self.conv.perguntar("resuma", exibidor=Gravador())
        self.assertEqual(self.conv.mensagens, antes)


class TestFormatacao(unittest.TestCase):
    def test_numeros(self):
        self.assertEqual(c.fmt_segundos(2.4), "2,4 s")
        self.assertEqual(c.fmt_gb(6_700_000_000), "6,7 GB")
        self.assertEqual(c.fmt_mil(32768), "32 mil")
        self.assertEqual(c.fmt_mil(512), "512")
        self.assertEqual(c.fmt_contexto(412, 32768), "1%")
        self.assertEqual(c.fmt_contexto(10, 32768), "<1%")

    def test_resumo_modelo(self):
        self.assertEqual(c.resumo_modelo(MODELO, SHOW, PS), [
            ("modelo", "ornith-1.5:9b · 9B · Q4 · lê imagens"),
            ("memória", "6,7 GB na GPU · conversa até 32 mil tokens"),
        ])

    def test_resumo_modelo_nao_carregado(self):
        self.assertEqual(c.resumo_modelo(MODELO, SHOW, None)[1],
                         ("memória", "carrega na primeira pergunta"))

    def test_resumo_modelo_parte_na_cpu(self):
        self.assertEqual(c.resumo_modelo(MODELO, SHOW, dict(PS, size_vram=5_000_000_000))[1][1],
                         "6,7 GB (parte na CPU) · conversa até 32 mil tokens")

    def test_resumo_modelo_sem_imagem_e_tamanho_quebrado(self):
        show = {"capabilities": ["completion"],
                "details": {"parameter_size": "8.2B", "quantization_level": "F16"}}
        self.assertEqual(c.resumo_modelo("outro", show, PS)[0], ("modelo", "outro · 8,2B · F16"))

    def test_linha_detalhes(self):
        self.assertEqual(c.linha_detalhes(FINAL, 32768, None),
                         "⏱ 2,4 s   ⚡ 18 tokens/s   ✎ 64 tokens   ▤ contexto 1%")

    def test_contexto_de_varias_rodadas(self):
        # O contexto usado é o da última rodada (348 + 64), não a soma das saídas de todas.
        self.assertTrue(c.linha_detalhes(c.somar_metricas([FINAL, FINAL]), 1000, None).endswith("▤ contexto 41%"))

    def test_linha_detalhes_pensou_sem_contexto(self):
        self.assertEqual(c.linha_detalhes(FINAL, None, 8.0),
                         "⏱ 2,4 s   ⚡ 18 tokens/s   ✎ 64 tokens   ✦ pensou 8,0 s")


class Gravador:
    """Exibidor de teste: anota cada chamada em vez de desenhar; perguntar() responde com a lista dada."""

    def __init__(self, respostas=()):
        self.chamadas = []
        self.respostas = list(respostas)

    def acao(self, resumo, alterou):
        self.chamadas.append(("acao", resumo, alterou))

    def usando_ferramentas(self):
        self.chamadas.append(("usando_ferramentas",))

    def perguntar(self, pergunta, detalhe):
        self.chamadas.append(("perguntar", pergunta))
        return self.respostas.pop(0) if self.respostas else ""

    def inicio(self):
        self.chamadas.append(("inicio",))

    def pensando(self, texto):
        self.chamadas.append(("pensando", texto))

    def texto(self, pedaco):
        self.chamadas.append(("texto", pedaco))

    def fim(self, metricas, contexto_total, pensou):
        self.chamadas.append(("fim", metricas and metricas["eval_count"], contexto_total, pensou))

    def interrompido(self):
        self.chamadas.append(("interrompido",))


class TestConversa(unittest.TestCase):
    def setUp(self):
        self.fake = FakeOllama().__enter__()
        self._conversas = c.CONVERSAS
        c.CONVERSAS = Path(tempfile.mkdtemp()) / "conversas"
        self.conv = c.Conversa(dict(c.PADRAO, servidor=self.fake.url))
        self.conv.trocar_modelo(MODELO)

    def tearDown(self):
        c.CONVERSAS = self._conversas
        self.fake.__exit__()

    def test_metricas_guardadas(self):
        self.fake.respostas = ["Oi", "!"]
        g = Gravador()
        self.assertEqual(self.conv.perguntar("oi", exibidor=g), "Oi!")
        self.assertEqual(self.conv.metricas["eval_count"], 64)
        self.assertIsNone(self.conv.pensou)
        self.assertEqual(g.chamadas, [("inicio",), ("texto", "Oi"), ("texto", "!"), ("fim", 64, 32768, None)])

    def test_erro_inesperado_para_o_exibidor(self):
        # O exibidor rico desliga o eco do teclado; ele tem de ser parado (e o eco religado) em qualquer erro.
        self.fake.linha_quebrada = True
        g = Gravador()
        with self.assertRaises(ValueError):
            self.conv.perguntar("oi", exibidor=g)
        self.assertEqual(g.chamadas[-1], ("fim", None, None, None))

    def test_pensou_medido(self):
        self.fake.pensamentos = ["hmm"]
        self.fake.atraso = 0.1
        self.conv.pensar = True
        g = Gravador()
        self.conv.perguntar("17*23?", exibidor=g)
        self.assertGreater(self.conv.pensou, 0.05)
        self.assertIn(("pensando", "hmm"), g.chamadas)


def console_de_teste(largura):
    return Console(file=io.StringIO(), width=largura, color_system=None)


def linhas(console):
    return [linha.rstrip() for linha in console.file.getvalue().splitlines()]


class TestRich(unittest.TestCase):
    def test_separar_blocos(self):
        self.assertEqual(c.separar_blocos("a\n\nb\n\nc"), (["a", "b"], "c"))
        self.assertEqual(c.separar_blocos("a\n\n\nb"), (["a"], "b"))
        self.assertEqual(c.separar_blocos("a\n"), ([], "a\n"))
        self.assertEqual(c.separar_blocos(""), ([], ""))

    def test_separar_blocos_codigo(self):
        self.assertEqual(c.separar_blocos("```\nx\n\ny\n```\n\nz"), (["```\nx\n\ny\n```"], "z"))

    def test_barra(self):
        con = console_de_teste(40)
        con.print(c.Barra(Text("um\ndois")))
        self.assertEqual(linhas(con), ["▎ um", "▎ dois"])

    def test_blocos_aparecem_uma_vez(self):
        con = console_de_teste(60)
        ex = c.ExibidorRico(con)
        ex.inicio()
        for i in range(60):
            ex.texto(f"parágrafo {i}\n\n")
        ex.fim(FINAL, 32768, None)
        saida = linhas(con)
        for i in range(60):
            self.assertEqual(saida.count(f"▎ parágrafo {i}"), 1)
        self.assertEqual(saida[0], "▎ chrono")
        self.assertIn("⚡ 18 tokens/s", saida[-1])

    def test_formata_negrito(self):
        con = console_de_teste(60)
        ex = c.ExibidorRico(con)
        ex.inicio()
        ex.texto("a **cerâmica** é melhor")
        ex.fim(FINAL, 32768, None)
        self.assertIn("▎ a cerâmica é melhor", linhas(con))

    def test_lista_sem_linha_vazia_no_comeco(self):
        # A rich põe uma linha vazia antes de toda lista; dentro da barrinha isso sobra.
        con = console_de_teste(60)
        ex = c.ExibidorRico(con)
        ex.inicio()
        ex.texto("- **a** x\n- b\n\ndepois")
        ex.fim(FINAL, 32768, None)
        self.assertEqual(linhas(con)[:5], ["▎ chrono", "▎  • a x", "▎  • b", "▎", "▎ depois"])

    def test_titulo_alinhado_a_esquerda(self):
        # A rich centraliza títulos; dentro da barrinha eles ficam soltos no meio da tela.
        con = console_de_teste(60)
        ex = c.ExibidorRico(con)
        ex.inicio()
        ex.texto("texto\n\n# Freios\n\nmais")
        ex.fim(FINAL, 32768, None)
        self.assertEqual(linhas(con)[:6], ["▎ chrono", "▎ texto", "▎", "▎ Freios", "▎", "▎ mais"])

    def test_interrompido(self):
        con = console_de_teste(60)
        ex = c.ExibidorRico(con)
        ex.inicio()
        ex.texto("começo da resposta")
        ex.interrompido()
        self.assertEqual(linhas(con)[-2:], ["▎ começo da resposta", "  [interrompido]"])

    def test_acao_aparece_antes_da_resposta(self):
        con = console_de_teste(60)
        ex = c.ExibidorRico(con)
        ex.inicio()
        ex.acao("lendo a.txt", False)
        ex.acao("criado ~/x.txt", True)
        ex.texto("Resumo")
        ex.fim(FINAL, 32768, None)
        self.assertEqual(linhas(con)[:4], ["◇ lendo a.txt", "◆ criado ~/x.txt", "▎ chrono", "▎ Resumo"])

    def test_controles_nao_chegam_na_tela(self):
        # Texto vindo de arquivos ou do modelo não pode apagar linhas nem disfarçar a pergunta.
        con = console_de_teste(60)
        ex = c.ExibidorRico(con)
        ex.inicio()
        ex.acao("lendo a\x1b[2K\x1b[1Ab.txt", False)
        ex.texto("x\x1b]0;título\x07y")
        ex.fim(FINAL, 32768, None)
        saida = con.file.getvalue()
        self.assertNotIn("\x1b", saida)
        self.assertNotIn("\x07", saida)
        self.assertIn("◇ lendo a[2K[1Ab.txt", saida)

    def test_animacao_usando_ferramentas(self):
        ex = c.ExibidorRico(console_de_teste(60))
        ex.inicio()
        ex.usando_ferramentas()
        self.assertEqual(ex.espera.fase, "usando as ferramentas")
        ex.fim(None, None, None)

    def test_eco_desligado_na_animacao_e_ligado_na_pergunta(self):
        # Confere o eco do teclado de verdade, num terminal falso, em cada momento.
        mestre, escravo = os.openpty()
        self.addCleanup(os.close, mestre)
        self.addCleanup(os.close, escravo)

        class Teclado:
            def fileno(self):
                return escravo

            def isatty(self):
                return True

        def eco():
            return bool(termios.tcgetattr(escravo)[3] & termios.ECHO)

        momentos = []
        with mock.patch.object(sys, "stdin", Teclado()), \
                mock.patch.object(c, "ler_resposta", lambda prompt: momentos.append(("pergunta", eco())) or "s"):
            ex = c.ExibidorRico(console_de_teste(60))
            ex.inicio()
            momentos.append(("animação", eco()))
            ex.perguntar("Criar o arquivo x?", None)
            momentos.append(("depois da pergunta", eco()))
            ex.fim(None, None, None)
            momentos.append(("fim", eco()))
        self.assertEqual(momentos, [("animação", False), ("pergunta", True), ("depois da pergunta", False),
                                    ("fim", True)])

    def test_confirmador_t_nao_pula_substituir(self):
        g = Gravador(respostas=["t", "s"])
        confirmar = c.Confirmador(g)
        self.assertTrue(confirmar("Criar a pasta x?"))
        self.assertTrue(confirmar("Substituir o arquivo y? Ele já existe.", "prévia", sempre_perguntar=True))
        self.assertTrue(confirmar("Mover z para w?"))
        self.assertEqual([ch[1] for ch in g.chamadas], ["Criar a pasta x?", "Substituir o arquivo y? Ele já existe."])

    def test_acao_vem_depois_do_texto_que_a_anuncia(self):
        con = console_de_teste(60)
        ex = c.ExibidorRico(con)
        ex.inicio()
        ex.texto("Vou ver a pasta.")
        ex.acao("listando ~/x", False)
        ex.texto("\n\nTem dois arquivos.")
        ex.fim(FINAL, 32768, None)
        self.assertEqual(linhas(con)[:5], ["▎ chrono", "▎ Vou ver a pasta.", "◇ listando ~/x", "▎", "▎ Tem dois arquivos."])

    def test_cabecalho_ferramentas(self):
        con = console_de_teste(100)
        con.print(c.cabecalho(MODELO, SHOW, PS, "nova", "desligado", "ligadas"))
        self.assertIn("conversa nova · raciocínio desligado · ferramentas ligadas", con.file.getvalue())

    def test_cauda_mostra_as_ultimas_linhas(self):
        # O bloco em andamento mostra o final, que é o que está chegando, e cabe na tela.
        con = Console(file=io.StringIO(), width=40, height=12, color_system=None)
        con.print(c.Cauda(Text("\n".join(f"linha {i}" for i in range(30)))))
        self.assertEqual(linhas(con), [f"linha {i}" for i in range(20, 30)])

    def test_prompt_colorido(self):
        # O readline do Mac (libedit) escreve todos os trechos entre \001 e \002 antes do texto,
        # então só o código que liga a cor pode ir no prompt; quem desliga é o ler_entrada.
        con = Console(file=io.StringIO(), force_terminal=True, color_system="256")
        self.assertEqual(c.prompt_colorido(con), "\001\x1b[38;5;79m\002você › ")

    def test_prompt_sem_cor(self):
        self.assertEqual(c.prompt_colorido(console_de_teste(60)), "você › ")

    def test_cabecalho_largura_40(self):
        con = console_de_teste(40)
        con.print(c.cabecalho(MODELO, SHOW, PS, "nova", "desligado", "ligadas"))
        saida = con.file.getvalue()
        self.assertIn("◆ chrono", saida)
        self.assertIn("imagens", saida)  # em 40 colunas "lê imagens" quebra em duas linhas
        self.assertTrue(all(len(linha) <= 40 for linha in saida.splitlines()))


class TerminalFalso:
    """Roda o chrono num terminal falso (pty) de 100 colunas.

    Uma linha de execução separada lê a tela sem parar, como um terminal de verdade:
    se ninguém lê, o readline trava esperando a tela "esvaziar" e o que se digita se perde.
    """

    def __init__(self, args, home, linhas=40, colunas=100, **env_extra):
        env = dict(os.environ, HOME=home, PYTHONUSERBASE=site.getuserbase(), TERM="xterm-256color")
        env.update(env_extra)  # um teste pode trocar até o TERM
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", linhas, colunas, 0, 0))
            os.execve(sys.executable, [sys.executable, str(RAIZ / "chrono.py"), *args], env)
        self.bruto = b""
        self.pos = 0
        self.leitor = threading.Thread(target=self._ler_sempre, daemon=True)
        self.leitor.start()

    def _ler_sempre(self):
        while True:
            try:
                dados = os.read(self.fd, 65536)
            except OSError:
                return
            if not dados:
                return
            self.bruto += dados

    def texto(self):
        return re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]|[\r\x01\x02]", "", self.bruto.decode("utf-8", "replace"))

    def esperar(self, trecho, limite=10):
        fim = time.time() + limite
        while time.time() < fim:
            achou = self.texto().find(trecho, self.pos)
            if achou >= 0:
                self.pos = achou + len(trecho)
                return
            time.sleep(0.02)
        raise AssertionError(f"não apareceu {trecho!r}; tela:\n{self.texto()[-1500:]}")

    def digitar(self, texto):
        time.sleep(0.2)
        os.write(self.fd, (texto + "\r").encode())

    def ctrl_c(self):
        os.write(self.fd, b"\x03")

    def encerrar(self):
        try:
            os.write(self.fd, b"\x04")
        except OSError:
            pass  # o chrono já tinha saído sozinho
        _, status = os.waitpid(self.pid, 0)
        self.leitor.join(timeout=2)
        os.close(self.fd)
        return os.waitstatus_to_exitcode(status)


class TestTerminal(unittest.TestCase):
    def setUp(self):
        self.fake = FakeOllama().__enter__()
        self.home = preparar_home(self.fake.url)

    def tearDown(self):
        self.fake.__exit__()

    def test_chat_completo(self):
        self.fake.atraso = 0.2
        self.fake.respostas = ["A **cerâmica** ", "é melhor."]
        t = TerminalFalso([], self.home)
        t.esperar("você ›")
        t.digitar("pastilha?")
        t.esperar("tokens/s")
        t.esperar("você ›")
        t.digitar("de novo")
        time.sleep(0.1)  # a primeira palavra só chega depois de 0,2 s: ainda está na animação
        t.ctrl_c()
        t.esperar("[interrompido]")
        t.esperar("você ›")
        t.digitar("/modelo nao-existe")
        t.esperar("ollama pull nao-existe")
        t.esperar("você ›")
        self.assertEqual(t.encerrar(), 0)
        tela = t.texto()
        for trecho in ["◆ chrono", "lê imagens", "6,7 GB na GPU", "conversa nova", "▎ chrono",
                       "▎ A cerâmica é melhor.", "⚡ 18 tokens/s", "▤ contexto 1%"]:
            self.assertIn(trecho, tela)
        self.assertNotIn("**", tela)
        self.assertNotIn("Traceback", tela)
        self.assertIn(b"pastilha?\r\n\x1b[0m", t.bruto)  # a cor verde do que foi digitado é desligada
        self.assertIn("você › /modelo nao-existe", tela)  # o eco do teclado voltou depois do Ctrl+C

    def test_pergunta_rapida_sem_cabecalho(self):
        t = TerminalFalso(["oi"], self.home)
        t.esperar("tokens/s")
        self.assertEqual(t.encerrar(), 0)
        self.assertIn("▎ Oi!", t.texto())
        self.assertNotIn("◆ chrono", t.texto())

    def test_imagem_com_erro_nao_trava_o_chat(self):
        t = TerminalFalso(["-i", "/nao/existe.jpg"], self.home)
        t.esperar("você ›")
        t.digitar("que peça é essa?")
        t.esperar("Imagem não encontrada")
        t.esperar("você ›")
        t.digitar("e agora, sem imagem?")
        t.esperar("tokens/s")
        self.assertEqual(t.encerrar(), 0)

    def chat_que_cria_arquivo(self, resposta_do_usuario):
        """Abre o chat, o modelo pede para criar x.txt, e o usuário responde à confirmação."""
        alvo = Path(self.home) / "x.txt"
        self.fake.rodadas = [{"tool_calls": [{"function": {"name": "escrever_arquivo",
                                                           "arguments": {"caminho": str(alvo), "conteudo": "oi"}}}]},
                             {"respostas": ["Pronto."]}]
        t = TerminalFalso([], self.home)
        t.esperar("você ›")
        t.digitar("crie x.txt")
        t.esperar("? Criar o arquivo ~/x.txt? (s/n/t)")
        resposta_do_usuario(t)
        t.esperar("tokens/s")
        t.esperar("você ›")
        self.assertEqual(t.encerrar(), 0)
        self.assertNotIn("Traceback", t.texto())
        return alvo, t.texto()

    def test_confirmacao_sim(self):
        alvo, tela = self.chat_que_cria_arquivo(lambda t: t.digitar("s"))
        self.assertEqual(alvo.read_text(), "oi")
        self.assertIn("◆ criado ~/x.txt", tela)
        self.assertIn("ferramentas ligadas", tela)

    def test_confirmacao_nao(self):
        alvo, tela = self.chat_que_cria_arquivo(lambda t: t.digitar("n"))
        self.assertFalse(alvo.exists())
        self.assertIn("◇ recusado: escrever ~/x.txt", tela)

    def test_resposta_da_confirmacao_nao_vai_para_o_historico(self):
        alvo = Path(self.home) / "x.txt"
        self.fake.rodadas = [{"tool_calls": [{"function": {"name": "escrever_arquivo",
                                                           "arguments": {"caminho": str(alvo), "conteudo": "oi"}}}]},
                             {"respostas": ["Pronto."]}]
        t = TerminalFalso([], self.home)
        t.esperar("você ›")
        t.digitar("crie x.txt")
        t.esperar("(s/n/t)")
        t.digitar("s")
        t.esperar("tokens/s")
        t.esperar("você ›")
        time.sleep(0.2)
        os.write(t.fd, b"\x1b[A\r")  # seta para cima e Enter: repete a última mensagem do chat
        t.esperar("tokens/s")
        t.esperar("você ›")
        self.assertEqual(t.encerrar(), 0)
        linhas_do_chat = t.texto().splitlines()
        self.assertNotIn("você › s", linhas_do_chat)
        self.assertEqual(linhas_do_chat.count("você › crie x.txt"), 2)

    def test_digitacao_adiantada_nao_confirma(self):
        # Um "s" digitado durante a animação, antes de a pergunta aparecer, não pode respondê-la.
        alvo = Path(self.home) / "x.txt"
        self.fake.atraso = 0.6
        self.fake.rodadas = [{"tool_calls": [{"function": {"name": "escrever_arquivo",
                                                           "arguments": {"caminho": str(alvo), "conteudo": "oi"}}}]},
                             {"respostas": ["Pronto."]}]
        t = TerminalFalso([], self.home)
        t.esperar("você ›")
        t.digitar("crie x.txt")
        t.digitar("s")  # adiantado: a pergunta só aparece depois de 0,6 s
        t.esperar("(s/n/t)")
        t.digitar("n")
        t.esperar("tokens/s")
        self.assertEqual(t.encerrar(), 0)
        self.assertFalse(alvo.exists())
        self.assertIn("◇ recusado: escrever ~/x.txt", t.texto())

    def test_ctrl_c_na_confirmacao(self):
        alvo, tela = self.chat_que_cria_arquivo(lambda t: (time.sleep(0.2), t.ctrl_c()))
        self.assertFalse(alvo.exists())
        self.assertIn("◇ recusado: escrever ~/x.txt", tela)

    def test_sem_rich_no_terminal(self):
        t = TerminalFalso(["oi"], self.home, PYTHONNOUSERSITE="1")
        t.esperar("pip3 install --user rich")
        self.assertEqual(t.encerrar(), 1)
        self.assertNotIn("Traceback", t.texto())

    def test_sem_rich_saida_simples_funciona(self):
        env_sem_rich = dict(os.environ, HOME=self.home, PYTHONNOUSERSITE="1")
        r = subprocess.run([sys.executable, str(RAIZ / "chrono.py"), "oi"], input="", capture_output=True,
                           text=True, env=env_sem_rich, timeout=30)
        self.assertEqual((r.returncode, r.stdout), (0, "Oi!\n"))


class TestDetalhes(unittest.TestCase):
    """Os seis detalhes menores apontados na revisão final."""

    def test_bloco_de_codigo_mantem_margem_de_cima(self):
        # A margem do bloco de código é uma linha "vazia" com fundo colorido: não pode sumir.
        con = console_de_teste(40)
        con.print(c.Barra(c.Formatado("```python\nx = 1\n```")))
        self.assertEqual(linhas(con), ["▎", "▎  x = 1", "▎"])

    def test_continuacao_de_item_de_lista_fica_no_bloco(self):
        # Linha em branco seguida de linha recuada continua o item; só fecha antes de "2. b".
        self.assertEqual(c.separar_blocos("1. a\n\n   continua\n\n2. b"), (["1. a\n\n   continua"], "2. b"))
        # Enquanto a linha seguinte não começou a chegar, ainda não dá para saber.
        self.assertEqual(c.separar_blocos("a\n\n"), ([], "a\n\n"))

    def test_nome_de_modelo_sem_etiqueta(self):
        self.assertTrue(c.mesmo_modelo("llama3.2", "llama3.2:latest"))
        self.assertTrue(c.mesmo_modelo("qwen3.5:9b", "qwen3.5:9b"))
        self.assertFalse(c.mesmo_modelo("llama3.2", "llama3.2:1b"))

    def test_conversa_com_nome_fora_do_padrao(self):
        arquivo = Path(tempfile.mkdtemp()) / "backup antigo.json"
        arquivo.write_text("{}", encoding="utf-8")
        quando = datetime(2026, 10, 30, 10, 11).timestamp()
        os.utime(arquivo, (quando, quando))
        conv = c.Conversa(c.PADRAO)
        conv.arquivo = arquivo
        self.assertEqual(conv.descricao(), "continuação de 30/10 10:11")

    def test_prompt_nao_suja_saida_redirecionada(self):
        saida = io.StringIO()
        with mock.patch("builtins.input", return_value="oi"), contextlib.redirect_stdout(saida):
            self.assertEqual(c.ler_entrada("você › "), "oi")
        self.assertEqual(saida.getvalue(), "")

    def test_link_mostra_o_endereco(self):
        con = console_de_teste(60)
        con.print(c.Barra(c.Formatado("veja [o site](https://exemplo.com.br)")))
        self.assertEqual(linhas(con), ["▎ veja o site (https://exemplo.com.br)"])


class TestTelaPequena(unittest.TestCase):
    """Janela de 12 linhas: um bloco maior que a tela não pode ficar repetido no histórico."""

    def setUp(self):
        self.fake = FakeOllama().__enter__()
        self.home = preparar_home(self.fake.url)
        self.fake.respostas = [f"- item {i}\n" for i in range(30)]
        self.fake.atraso = 0.03

    def tearDown(self):
        self.fake.__exit__()

    def historico(self, t):
        return Tela(12, 60).escrever(t.bruto.decode("utf-8", "replace")).texto()

    def test_bloco_maior_que_a_tela_aparece_uma_vez(self):
        t = TerminalFalso(["lista"], self.home, linhas=12, colunas=60)
        t.esperar("tokens/s")
        t.encerrar()
        tela = self.historico(t)
        for i in range(30):
            self.assertEqual(tela.count(f"▎  • item {i}"), 1, f"item {i}:\n" + "\n".join(tela))

    def test_ctrl_c_no_meio_de_bloco_maior_que_a_tela(self):
        t = TerminalFalso(["lista"], self.home, linhas=12, colunas=60)
        t.esperar("item 20")  # só aparece enquanto chega se a tela mostrar o fim do bloco
        t.ctrl_c()
        t.esperar("[interrompido]")
        t.encerrar()
        tela = self.historico(t)
        for i in range(20):
            self.assertEqual(tela.count(f"▎  • item {i}"), 1, f"item {i}:\n" + "\n".join(tela))


class TestComandoModelo(unittest.TestCase):
    def setUp(self):
        self.fake = FakeOllama().__enter__()
        self.conv = c.Conversa(dict(c.PADRAO, servidor=self.fake.url))
        self.conv.trocar_modelo(MODELO)
        self.con = console_de_teste(80)
        self.silencio = contextlib.redirect_stdout(io.StringIO())  # comando() avisa com print()
        self.silencio.__enter__()

    def tearDown(self):
        self.silencio.__exit__(None, None, None)
        self.fake.__exit__()

    def test_comando_ferramentas(self):
        self.assertTrue(self.conv.ferramentas)
        c.comando(self.conv, "/ferramentas", [], self.con)
        self.assertFalse(self.conv.ferramentas)
        c.comando(self.conv, "/ferramentas", [], self.con)
        self.assertTrue(self.conv.ferramentas)

    def test_modelo_que_falha_nao_religa_ferramentas(self):
        self.conv.ferramentas = False
        c.comando(self.conv, f"/modelo {QUEBRADO}", [], self.con)
        self.assertFalse(self.conv.ferramentas)

    def test_comando_ferramentas_sem_suporte(self):
        self.conv.recursos.discard("tools")
        self.conv.ferramentas = False
        c.comando(self.conv, "/ferramentas", [], self.con)
        self.assertFalse(self.conv.ferramentas)

    def test_modelo_que_falha_ao_carregar_nao_troca(self):
        self.assertTrue(c.comando(self.conv, f"/modelo {QUEBRADO}", [], self.con))
        self.assertEqual(self.conv.modelo, MODELO)
        self.assertIn("vision", self.conv.recursos)

    def test_ctrl_c_ao_trocar_modelo_volta_ao_anterior(self):
        def interromper(config, modelo):
            raise KeyboardInterrupt
        original, c.carregar_modelo = c.carregar_modelo, interromper
        try:
            self.assertTrue(c.comando(self.conv, f"/modelo {QUEBRADO}", [], self.con))
        finally:
            c.carregar_modelo = original
        self.assertEqual(self.conv.modelo, MODELO)


def ferramentas_pedidas(pedido):
    return [t["function"]["name"] for t in pedido.get("tools", [])]


class TestAgenteNaConversa(unittest.TestCase):
    def setUp(self):
        self.fake = FakeOllama().__enter__()
        self._conversas = c.CONVERSAS
        c.CONVERSAS = Path(tempfile.mkdtemp()) / "conversas"
        self.conv = c.Conversa(dict(c.PADRAO, servidor=self.fake.url))
        self.conv.trocar_modelo(MODELO)

    def tearDown(self):
        c.CONVERSAS = self._conversas
        self.fake.__exit__()

    def agente(self, **campos):
        return c.agentes.Agente(**dict({"nome": "x", "instrucoes": "Seja X."}, **campos))

    def test_usar_agente_aplica_tudo(self):
        agente = self.agente(modelo=OUTRO, pensar=True, ferramentas="leitura")
        self.conv.usar_agente(agente)
        self.assertIs(self.conv.agente, agente)
        self.assertEqual((self.conv.modelo, self.conv.pensar, self.conv.so_leitura, self.conv.ferramentas),
                         (OUTRO, True, True, True))
        self.assertEqual(self.conv.mensagens, [{"role": "system", "content": "Seja X."}])

    def test_sem_agente_usa_o_config(self):
        self.conv.usar_agente(self.agente(pensar=True))
        self.conv.usar_agente(None)
        self.assertIsNone(self.conv.agente)
        self.assertEqual((self.conv.modelo, self.conv.pensar, self.conv.so_leitura), (MODELO, False, False))
        self.assertEqual(self.conv.mensagens, [{"role": "system", "content": c.PADRAO["sistema"]}])

    def test_so_leitura_nao_oferece_alteracoes(self):
        self.conv.usar_agente(self.agente(ferramentas="leitura"))
        self.conv.perguntar("oi", exibidor=Gravador())
        nomes = ferramentas_pedidas(self.fake.pedidos[-1])
        self.assertIn("ler_arquivo", nomes)
        self.assertNotIn("escrever_arquivo", nomes)

    def test_ferramentas_desligadas(self):
        self.conv.usar_agente(self.agente(ferramentas="desligadas"))
        self.assertFalse(self.conv.ferramentas)
        self.conv.perguntar("oi", exibidor=Gravador())
        self.assertNotIn("tools", self.fake.pedidos[-1])

    def test_modelo_da_opcao_ganha_do_agente(self):
        self.conv.usar_agente(self.agente(modelo=OUTRO, ferramentas="desligadas"), modelo=MODELO)
        self.assertEqual(self.conv.modelo, MODELO)
        self.assertFalse(self.conv.ferramentas)

    def test_agente_com_modelo_inexistente_nao_troca(self):
        primeiro = self.agente(nome="a", instrucoes="A.")
        self.conv.usar_agente(primeiro)
        self.conv.mensagens.append({"role": "user", "content": "oi"})
        antes = list(self.conv.mensagens)
        with self.assertRaises(c.ErroIA):
            self.conv.usar_agente(self.agente(modelo="nao-existe"))
        self.assertIs(self.conv.agente, primeiro)
        self.assertEqual((self.conv.modelo, self.conv.mensagens), (MODELO, antes))

    def test_continuar_mantem_historico_e_modelo(self):
        self.conv.mensagens.append({"role": "user", "content": "oi"})
        self.conv.modelo = OUTRO  # como se viesse da conversa salva
        self.conv.usar_agente(self.agente(modelo=MODELO, pensar=True), nova_conversa=False)
        self.assertEqual((self.conv.modelo, self.conv.pensar), (OUTRO, True))
        self.assertEqual(self.conv.mensagens[-1], {"role": "user", "content": "oi"})

    def test_conversa_salva_o_agente(self):
        self.conv.usar_agente(self.agente(nome="atendente"))
        self.conv.perguntar("oi", exibidor=Gravador())
        self.assertEqual(json.loads(self.conv.arquivo.read_text(encoding="utf-8"))["agente"], "atendente")

    def test_descrever_agente(self):
        self.assertEqual(c.descrever_agente(self.conv), "geral (padrão do config.json)")
        self.conv.usar_agente(self.agente(nome="atendente", descricao="rascunha respostas"))
        self.assertEqual(c.descrever_agente(self.conv), "atendente · rascunha respostas")
        self.conv.usar_agente(self.agente(nome="curto"))
        self.assertEqual(c.descrever_agente(self.conv), "curto")

    def test_descrever_agente_salvo_sem_arquivo(self):
        self.conv.usar_agente(None)
        self.conv.agente_salvo = "atendente"
        self.assertEqual(c.descrever_agente(self.conv), "atendente (arquivo do agente indisponível; usando o config.json)")

    def test_cabecalho_agente_com_colchetes(self):
        con = console_de_teste(100)
        con.print(c.cabecalho(MODELO, SHOW, PS, "nova", "desligado", "ligadas", agente="x · respostas [/ml] [b]rápidas"))
        self.assertIn("x · respostas [/ml] [b]rápidas", con.file.getvalue())

    def test_cabecalho_mostra_agente(self):
        con = console_de_teste(100)
        con.print(c.cabecalho(MODELO, SHOW, PS, "nova", "desligado", "ligadas",
                              agente="atendente · rascunha respostas"))
        self.assertRegex(con.file.getvalue(), r"agente\s+atendente · rascunha respostas")


class TestComandoAgente(unittest.TestCase):
    def setUp(self):
        self.fake = FakeOllama().__enter__()
        self._guardados = (c.CONVERSAS, c.PASTA_AGENTES, c.abrir_no_textedit, c.carregar_modelo)
        c.CONVERSAS = Path(tempfile.mkdtemp()) / "conversas"
        c.PASTA_AGENTES = Path(tempfile.mkdtemp()) / "agentes"
        c.agentes.criar_prontos(c.PASTA_AGENTES, c.PADRAO["sistema"])
        self.abertos = []
        c.abrir_no_textedit = self.abertos.append
        self.conv = c.Conversa(dict(c.PADRAO, servidor=self.fake.url))
        self.conv.usar_agente(c.agentes.carregar(c.PASTA_AGENTES, "geral"))
        self.con = console_de_teste(80)
        self.saida = io.StringIO()
        self.silencio = contextlib.redirect_stdout(self.saida)
        self.silencio.__enter__()

    def tearDown(self):
        self.silencio.__exit__(None, None, None)
        c.CONVERSAS, c.PASTA_AGENTES, c.abrir_no_textedit, c.carregar_modelo = self._guardados
        self.fake.__exit__()

    def comando(self, texto):
        return c.comando(self.conv, texto, [], self.con)

    def escrever(self, nome, texto):
        (c.PASTA_AGENTES / f"{nome}.txt").write_text(texto, encoding="utf-8")

    def conversa_com_historico(self):
        self.conv.mensagens += [{"role": "user", "content": "oi"}, {"role": "assistant", "content": "Oi!"}]
        return list(self.conv.mensagens)

    def test_trocar_comeca_conversa_nova(self):
        self.conversa_com_historico()
        self.assertTrue(self.comando("/agente atendente"))
        self.assertEqual(self.conv.agente.nome, "atendente")
        self.assertEqual(len(self.conv.mensagens), 1)
        self.assertTrue(self.conv.mensagens[0]["content"].startswith("Você ajuda a JR Auto Peças"))
        self.assertTrue(self.conv.so_leitura)

    def test_trocar_para_o_mesmo_recarrega(self):
        self.comando("/agente atendente")
        self.escrever("atendente", "descrição: novo\n\nInstruções novas.")
        self.comando("/agente atendente")
        self.assertEqual(self.conv.mensagens[0]["content"], "Instruções novas.")

    def test_nova_mantem_o_agente(self):
        self.comando("/agente atendente")
        self.conversa_com_historico()
        self.comando("/nova")
        self.assertEqual(self.conv.agente.nome, "atendente")
        self.assertEqual(len(self.conv.mensagens), 1)
        self.assertTrue(self.conv.mensagens[0]["content"].startswith("Você ajuda a JR Auto Peças"))

    def test_agente_com_modelo_quebrado_mantem_o_anterior(self):
        self.escrever("pesado", f"modelo: {QUEBRADO}\n\nx")
        antes = self.conversa_com_historico()
        self.assertTrue(self.comando("/agente pesado"))
        self.assertEqual((self.conv.agente.nome, self.conv.modelo, self.conv.mensagens), ("geral", MODELO, antes))
        self.assertIn("Continua com o agente geral.", self.saida.getvalue())

    def test_ctrl_c_na_troca_volta_ao_anterior(self):
        def interromper(config, modelo):
            raise KeyboardInterrupt
        c.carregar_modelo = interromper
        antes = self.conversa_com_historico()
        self.assertTrue(self.comando("/agente atendente"))
        self.assertEqual((self.conv.agente.nome, self.conv.mensagens, self.conv.so_leitura), ("geral", antes, False))
        self.assertIn("[interrompido]", self.saida.getvalue())

    def test_agente_quebrado_nao_troca(self):
        self.escrever("quebrado", "modlo: x\ndescrição: y\n\nz")
        self.assertTrue(self.comando("/agente quebrado"))
        self.assertIn('não conheço "modlo"', self.saida.getvalue())
        self.assertEqual(self.conv.agente.nome, "geral")

    def test_agente_inexistente_no_chat(self):
        self.comando("/agente vendas")
        self.assertIn("Não existe o agente vendas; os agentes são: atendente, geral, planilhas", self.saida.getvalue())
        self.assertEqual(self.conv.agente.nome, "geral")

    def test_lista_com_agente_quebrado(self):
        self.escrever("quebrado", "modlo: x\ndescrição: y\n\nz")
        self.comando("/agente")
        saida = self.saida.getvalue()
        self.assertIn("Agente: geral · assistente para qualquer assunto", saida)
        self.assertRegex(saida, r"● geral\s+assistente para qualquer assunto")
        self.assertRegex(saida, r"  atendente\s+rascunha respostas para clientes do Mercado Livre")
        self.assertRegex(saida, r"  quebrado\s+⚠ linha 1 do agente quebrado")
        self.assertIn("Trocar: /agente NOME · criar: /agente novo NOME · editar: /agente editar [NOME]", saida)

    def test_novo_cria_e_abre(self):
        self.comando("/agente novo vendas")
        self.assertTrue((c.PASTA_AGENTES / "vendas.txt").exists())
        self.assertEqual(self.abertos, [c.PASTA_AGENTES / "vendas.txt"])
        self.assertIn("/agente vendas", self.saida.getvalue())

    def test_novo_recusa_existente(self):
        self.comando("/agente novo atendente")
        self.assertIn("Já existe o agente atendente", self.saida.getvalue())
        self.assertEqual(self.abertos, [])

    def test_novo_com_erro_do_sistema(self):
        self.assertTrue(self.comando("/agente novo " + "a" * 300))
        self.assertIn("Não consegui criar o agente", self.saida.getvalue())
        self.assertEqual(self.abertos, [])

    def test_novo_sem_nome(self):
        self.comando("/agente novo")
        self.assertIn("Use: /agente novo NOME", self.saida.getvalue())
        self.assertEqual(self.abertos, [])

    def test_editar_abre_o_atual(self):
        self.comando("/agente planilhas")
        self.comando("/agente editar")
        self.comando("/agente editar atendente")
        self.assertEqual(self.abertos, [c.PASTA_AGENTES / "planilhas.txt", c.PASTA_AGENTES / "atendente.txt"])
        self.assertIn("A mudança vale na próxima vez que você usar /agente planilhas.", self.saida.getvalue())

    def test_editar_agente_quebrado_abre(self):
        # É justamente para consertar que se abre um agente com erro.
        self.escrever("quebrado", "modlo: x\n\nz")
        self.comando("/agente editar quebrado")
        self.assertEqual(self.abertos, [c.PASTA_AGENTES / "quebrado.txt"])

    def test_editar_sem_agente(self):
        self.conv.usar_agente(None)
        self.comando("/agente editar")
        self.assertIn("O agente atual vem do config.json; para editar o geral, use /agente editar geral.",
                      self.saida.getvalue())
        self.assertEqual(self.abertos, [])

    def test_modelo_mantem_ferramentas_desligadas(self):
        self.escrever("calado", "ferramentas: desligadas\n\nx")
        self.comando("/agente calado")
        self.comando(f"/modelo {MODELO}")
        self.assertFalse(self.conv.ferramentas)

    def test_ajuda_lista_agente(self):
        self.comando("/ajuda")
        self.assertIn("/agente [nome]", self.saida.getvalue())
        self.assertIn("/agente novo NOME", self.saida.getvalue())


class TestMenuAgentes(unittest.TestCase):
    """O /agente no terminal de verdade: o menu com as setas."""

    def setUp(self):
        self.fake = FakeOllama().__enter__()
        self.home = preparar_home(self.fake.url)
        self.agentes = Path(self.home) / ".chrono" / "agentes"
        # Um "open" de mentira na frente do PATH: os testes nunca abrem o TextEdit de verdade.
        self.bin = Path(tempfile.mkdtemp())
        self.abertos = self.bin / "abertos.txt"
        (self.bin / "open").write_text(f'#!/bin/sh\necho "$@" >> "{self.abertos}"\n', encoding="utf-8")
        (self.bin / "open").chmod(0o755)

    def tearDown(self):
        self.fake.__exit__()

    def abrir_chat(self):
        t = TerminalFalso([], self.home, PATH=f"{self.bin}:{os.environ['PATH']}")
        t.esperar("você ›")
        return t

    def abrir_menu(self, t):
        t.digitar("/agente")
        t.esperar("Escolha o agente")

    def teclas(self, t, *pedacos):
        for pedaco in pedacos:
            time.sleep(0.15)
            os.write(t.fd, pedaco)

    def abertos_no_textedit(self):
        return self.abertos.read_text(encoding="utf-8").splitlines() if self.abertos.exists() else []

    def test_menu_seta_e_enter_troca(self):
        t = self.abrir_chat()
        self.abrir_menu(t)
        self.teclas(t, b"\x1b[B", b"\r")  # geral → planilhas
        t.esperar("planilhas · lê, organiza")
        t.esperar("você ›")
        self.abrir_menu(t)
        t.esperar("● planilhas")
        self.teclas(t, b"\x1b")
        t.esperar("Continua com o agente planilhas")
        self.assertEqual(t.encerrar(), 0)

    def test_menu_esc_nao_troca(self):
        t = self.abrir_chat()
        self.abrir_menu(t)
        self.teclas(t, b"\x1b")
        t.esperar("Continua com o agente geral · assistente para qualquer assunto.")
        t.esperar("você ›")
        self.assertEqual(t.encerrar(), 0)
        self.assertEqual(t.texto().count("◆ chrono"), 1)

    def test_menu_e_abre_no_textedit(self):
        t = self.abrir_chat()
        self.abrir_menu(t)
        self.teclas(t, b"\x1b[A", b"e")  # geral → atendente
        t.esperar("A mudança vale na próxima vez que você usar /agente atendente.")
        self.assertEqual(t.encerrar(), 0)
        self.assertEqual(len(self.abertos_no_textedit()), 1)
        self.assertTrue(self.abertos_no_textedit()[0].startswith("-e "))
        self.assertTrue(self.abertos_no_textedit()[0].endswith("atendente.txt"))

    def test_menu_cria_agente_novo(self):
        t = self.abrir_chat()
        self.abrir_menu(t)
        self.teclas(t, b"\x1b[A", b"\x1b[A", b"\r")  # geral → atendente → "+ criar agente novo"
        t.esperar("Nome do agente novo:")
        t.digitar("vendas")
        t.esperar("Criei o agente vendas")
        self.assertEqual(t.encerrar(), 0)
        self.assertTrue((self.agentes / "vendas.txt").exists())
        self.assertTrue(self.abertos_no_textedit()[0].endswith("vendas.txt"))

    def test_menu_agente_quebrado_mostra_erro(self):
        t = self.abrir_chat()  # a primeira vez cria os agentes prontos
        (self.agentes / "quebrado.txt").write_text("modlo: x\n\nz", encoding="utf-8")
        self.abrir_menu(t)
        t.esperar("⚠")
        self.teclas(t, b"\x1b[B", b"\x1b[B", b"\r")  # geral → planilhas → quebrado
        t.esperar('não conheço "modlo"')
        t.esperar("você ›")
        self.abrir_menu(t)
        t.esperar("● geral")
        self.teclas(t, b"\x1b")
        t.esperar("Continua com o agente geral")
        self.assertEqual(t.encerrar(), 0)

    def test_menu_ctrl_c_restaura_o_terminal(self):
        t = self.abrir_chat()
        self.abrir_menu(t)
        self.teclas(t, b"\x03")
        t.esperar("você ›")
        t.digitar("/modelo")
        t.esperar(f"Modelo: {MODELO}")
        self.assertEqual(t.encerrar(), 0)
        self.assertIn("você › /modelo", t.texto())  # o eco do teclado voltou

    def test_menu_ignora_o_que_foi_digitado_antes(self):
        t = self.abrir_chat()
        time.sleep(0.2)
        os.write(t.fd, b"/agente\r\r")  # o segundo Enter chega antes de o menu abrir
        t.esperar("Escolha o agente")
        time.sleep(0.5)
        self.teclas(t, b"\x1b")
        t.esperar("Continua com o agente geral")
        self.assertEqual(t.encerrar(), 0)

    def test_menu_novo_esc_desiste(self):
        # No readline, o Esc se juntava à tecla seguinte: Esc + "vendas" criava "endas.txt".
        t = self.abrir_chat()
        self.abrir_menu(t)
        self.teclas(t, b"\x1b[A", b"\x1b[A", b"\r")
        t.esperar("Nome do agente novo")
        self.teclas(t, b"ven", b"\x1b")
        t.esperar("Nenhum agente criado.")
        t.esperar("você ›")
        self.assertEqual(t.encerrar(), 0)
        self.assertEqual(sorted(p.name for p in self.agentes.iterdir()),
                         ["atendente.txt", "geral.txt", "planilhas.txt"])

    def test_menu_novo_com_acento_e_apagar(self):
        t = self.abrir_chat()
        self.abrir_menu(t)
        self.teclas(t, b"\x1b[A", b"\x1b[A", b"\r")
        t.esperar("Nome do agente novo")
        self.teclas(t, "Orçamenx".encode(), b"\x7f", b"to", b"\r")
        t.esperar("Criei o agente Orçamento")
        self.assertEqual(t.encerrar(), 0)
        self.assertTrue((self.agentes / "Orçamento.txt").exists())

    def test_menu_enter_no_atual_mantem_a_conversa(self):
        t = self.abrir_chat()
        t.digitar("oi")
        t.esperar("tokens/s")
        t.esperar("você ›")
        self.abrir_menu(t)
        self.teclas(t, b"\r")  # o menu abre no agente atual (geral)
        t.esperar("Você já está no agente geral; a conversa continua.")
        t.esperar("você ›")
        self.assertEqual(t.encerrar(), 0)
        self.assertEqual(t.texto().count("◆ chrono"), 1)

    def test_terminal_simples_mostra_a_lista(self):
        # Num terminal "dumb" a rich não desenha a parte ao vivo: o menu ficaria invisível.
        t = TerminalFalso([], self.home, TERM="dumb", PATH=f"{self.bin}:{os.environ['PATH']}")
        t.esperar("você ›")
        t.digitar("/agente")
        t.esperar("Trocar: /agente NOME")
        self.assertEqual(t.encerrar(), 0)
        self.assertNotIn("Escolha o agente", t.texto())

    def test_menu_sem_agentes_cria(self):
        self.agentes.mkdir()  # pasta vazia: os agentes prontos não são criados
        t = self.abrir_chat()
        self.abrir_menu(t)
        t.esperar("+ criar agente novo")
        self.teclas(t, b"\r")
        t.esperar("Nome do agente novo:")
        t.digitar("vendas")
        t.esperar("Criei o agente vendas")
        self.assertEqual(t.encerrar(), 0)
        self.assertTrue((self.agentes / "vendas.txt").exists())


def escrever_skill(pasta, nome, descricao, instrucoes):
    (pasta / nome).mkdir(parents=True, exist_ok=True)
    (pasta / nome / "SKILL.md").write_text(f"---\nname: {nome}\ndescription: {descricao}\n---\n\n{instrucoes}\n",
                                          encoding="utf-8")


class TestSkillsNaConversa(unittest.TestCase):
    def setUp(self):
        self.fake = FakeOllama().__enter__()
        self._guardados = (c.CONVERSAS, c.PASTA_SKILLS)
        c.CONVERSAS = Path(tempfile.mkdtemp()) / "conversas"
        c.PASTA_SKILLS = Path(tempfile.mkdtemp()) / "skills"
        c.skills.criar_prontas(c.PASTA_SKILLS)
        escrever_skill(c.PASTA_SKILLS, "x", "faz x", "Faça x.")
        self.conv = c.Conversa(dict(c.PADRAO, servidor=self.fake.url))
        self.conv.trocar_modelo(MODELO)
        lixeira = mock.patch.object(c.ferramentas, "LIXEIRA", Path(tempfile.mkdtemp()))
        lixeira.start()
        self.addCleanup(lixeira.stop)

    def tearDown(self):
        c.CONVERSAS, c.PASTA_SKILLS = self._guardados
        self.fake.__exit__()

    def skill(self, nome):
        return c.skills.carregar(c.PASTA_SKILLS, nome)

    def test_skill_vai_no_prompt_e_nao_no_historico(self):
        self.conv.ligar_skill(self.skill("x"))
        self.conv.perguntar("oi", exibidor=Gravador())
        sistema = self.fake.pedidos[-1]["messages"][0]["content"]
        self.assertTrue(sistema.endswith("\n\n" + c.skills.texto_para_o_modelo(self.skill("x"))))
        self.assertEqual(self.conv.mensagens[0]["content"], c.PADRAO["sistema"])

    def test_skill_vai_no_prompt_mesmo_sem_ferramentas(self):
        self.conv.ferramentas = False
        self.conv.ligar_skill(self.skill("x"))
        self.conv.perguntar("oi", exibidor=Gravador())
        self.assertIn("# Skill ligada: x", self.fake.pedidos[-1]["messages"][0]["content"])

    def test_ligar_de_novo_recarrega(self):
        self.assertFalse(self.conv.ligar_skill(self.skill("x")))
        self.assertTrue(self.conv.ligar_skill(self.skill("X")))
        self.assertEqual(len(self.conv.skills), 1)
        self.assertTrue(self.conv.desligar_skill("x"))
        self.assertFalse(self.conv.desligar_skill("x"))

    def test_criar_skill_so_com_a_skill_creator(self):
        self.conv.perguntar("oi", exibidor=Gravador())
        self.assertNotIn("criar_skill", ferramentas_pedidas(self.fake.pedidos[-1]))
        self.conv.ligar_skill(self.skill("skill-creator"))
        self.conv.perguntar("oi", exibidor=Gravador())
        self.assertIn("criar_skill", ferramentas_pedidas(self.fake.pedidos[-1]))
        self.conv.so_leitura = True
        self.conv.perguntar("oi", exibidor=Gravador())
        self.assertNotIn("criar_skill", ferramentas_pedidas(self.fake.pedidos[-1]))

    def test_criar_skill_pelo_modelo(self):
        self.conv.ligar_skill(self.skill("skill-creator"))
        argumentos = {"nome": "vendas", "descricao": "resume as vendas", "instrucoes": "1. Leia."}
        self.fake.rodadas = [{"tool_calls": [{"function": {"name": "criar_skill", "arguments": argumentos}}]},
                             {"respostas": ["Pronto."]}]
        gravador = Gravador(["s"])
        self.conv.perguntar("salva", exibidor=gravador)
        self.assertEqual(c.skills.carregar(c.PASTA_SKILLS, "vendas").descricao, "resume as vendas")
        self.assertIn(("acao", "criada a skill vendas", True), gravador.chamadas)

    def test_modelo_sabe_quando_nao_pode_salvar(self):
        aviso = "A ferramenta criar_skill não está disponível agora"
        self.conv.ligar_skill(self.skill("skill-creator"))
        self.conv.perguntar("oi", exibidor=Gravador())
        self.assertNotIn(aviso, self.fake.pedidos[-1]["messages"][0]["content"])
        self.conv.so_leitura = True
        self.conv.perguntar("oi", exibidor=Gravador())
        self.assertIn(aviso, self.fake.pedidos[-1]["messages"][0]["content"])

    def test_conversa_salva_as_skills(self):
        self.conv.ligar_skill(self.skill("x"))
        self.conv.perguntar("oi", exibidor=Gravador())
        self.assertEqual(json.loads(self.conv.arquivo.read_text(encoding="utf-8"))["skills"], ["x"])

    def test_texto_do_prompt(self):
        self.assertEqual(c.texto_do_prompt(self.conv), "você ›")
        self.conv.ligar_skill(self.skill("x"))
        self.conv.ligar_skill(self.skill("skill-creator"))
        self.assertEqual(c.texto_do_prompt(self.conv), "você · x, skill-creator ›")


class TestComandoSkill(unittest.TestCase):
    def setUp(self):
        self.fake = FakeOllama().__enter__()
        self._guardados = (c.CONVERSAS, c.PASTA_SKILLS, c.PASTA_AGENTES, c.abrir_no_textedit)
        c.CONVERSAS = Path(tempfile.mkdtemp()) / "conversas"
        c.PASTA_SKILLS = Path(tempfile.mkdtemp()) / "skills"
        c.skills.criar_prontas(c.PASTA_SKILLS)
        escrever_skill(c.PASTA_SKILLS, "x", "faz x", "Faça x.")
        escrever_skill(c.PASTA_SKILLS, "y", "faz y", "Faça y.")
        c.PASTA_AGENTES = Path(tempfile.mkdtemp()) / "agentes"
        c.agentes.criar_prontos(c.PASTA_AGENTES, c.PADRAO["sistema"])
        self.abertos = []
        c.abrir_no_textedit = self.abertos.append
        self.conv = c.Conversa(dict(c.PADRAO, servidor=self.fake.url))
        self.conv.usar_agente(c.agentes.carregar(c.PASTA_AGENTES, "geral"))
        self.con = console_de_teste(80)
        self.saida = io.StringIO()
        self.silencio = contextlib.redirect_stdout(self.saida)
        self.silencio.__enter__()

    def tearDown(self):
        self.silencio.__exit__(None, None, None)
        c.CONVERSAS, c.PASTA_SKILLS, c.PASTA_AGENTES, c.abrir_no_textedit = self._guardados
        self.fake.__exit__()

    def comando(self, texto):
        return c.comando(self.conv, texto, [], self.con)

    def ligadas(self):
        return [s.nome for s in self.conv.skills]

    def test_skill_liga_e_recarrega(self):
        self.comando("/skill x")
        self.comando("/skill X")
        self.assertEqual(self.ligadas(), ["x"])
        self.assertIn("Skill x ligada.", self.saida.getvalue())
        self.assertIn("Skill x recarregada.", self.saida.getvalue())

    def test_skill_desligar(self):
        self.comando("/skill desligar")
        self.assertIn("Nenhuma skill estava ligada.", self.saida.getvalue())
        self.comando("/skill x")
        self.comando("/skill y")
        self.comando("/skill desligar x")
        self.assertEqual(self.ligadas(), ["y"])
        self.assertIn("Skill x desligada.", self.saida.getvalue())
        self.comando("/skill desligar x")
        self.assertIn("Não há skill x ligada.", self.saida.getvalue())
        self.comando("/skill desligar")
        self.assertEqual(self.ligadas(), [])
        self.assertIn("Skills desligadas.", self.saida.getvalue())

    def test_skill_inexistente(self):
        self.comando("/skill vendas")
        self.assertIn("Não existe a skill vendas; as skills são: skill-creator, x, y", self.saida.getvalue())
        self.assertEqual(self.ligadas(), [])

    def test_skill_editar_abre(self):
        self.comando("/skill editar x")
        self.assertEqual(self.abertos, [c.PASTA_SKILLS / "x" / "SKILL.md"])
        self.assertIn("A mudança vale na próxima vez que você ligar a skill (/skill x).", self.saida.getvalue())
        self.comando("/skill editar")
        self.assertIn("Use: /skill editar NOME", self.saida.getvalue())

    def test_lista_de_skills(self):
        self.comando("/skill x")
        self.comando("/skill")
        saida = self.saida.getvalue()
        self.assertRegex(saida, r"✓ x\s+faz x")
        self.assertRegex(saida, r"  skill-creator\s+ajuda a criar uma skill nova para o chrono")
        self.assertIn("Use: /skill NOME · desligar: /skill desligar [NOME] · editar: /skill editar NOME", saida)

    def test_skill_creator_sem_ferramentas_avisa(self):
        self.comando("/agente atendente")  # só leitura
        self.comando("/skill skill-creator")
        self.assertIn("A skill-creator precisa das ferramentas ligadas para salvar a skill; com este agente ela "
                      "só consegue escrever o texto para você copiar.", self.saida.getvalue())

    def test_nova_desliga_as_skills(self):
        self.comando("/skill x")
        self.comando("/nova")
        self.assertEqual(self.ligadas(), [])
        self.assertIn("Skills desligadas.", self.saida.getvalue())

    def test_trocar_agente_desliga_as_skills(self):
        self.comando("/skill x")
        self.comando("/agente planilhas")
        self.assertEqual(self.ligadas(), [])
        self.assertIn("Skills desligadas.", self.saida.getvalue())

    def test_ajuda_lista_skill(self):
        self.comando("/ajuda")
        for trecho in ("/skill [nome]", "/skill desligar [nome]", "/skill editar NOME"):
            self.assertIn(trecho, self.saida.getvalue())


class TestSkillsNoPrograma(unittest.TestCase):
    def setUp(self):
        self.fake = FakeOllama().__enter__()
        self.home = preparar_home(self.fake.url)
        self.skills = Path(self.home) / ".chrono" / "skills"

    def tearDown(self):
        self.fake.__exit__()

    def sistema_pedido(self):
        return self.fake.pedidos[-1]["messages"][0]["content"]

    def test_primeira_vez_cria_a_skill_creator(self):
        self.assertEqual(rodar(["oi"], self.home).returncode, 0)
        self.assertTrue((self.skills / "skill-creator" / "SKILL.md").exists())

    def test_opcao_s_liga_a_skill(self):
        escrever_skill(self.skills, "x", "faz x", "Faça x.")
        r = rodar(["-s", "x", "oi"], self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("# Skill ligada: x\n(faz x)\nFaça x.", self.sistema_pedido())

    def test_opcao_s_inexistente(self):
        rodar(["oi"], self.home)
        r = rodar(["-s", "vendas", "oi"], self.home)
        self.assertEqual(r.returncode, 1)
        self.assertIn("Não existe a skill vendas; as skills são: skill-creator", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_continuar_volta_com_as_skills(self):
        escrever_skill(self.skills, "x", "faz x", "Faça x.")
        self.assertEqual(rodar(["-s", "x", "oi"], self.home).returncode, 0)
        r = rodar(["-c", "e agora?"], self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("# Skill ligada: x", self.sistema_pedido())

    def test_continuar_skill_sumiu_avisa(self):
        escrever_skill(self.skills, "x", "faz x", "Faça x.")
        self.assertEqual(rodar(["-s", "x", "oi"], self.home).returncode, 0)
        (self.skills / "x" / "SKILL.md").unlink()
        (self.skills / "x").rmdir()
        r = rodar(["-c", "e agora?"], self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Não liguei a skill x", r.stderr)
        self.assertNotIn("# Skill ligada", self.sistema_pedido())

    def test_pergunta_rapida_avisa_as_skills_ligadas(self):
        # Sem prompt na tela, o -c religava as skills da última conversa sem aviso nenhum.
        escrever_skill(self.skills, "x", "faz x", "Faça x.")
        self.assertIn("Skills ligadas: x", rodar(["-s", "x", "oi"], self.home).stderr)
        self.assertIn("Skills ligadas: x", rodar(["-c", "e agora?"], self.home).stderr)

    def test_opcao_s_criador_no_chat_avisa(self):
        t = TerminalFalso(["-a", "atendente", "-s", "skill-creator"], self.home)  # atendente: só leitura
        t.esperar("A skill-creator precisa das ferramentas ligadas")
        t.esperar("você · skill-creator ›")
        self.assertEqual(t.encerrar(), 0)

    def test_menu_liga_criador_avisa(self):
        t = TerminalFalso(["-a", "atendente"], self.home)
        t.esperar("você ›")
        t.digitar("/skill")
        t.esperar("Skills   ↑↓ escolher")
        for tecla in (b"\r", b"\x1b"):  # liga a skill-creator (a primeira) e sai
            time.sleep(0.15)
            os.write(t.fd, tecla)
        t.esperar("A skill-creator precisa das ferramentas ligadas")
        self.assertEqual(t.encerrar(), 0)

    def test_menu_e_no_criar_nao_liga(self):
        t = TerminalFalso([], self.home)
        t.esperar("você ›")
        t.digitar("/skill")
        t.esperar("+ criar skill nova")
        for tecla in (b"\x1b[B", b"e"):
            time.sleep(0.15)
            os.write(t.fd, tecla)
        t.esperar("Nenhuma skill ligada.")
        t.esperar("você ›")
        self.assertEqual(t.encerrar(), 0)
        self.assertNotIn("você · skill-creator", t.texto())

    def test_listar_skills(self):
        r = rodar(["--skills"], self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"skill-creator\s+ajuda a criar uma skill nova para o chrono")

    def test_prompt_mostra_as_skills(self):
        escrever_skill(self.skills, "x", "faz x", "Faça x.")
        t = TerminalFalso([], self.home)
        t.esperar("você ›")
        t.digitar("/skill x")
        t.esperar("você · x ›")
        self.assertEqual(t.encerrar(), 0)

    def test_menu_de_skills_liga_varias(self):
        escrever_skill(self.skills, "a", "faz a", "Faça a.")
        escrever_skill(self.skills, "b", "faz b", "Faça b.")
        t = TerminalFalso([], self.home)
        t.esperar("você ›")
        t.digitar("/skill")
        t.esperar("Skills   ↑↓ escolher")
        for tecla in (b"\r", b"\x1b[B", b"\r", b"\x1b"):
            time.sleep(0.15)
            os.write(t.fd, tecla)
        t.esperar("Skills ligadas: a, b")
        t.esperar("você · a, b ›")
        self.assertEqual(t.encerrar(), 0)

    def test_menu_de_skills_criar_liga_o_criador(self):
        t = TerminalFalso([], self.home)  # a primeira vez cria só a skill-creator
        t.esperar("você ›")
        t.digitar("/skill")
        t.esperar("+ criar skill nova")
        for tecla in (b"\x1b[B", b"\r"):
            time.sleep(0.15)
            os.write(t.fd, tecla)
        t.esperar("A skill-creator está ligada: diga que skill você quer criar.")
        t.esperar("você · skill-creator ›")
        self.assertEqual(t.encerrar(), 0)


class TestAgentesNoPrograma(unittest.TestCase):
    def setUp(self):
        self.fake = FakeOllama().__enter__()
        self.home = preparar_home(self.fake.url)
        self.agentes = Path(self.home) / ".chrono" / "agentes"

    def tearDown(self):
        self.fake.__exit__()

    def escrever_agente(self, nome, texto):
        self.agentes.mkdir(exist_ok=True)
        (self.agentes / f"{nome}.txt").write_text(texto, encoding="utf-8")

    def sistema_pedido(self):
        return self.fake.pedidos[-1]["messages"][0]["content"]

    def test_primeira_vez_cria_os_agentes(self):
        self.assertEqual(rodar(["oi"], self.home).returncode, 0)
        self.assertEqual(sorted(p.name for p in self.agentes.iterdir()),
                         ["atendente.txt", "geral.txt", "planilhas.txt"])
        self.assertIn(c.PADRAO["sistema"], (self.agentes / "geral.txt").read_text(encoding="utf-8"))

    def test_chrono_sem_opcao_igual_a_hoje(self):
        r = rodar(["oi"], self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        pedido = self.fake.pedidos[-1]
        self.assertTrue(self.sistema_pedido().startswith(c.PADRAO["sistema"]))
        self.assertEqual((pedido["model"], pedido["think"]), (MODELO, False))
        self.assertIn("ler_arquivo", ferramentas_pedidas(pedido))

    def test_opcao_a_usa_o_agente(self):
        self.escrever_agente("curto", f"modelo: {OUTRO}\n\nResponda curto.")
        r = rodar(["-a", "curto", "oi"], self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.fake.pedidos[-1]["model"], OUTRO)
        self.assertTrue(self.sistema_pedido().startswith("Responda curto."))

    def test_m_ganha_do_agente(self):
        self.escrever_agente("curto", f"modelo: {OUTRO}\n\nResponda curto.")
        self.assertEqual(rodar(["-a", "curto", "-m", MODELO, "oi"], self.home).returncode, 0)
        self.assertEqual(self.fake.pedidos[-1]["model"], MODELO)

    def test_agente_inexistente(self):
        r = rodar(["-a", "vendas", "oi"], self.home)
        self.assertEqual(r.returncode, 1)
        self.assertIn("Não existe o agente vendas; os agentes são: atendente, geral, planilhas", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_agente_padrao_quebrado_avisa_e_abre(self):
        self.escrever_agente("geral", "modlo: x\ndescrição: y\n\nz")
        r = rodar(["oi"], self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Não usei o agente geral", r.stderr)
        self.assertIn('não conheço "modlo"', r.stderr)
        self.assertTrue(self.sistema_pedido().startswith(c.PADRAO["sistema"]))

    def test_a_com_c_e_erro(self):
        r = rodar(["-a", "geral", "-c", "oi"], self.home)
        self.assertEqual(r.returncode, 1)
        self.assertIn("Use -a para começar com um agente ou -c para continuar a última conversa, não os dois.",
                      r.stderr)

    def test_continuar_volta_com_o_agente(self):
        self.escrever_agente("pensador", "raciocínio: ligado\n\nPense.")
        self.assertEqual(rodar(["-a", "pensador", "oi"], self.home).returncode, 0)
        r = rodar(["-c", "e agora?"], self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.sistema_pedido().startswith("Pense."))
        self.assertTrue(self.fake.pedidos[-1]["think"])

    def agente_salvo(self):
        conversas = sorted((Path(self.home) / ".chrono" / "conversas").glob("*.json"))
        return json.loads(conversas[-1].read_text(encoding="utf-8"))["agente"]

    def test_continuar_com_agente_quebrado_avisa_e_guarda_o_nome(self):
        self.assertEqual(rodar(["-a", "atendente", "oi"], self.home).returncode, 0)
        (self.agentes / "atendente.txt").write_text("ferramentas: so leitra\n\nx", encoding="utf-8")
        r = rodar(["-c", "e agora?"], self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Não usei o agente atendente", r.stderr)
        self.assertEqual(self.agente_salvo(), "atendente")

    def test_continuar_sem_o_arquivo_guarda_o_nome(self):
        self.assertEqual(rodar(["-a", "atendente", "oi"], self.home).returncode, 0)
        (self.agentes / "atendente.txt").unlink()
        r = rodar(["-c", "e agora?"], self.home)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertEqual(self.agente_salvo(), "atendente")

    def test_listar_agentes(self):
        r = rodar(["--agentes"], self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"● geral\s+assistente para qualquer assunto")
        self.assertRegex(r.stdout, r"  atendente\s+rascunha respostas para clientes do Mercado Livre")
        self.assertIn("planilhas", r.stdout)

    def test_chat_mostra_agente_no_cabecalho(self):
        t = TerminalFalso(["-a", "atendente"], self.home)
        t.esperar("você ›")
        self.assertEqual(t.encerrar(), 0)
        tela = t.texto()
        self.assertIn("atendente · rascunha respostas para clientes do Mercado Livre", tela)
        self.assertIn("ferramentas só leitura", tela)


if __name__ == "__main__":
    unittest.main()
