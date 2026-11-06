import base64
import errno
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import limpeza  # noqa: E402,F401  (pasta temporária apagada no fim da rodada)
import fabrica  # noqa: E402
import ferramentas as f  # noqa: E402


def nunca(pergunta, detalhe=None, sempre_perguntar=False):
    raise AssertionError(f"não devia perguntar: {pergunta}")


class Base(unittest.TestCase):
    """Uma "casa" de mentira, com Documents e uma pasta de projeto, no lugar do HOME de verdade."""

    def setUp(self):
        self.casa = Path(tempfile.mkdtemp(prefix="chrono-casa-")).resolve()
        (self.casa / "Documents").mkdir()
        self.base = self.casa / "projeto"
        self.base.mkdir()
        for nome, valor in (("CASA", self.casa), ("LIXEIRA", self.casa / ".Trash")):
            remendo = mock.patch.object(f, nome, valor)
            remendo.start()
            self.addCleanup(remendo.stop)

    def rodar(self, ferramenta, confirmar=nunca, **argumentos):
        return f.executar(ferramenta, argumentos, confirmar, self.base)


class TestCaminhos(Base):
    def test_traduz_nome_existente(self):
        (self.casa / "Documents" / "a.txt").write_text("x")
        self.assertEqual(f.resolver_caminho("~/Documentos/a.txt", self.base), self.casa / "Documents" / "a.txt")

    def test_traduz_prefixo_para_caminho_novo(self):
        self.assertEqual(f.resolver_caminho("~/Documentos/novo.txt", self.base),
                         self.casa / "Documents" / "novo.txt")

    def test_area_de_trabalho(self):
        (self.casa / "Desktop").mkdir()
        self.assertEqual(f.resolver_caminho("~/Área de Trabalho", self.base), self.casa / "Desktop")

    def test_pasta_que_existe_em_portugues_fica(self):
        (self.casa / "Imagens").mkdir()
        self.assertEqual(f.resolver_caminho("~/Imagens", self.base), self.casa / "Imagens")

    def test_relativo_usa_base(self):
        self.assertEqual(f.resolver_caminho("x.txt", self.base), self.base / "x.txt")

    def test_abreviar(self):
        self.assertEqual(f.abreviar(self.base / "a.txt"), "~/projeto/a.txt")
        self.assertEqual(f.abreviar(Path("/tmp")), "/tmp")


