import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import limpeza  # noqa: E402,F401  (pasta temporária apagada no fim da rodada)
import ferramentas  # noqa: E402
import skills as s  # noqa: E402


class Respostas:
    """confirmar() de teste: anota cada pergunta e responde com a lista dada."""

    def __init__(self, *respostas):
        self.respostas = list(respostas)
        self.perguntas = []

    def __call__(self, pergunta, detalhe=None, sempre_perguntar=False):
        self.perguntas.append((pergunta, detalhe, sempre_perguntar))
        return self.respostas.pop(0) if self.respostas else False


class TestLer(unittest.TestCase):
    def test_le_cabecalho_e_instrucoes(self):
        self.assertEqual(s.ler("---\nname: x\ndescription: faz y\n---\n\n1. passo", "x"),
                         s.Skill(nome="x", descricao="faz y", instrucoes="1. passo"))

    def test_sem_cabecalho(self):
        self.assertEqual(s.ler("1. passo\n2. outro", "x"), s.Skill(nome="x", instrucoes="1. passo\n2. outro"))

    def test_cabecalho_do_claude(self):
        texto = ('---\nname: x\ndescription: "Faz y. Use quando z."\nversion: 4.7.0\n'
                 'argument-hint: "[a]"\n---\n\n# X\nFaça.')
        skill = s.ler(texto, "x")
        self.assertEqual((skill.descricao, skill.instrucoes), ("Faz y. Use quando z.", "# X\nFaça."))

    def test_nome_da_pasta_vale(self):
        self.assertEqual(s.ler("---\nname: outro\n---\nFaça.", "x").nome, "x")

    def test_cabecalho_sem_fim(self):
        with self.assertRaises(s.ErroSkill) as erro:
            s.ler("---\nname: x\n1. passo", "x")
        self.assertEqual(str(erro.exception), "o cabeçalho da skill x começa com --- mas não termina com ---")

    def test_sem_instrucoes(self):
        with self.assertRaises(s.ErroSkill) as erro:
            s.ler("---\nname: x\ndescription: y\n---\n\n", "x")
        self.assertEqual(str(erro.exception),
                         "a skill x não tem instruções: escreva o passo a passo depois do cabeçalho")

    def test_grande_demais(self):
        with self.assertRaises(s.ErroSkill) as erro:
            s.ler("a" * 20001, "x")
        self.assertEqual(str(erro.exception), "a skill x é grande demais (20001 caracteres); o limite é 20000")

    def test_bom_e_crlf(self):
        skill = s.ler("﻿---\r\nname: x\r\ndescription: y\r\n---\r\n\r\nFaça.\r\n", "x")
        self.assertEqual((skill.descricao, skill.instrucoes), ("y", "Faça."))


