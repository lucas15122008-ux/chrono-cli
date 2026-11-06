# chrono com ferramentas: registro da execução

Decisões, correções e pendências da implementação do plano docs/superpowers/plans/2026-11-02-chrono-ferramentas.md.

- Setup: Ruling: pasta não é repositório git — BASE = cópia de chrono.py e tests/ em .superpowers/sdd/2026-11-02-chrono-ferramentas/BASE; revisão final por diff — custo se errado: sem histórico por tarefa
- Pre-flight: T3 consome definicoes(alterar)/executar(nome, argumentos, confirmar, base) de T1–T2 — bate; T4 consome acao(resumo, alterou)/perguntar(pergunta, detalhe) de T3 — bate
- Task 1: Ruling: CASA e LIXEIRA viraram constantes do módulo (os testes trocam por pastas temporárias) em vez do parâmetro casa= do plano — custo se errado: nenhum
- Task 1: Ruling: listar_pasta ignora itens ocultos (começam com ponto) e buscar_texto pula pastas ocultas e arquivos > 2 MB — custo se errado: o modelo não vê .env, .git etc.
- Task 1: Ruling: ver_imagem reduz fotos heic/tiff para no máximo 1600 px ao converter — custo se errado: detalhe fino perdido em fotos grandes
- Task 1: complete (tests: python3 -m unittest discover -s tests → Ran 65 OK)
- Task 2: Ruling: test_escrever_em_pasta_que_nao_existe, test_mover_nao_sobrescreve e test_lixeira_recusa_pasta_do_usuario passavam antes da hora (ferramenta inexistente também dá 'erro:'); passaram a conferir a mensagem exata e falharam antes da implementação
- Task 2: Ruling: mandar_para_lixeira recusa a pasta do usuário, a raiz do disco e a própria Lixeira — custo se errado: nenhum
- Task 2: Ruling: mover e escrever_arquivo exigem que a pasta de destino exista (o modelo usa criar_pasta antes) — custo se errado: uma rodada a mais de ferramenta
- Task 2: complete (tests: python3 -m unittest discover -s tests → Ran 79 OK)
- Task 3: Ruling: test_ferramentas_desligadas e test_resposta_n_recusa passavam antes da implementação (nada ligado ainda); viraram proteção depois dela
- Task 3: Ruling: a resposta final da pergunta é o texto da última rodada; texto de rodadas anteriores aparece na tela separado por linha em branco — custo se errado: o histórico guarda só o texto final como resposta
- Task 3: Ruling: erro em qualquer rodada desfaz a pergunta inteira no histórico (mensagens da pergunta e das ferramentas) — custo se errado: alterações já confirmadas não ficam registradas na conversa
- Task 3: complete (tests: python3 -m unittest discover -s tests -v → Ran 90 tests in 19.813s OK, verbose.log)
- Ambiente: Mac em repouso (bateria 45%, DarkWake de ~21 s a cada ~15 min) — rodadas de 921 s e 701 s falharam porque o repouso congelou testes no meio (sono de 702 s = teste de 701,5 s); não é defeito do código. Execução pausada antes da Task 4.
- Task 4: Ruling: linhas ◆ (alteração feita) em lilás #AFA9EC e ◇ em cinza; depois de uma ação a animação vira 'pensando…' — custo se errado: só cor/texto
- Task 4: Ruling: a prévia do arquivo aparece em cinza com barrinha cinza, acima da pergunta em âmbar — custo se errado: só visual
- Task 4: Ruling: o teste de eco procurava 'você › depois' a partir de depois do 'você ›' já encontrado; passou a procurar ' depois' (tela capturada mostra o fluxo certo)
- Task 4: complete (tests: caffeinate -i python3 -m unittest discover -s tests → Ran 97 OK)
- Task 5: Ruling: teste real mostrou que o modelo não sabia a pasta atual e pedia caminhos em vez de usar ferramentas (spec não previa); com ferramentas ligadas, o pedido leva CONTEXTO_FERRAMENTAS no prompt de sistema (pasta atual, usar ferramentas sozinho, confirmação é automática) — só no pedido, não no histórico — test_modelo_sabe_a_pasta_atual RED→GREEN — custo se errado: ~90 tokens a mais por pedido
- Task 5: Ruling: texto que anuncia a ação ('Vou ver a pasta.') é impresso antes da linha ◇/◆ — test_acao_vem_depois_do_texto_que_a_anuncia RED→GREEN — custo se errado: nenhum
- Task 5: teste real com qwen3.5:9b numa casa temporária: listar, ler, criar com 's' (arquivo criado), lixeira com 'n' (nada movido), Documentos→Documents; nada fora da casa temporária mudou
- Task 5: complete (tests: caffeinate -i python3 -m unittest discover -s tests ×3 → Ran 100 tests OK nas três)
- Final review: revisor separado (opus), veredito 'With fixes'
- Final: fixed '..' no caminho esvaziava pasta numa Lixeira de nome oculto — resolver_caminho resolve . e .. de verdade, travas comparam caminhos resolvidos — test_lixeira_com_ponto_ponto, test_lixeira_ponto_ponto_ate_a_casa_e_recusado, test_resolver_tira_ponto_ponto RED→GREEN, suite 118/118
- Final: fixed digitação adiantada respondia a confirmação — tcflush antes da pergunta — test_digitacao_adiantada_nao_confirma RED→GREEN, suite 118/118
- Final: fixed leitura de arquivo enorme/especial travava ou enchia a memória — só arquivos comuns, leitura limitada a 80 KB, imagens > 5 MB reduzidas — test_ler_arquivo_grande_le_so_o_comeco, test_arquivo_especial_nao_trava, test_ver_imagem_grande_e_reduzida RED→GREEN, suite 118/118
- Final: fixed erro inesperado numa ferramenta derrubava o chat — executar pega qualquer exceção; sips com tempo esgotado vira erro — test_erro_inesperado_vira_resultado, test_sips_demorado_vira_erro RED→GREEN, suite 118/118
- Final: Ruling: achado 5 ('t' aprovava substituir arquivo) tratado como Important — substituir pergunta sempre, mesmo depois de 't', cumprindo o 'avisa em destaque' do desenho — test_substituir_sempre_pergunta, test_confirmador_t_nao_pula_substituir RED→GREEN — custo se errado: uma pergunta a mais por arquivo substituído num lote
- Final: Ruling: achado 6 (listas sem data; o exemplo do desenho 'o último orçamento' não funcionava) tratado como Important — listar_pasta e buscar_arquivos mostram tamanho e data, listar_pasta aceita ordem='data', buscar_arquivos põe os mais novos primeiro — test_listar_pasta, test_listar_pasta_por_data, test_buscar_arquivos_mostra_data RED→GREEN — custo se errado: respostas das ferramentas um pouco maiores
- Final: Ruling: achado 7 (atalho: pergunta mostrava um arquivo e escrevia em outro) subiu de Minor para Important — aprovação diferente do que acontece — a pergunta mostra o destino e o atalho — test_escrever_por_atalho_mostra_o_destino RED→GREEN — custo se errado: nenhum
- Final: Ruling: achado 8 (códigos de controle de arquivos/modelo na tela) subiu de Minor para Important — podiam disfarçar a pergunta de confirmação — limpar() em ações, prévia, pergunta e texto — test_controles_nao_chegam_na_tela RED→GREEN — custo se errado: nenhum
- Final: Ruling: achado 13 (cp1252/UTF-16; PDF lido como texto) subiu de Minor para Important — exportações do ERP do Lucas (Windows) sairiam com acentos quebrados — decodifica UTF-8, UTF-16 com BOM e cp1252; recusa PDF/Excel/Word pela extensão — test_ler_windows_cp1252, test_ler_utf16, test_formato_que_nao_le RED→GREEN — custo se errado: arquivo latin-1 raro lido como cp1252
- Final: Ruling: CASA passou a ser Path.home().resolve(), porque resolver_caminho agora resolve as pastas — os testes de confirmação no terminal pegaram (casa de teste em /var → /private/var) — custo se errado: nenhum
- Final: Ruling: TestFerramentasNaConversa troca CASA e LIXEIRA por pastas temporárias (do achado 19), para nenhum teste futuro mexer na Lixeira de verdade
- Final: minor (corrigido depois): prévia sem limite por linha (uma linha enorme enche a tela)
- Final: minor (corrigido depois): respostas às confirmações ('s') entram no histórico de digitação (↑ traz 's')
- Final: minor (corrigido depois): /modelo que falha ao carregar religa as ferramentas que estavam desligadas
- Final: minor (corrigido depois): % de contexto soma as saídas de todas as rodadas ao prompt da última (mostra um pouco a mais)
- Final: minor (corrigido depois): renomear só maiúsculas/minúsculas (nota.txt → Nota.txt) diz 'já existe' no APFS
- Final: minor (corrigido depois): animação diz 'carregando o modelo…' enquanto a primeira ferramenta roda
- Final: minor (corrigido depois): erros do sistema chegam ao modelo em inglês ('No such file or directory')
- Final: minor (corrigido depois): erro numa rodada posterior apaga do histórico alterações já confirmadas na mesma pergunta
- Final: minor (corrigido depois): ver_imagem é oferecida a modelos que não leem imagem; sem teclado, as 9 ferramentas são enviadas mesmo sabendo que as de alteração serão recusadas
- Final: minor (corrigido depois): o teste de eco ' depois' não distingue eco do terminal do eco do próprio readline
- Final: Ruling: substituir após 's', ler fora da pasta do usuário, escrever arquivos ocultos após 's', limite de 20 mil caracteres, imagens em base64 no histórico, formato MCP (parameters x inputSchema), Ctrl+C no meio do ciclo, intervalo entre conferir e mover, PDF/Excel e reavaliação do prompt na rodada final — ficam como estão: são o que o desenho define ou têm custo desprezível
- Final: recomendação do revisor levada ao Lucas: testar uma vez a Lixeira de verdade com um arquivo de teste (o 'Colocar de volta' do Finder não funciona para itens movidos assim); busca de texto em ~ inteira pode passar por ~/Library e iCloud