class TestLeitura(Base):
    def test_listar_pasta(self):
        (self.base / "b.txt").write_text("x" * 2048)
        (self.base / "a").mkdir()
        (self.base / ".escondido").write_text("")
        for nome in ("a", "b.txt"):
            os.utime(self.base / nome, (datetime(2026, 10, 30, 10, 11).timestamp(),) * 2)
        r = self.rodar("listar_pasta", caminho=str(self.base))
        self.assertEqual(r.texto, "a/  (30/10 10:11)\nb.txt  (2 KB · 30/10 10:11)")
        self.assertEqual(r.resumo, "listando ~/projeto")

    def test_listar_pasta_por_data(self):
        # Para "o último orçamento que salvei": os mais novos primeiro.
        for dia, nome in ((1, "antigo.txt"), (3, "novo.txt"), (2, "meio.txt")):
            (self.base / nome).write_text("")
            os.utime(self.base / nome, (datetime(2026, 11, dia, 9, 0).timestamp(),) * 2)
        texto = self.rodar("listar_pasta", caminho=".", ordem="data").texto
        self.assertEqual([linha.split()[0] for linha in texto.splitlines()], ["novo.txt", "meio.txt", "antigo.txt"])

    def test_buscar_arquivos_mostra_data(self):
        arquivo = self.base / "orc.txt"
        arquivo.write_text("")
        os.utime(arquivo, (datetime(2026, 10, 30, 10, 11).timestamp(),) * 2)
        with mock.patch("subprocess.run", return_value=mock.Mock(stdout=f"{arquivo}\n", returncode=0)):
            self.assertEqual(self.rodar("buscar_arquivos", nome="orc").texto, f"{arquivo}  (0 B · 30/10 10:11)")

    def test_listar_pasta_limite(self):
        for i in range(150):
            (self.base / f"f{i:03}.txt").write_text("")
        linhas = self.rodar("listar_pasta", caminho=".").texto.splitlines()
        self.assertEqual((len(linhas), linhas[-1]), (101, "… e mais 50"))

    def test_ler_arquivo(self):
        (self.base / "a.txt").write_text("pastilha cerâmica", encoding="utf-8")
        r = self.rodar("ler_arquivo", caminho="a.txt")
        self.assertEqual((r.texto, r.resumo), ("pastilha cerâmica", "lendo a.txt"))

    def test_ler_arquivo_corta(self):
        (self.base / "g.txt").write_text("x" * 30000)
        texto = self.rodar("ler_arquivo", caminho="g.txt").texto
        self.assertTrue(texto.startswith("x" * 20000))
        self.assertTrue(texto.endswith("(arquivo cortado: mostrei 20000 de 30000 caracteres)"))
        self.assertNotIn("x" * 20001, texto)

    def test_ler_arquivo_grande_le_so_o_comeco(self):
        (self.base / "enorme.txt").write_text("x" * 1_000_000)
        aberturas = []
        original = Path.read_bytes
        with mock.patch.object(Path, "read_bytes", lambda p: aberturas.append(p) or original(p)):
            texto = self.rodar("ler_arquivo", caminho="enorme.txt").texto
        self.assertEqual(aberturas, [])  # não carrega o arquivo inteiro na memória
        self.assertTrue(texto.endswith("(arquivo cortado: mostrei 20000 caracteres de um arquivo de 1,0 MB)"))

    def test_ler_windows_cp1252(self):
        # Exportações de sistemas Windows (como ERPs) costumam vir em cp1252.
        (self.base / "export.csv").write_bytes("Orçamento;Pastilha dianteira;R$ 89,90".encode("cp1252"))
        self.assertEqual(self.rodar("ler_arquivo", caminho="export.csv").texto, "Orçamento;Pastilha dianteira;R$ 89,90")

    def test_ler_utf16(self):
        (self.base / "u16.txt").write_bytes("Ação".encode("utf-16"))
        self.assertEqual(self.rodar("ler_arquivo", caminho="u16.txt").texto, "Ação")

    def test_formato_que_nao_le(self):
        (self.base / "slides.pptx").write_bytes(b"PK sem zero")
        self.assertEqual(self.rodar("ler_arquivo", caminho="slides.pptx").texto,
                         "erro: slides.pptx é um arquivo do PowerPoint, e eu ainda não leio esse formato.")

    def test_arquivo_especial_nao_trava(self):
        os.mkfifo(self.base / "cano")
        (self.base / "a.txt").write_text("pastilha")
        resultados = []
        for nome, argumentos in [("ler_arquivo", {"caminho": "cano"}), ("buscar_texto", {"texto": "pastilha", "pasta": "."}),
                                 ("ler_arquivo", {"caminho": "/dev/zero"})]:
            linha = threading.Thread(target=lambda n=nome, a=argumentos: resultados.append(f.executar(n, a, nunca, self.base)),
                                     daemon=True)
            linha.start()
            linha.join(5)
            self.assertFalse(linha.is_alive(), f"{nome} travou em {argumentos}")
        self.assertEqual(resultados[0].texto, "erro: ~/projeto/cano não é um arquivo comum.")
        self.assertEqual(resultados[1].texto, "a.txt:1: pastilha")
        self.assertTrue(resultados[2].texto.startswith("erro:"))

    def test_ler_arquivo_binario(self):
        (self.base / "b.bin").write_bytes(b"abc\x00def")
        texto = self.rodar("ler_arquivo", caminho="b.bin").texto
        self.assertTrue(texto.startswith("erro:"))
        self.assertIn("não é um arquivo de texto", texto)

    def test_ler_arquivo_inexistente(self):
        r = self.rodar("ler_arquivo", caminho="nada.txt")
        self.assertTrue(r.texto.startswith("erro:"))
        self.assertEqual(r.resumo, "não achei nada.txt")

    def test_erro_de_permissao_vira_resultado(self):
        arquivo = self.base / "secreto.txt"
        arquivo.write_text("x")
        arquivo.chmod(0)
        self.addCleanup(arquivo.chmod, 0o644)
        r = self.rodar("ler_arquivo", caminho="secreto.txt")
        self.assertEqual(r.texto, "erro: sem permissão para acessar ~/projeto/secreto.txt.")

    def test_buscar_texto(self):
        (self.base / "a.txt").write_text("Pastilha dianteira\noutra linha")
        (self.base / "b.md").write_text("nada aqui\ntem PASTILHA aqui")
        (self.base / "c.txt").write_text("disco")
        (self.base / ".git").mkdir()
        (self.base / ".git" / "x.txt").write_text("pastilha")
        r = self.rodar("buscar_texto", texto="pastilha", pasta=".")
        self.assertEqual(sorted(r.texto.splitlines()), ["a.txt:1: Pastilha dianteira", "b.md:2: tem PASTILHA aqui"])
        self.assertEqual(r.resumo, 'procurando "pastilha" em ~/projeto')

    def test_buscar_arquivos(self):
        saida = mock.Mock(stdout="/x/orcamento.pdf\n/y/orc.txt\n", returncode=0)
        with mock.patch("subprocess.run", return_value=saida) as run:
            r = self.rodar("buscar_arquivos", nome="orc", pasta=str(self.base))
        self.assertEqual(run.call_args[0][0], ["mdfind", "-name", "orc", "-onlyin", str(self.base)])
        # Caminhos que não existem mais saem sem data.
        self.assertEqual((r.texto, r.resumo), ("/x/orcamento.pdf\n/y/orc.txt", 'procurando arquivos "orc"'))

    def test_buscar_arquivos_sem_resultado(self):
        with mock.patch("subprocess.run", return_value=mock.Mock(stdout="", returncode=0)):
            self.assertEqual(self.rodar("buscar_arquivos", nome="xyz").texto, "nenhum arquivo encontrado")

    def test_ver_imagem_png(self):
        (self.base / "foto.png").write_bytes(b"\x89PNG falso")
        r = self.rodar("ver_imagem", caminho="foto.png")
        self.assertEqual(r.imagens, [base64.b64encode(b"\x89PNG falso").decode()])
        self.assertEqual(r.resumo, "abrindo foto.png")

    def test_ver_imagem_heic_converte(self):
        (self.base / "foto.heic").write_bytes(b"heic")

        def sips_falso(args, **opcoes):
            Path(args[args.index("--out") + 1]).write_bytes(b"jpg convertido")
            return mock.Mock(returncode=0)

        with mock.patch("subprocess.run", side_effect=sips_falso) as run:
            r = self.rodar("ver_imagem", caminho="foto.heic")
        self.assertEqual(run.call_args[0][0][:4], ["sips", "-s", "format", "jpeg"])
        self.assertEqual(r.imagens, [base64.b64encode(b"jpg convertido").decode()])

    def test_ver_imagem_grande_e_reduzida(self):
        (self.base / "foto.jpg").write_bytes(b"j" * 6_000_000)

        def sips_falso(args, **opcoes):
            Path(args[args.index("--out") + 1]).write_bytes(b"menor")
            return mock.Mock(returncode=0)

        with mock.patch("subprocess.run", side_effect=sips_falso) as run:
            r = self.rodar("ver_imagem", caminho="foto.jpg")
        self.assertEqual(run.call_args[0][0][:4], ["sips", "-s", "format", "jpeg"])
        self.assertEqual(r.imagens, [base64.b64encode(b"menor").decode()])

    def test_sips_demorado_vira_erro(self):
        (self.base / "foto.heic").write_bytes(b"heic")
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("sips", 60)):
            self.assertTrue(self.rodar("ver_imagem", caminho="foto.heic").texto.startswith("erro:"))

    def test_ver_imagem_formato_errado(self):
        (self.base / "a.txt").write_text("x")
        self.assertTrue(self.rodar("ver_imagem", caminho="a.txt").texto.startswith("erro:"))


