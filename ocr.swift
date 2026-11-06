// Leitor de texto de páginas de PDF escaneadas, com o reconhecimento de texto do próprio macOS (Vision).
// Uso: chrono-ocr arquivo.pdf 1,2,3  →  JSON: [{"pagina": 1, "texto": "..."}]
// O chrono compila este arquivo sozinho na primeira vez que encontra um PDF escaneado.
import Foundation
import PDFKit
import Vision

let args = CommandLine.arguments
guard args.count >= 3, let documento = PDFDocument(url: URL(fileURLWithPath: args[1])) else { exit(2) }
let paginas = args[2].split(separator: ",").compactMap { Int($0) }
var resultado: [[String: Any]] = []
for numero in paginas where numero >= 1 && numero <= documento.pageCount {
    guard let pagina = documento.page(at: numero - 1) else { continue }
    let caixa = pagina.bounds(for: .mediaBox)
    let imagem = pagina.thumbnail(of: NSSize(width: caixa.width * 2, height: caixa.height * 2), for: .mediaBox)
    guard let cg = imagem.cgImage(forProposedRect: nil, context: nil, hints: nil) else { continue }
    let pedido = VNRecognizeTextRequest()
    pedido.recognitionLevel = .accurate
    pedido.recognitionLanguages = ["pt-BR", "en-US"]
    pedido.usesLanguageCorrection = true
    try? VNImageRequestHandler(cgImage: cg).perform([pedido])
    let linhas = (pedido.results ?? []).compactMap { $0.topCandidates(1).first?.string }
    resultado.append(["pagina": numero, "texto": linhas.joined(separator: "\n")])
}
FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: resultado))