## Detalhes menores corrigidos depois (a pedido do Lucas)

- Prévia corta cada linha em 200 caracteres — test_previa_corta_linha_longa RED→GREEN
- A resposta da confirmação não entra no histórico de digitação (set_auto_history desligado na pergunta) — test_resposta_da_confirmacao_nao_vai_para_o_historico RED→GREEN
- /modelo que falha devolve também o estado das ferramentas — test_modelo_que_falha_nao_religa_ferramentas RED→GREEN
- % de contexto usa a última rodada (prompt + resposta), não a soma das respostas — test_contexto_de_varias_rodadas RED→GREEN
- Renomear trocando só maiúsculas funciona — test_renomear_so_maiusculas RED→GREEN
- Animação mostra "usando as ferramentas…" enquanto uma ferramenta roda (novo método usando_ferramentas no exibidor) — test_animacao_usando_ferramentas, test_animacao_avisa_que_esta_usando_ferramentas RED→GREEN
- Erros do sistema traduzidos (não existe, já existe, disco cheio, em uso...) — test_erro_do_sistema_em_portugues RED→GREEN
- Ruling: erro numa rodada posterior guarda no histórico as rodadas de ferramenta já feitas, mais a nota "(a resposta foi interrompida por um erro)"; sem ferramenta feita, a pergunta inteira sai como antes — test_erro_depois_de_alterar_mantem_o_que_foi_feito RED→GREEN — custo se errado: uma nota a mais no histórico
- ver_imagem só é oferecida a modelos que leem imagem; sem teclado, só as ferramentas de leitura são enviadas (Conversa.pode_alterar) — test_definicoes_sem_imagem, test_ferramentas_oferecidas_conforme_o_que_da_para_fazer RED→GREEN
- Ruling: o teste fraco de eco (" depois") foi trocado por test_eco_desligado_na_animacao_e_ligado_na_pergunta, que lê o eco do terminal em cada momento; ele passou de cara porque o comportamento já estava certo (era um teste melhor, não uma correção)
- Suíte: 130/130 em três rodadas; conferido com o modelo real (orçamento mais recente pela data; renomear só maiúsculas)