class Respostas:
    """confirmar() de teste: responde com a lista dada e anota as perguntas."""

    def __init__(self, *respostas):
        self.respostas = list(respostas)
        self.perguntas = []

    def __call__(self, pergunta, detalhe=None, sempre_perguntar=False):
        self.perguntas.append((pergunta, detalhe))
        self.sempre = sempre_perguntar
        return self.respostas.pop(0)


class TestAlteracao(Base):
    def test_escrever_pergunta_e_cria(self):
        sim = Respostas(True)
        r = self.rodar("escrever_arquivo", sim, caminho="novo.txt", conteudo="linha 1\nlinha 2")
        self.assertEqual((self.base / "novo.txt").read_text(), "linha 1\nlinha 2")
        self.assertEqual(sim.perguntas, [("Criar o arquivo ~/projeto/novo.txt?", "linha 1\nlinha 2")])
        self.assertEqual((r.resumo, r.alterou), ("criado ~/projeto/novo.txt", True))

    def test_escrever_previa_longa(self):
        sim = Respostas(True)
        self.rodar("escrever_arquivo", sim, caminho="longo.txt", conteudo="\n".join(str(i) for i in range(25)))
        self.assertEqual(sim.perguntas[0][1], "\n".join(str(i) for i in range(10)) + "\n… (+15 linhas)")

    def test_previa_corta_linha_longa(self):
        sim = Respostas(True)
        self.rodar("escrever_arquivo", sim, caminho="min.js", conteudo="x" * 5000)
        self.assertEqual(sim.perguntas[0][1], "x" * 200 + "…")

    def test_renomear_so_maiusculas(self):
        # No disco do Mac, nota.txt e Nota.txt são o mesmo arquivo.
        (self.base / "nota.txt").write_text("x")
        self.rodar("mover", Respostas(True), origem="nota.txt", destino="Nota.txt")
        self.assertEqual([p.name for p in self.base.iterdir()], ["Nota.txt"])

    def test_erro_do_sistema_em_portugues(self):
        sem_espaco = OSError(errno.ENOSPC, "No space left on device", str(self.base / "a.txt"))
        with mock.patch.object(Path, "write_text", side_effect=sem_espaco):
            r = self.rodar("escrever_arquivo", Respostas(True), caminho="a.txt", conteudo="x")
        self.assertEqual(r.texto, "erro: ~/projeto/a.txt não coube: o disco está cheio.")

    def test_escrever_recusado(self):
        r = self.rodar("escrever_arquivo", Respostas(False), caminho="novo.txt", conteudo="x")
        self.assertFalse((self.base / "novo.txt").exists())
        self.assertTrue(r.texto.startswith("o usuário recusou"))
        self.assertEqual((r.resumo, r.alterou), ("recusado: escrever ~/projeto/novo.txt", False))

    def test_escrever_avisa_substituir(self):
        (self.base / "a.txt").write_text("antigo")
        sim = Respostas(True)
        self.rodar("escrever_arquivo", sim, caminho="a.txt", conteudo="novo")
        self.assertEqual(sim.perguntas[0][0], "Substituir o arquivo ~/projeto/a.txt? Ele já existe.")
        self.assertEqual((self.base / "a.txt").read_text(), "novo")

    def test_escrever_em_pasta_que_nao_existe(self):
        r = self.rodar("escrever_arquivo", caminho="nao/existe/a.txt", conteudo="x")
        self.assertEqual(r.texto, "erro: a pasta ~/projeto/nao/existe não existe; crie com criar_pasta antes.")

    def test_criar_pasta(self):
        sim = Respostas(True)
        r = self.rodar("criar_pasta", sim, caminho="~/Documentos/Clientes")
        self.assertTrue((self.casa / "Documents" / "Clientes").is_dir())
        self.assertEqual(sim.perguntas[0][0], "Criar a pasta ~/Documents/Clientes?")
        self.assertEqual(r.resumo, "pasta criada ~/Documents/Clientes")

    def test_mover_para_pasta(self):
        (self.base / "a.txt").write_text("x")
        (self.base / "destino").mkdir()
        sim = Respostas(True)
        r = self.rodar("mover", sim, origem="a.txt", destino="destino")
        self.assertTrue((self.base / "destino" / "a.txt").exists())
        self.assertEqual(sim.perguntas[0][0], "Mover ~/projeto/a.txt para ~/projeto/destino/a.txt?")
        self.assertEqual(r.resumo, "movido ~/projeto/a.txt → ~/projeto/destino/a.txt")

    def test_mover_renomeia(self):
        (self.base / "a.txt").write_text("x")
        self.rodar("mover", Respostas(True), origem="a.txt", destino="b.txt")
        self.assertEqual([p.name for p in self.base.iterdir()], ["b.txt"])

    def test_mover_nao_sobrescreve(self):
        (self.base / "a.txt").write_text("a")
        (self.base / "b.txt").write_text("b")
        r = self.rodar("mover", origem="a.txt", destino="b.txt")
        self.assertEqual(r.texto, "erro: ~/projeto/b.txt já existe; não vou sobrescrever.")
        self.assertEqual(((self.base / "a.txt").read_text(), (self.base / "b.txt").read_text()), ("a", "b"))

    def test_lixeira(self):
        (self.base / "a.txt").write_text("x")
        r = self.rodar("mandar_para_lixeira", Respostas(True), caminho="a.txt")
        self.assertFalse((self.base / "a.txt").exists())
        self.assertTrue((self.casa / ".Trash" / "a.txt").exists())
        self.assertEqual(r.resumo, "na Lixeira: a.txt")

    def test_lixeira_nome_unico(self):
        (self.casa / ".Trash").mkdir()
        (self.casa / ".Trash" / "a.txt").write_text("antigo")
        (self.base / "a.txt").write_text("novo")
        self.rodar("mandar_para_lixeira", Respostas(True), caminho="a.txt")
        self.assertEqual((self.casa / ".Trash" / "a 2.txt").read_text(), "novo")
        self.assertEqual((self.casa / ".Trash" / "a.txt").read_text(), "antigo")

    def test_lixeira_com_ponto_ponto(self):
        # ".." no fim apontava para a pasta de cima e a esvaziava numa Lixeira de nome oculto.
        (self.casa / "Documents" / "Clientes").mkdir()
        (self.casa / "Documents" / "orc.txt").write_text("x")
        sim = Respostas(True)
        self.rodar("mandar_para_lixeira", sim, caminho="~/Documents/Clientes/..")
        self.assertEqual(sim.perguntas[0][0], "Mandar ~/Documents para a Lixeira?")
        self.assertEqual([p.name for p in (self.casa / ".Trash").iterdir()], ["Documents"])

    def test_lixeira_ponto_ponto_ate_a_casa_e_recusado(self):
        r = self.rodar("mandar_para_lixeira", caminho="~/Documents/..")
        self.assertEqual(r.texto, "erro: não vou mandar ~ inteira para a Lixeira.")

    def test_resolver_tira_ponto_ponto(self):
        self.assertEqual(f.resolver_caminho("~/Documents/Clientes/..", self.base), self.casa / "Documents")

    def test_escrever_por_atalho_mostra_o_destino(self):
        (self.casa / ".zshrc").write_text("antigo")
        (self.base / "notas.txt").symlink_to(self.casa / ".zshrc")
        sim = Respostas(True)
        self.rodar("escrever_arquivo", sim, caminho="notas.txt", conteudo="novo")
        self.assertEqual(sim.perguntas[0][0],
                         "Substituir o arquivo ~/.zshrc (pelo atalho ~/projeto/notas.txt)? Ele já existe.")

    def test_substituir_sempre_pergunta(self):
        (self.base / "a.txt").write_text("antigo")
        sim = Respostas(True)
        self.rodar("escrever_arquivo", sim, caminho="a.txt", conteudo="novo")
        self.assertTrue(sim.sempre)  # nem o "t" (todas) pula esta pergunta
        criar = Respostas(True)
        self.rodar("escrever_arquivo", criar, caminho="b.txt", conteudo="novo")
        self.assertFalse(criar.sempre)

    def test_erro_inesperado_vira_resultado(self):
        r = self.rodar("buscar_arquivos", nome="a\x00b")  # o subprocess recusa o byte nulo
        self.assertTrue(r.texto.startswith("erro:"))
        r = self.rodar("escrever_arquivo", Respostas(True), caminho="a\x00b.txt", conteudo="x")
        self.assertTrue(r.texto.startswith("erro:"))

    def test_lixeira_recusa_pasta_do_usuario(self):
        r = self.rodar("mandar_para_lixeira", caminho="~")
        self.assertEqual(r.texto, "erro: não vou mandar ~ inteira para a Lixeira.")
        self.assertTrue(self.casa.exists())

    def test_leitura_nunca_pergunta(self):
        (self.base / "a.txt").write_text("x")
        (self.base / "f.png").write_bytes(b"png")
        with mock.patch("subprocess.run", return_value=mock.Mock(stdout="", returncode=0)):
            for nome, argumentos in [("listar_pasta", {"caminho": "."}), ("ler_arquivo", {"caminho": "a.txt"}),
                                     ("buscar_arquivos", {"nome": "a"}), ("ver_imagem", {"caminho": "f.png"}),
                                     ("buscar_texto", {"texto": "x", "pasta": "."})]:
                self.assertFalse(f.executar(nome, argumentos, nunca, self.base).texto.startswith("erro:"), nome)

    def test_definicoes_sem_imagem(self):
        nomes = [d["function"]["name"] for d in f.definicoes(imagens=False)]
        self.assertNotIn("ver_imagem", nomes)
        self.assertEqual(len(nomes), 15)

    def test_definicoes_completas(self):
        self.assertEqual([d["function"]["name"] for d in f.definicoes()],
                         ["listar_pasta", "ler_arquivo", "buscar_no_arquivo", "calcular_na_planilha",
                          "buscar_arquivos", "buscar_texto", "ver_imagem", "escrever_arquivo", "criar_pasta", "mover",
                          "mandar_para_lixeira", "criar_planilha", "mudar_na_planilha", "adicionar_coluna",
                          "adicionar_linhas", "apagar_linhas"])