class TestPasta(unittest.TestCase):
    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp()) / "skills"
        self.pasta.mkdir()

    def escrever(self, nome, texto, *apoio):
        pasta = self.pasta / nome
        pasta.mkdir()
        (pasta / "SKILL.md").write_text(texto, encoding="utf-8")
        for arquivo in apoio:
            (pasta / arquivo).write_text("x", encoding="utf-8")

    def test_carregar_ignora_maiusculas(self):
        self.escrever("conferir-pedidos", "---\ndescription: confere\n---\nFaça.", "modelo.xlsx", ".oculto")
        skill = s.carregar(self.pasta, "Conferir-Pedidos")
        self.assertEqual((skill.nome, skill.pasta, skill.apoio),
                         ("conferir-pedidos", self.pasta / "conferir-pedidos", ["modelo.xlsx"]))

    def test_carregar_inexistente(self):
        self.escrever("b", "x")
        self.escrever("a", "x")
        with self.assertRaises(s.ErroSkill) as erro:
            s.carregar(self.pasta, "c")
        self.assertEqual(str(erro.exception), "não existe a skill c; as skills são: a, b")

    def test_carregar_sem_skills(self):
        with self.assertRaises(s.ErroSkill) as erro:
            s.carregar(self.pasta, "c")
        self.assertEqual(str(erro.exception), "ainda não há skills em ~/.chrono/skills")

    def test_pasta_sem_skill_md(self):
        (self.pasta / "vazia").mkdir()
        with self.assertRaises(s.ErroSkill) as erro:
            s.carregar(self.pasta, "vazia")
        self.assertEqual(str(erro.exception), "a skill vazia não tem o arquivo SKILL.md")
        self.assertEqual(s.caminho(self.pasta, "vazia"), self.pasta / "vazia" / "SKILL.md")

    def test_nao_utf8(self):
        (self.pasta / "x").mkdir()
        (self.pasta / "x" / "SKILL.md").write_bytes("Faça".encode("utf-16"))
        with self.assertRaises(s.ErroSkill) as erro:
            s.carregar(self.pasta, "x")
        self.assertTrue(str(erro.exception).startswith("a skill x não foi salva como texto em UTF-8"))

    def test_listar_mostra_erro(self):
        self.escrever("b", "---\ndescription: desc b\n---\nFaça.")
        self.escrever("a", "---\nname: a\n")
        self.assertEqual(s.listar(self.pasta),
                         [("a", "⚠ o cabeçalho da skill a começa com --- mas não termina com ---"), ("b", "desc b")])

    def test_listar_pasta_que_nao_existe(self):
        self.assertEqual(s.listar(self.pasta / "nada"), [])

    def test_existe(self):
        self.escrever("Vendas", "x")
        self.assertTrue(s.existe(self.pasta, "vendas"))
        self.assertFalse(s.existe(self.pasta, "outra"))

    def test_criar_prontas(self):
        pasta = self.pasta / "nova"
        self.assertTrue(s.criar_prontas(pasta))
        criador = s.carregar(pasta, "skill-creator")
        self.assertEqual(criador.descricao, "ajuda a criar uma skill nova para o chrono")
        self.assertIn("criar_skill", criador.instrucoes)

    def test_criar_prontas_nao_sobrescreve(self):
        self.assertFalse(s.criar_prontas(self.pasta))
        self.assertEqual(list(self.pasta.iterdir()), [])

    def test_texto_para_o_modelo(self):
        self.escrever("conferir", "---\ndescription: confere pedidos\n---\n1. Leia.", "modelo.xlsx", "b.txt")
        self.assertEqual(s.texto_para_o_modelo(s.carregar(self.pasta, "conferir")),
                         "# Skill ligada: conferir\n(confere pedidos)\n1. Leia.\n"
                         f"Arquivos de apoio desta skill, em {ferramentas.abreviar(self.pasta / 'conferir')}: "
                         "b.txt, modelo.xlsx")
        self.assertEqual(s.texto_para_o_modelo(s.Skill(nome="x", instrucoes="Faça.")),
                         "# Skill ligada: x\nFaça.")


