import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import limpeza  # noqa: E402,F401  (pasta temporária apagada no fim da rodada)
import documentos as d  # noqa: E402
import fabrica  # noqa: E402

# O leitor de PDF escaneado é compilado uma vez só para todos os testes.
PROGRAMA_OCR = Path(tempfile.mkdtemp(prefix="chrono-ocr-")) / "chrono-ocr"
tem_swift = shutil.which("swiftc") is not None


class Base(unittest.TestCase):
    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp(prefix="chrono-doc-")).resolve()
        remendo = mock.patch.object(d, "PROGRAMA_OCR", PROGRAMA_OCR)
        remendo.start()
        self.addCleanup(remendo.stop)


class TestTipo(unittest.TestCase):
    def test_tipos(self):
        self.assertEqual([d.tipo(Path(n)) for n in ("a.pdf", "a.PDF", "a.docx", "a.rtf", "a.xlsx", "a.xls", "a.txt")],
                         ["pdf", "pdf", "word", "word", "planilha", "planilha", None])


class TestPdf(Base):
    def test_pdf_com_texto(self):
        fabrica.pdf_com_texto(self.pasta / "p.pdf", ["Pedido 4512\nEntrega amanhã", "Disco Fremax"])
        self.assertEqual(d.ler_pdf(self.pasta / "p.pdf"),
                         "=== página 1 ===\nPedido 4512\nEntrega amanhã\n\n=== página 2 ===\nDisco Fremax")

    def test_pdf_a_partir_de(self):
        fabrica.pdf_com_texto(self.pasta / "p.pdf", ["um", "dois", "três"])
        self.assertEqual(d.ler_pdf(self.pasta / "p.pdf", a_partir_de=3), "=== página 3 ===\ntrês")

    def test_pdf_pagina_que_nao_existe(self):
        fabrica.pdf_com_texto(self.pasta / "p.pdf", ["um"])
        with self.assertRaisesRegex(d.ErroDocumento, "o PDF tem só 1 página"):
            d.ler_pdf(self.pasta / "p.pdf", a_partir_de=5)

    def test_pdf_grande_corta_e_diz_como_continuar(self):
        fabrica.pdf_com_texto(self.pasta / "p.pdf", [f"página número {i}\n" + "x" * 900 for i in range(1, 31)])
        texto = d.ler_pdf(self.pasta / "p.pdf", limite=5000)
        self.assertIn("=== página 1 ===", texto)
        self.assertNotIn("=== página 30 ===", texto)
        ultima = max(int(n) for n in __import__("re").findall(r"=== página (\d+) ===", texto))
        self.assertTrue(texto.endswith(f"(mostrei as páginas 1 a {ultima} de 30; para continuar, "
                                       f"use a_partir_de={ultima + 1})"))

    def test_pdf_quebrado(self):
        (self.pasta / "q.pdf").write_bytes(b"isto nao e um pdf")
        with self.assertRaisesRegex(d.ErroDocumento, "não consegui abrir este PDF"):
            d.ler_pdf(self.pasta / "q.pdf")

    @unittest.skipUnless(tem_swift, "sem o compilador Swift")
    def test_pdf_escaneado_le_da_imagem(self):
        fabrica.pdf_escaneado(self.pasta / "e.pdf", "Pedido 4512\nPastilha de freio Cobreq\nEntrega amanhã")
        texto = d.ler_pdf(self.pasta / "e.pdf")
        self.assertTrue(texto.startswith("=== página 1 (lida da imagem) ===\n"))
        for trecho in ("Pedido 4512", "Pastilha de freio Cobreq", "amanhã"):
            self.assertIn(trecho, texto)

    def test_sem_ocr_disponivel_avisa(self):
        fabrica.pdf_escaneado(self.pasta / "e.pdf", "Pedido 4512")
        with mock.patch.object(d, "_programa_ocr", side_effect=d.ErroDocumento("sem leitor")):
            self.assertEqual(d.ler_pdf(self.pasta / "e.pdf"),
                             "=== página 1 ===\n(página sem texto; não consegui ler a imagem: sem leitor)")