class TestDocumentos(Base):
    def setUp(self):
        super().setUp()
        fabrica.pdf_com_texto(self.base / "nota.pdf", ["Pedido 4512\nPastilha Cobreq", "Disco Fremax"])
        fabrica.planilha(self.base / "precos.xlsx", {"Preços": fabrica.TABELA, "Estoque": [["Código", "Qtd"], [101, 7]]})
        fabrica.word(self.base / "carta.docx", "Prezado cliente\nSegue o Orçamento")

    def test_ler_pdf(self):
        r = self.rodar("ler_arquivo", caminho="nota.pdf")
        self.assertTrue(r.texto.startswith("=== página 1 ===\nPedido 4512"))
        self.assertEqual(r.resumo, "lendo nota.pdf")

    def test_ler_pdf_a_partir_de_escrito_por_extenso(self):
        self.assertEqual(self.rodar("ler_arquivo", caminho="nota.pdf", a_partir_de="página 2").texto,
                         "=== página 2 ===\nDisco Fremax")

    def test_ler_planilha_uma_aba(self):
        self.assertEqual(self.rodar("ler_arquivo", caminho="precos.xlsx", aba="Estoque").texto,
                         "=== aba Estoque (2 linhas) ===\n1: Código | Qtd\n2: 101 | 7")

    def test_planilha_grande_abre_no_resumo(self):
        linhas = [["Código", "Descrição"]] + [[i, f"Peça {i}"] for i in range(1, 501)]
        fabrica.planilha(self.base / "grande.xlsx", {"Tabela": linhas})
        texto = self.rodar("ler_arquivo", caminho="grande.xlsx").texto
        self.assertTrue(texto.endswith('a_partir_de=21; para achar um item, use buscar_no_arquivo)'))

    def test_ler_word(self):
        self.assertEqual(self.rodar("ler_arquivo", caminho="carta.docx").texto, "Prezado cliente\nSegue o Orçamento")

    def test_ler_texto_a_partir_de_uma_linha(self):
        (self.base / "lista.txt").write_text("\n".join(f"item {i}" for i in range(1, 11)))
        self.assertEqual(self.rodar("ler_arquivo", caminho="lista.txt", a_partir_de="9").texto,
                         "(a partir da linha 9)\nitem 9\nitem 10")

    def test_a_partir_de_invalido(self):
        self.assertEqual(self.rodar("ler_arquivo", caminho="nota.pdf", a_partir_de="do começo").texto,
                         'erro: a_partir_de precisa ser um número (por exemplo "3").')

    def test_buscar_no_arquivo_planilha(self):
        r = self.rodar("buscar_no_arquivo", caminho="precos.xlsx", texto="fremax")
        self.assertEqual(r.texto, "aba Preços — cabeçalho: Código | Descrição | Preço | Atualizado\n"
                                  "linha 3: 102 | Disco de freio Fremax Gol G5 | 159 | 31/10/2026 14:30")
        self.assertEqual(r.resumo, 'procurando "fremax" em precos.xlsx')

    def test_buscar_no_arquivo_texto(self):
        (self.base / "lista.txt").write_text("Pastilha\nDisco\nAmortecedor Cofap")
        self.assertEqual(self.rodar("buscar_no_arquivo", caminho="lista.txt", texto="cofap").texto,
                         "linha 3: Amortecedor Cofap")

    def test_buscar_no_arquivo_sem_resultado(self):
        self.assertEqual(self.rodar("buscar_no_arquivo", caminho="nota.pdf", texto="bateria").texto,
                         "nada encontrado")

    def test_buscar_texto_olha_dentro_de_documentos(self):
        achados = self.rodar("buscar_texto", texto="cobreq", pasta=".").texto.splitlines()
        self.assertIn("nota.pdf: página 1: Pastilha Cobreq", achados)
        self.assertIn("precos.xlsx: linha 2: 101 | Pastilha de freio Cobreq Gol G5 | 89,9 | 30/10/2026", achados)

    def test_buscar_texto_sem_acento(self):
        achados = self.rodar("buscar_texto", texto="orcamento", pasta=".").texto.splitlines()
        self.assertIn("carta.docx: linha 2: Segue o Orçamento", achados)

    def test_falta_biblioteca_vira_erro(self):
        with mock.patch.object(f.documentos, "ler_pdf", side_effect=f.documentos.FaltaBiblioteca("pypdf", "PDF")):
            r = self.rodar("ler_arquivo", caminho="nota.pdf")
        self.assertEqual((r.texto, r.resumo), ("erro: para ler PDF, falta a biblioteca pypdf: rode pip3 install "
                                               "--user pypdf.", "falta a biblioteca pypdf"))


