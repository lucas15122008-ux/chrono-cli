import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import limpeza  # noqa: E402,F401  (pasta temporária apagada no fim da rodada)
import fabrica  # noqa: E402
import planilhas as p  # noqa: E402

ESTOQUE = [["Código", "Descrição", "Marca", "Preço", "Estoque"],
           [101, "Pastilha Cobreq Gol G5", "Cobreq", 89.9, 10],
           [102, "Disco Fremax Gol G5", "Fremax", 159.0, 4],
           [103, "Amortecedor Cofap", "Cofap", 249.5, 2],
           [104, "Pastilha Cobreq Palio", "Cobreq", 79.9, 0],
           [105, "Vela NGK", "NGK", "R$ 25,00", 30],
           [106, "Peça sem preço", "NGK", None, 1]]


class Base(unittest.TestCase):
    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp(prefix="chrono-plan-")).resolve()
        self.arquivo = self.pasta / "estoque.xlsx"
        fabrica.planilha(self.arquivo, {"Peças": ESTOQUE})


class TestNumeros(unittest.TestCase):
    def test_numero(self):
        self.assertEqual([p.numero(t) for t in ("R$ 1.234,56", "89,9", "1.234", "1.5", "-3", "abc", "")],
                         [1234.56, 89.9, 1234.0, 1.5, -3.0, None, None])

    def test_formato(self):
        self.assertEqual([p.formatar(v) for v in (603.3, 47.0, 1234567.891, -2.5)],
                         ["603,30", "47", "1.234.567,89", "-2,50"])


class TestCalcular(Base):
    def calc(self, operacao, coluna=None, **opcoes):
        return p.calcular(self.arquivo, operacao, coluna, **opcoes)

    def test_soma(self):
        self.assertEqual(self.calc("soma", "Preço"), "soma de Preço: 603,30 (5 linhas com número; 1 sem número)")

    def test_soma_com_filtro(self):
        self.assertEqual(self.calc("soma", "Preço", filtro="Marca = Cobreq"),
                         "soma de Preço onde Marca = Cobreq: 169,80 (2 linhas)")

    def test_dois_filtros(self):
        self.assertEqual(self.calc("soma", "preco", filtro="marca = cobreq e Preço > 80"),
                         "soma de Preço onde marca = cobreq e Preço > 80: 89,90 (1 linha)")

    def test_media(self):
        self.assertEqual(self.calc("média", "Preço"), "média de Preço: 120,66 (5 linhas com número; 1 sem número)")

    def test_contagem(self):
        self.assertEqual(self.calc("contagem"), "contagem: 6 linhas")
        self.assertEqual(self.calc("contagem", filtro="Estoque = 0"), "contagem onde Estoque = 0: 1 linha")

    def test_maior_mostra_a_linha(self):
        self.assertEqual(self.calc("maior", "Preço"),
                         "maior Preço: 249,50 — linha 4: 103 | Amortecedor Cofap | Cofap | 249,5 | 2")

    def test_menor_com_contem(self):
        self.assertEqual(self.calc("menor", "D", filtro="Descrição contém pastilha"),
                         "menor Preço onde Descrição contém pastilha: 79,90 — linha 5: 104 | Pastilha Cobreq Palio | "
                         "Cobreq | 79,9 | 0")

    def test_agrupar(self):
        self.assertEqual(self.calc("soma", "Estoque", agrupar_por="Marca"),
                         "soma de Estoque por Marca (4 grupos):\nNGK: 31 (2 linhas)\nCobreq: 10 (2 linhas)\n"
                         "Fremax: 4 (1 linha)\nCofap: 2 (1 linha)")

    def test_contagem_agrupada(self):
        self.assertEqual(self.calc("contagem", agrupar_por="Marca"),
                         "contagem por Marca (4 grupos):\nCobreq: 2\nNGK: 2\nFremax: 1\nCofap: 1")

    def test_coluna_que_nao_existe(self):
        with self.assertRaisesRegex(p.ErroPlanilha, "não existe a coluna Custo; as colunas são: Código, Descrição, "
                                                    "Marca, Preço, Estoque"):
            self.calc("soma", "Custo")

    def test_filtro_que_nao_entendi(self):
        with self.assertRaisesRegex(p.ErroPlanilha, 'não entendi o filtro "Marca Bosch"'):
            self.calc("contagem", filtro="Marca Bosch")

    def test_operacao_que_nao_existe(self):
        with self.assertRaisesRegex(p.ErroPlanilha, "operação desconhecida: mediana; use soma, média, contagem, "
                                                    "maior ou menor"):
            self.calc("mediana", "Preço")

    def test_sem_coluna_para_somar(self):
        with self.assertRaisesRegex(p.ErroPlanilha, "diga a coluna"):
            self.calc("soma")

    def test_nada_bate_no_filtro(self):
        self.assertEqual(self.calc("soma", "Preço", filtro="Marca = Bosch"),
                         "soma de Preço onde Marca = Bosch: nenhuma linha bate com o filtro")


