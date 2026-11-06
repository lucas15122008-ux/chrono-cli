"""Fabrica arquivos de teste de verdade (PDF, PDF escaneado, Word, Excel) sem instalar nada a mais."""
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path


def pdf_com_texto(caminho, paginas):
    """PDF mínimo com uma página por texto, em Helvetica e com acentos (WinAnsi)."""
    objetos = []
    kids = []
    fonte = 3 + 2 * len(paginas)
    for i, texto in enumerate(paginas):
        pagina, conteudo = 3 + 2 * i, 4 + 2 * i
        kids.append(f"{pagina} 0 R")
        linhas = texto.split("\n")
        comandos = "BT /F1 12 Tf 50 750 Td 15 TL " + " ".join(
            "(" + l.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") Tj T*" for l in linhas) + " ET"
        dados = comandos.encode("cp1252")
        objetos.append((pagina, f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {conteudo} 0 R "
                                f"/Resources << /Font << /F1 {fonte} 0 R >> >> >>".encode()))
        objetos.append((conteudo, b"<< /Length %d >>\nstream\n" % len(dados) + dados + b"\nendstream"))
    objetos.insert(0, (2, f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(paginas)} >>".encode()))
    objetos.insert(0, (1, b"<< /Type /Catalog /Pages 2 0 R >>"))
    objetos.append((fonte, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"))
    saida = bytearray(b"%PDF-1.4\n")
    posicoes = {}
    for numero, corpo in sorted(objetos):
        posicoes[numero] = len(saida)
        saida += b"%d 0 obj\n" % numero + corpo + b"\nendobj\n"
    xref = len(saida)
    saida += b"xref\n0 %d\n0000000000 65535 f \n" % (len(posicoes) + 1)
    for numero in sorted(posicoes):
        saida += b"%010d 00000 n \n" % posicoes[numero]
    saida += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(posicoes) + 1, xref)
    Path(caminho).write_bytes(bytes(saida))


def pdf_escaneado(caminho, texto):
    """PDF de uma página que é só imagem, como um documento escaneado."""
    with tempfile.TemporaryDirectory() as pasta:
        original, imagem = Path(pasta) / "original.pdf", Path(pasta) / "pagina.png"
        pdf_com_texto(original, [texto])
        subprocess.run(["sips", "-s", "format", "png", "-Z", "1600", str(original), "--out", str(imagem)],
                       capture_output=True, check=True)
        subprocess.run(["sips", "-s", "format", "pdf", str(imagem), "--out", str(caminho)],
                       capture_output=True, check=True)


def word(caminho, texto):
    with tempfile.TemporaryDirectory() as pasta:
        origem = Path(pasta) / "origem.txt"
        origem.write_text(texto, encoding="utf-8")
        subprocess.run(["textutil", "-convert", Path(caminho).suffix[1:], str(origem), "-output", str(caminho)],
                       capture_output=True, check=True)


def planilha(caminho, abas):
    """abas: {"Nome": [[linha], [linha], ...]}"""
    import openpyxl
    livro = openpyxl.Workbook()
    livro.remove(livro.active)
    for nome, linhas in abas.items():
        aba = livro.create_sheet(nome)
        for linha in linhas:
            aba.append(linha)
    livro.save(caminho)


TABELA = [["Código", "Descrição", "Preço", "Atualizado"],
          [101, "Pastilha de freio Cobreq Gol G5", 89.9, datetime(2026, 10, 30)],
          [102, "Disco de freio Fremax Gol G5", 159.0, datetime(2026, 10, 31, 14, 30)],
          [103, "Amortecedor Cofap dianteiro", 249.5, None]]