class TestCriarSkill(unittest.TestCase):
    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp()) / "skills"
        self.pasta.mkdir()
        self.lixeira = Path(tempfile.mkdtemp())
        remendo = mock.patch.object(ferramentas, "LIXEIRA", self.lixeira)
        remendo.start()
        self.addCleanup(remendo.stop)
        self.args = {"nome": "vendas", "descricao": "resume as vendas do dia", "instrucoes": "1. Leia.\n2. Some."}
        self.conteudo = "---\nname: vendas\ndescription: resume as vendas do dia\n---\n\n1. Leia.\n2. Some.\n"

    def test_definicao(self):
        funcao = s.DEFINICAO_CRIAR_SKILL["function"]
        self.assertEqual((s.DEFINICAO_CRIAR_SKILL["type"], funcao["name"]), ("function", "criar_skill"))
        self.assertEqual(funcao["parameters"]["required"], ["nome", "descricao", "instrucoes"])

    def test_criar_skill_nova(self):
        confirmar = Respostas(True)
        resultado = s.criar_skill(self.pasta, self.args, confirmar)
        arquivo = self.pasta / "vendas" / "SKILL.md"
        self.assertEqual(arquivo.read_text(encoding="utf-8"), self.conteudo)
        self.assertEqual(confirmar.perguntas,
                         [(f"Criar a skill vendas em {ferramentas.abreviar(arquivo)}?", self.conteudo, False)])
        self.assertTrue(resultado.alterou)
        self.assertEqual(resultado.resumo, "criada a skill vendas")
        self.assertIn("para usar: /skill vendas", resultado.texto)

    def test_criar_skill_recusada(self):
        resultado = s.criar_skill(self.pasta, self.args, Respostas(False))
        self.assertFalse((self.pasta / "vendas").exists())
        self.assertTrue(resultado.texto.startswith("erro:"))
        self.assertEqual(resultado.resumo, "skill vendas não criada")

    def test_substituir_pergunta_sempre_e_guarda_a_antiga(self):
        (self.pasta / "vendas").mkdir()
        (self.pasta / "vendas" / "SKILL.md").write_text("versão antiga", encoding="utf-8")
        confirmar = Respostas(True)
        s.criar_skill(self.pasta, self.args, confirmar)
        self.assertEqual(confirmar.perguntas, [("Substituir a skill vendas?", self.conteudo, True)])
        self.assertEqual((self.pasta / "vendas" / "SKILL.md").read_text(encoding="utf-8"), self.conteudo)
        self.assertEqual((self.lixeira / "vendas SKILL (antes de substituir).md").read_text(encoding="utf-8"),
                         "versão antiga")

    def test_criar_skill_argumentos_ruins(self):
        self.assertTrue(s.criar_skill(self.pasta, json.dumps(self.args), Respostas(True)).texto.startswith("skill criada"))
        casos = [(dict(self.args, nome="outra", descricao=""), "erro: falta a descrição: uma frase dizendo quando usar a skill"),
                 (dict(self.args, nome="outra", instrucoes=" "), "erro: faltam as instruções da skill"),
                 (dict(self.args, nome="a b"), "erro: o nome da skill só pode ter letras, números, - e _ (sem espaços)"),
                 (dict(self.args, nome="editar"), 'erro: "editar" é um comando; escolha outro nome'),
                 ({"nome": "outra"}, "erro: falta a descrição: uma frase dizendo quando usar a skill"),
                 ("isto não é json", "erro: não entendi os argumentos da ferramenta")]
        for argumentos, esperado in casos:
            with self.subTest(argumentos=argumentos):
                confirmar = Respostas(True)
                self.assertEqual(s.criar_skill(self.pasta, argumentos, confirmar).texto, esperado)
                self.assertEqual(confirmar.perguntas, [])
        self.assertEqual([p.name for p in self.pasta.iterdir()], ["vendas"])

    def test_criar_skill_limites(self):
        grande = s.criar_skill(self.pasta, dict(self.args, nome="grande", instrucoes="a" * 20500), Respostas(True))
        self.assertTrue(grande.texto.startswith("erro: a skill fica grande demais ("))
        self.assertFalse((self.pasta / "grande").exists())
        comprido = s.criar_skill(self.pasta, dict(self.args, nome="a" * 300), Respostas(True))
        self.assertEqual(comprido.texto, "erro: o nome da skill pode ter no máximo 64 caracteres")
        s.criar_skill(self.pasta, dict(self.args, nome="linhas", descricao="linha1\n---\nlinha2"), Respostas(True))
        skill = s.carregar(self.pasta, "linhas")
        self.assertEqual((skill.descricao, skill.instrucoes), ("linha1 --- linha2", "1. Leia.\n2. Some."))

    def test_criar_skill_sem_pasta(self):
        pasta = self.pasta / "apagada"
        s.criar_skill(pasta, self.args, Respostas(True))
        self.assertTrue((pasta / "vendas" / "SKILL.md").exists())


if __name__ == "__main__":
    unittest.main()