def abrir(caminho):
    import openpyxl
    return openpyxl.load_workbook(caminho).active


class TestCriar(Base):
    def test_tabela_escrita_pelo_modelo(self):
        self.assertEqual(p.tabela("Código | Descrição | Preço | Data\n101 | Pastilha | 89,90 | 30/10/2026\n\n"
                                  "0123 | Disco | 159"),
                         [["Código", "Descrição", "Preço", "Data"], [101, "Pastilha", 89.9, datetime(2026, 10, 30)],
                          ["0123", "Disco", 159]])

    def test_tabela_com_ponto_e_virgula(self):
        self.assertEqual(p.tabela("a;b\n1;2"), [["a", "b"], [1, 2]])

    def test_tabela_markdown(self):
        self.assertEqual(p.tabela("| Peça | Preço |\n|---|---:|\n| Vela | 25 |"), [["Peça", "Preço"], ["Vela", 25]])

    def test_tabela_vazia(self):
        with self.assertRaisesRegex(p.ErroPlanilha, "a tabela está vazia"):
            p.tabela("  \n ")

    def test_criar(self):
        destino = self.pasta / "nova.xlsx"
        p.criar(destino, [["Peça", "Preço"], ["Vela", 25]], aba="Preços")
        aba = abrir(destino)
        self.assertEqual((aba.title, aba["A1"].value, aba["B2"].value, aba["A1"].font.bold, aba.freeze_panes),
                         ("Preços", "Peça", 25, True, "A2"))

    def test_previa(self):
        self.assertEqual(p.previa([["Peça", "Preço"], ["Vela", 25.5]]), "1: Peça | Preço\n2: Vela | 25,5")


