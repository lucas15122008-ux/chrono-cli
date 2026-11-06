"""Ollama de mentira para os testes: responde como a API real, sem carregar modelo nenhum."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODELO = "ornith-1.5:9b"  # o mesmo do padrão do chrono
QUEBRADO = "grande:70b"  # existe, mas não cabe na memória: /api/show responde, carregar falha
OUTRO = "leve:4b"  # um segundo modelo que funciona, para os agentes com modelo próprio
SHOW = {
    "capabilities": ["completion", "vision", "tools", "thinking"],
    "details": {"parameter_size": "9.0B", "quantization_level": "Q4_K_M"},
}
PS = {"name": MODELO, "model": MODELO, "size": 6_700_000_000, "size_vram": 6_700_000_000,
      "context_length": 32768}
FINAL = {"total_duration": 2_400_000_000, "eval_count": 64, "eval_duration": 3_500_000_000,
         "prompt_eval_count": 348}


class FakeOllama:
    def __init__(self):
        # Cada /api/chat usa a próxima rodada combinada, se houver: {"tool_calls": [...]} ou
        # {"respostas": [...]}; sem rodadas, responde com self.respostas.
        self.rodadas = []
        self.respostas = ["Oi!"]
        self.pensamentos = []
        self.atraso = 0.0
        self.linha_quebrada = False  # manda uma linha que não é JSON no meio da resposta
        self.carregado = False
        self.pedidos = []

    def __enter__(self):
        fake = self

        class Atendente(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _json(self, codigo, dados):
                corpo = json.dumps(dados).encode()
                self.send_response(codigo)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(corpo)))
                self.end_headers()
                self.wfile.write(corpo)

            def do_GET(self):
                if self.path == "/api/tags":
                    self._json(200, {"models": [{"name": MODELO}]})
                elif self.path == "/api/ps":
                    self._json(200, {"models": [PS] if fake.carregado else []})
                else:
                    self._json(404, {"error": "not found"})

            def do_POST(self):
                corpo = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                if corpo.get("model") not in (MODELO, QUEBRADO, OUTRO):
                    self._json(404, {"error": f"model '{corpo.get('model')}' not found"})
                elif self.path == "/api/show":
                    self._json(200, SHOW)
                elif corpo["model"] == QUEBRADO:
                    self._json(500, {"error": "model requires more system memory than is available"})
                elif self.path == "/api/generate":
                    fake.carregado = True
                    self._json(200, {"model": MODELO, "done": True})
                elif self.path == "/api/chat":
                    fake.pedidos.append(corpo)
                    fake.carregado = True
                    self._transmitir()
                else:
                    self._json(404, {"error": "not found"})

            def _transmitir(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.end_headers()
                rodada = fake.rodadas.pop(0) if fake.rodadas else {"respostas": fake.respostas}
                pedacos = [{"content": "", "thinking": t} for t in fake.pensamentos]
                if "tool_calls" in rodada:
                    pedacos.append({"content": "", "tool_calls": rodada["tool_calls"]})
                pedacos += [{"content": r} for r in rodada.get("respostas", [])]
                try:
                    for p in pedacos:
                        time.sleep(fake.atraso)
                        linha = {"message": dict(p, role="assistant"), "done": False}
                        self.wfile.write((json.dumps(linha) + "\n").encode())
                        self.wfile.flush()
                    if fake.linha_quebrada or rodada.get("quebrada"):
                        self.wfile.write(b"isto nao e json\n")
                    final = dict(FINAL, message={"role": "assistant", "content": ""}, done=True)
                    self.wfile.write((json.dumps(final) + "\n").encode())
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.servidor = ThreadingHTTPServer(("127.0.0.1", 0), Atendente)
        self.url = f"http://127.0.0.1:{self.servidor.server_port}"
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *args):
        self.servidor.shutdown()
        self.servidor.server_close()
