"""Uma pasta temporária só para cada rodada de testes, apagada no fim.

Antes, cada rodada deixava uns 10 MB de pastas temporárias para trás. Basta importar este
módulo antes de criar qualquer pasta temporária: tudo o que o tempfile criar fica aqui dentro.
"""
import atexit
import os
import shutil
import tempfile

RAIZ = tempfile.mkdtemp(prefix="chrono-testes-")
tempfile.tempdir = RAIZ
os.environ["TMPDIR"] = RAIZ  # o chrono que os testes abrem também usa esta pasta
atexit.register(shutil.rmtree, RAIZ, True)