class TestEditar(Base):
    def editar(self, alteracoes, **opcoes):
        edicao = p.preparar_edicao(self.arquivo, alteracoes, **opcoes)
        edicao.aplicar()
        return edicao, abrir(self.arquivo)

    def test_muda_uma_celula_mostrando_a_linha(self):
        # No teste real, o modelo mudou a linha errada; com a linha inteira na confirmação, o engano fica à vista.
        edicao, aba = self.editar("D2 = 99,90")
        self.assertEqual(edicao.descricao, ["D2: 89,9 → 99,90 (linha 2: 101 | Pastilha Cobreq Gol G5 | Cobreq | 89,9 | "
                                            "10)"])
        self.assertEqual(aba["D2"].value, 99.9)

    def test_muda_pelo_conteudo(self):
        edicao, aba = self.editar("Preço = 149,90 onde Marca = Fremax")
        self.assertEqual(edicao.descricao, ["Preço na linha 3: 159 → 149,90 (102 | Disco Fremax Gol G5 | Fremax | 159 | "
                                            "4)"])
        self.assertEqual(aba["D3"].value, 149.9)

    def test_muda_pelo_conteudo_varias_linhas(self):
        _, aba = self.editar("Estoque = 99 onde Descrição contém pastilha")
        self.assertEqual((aba["E2"].value, aba["E5"].value, aba["E3"].value), (99, 99, 4))

    def test_muda_pelo_conteudo_sem_linha(self):
        with self.assertRaisesRegex(p.ErroPlanilha, "nenhuma linha bate com o filtro Marca = Bosch"):
            p.preparar_edicao(self.arquivo, "Preço = 1 onde Marca = Bosch")

    def test_coluna_nova_avisa_que_e_valor_fixo(self):
        edicao = p.preparar_edicao(self.arquivo, "Total = [Preço] * [Estoque]")
        self.assertIn("a coluna nova guarda valores fixos, calculados agora (não é fórmula do Excel): se a coluna "
                      "de origem mudar depois, ela não muda", edicao.avisos)

    def test_linha_nova(self):
        edicao, aba = self.editar("+ 107 | Bateria Moura | Moura | 450 | 3")
        self.assertEqual(edicao.descricao, ["linha nova 8: 107 | Bateria Moura | Moura | 450 | 3"])
        self.assertEqual([c.value for c in aba[8]], [107, "Bateria Moura", "Moura", 450, 3])

    def test_coluna_calculada(self):
        edicao, aba = self.editar("coluna Preço +10% = [Preço] * 1,1")
        self.assertEqual(edicao.descricao, ["coluna nova F (Preço +10%): 5 valores calculados; 1 linha sem número ficou "
                                            "vazia"])
        self.assertEqual(aba["F1"].value, "Preço +10%")
        self.assertAlmostEqual(aba["F2"].value, 98.89)
        self.assertIsNone(aba["F7"].value)

    def test_coluna_calculada_sem_a_palavra_coluna(self):
        # No teste real, o modelo sempre escrevia assim, sem o "coluna" na frente, e não conseguia acertar.
        edicao, aba = self.editar("Preço com 5% de desconto = [Preço] * 0,95")
        self.assertEqual(edicao.descricao, ["coluna nova F (Preço com 5% de desconto): 5 valores calculados; 1 linha "
                                            "sem número ficou vazia"])
        self.assertAlmostEqual(aba["F2"].value, 85.405)

    def test_coluna_com_duas_colunas(self):
        _, aba = self.editar("coluna Valor em estoque = [Preço] * [Estoque]")
        self.assertAlmostEqual(aba["F2"].value, 899.0)

    def test_apagar_linha(self):
        edicao, aba = self.editar("apagar linha 3")
        self.assertEqual(edicao.descricao, ["apagar linha 3: 102 | Disco Fremax Gol G5 | Fremax | 159 | 4"])
        self.assertEqual(aba["A3"].value, 103)

    def test_varias_alteracoes_apagar_usa_a_numeracao_de_antes(self):
        _, aba = self.editar("apagar linha 2\nD3 = 200\napagar linha 4")
        self.assertEqual([aba[f"A{n}"].value for n in range(2, 6)], [102, 104, 105, 106])
        self.assertEqual(aba["D2"].value, 200)

    def test_formula_continua_formula(self):
        aba = abrir(self.arquivo)
        aba["G2"] = "=D2*2"
        aba.parent.save(self.arquivo)
        _, aba = self.editar("D3 = 1")
        self.assertEqual(aba["G2"].value, "=D2*2")

    def test_celula_com_formula_nova(self):
        _, aba = self.editar("G2 = =D2*E2")
        self.assertEqual(aba["G2"].value, "=D2*E2")

    def test_conta_numa_celula_e_recusada(self):
        # No teste real, o modelo escreveu "C4 = [Preço] * 0,95" e o texto foi gravado por cima de um preço.
        with self.assertRaisesRegex(p.ErroPlanilha, r"para calcular a partir de outras colunas, crie uma coluna "
                                                    r"nova, assim: coluna Nome da coluna = \[Preço\] \* 0,95"):
            p.preparar_edicao(self.arquivo, "D4 = [Preço] * 0,95")

    def test_alteracao_que_nao_entendi(self):
        with self.assertRaisesRegex(p.ErroPlanilha, 'não entendi a alteração "mude tudo"'):
            p.preparar_edicao(self.arquivo, "mude tudo")

    def test_conta_que_nao_e_conta(self):
        with self.assertRaisesRegex(p.ErroPlanilha, "a conta só pode usar números, colunas entre colchetes"):
            p.preparar_edicao(self.arquivo, "coluna X = __import__('os')")

    def test_conta_com_coluna_que_nao_existe(self):
        with self.assertRaisesRegex(p.ErroPlanilha, "não existe a coluna Custo"):
            p.preparar_edicao(self.arquivo, "coluna X = [Custo] * 2")

    def test_divisao_por_zero_fica_vazia(self):
        _, aba = self.editar("coluna Preço por unidade = [Preço] / [Estoque]")
        self.assertIsNone(aba["F5"].value)  # estoque 0

    def test_apagar_linha_que_nao_existe(self):
        with self.assertRaisesRegex(p.ErroPlanilha, "a aba Peças tem só 7 linhas"):
            p.preparar_edicao(self.arquivo, "apagar linha 12")

    def test_avisa_que_graficos_se_perdem(self):
        from openpyxl.chart import BarChart, Reference
        aba = abrir(self.arquivo)
        grafico = BarChart()
        grafico.add_data(Reference(aba, min_col=4, min_row=1, max_row=7))
        aba.add_chart(grafico, "H2")
        aba.parent.save(self.arquivo)
        self.assertTrue(any("gráficos" in aviso for aviso in p.preparar_edicao(self.arquivo, "D2 = 1").avisos))

    def test_nao_edita_xls(self):
        (self.pasta / "antiga.xls").write_bytes(b"x")
        with self.assertRaisesRegex(p.ErroPlanilha, "não edito planilhas .xls"):
            p.preparar_edicao(self.pasta / "antiga.xls", "A1 = 1")


