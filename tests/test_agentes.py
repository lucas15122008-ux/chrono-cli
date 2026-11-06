import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import limpeza  # noqa: E402,F401  (pasta temporária apagada no fim da rodada)
import agentes as a  # noqa: E402

CONHECIDAS = "as configurações são: descrição, modelo, raciocínio, ferramentas"


class TestLer(unittest.TestCase):
    def test_le_configuracoes_e_instrucoes(self):
        texto = "descrição: x\nmodelo: m:1\nraciocínio: ligado\nferramentas: só leitura\n\nFaça y.\nE z."
        self.assertEqual(a.ler(texto, "a"),
                         a.Agente(nome="a", descricao="x", modelo="m:1", pensar=True, ferramentas="leitura",
                                  instrucoes="Faça y.\nE z."))

    def test_sem_acento_e_maiusculas(self):
        agente = a.ler("Raciocinio: Desligado\nFERRAMENTAS: so leitura\n\nx", "a")
        self.assertEqual((agente.pensar, agente.ferramentas), (False, "leitura"))

    def test_sim_e_nao(self):
        agente = a.ler("raciocínio: sim\nferramentas: não\n\nx", "a")
        self.assertEqual((agente.pensar, agente.ferramentas), (True, "desligadas"))

    def test_sem_configuracoes(self):
        texto = "Atenção: responda curto.\nSempre."
        self.assertEqual(a.ler(texto, "a"), a.Agente(nome="a", instrucoes=texto))

    def test_comentarios_ignorados(self):
        agente = a.ler(a.MODELO_NOVO.replace("NOME", "vendas"), "vendas")
        self.assertEqual((agente.descricao, agente.pensar, agente.ferramentas, agente.modelo),
                         ("para que serve este agente, numa frase", False, "ligadas", None))
        self.assertNotIn("#", agente.instrucoes)
        self.assertTrue(agente.instrucoes.startswith("Escreva aqui as instruções"))

    def test_configuracao_desconhecida(self):
        with self.assertRaises(a.ErroAgente) as erro:
            a.ler("descrição: x\nmodlo: m\n\ny", "a")
        self.assertEqual(str(erro.exception),
                         f'linha 2 do agente a: não conheço "modlo"; {CONHECIDAS} (quis dizer modelo?)')

    def test_configuracao_sozinha_com_erro(self):
        # Sem nenhuma configuração certa no bloco, "modlo" ia parar nas instruções sem aviso.
        with self.assertRaises(a.ErroAgente) as erro:
            a.ler("modlo: qwen3:8b\n\nVocê responde.", "a")
        self.assertEqual(str(erro.exception),
                         f'linha 1 do agente a: não conheço "modlo"; {CONHECIDAS} (quis dizer modelo?)')

    def test_apelidos(self):
        agente = a.ler("pensar: ligado\nferramenta: só leitura\n\nx", "a")
        self.assertEqual((agente.pensar, agente.ferramentas), (True, "leitura"))

    def test_configuracao_depois_da_linha_em_branco(self):
        with self.assertRaises(a.ErroAgente) as erro:
            a.ler("descrição: x\n\nferramentas: só leitura\n\nInstruções.", "a")
        self.assertEqual(str(erro.exception), "linha 3 do agente a: as configurações ficam juntas no começo, "
                                              "sem linha em branco entre elas")

    def test_instrucao_parecida_com_configuracao(self):
        agente = a.ler("descrição: x\n\nModelo: responda sempre assim.\nE mais.", "a")
        self.assertEqual((agente.modelo, agente.instrucoes), (None, "Modelo: responda sempre assim.\nE mais."))

    def test_linha_que_nao_e_configuracao(self):
        with self.assertRaises(a.ErroAgente) as erro:
            a.ler("ferramentas: ligadas\nSeja curto.\n\ny", "a")
        self.assertEqual(str(erro.exception),
                         'linha 2 do agente a: "Seja curto." não é uma configuração; separe as instruções '
                         'das configurações com uma linha em branco')

    def test_valor_invalido(self):
        with self.assertRaises(a.ErroAgente) as erro:
            a.ler("ferramentas: talvez\n\ny", "a")
        self.assertEqual(str(erro.exception),
                         "linha 1 do agente a: ferramentas: talvez — use ligadas, desligadas ou só leitura")
        with self.assertRaises(a.ErroAgente) as erro:
            a.ler("descrição: x\nraciocínio:\n\ny", "a")
        self.assertEqual(str(erro.exception), "linha 2 do agente a: raciocínio: — use ligado ou desligado")

    def test_sem_instrucoes(self):
        with self.assertRaises(a.ErroAgente) as erro:
            a.ler("descrição: x\n", "a")
        self.assertEqual(str(erro.exception),
                         "o agente a não tem instruções: escreva o que ele deve fazer depois das "
                         "configurações, separado por uma linha em branco")

    def test_arquivo_rtf_avisa(self):
        with self.assertRaises(a.ErroAgente) as erro:
            a.ler("{\\rtf1\\ansi\\ansicpg1252 Você ajuda...}", "a")
        self.assertEqual(str(erro.exception),
                         "o agente a foi salvo como texto formatado; no TextEdit, use Formatar › "
                         "Converter em Texto Simples e salve de novo")