class TestWord(Base):
    def test_docx(self):
        fabrica.word(self.pasta / "n.docx", "Orçamento\nAmortecedor Cofap")
        self.assertEqual(d.ler_word(self.pasta / "n.docx"), "Orçamento\nAmortecedor Cofap")

    def test_rtf(self):
        fabrica.word(self.pasta / "n.rtf", "Nota em RTF")
        self.assertEqual(d.ler_word(self.pasta / "n.rtf"), "Nota em RTF")


class TestPlanilha(Base):
    def setUp(self):
        super().setUp()
        self.arquivo = self.pasta / "precos.xlsx"
        fabrica.planilha(self.arquivo, {"Preços": fabrica.TABELA, "Estoque": [["Código", "Qtd"], [101, 7]]})

    def test_le_todas_as_abas(self):
        self.assertEqual(d.ler_planilha(self.arquivo),
                         "abas: Preços, Estoque\n\n"
                         "=== aba Preços (4 linhas) ===\n"
                         "1: Código | Descrição | Preço | Atualizado\n"
                         "2: 101 | Pastilha de freio Cobreq Gol G5 | 89,9 | 30/10/2026\n"
                         "3: 102 | Disco de freio Fremax Gol G5 | 159 | 31/10/2026 14:30\n"
                         "4: 103 | Amortecedor Cofap dianteiro | 249,5\n\n"
                         "=== aba Estoque (2 linhas) ===\n"
                         "1: Código | Qtd\n"
                         "2: 101 | 7")

    def test_uma_aba_a_partir_de_uma_linha_mostra_o_cabecalho(self):
        self.assertEqual(d.ler_planilha(self.arquivo, aba="Preços", a_partir_de=4),
                         "=== aba Preços (4 linhas) ===\n"
                         "1: Código | Descrição | Preço | Atualizado\n"
                         "4: 103 | Amortecedor Cofap dianteiro | 249,5")

    def test_aba_que_nao_existe(self):
        with self.assertRaisesRegex(d.ErroDocumento, "não existe a aba Vendas; as abas são: Preços, Estoque"):
            d.ler_planilha(self.arquivo, aba="Vendas")

    def test_planilha_grande_mostra_um_resumo(self):
        # Entregar centenas de linhas de uma vez deixava o modelo minutos "lendo".
        linhas = [["Código", "Descrição"]] + [[i, f"Peça número {i}"] for i in range(1, 3001)]
        fabrica.planilha(self.pasta / "grande.xlsx", {"Tabela": linhas})
        texto = d.ler_planilha(self.pasta / "grande.xlsx")
        self.assertEqual(texto.splitlines()[:4], ["abas: Tabela", "", "=== aba Tabela (3001 linhas) ===",
                                                  "1: Código | Descrição"])
        self.assertIn("20: 19 | Peça número 19", texto)
        self.assertNotIn("21: 20 |", texto)
        self.assertTrue(texto.endswith('(mostrei as linhas 1 a 20 de 3001 da aba Tabela; para continuar, use '
                                       'aba="Tabela" e a_partir_de=21; para achar um item, use buscar_no_arquivo)'))

    def test_planilha_continua_de_200_em_200(self):
        linhas = [["Código", "Descrição"]] + [[i, f"Peça número {i}"] for i in range(1, 3001)]
        fabrica.planilha(self.pasta / "grande.xlsx", {"Tabela": linhas})
        texto = d.ler_planilha(self.pasta / "grande.xlsx", aba="Tabela", a_partir_de=21)
        linhas_mostradas = [l for l in texto.splitlines() if l[:1].isdigit()]
        self.assertEqual((linhas_mostradas[0], linhas_mostradas[1], linhas_mostradas[-1]),
                         ("1: Código | Descrição", "21: 20 | Peça número 20", "220: 219 | Peça número 219"))
        self.assertTrue(texto.endswith('(mostrei as linhas 21 a 220 de 3001 da aba Tabela; para continuar, use '
                                       'aba="Tabela" e a_partir_de=221; para achar um item, use buscar_no_arquivo)'))

    def test_planilha_continua_respeitando_o_limite_de_caracteres(self):
        linhas = [["Código", "Descrição"]] + [[i, "x" * 100] for i in range(1, 3001)]
        fabrica.planilha(self.pasta / "larga.xlsx", {"Tabela": linhas})
        texto = d.ler_planilha(self.pasta / "larga.xlsx", a_partir_de=2, limite=5000)
        self.assertLess(len(texto), 5300)
        self.assertIn("para continuar, use", texto)

    def test_linha_alem_do_fim(self):
        with self.assertRaisesRegex(d.ErroDocumento, "a aba Preços tem só 4 linhas"):
            d.ler_planilha(self.arquivo, aba="Preços", a_partir_de=9)

    def test_muitas_abas_mostram_previa_das_10_primeiras(self):
        fabrica.planilha(self.pasta / "abas.xlsx", {f"Mês {i}": [["Item"], [i]] for i in range(1, 13)})
        texto = d.ler_planilha(self.pasta / "abas.xlsx")
        self.assertIn("=== aba Mês 10 (2 linhas) ===", texto)
        self.assertNotIn("=== aba Mês 11", texto)
        self.assertTrue(texto.endswith("(abas sem prévia: Mês 11, Mês 12; para ver uma delas, use aba=\"nome\")"))

    def test_xls_antigo(self):
        celula = lambda valor, tipo=1: mock.Mock(value=valor, ctype=tipo)  # noqa: E731
        aba = mock.Mock(nrows=2, ncols=2)
        aba.row.side_effect = [[celula("Código"), celula("Preço")], [celula(101.0, 2), celula(89.9, 2)]]
        livro = mock.Mock(datemode=0)
        livro.sheet_names.return_value = ["Plan1"]
        livro.sheet_by_name.return_value = aba
        with mock.patch("xlrd.open_workbook", return_value=livro):
            self.assertEqual(d.ler_planilha(self.pasta / "antigo.xls"),
                             "abas: Plan1\n\n=== aba Plan1 (2 linhas) ===\n1: Código | Preço\n2: 101 | 89,9")

    def test_falta_biblioteca(self):
        with mock.patch.dict(sys.modules, {"openpyxl": None}):
            with self.assertRaisesRegex(d.FaltaBiblioteca, r"pip3 install --user openpyxl"):
                d.ler_planilha(self.arquivo)