class TestOperacoes(Base):
    """As operações separadas que as ferramentas usam (no teste real, a minilinguagem confundia o modelo)."""

    def preparar(self):
        return p.Edicao(self.arquivo)

    def test_mudar_onde(self):
        edicao = self.preparar()
        edicao.mudar_onde("Preço", "149,90", "Marca = Fremax")
        edicao.aplicar()
        self.assertEqual(edicao.descricao, ["Preço na linha 3: 159 → 149,90 (102 | Disco Fremax Gol G5 | Fremax | 159 | 4)"])
        self.assertEqual(abrir(self.arquivo)["D3"].value, 149.9)

    def test_valor_com_colchetes_e_recusado(self):
        with self.assertRaisesRegex(p.ErroPlanilha, "para calcular a partir de outras colunas, use adicionar_coluna"):
            self.preparar().mudar_onde("Preço", "[Preço] * 0,95", "Marca = Fremax")

    def test_valor_que_parece_conta_e_recusado(self):
        with self.assertRaisesRegex(p.ErroPlanilha, r"o valor parece uma conta; escreva o resultado \(como 142,41\)"):
            self.preparar().mudar_onde("Preço", "149,90 * 0,95", "Marca = Fremax")

    def test_nova_coluna(self):
        edicao = self.preparar()
        edicao.nova_coluna("Preço com desconto", "[Preço] * 0,95")
        edicao.aplicar()
        self.assertAlmostEqual(abrir(self.arquivo)["F2"].value, 85.405)

    def test_coluna_que_ja_existe(self):
        with self.assertRaisesRegex(p.ErroPlanilha, "já existe a coluna Preço"):
            self.preparar().nova_coluna("preço", "[Preço] * 2")

    def test_nova_linha(self):
        edicao = self.preparar()
        edicao.nova_linha(["107", "Bateria Moura", "Moura", "450", "3"])
        edicao.aplicar()
        self.assertEqual([c.value for c in abrir(self.arquivo)[8]], [107, "Bateria Moura", "Moura", 450, 3])

    def test_nova_linha_com_conta_e_recusada(self):
        with self.assertRaisesRegex(p.ErroPlanilha, "parece uma conta; para uma coluna calculada, use adicionar_coluna"):
            self.preparar().nova_linha(["Preço5% = [Preço] * 0,95"])

    def test_nova_linha_com_colunas_demais(self):
        with self.assertRaisesRegex(p.ErroPlanilha, "a planilha tem 5 colunas \\(Código, Descrição, Marca, Preço, "
                                                    "Estoque\\), mas a linha tem 7 valores"):
            self.preparar().nova_linha(["1", "2", "3", "4", "5", "6", "7"])

    def test_apagar_onde(self):
        edicao = self.preparar()
        edicao.apagar_onde("Marca = NGK")
        edicao.aplicar()
        self.assertEqual(edicao.descricao, ["apagar linha 6: 105 | Vela NGK | NGK | R$ 25,00 | 30",
                                            "apagar linha 7: 106 | Peça sem preço | NGK |  | 1"])
        self.assertEqual(abrir(self.arquivo).max_row, 5)

    def test_apagar_onde_sem_linha(self):
        with self.assertRaisesRegex(p.ErroPlanilha, "nenhuma linha bate com o filtro Marca = Bosch"):
            self.preparar().apagar_onde("Marca = Bosch")


if __name__ == "__main__":
    unittest.main()