class TestPasta(unittest.TestCase):
    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp()) / "agentes"
        self.pasta.mkdir()

    def escrever(self, nome, texto):
        (self.pasta / f"{nome}.txt").write_text(texto, encoding="utf-8")

    def test_bom_e_crlf(self):
        (self.pasta / "a.txt").write_bytes("﻿descrição: x\r\n\r\nFaça y.\r\n".encode("utf-8"))
        agente = a.carregar(self.pasta, "a")
        self.assertEqual((agente.descricao, agente.instrucoes, agente.arquivo),
                         ("x", "Faça y.", self.pasta / "a.txt"))

    def test_carregar_ignora_maiusculas(self):
        self.escrever("Atendente", "Responda.")
        self.assertEqual(a.carregar(self.pasta, "ATENDENTE").nome, "Atendente")

    def test_carregar_inexistente(self):
        self.escrever("b", "x")
        self.escrever("a", "x")
        with self.assertRaises(a.ErroAgente) as erro:
            a.carregar(self.pasta, "c")
        self.assertEqual(str(erro.exception), "não existe o agente c; os agentes são: a, b")

    def test_carregar_sem_agentes(self):
        with self.assertRaises(a.ErroAgente) as erro:
            a.carregar(self.pasta, "c")
        self.assertEqual(str(erro.exception), "ainda não há agentes em ~/.chrono/agentes")

    def test_listar_mostra_erro_sem_quebrar(self):
        self.escrever("a", "descrição: desc a\n\nx")
        self.escrever("b", "modlo: x\ndescrição: y\n\nz")
        self.assertEqual(a.listar(self.pasta),
                         [("a", "desc a"),
                          ("b", f'⚠ linha 1 do agente b: não conheço "modlo"; {CONHECIDAS} (quis dizer modelo?)')])

    def test_existe(self):
        self.escrever("Geral", "x")
        self.assertTrue(a.existe(self.pasta, "geral"))
        self.assertFalse(a.existe(self.pasta, "vendas"))
        self.assertFalse(a.existe(self.pasta / "nada", "geral"))

    def test_listar_pasta_que_nao_existe(self):
        self.assertEqual(a.listar(self.pasta / "nada"), [])

    def test_criar_prontos(self):
        pasta = self.pasta / "nova"
        self.assertTrue(a.criar_prontos(pasta, "Sistema X."))
        self.assertEqual([nome for nome, _ in a.listar(pasta)], ["atendente", "geral", "planilhas"])
        geral = a.carregar(pasta, "geral")
        self.assertEqual((geral.instrucoes, geral.descricao), ("Sistema X.", "assistente para qualquer assunto"))
        self.assertEqual(a.carregar(pasta, "atendente").ferramentas, "leitura")
        self.assertTrue(a.carregar(pasta, "atendente").instrucoes.startswith("Você ajuda a JR Auto Peças"))
        self.assertEqual(a.carregar(pasta, "planilhas").ferramentas, "ligadas")

    def test_criar_prontos_nao_sobrescreve(self):
        self.escrever("geral", "Meu jeito.")
        self.assertFalse(a.criar_prontos(self.pasta, "Sistema X."))
        self.assertEqual((self.pasta / "geral.txt").read_text(encoding="utf-8"), "Meu jeito.")
        self.assertEqual([p.name for p in self.pasta.iterdir()], ["geral.txt"])

    def test_criar_novo(self):
        caminho = a.criar_novo(self.pasta, "vendas")
        self.assertEqual(caminho, self.pasta / "vendas.txt")
        self.assertEqual(caminho.read_text(encoding="utf-8"), a.MODELO_NOVO.replace("NOME", "vendas"))

    def test_criar_novo_erro_do_sistema(self):
        arquivo = self.pasta / "nao-e-pasta"
        arquivo.write_text("x", encoding="utf-8")
        for pasta, nome in ((arquivo, "vendas"), (self.pasta, "a" * 300)):
            with self.subTest(nome=nome[:10]):
                with self.assertRaises(a.ErroAgente) as erro:
                    a.criar_novo(pasta, nome)
                self.assertTrue(str(erro.exception).startswith(f"não consegui criar o agente {nome}:"))

    def test_criar_novo_recusa(self):
        self.escrever("atendente", "x")
        casos = {"atendente": "já existe o agente atendente; para mudar, use /agente editar atendente",
                 "Atendente": "já existe o agente Atendente; para mudar, use /agente editar Atendente",
                 "novo": '"novo" é um comando; escolha outro nome',
                 "editar": '"editar" é um comando; escolha outro nome',
                 "meu agente": "o nome do agente só pode ter letras, números, - e _ (sem espaços)"}
        for nome, mensagem in casos.items():
            with self.subTest(nome=nome):
                with self.assertRaises(a.ErroAgente) as erro:
                    a.criar_novo(self.pasta, nome)
                self.assertEqual(str(erro.exception), mensagem)
        self.assertEqual([p.name for p in self.pasta.iterdir()], ["atendente.txt"])


if __name__ == "__main__":
    unittest.main()