class TestPlanilhasNasFerramentas(Base):
    def setUp(self):
        super().setUp()
        fabrica.planilha(self.base / "estoque.xlsx",
                         {"Peças": [["Peça", "Marca", "Preço"], ["Pastilha", "Cobreq", 89.9], ["Disco", "Fremax", 159]]})

    def test_calcular(self):
        r = self.rodar("calcular_na_planilha", caminho="estoque.xlsx", operacao="soma", coluna="Preço")
        self.assertEqual((r.texto, r.resumo), ("soma de Preço: 248,90 (2 linhas)", "calculando soma em estoque.xlsx"))

    def test_calcular_com_erro(self):
        r = self.rodar("calcular_na_planilha", caminho="estoque.xlsx", operacao="soma", coluna="Custo")
        self.assertTrue(r.texto.startswith("erro: não existe a coluna Custo"))

    def test_criar_pergunta_com_previa(self):
        sim = Respostas(True)
        r = self.rodar("criar_planilha", sim, caminho="nova.xlsx", conteudo="Peça | Preço\nVela | 25")
        self.assertEqual(sim.perguntas, [("Criar a planilha ~/projeto/nova.xlsx (2 linhas, 2 colunas)?",
                                          "1: Peça | Preço\n2: Vela | 25")])
        self.assertTrue((self.base / "nova.xlsx").exists())
        self.assertEqual((r.resumo, r.alterou), ("criada ~/projeto/nova.xlsx", True))

    def test_criar_recusado(self):
        r = self.rodar("criar_planilha", Respostas(False), caminho="nova.xlsx", conteudo="a | b")
        self.assertFalse((self.base / "nova.xlsx").exists())
        self.assertTrue(r.texto.startswith("o usuário recusou"))

    def test_criar_por_cima_sempre_pergunta(self):
        sim = Respostas(True)
        self.rodar("criar_planilha", sim, caminho="estoque.xlsx", conteudo="a | b")
        self.assertEqual(sim.perguntas[0][0], "Substituir a planilha ~/projeto/estoque.xlsx? Ela já existe.")
        self.assertTrue(sim.sempre)

    def test_criar_so_xlsx(self):
        r = self.rodar("criar_planilha", caminho="nova.csv", conteudo="a | b")
        self.assertEqual(r.texto, "erro: só crio planilhas .xlsx; use um nome terminado em .xlsx.")

    def alterar(self, ferramenta, resposta=True, **argumentos):
        respostas = Respostas(resposta)
        return self.rodar(ferramenta, respostas, caminho="estoque.xlsx", **argumentos), respostas

    def planilha(self):
        import openpyxl
        return openpyxl.load_workbook(self.base / "estoque.xlsx").active

    def test_mudar_pergunta_e_guarda_a_versao_de_antes(self):
        r, sim = self.alterar("mudar_na_planilha", coluna="Preço", valor="149,90", onde="Peça = disco")
        pergunta, detalhe = sim.perguntas[0]
        self.assertEqual(pergunta, "Alterar a planilha ~/projeto/estoque.xlsx? (1 alteração)")
        self.assertIn("Preço na linha 3: 159 → 149,90 (Disco | Fremax | 159)", detalhe)
        self.assertIn("a versão de agora vai para a Lixeira", detalhe)
        self.assertTrue(sim.sempre)  # mexe no que já existe: nem o "t" pula
        self.assertTrue((self.casa / ".Trash" / "estoque (antes de editar).xlsx").exists())
        self.assertEqual(self.planilha()["C3"].value, 149.9)
        self.assertEqual((r.resumo, r.alterou), ("alterada ~/projeto/estoque.xlsx", True))
        # O modelo recebe o que foi feito de verdade, para não inventar outro resumo.
        self.assertIn("Preço na linha 3: 159 → 149,90", r.texto)

    def test_adicionar_coluna(self):
        r, _ = self.alterar("adicionar_coluna", nome="Com desconto", conta="[Preço] * 0,95")
        self.assertAlmostEqual(self.planilha()["D2"].value, 85.405)
        self.assertIn("não é fórmula do Excel", r.texto)

    def test_adicionar_linhas(self):
        self.alterar("adicionar_linhas", linhas="Vela | NGK | 25,90\nBateria | Moura | 450")
        self.assertEqual([[c.value for c in linha] for linha in self.planilha().iter_rows(min_row=4)],
                         [["Vela", "NGK", 25.9], ["Bateria", "Moura", 450]])

    def test_apagar_linhas(self):
        self.alterar("apagar_linhas", onde="Marca = Fremax")
        self.assertEqual(self.planilha().max_row, 2)

    def test_recusado_nao_mexe(self):
        r, _ = self.alterar("mudar_na_planilha", resposta=False, coluna="Preço", valor="1", onde="Peça = disco")
        self.assertTrue(r.texto.startswith("o usuário recusou"))
        self.assertFalse((self.casa / ".Trash").exists())
        self.assertEqual(self.planilha()["C3"].value, 159)

    def test_erro_nem_pergunta(self):
        r = self.rodar("mudar_na_planilha", caminho="estoque.xlsx", coluna="Preço", valor="[Preço] * 0,95",
                       onde="Peça = disco")
        self.assertTrue(r.texto.startswith("erro: um valor não pode ter colunas entre colchetes"))