class TestBuscar(Base):
    def test_busca_na_planilha_com_cabecalho(self):
        linhas = [["Código", "Descrição", "Preço"]] + [[i, f"Peça {i}", 10] for i in range(1, 2001)]
        linhas[1234] = [1234, "Pastilha Cobreq Gol G5", 89.9]
        fabrica.planilha(self.pasta / "t.xlsx", {"Preços": linhas})
        self.assertEqual(d.buscar(self.pasta / "t.xlsx", "cobreq"),
                         ["aba Preços — cabeçalho: Código | Descrição | Preço",
                          "linha 1235: 1234 | Pastilha Cobreq Gol G5 | 89,9"])

    def test_busca_sem_acento(self):
        fabrica.word(self.pasta / "n.docx", "nada\nOrçamento do João\nfim")
        self.assertEqual(d.buscar(self.pasta / "n.docx", "orcamento joao"), [])
        self.assertEqual(d.buscar(self.pasta / "n.docx", "orcamento do joao"), ["linha 2: Orçamento do João"])

    def test_busca_no_pdf_diz_a_pagina(self):
        fabrica.pdf_com_texto(self.pasta / "p.pdf", ["Pedido 4512", "Disco Fremax\nPastilha Cobreq"])
        self.assertEqual(d.buscar(self.pasta / "p.pdf", "fremax"), ["página 2: Disco Fremax"])


if __name__ == "__main__":
    unittest.main()