class TestExecutar(Base):
    def test_argumentos_em_texto(self):
        (self.base / "a.txt").write_text("oi")
        r = f.executar("ler_arquivo", '{"caminho": "a.txt"}', nunca, self.base)
        self.assertEqual(r.texto, "oi")

    def test_ferramenta_desconhecida(self):
        r = self.rodar("formatar_disco")
        self.assertEqual((r.texto, r.resumo), ("erro: não existe a ferramenta formatar_disco.",
                                               "ferramenta desconhecida: formatar_disco"))

    def test_argumento_faltando(self):
        self.assertEqual(self.rodar("ler_arquivo").texto, "erro: faltou caminho.")

    def test_argumentos_invalidos(self):
        self.assertTrue(f.executar("ler_arquivo", "{quebrado", nunca, self.base).texto.startswith("erro:"))

    def test_definicoes_de_leitura(self):
        definicoes = f.definicoes(alterar=False)
        self.assertEqual([d["function"]["name"] for d in definicoes],
                         ["listar_pasta", "ler_arquivo", "buscar_no_arquivo", "calcular_na_planilha",
                          "buscar_arquivos", "buscar_texto", "ver_imagem"])
        primeira = definicoes[0]
        self.assertEqual(primeira["type"], "function")
        self.assertEqual(primeira["function"]["parameters"]["required"], ["caminho"])
        self.assertIn("~/Documents", primeira["function"]["parameters"]["properties"]["caminho"]["description"])


if __name__ == "__main__":
    unittest.main()
