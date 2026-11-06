# chrono: registro da execução

Decisões, correções e pendências da implementação do plan docs/superpowers/plans/2026-11-02-chrono.md.

- Setup: Ruling: pasta não é repositório git — sem worktree/commits; BASE = cópia de ia.py em .superpowers/sdd/2026-11-02-chrono/BASE-ia.py, revisão final por diff contra ela — custo se errado: sem histórico de commits por tarefa
- Pre-flight: T3 consome linha_detalhes(m, contexto_total, pensou) de T2 — bate; T4 consome interface Exibidor de T3 (fim(metricas, contexto_total, pensou)) — bate; T5 consome cabecalho/ExibidorRico de T4 — bate
- Task 1: complete (tests: python3 -m unittest discover -s tests → 4/4 OK; rich 15.0.0 instalada)
- Task 2: complete (tests: python3 -m unittest discover -s tests → Ran 11 OK)
- Task 2: Ruling: fmt_mil arredonda para baixo (32768 → "32 mil"), senão daria 33 e o teste do plano pede 32 — custo se errado: número 1 mil menor que o real
- Task 3: Ruling: erro no meio da resposta chama exibidor.fim(None, None, None) antes de propagar, para a animação parar — custo se errado: linha em branco extra antes da mensagem de erro
- Task 3: Ruling: estado_ollama devolve None em qualquer ErroIA (não derruba a resposta já mostrada) — custo se errado: linha de detalhes sem o % de contexto
- Task 3: complete (tests: python3 -m unittest discover -s tests → Ran 13 OK)
- Task 4: Ruling: testes comparam linhas sem espaços à direita (a rich completa linhas com espaços) e checam '▎ parágrafo N' — custo se errado: nenhum visível
- Task 4: Ruling: test_cabecalho_largura_40 checa 'imagens' em vez de 'lê imagens', porque em 40 colunas a frase quebra (comportamento desejado) — custo se errado: nenhum
- Task 4: Ruling: blocos separados por uma linha só com a barrinha (o plano não dizia), para os parágrafos não grudarem — custo se errado: uma linha a mais por parágrafo
- Task 4: complete (tests: python3 -m unittest discover -s tests → Ran 20 OK)
- Task 5: Ruling: TerminalFalso lê a tela numa thread contínua — sem isso o readline (libedit) trava esperando a saída esvaziar e o que se digita some (provado em exp4: eco=False vs eco=True) — custo se errado: nenhum no programa, só no teste
- Task 5: Ruling: prompt leva só o código que liga o verde (libedit escreve todos os trechos \001…\002 antes do texto, o que deixava o 'você ›' sem cor); ler_entrada desliga a cor depois do Enter, então o texto digitado também fica verde — custo se errado: texto digitado verde, diferente do mockup
- Task 5: Ruling: escrever o prompt fora do input() foi descartado — o libedit faz '\r' ao apagar a linha toda e escreve por cima do 'você ›' (exp5)
- Task 5: Ruling: dica '/ajuda mostra os comandos · Ctrl+D sai' em cinza abaixo do cabeçalho (estava no ia antigo, o mockup não mostrava) — custo se errado: uma linha a mais
- Task 5: Ruling: /modelo NOME recarrega o modelo com a animação e reimprime o cabeçalho — custo se errado: alguns segundos de espera ao trocar
- Task 5: complete (tests: python3 -m unittest discover -s tests → Ran 26 OK)
- Task 6: Ruling: no teste real a rich punha uma linha vazia antes de listas e centralizava o título '#'; Barra pula linhas vazias iniciais e ganhou separar=; Formatado/Titulo deixam títulos à esquerda — testes test_lista_sem_linha_vazia_no_comeco e test_titulo_alinhado_a_esquerda RED→GREEN — custo se errado: nenhum
- Task 6: dados movidos ~/.ia → ~/.chrono (3 conversas), ~/.local/bin/ia removido, ~/.local/bin/chrono → link para chrono.py; teste real com qwen3.5:9b: detalhes, Ctrl+C, pensou, saída 0
- Task 6: complete (tests: python3 -m unittest discover -s tests → Ran 28 OK)
- Final review: revisor separado (opus), veredito 'With fixes'
- Final: fixed texto repetido quando o último bloco é maior que a tela (_parar esvazia a parte ao vivo antes do stop) — test_bloco_maior_que_a_tela_aparece_uma_vez RED→GREEN, suite 35/35
- Final: fixed bloco em andamento congelado com '...' (Cauda mostra as últimas linhas) — test_cauda_mostra_as_ultimas_linhas e test_ctrl_c_no_meio_de_bloco_maior_que_a_tela RED→GREEN, suite 35/35
- Final: fixed Ctrl+C durante /modelo fechava o chat — test_ctrl_c_ao_trocar_modelo_volta_ao_anterior RED→GREEN, suite 35/35
- Final: Ruling: achado 10 (modelo fica trocado quando falha ao carregar) subiu de Minor para Important — prende o chat num modelo que não responde; mesma correção do Ctrl+C no /modelo — fixed test_modelo_que_falha_ao_carregar_nao_troca RED→GREEN — custo se errado: nenhum
- Final: Ruling: 'erro de imagem se repete para sempre' (deixado de lado pelo revisor por ser bug antigo) virou Important — o chat fica inutilizável até reiniciar; a imagem agora é descartada com aviso — fixed test_imagem_com_erro_nao_trava_o_chat RED→GREEN — custo se errado: quem queria trocar de modelo e reenviar a imagem precisa anexá-la de novo
- Final: Ruling: eco do teclado desligado enquanto a parte ao vivo está na tela (era o minor 6) — era a causa da linha repetida no Ctrl+C no meio de bloco grande — custo se errado: o que se digita durante uma resposta só aparece no próximo 'você ›'
- Final: Ruling: _transmitir para o exibidor em qualquer exceção e _parar pode ser chamado duas vezes (era o minor 5) — necessário porque o exibidor agora desliga o eco — fixed test_erro_inesperado_para_o_exibidor RED→GREEN — custo se errado: nenhum
- Final: minor (corrigido depois): bloco de código perde a linha de margem de cima (Barra pula linhas em branco com fundo colorido)
- Final: minor (corrigido depois): listas com linha em branco entre itens: parágrafo de continuação recuado vira bloco de código ou perde o recuo
- Final: minor (corrigido depois): nome de modelo sem etiqueta (llama3.2 vs llama3.2:latest) não casa em /api/ps — cabeçalho sem memória real e detalhes sem %
- Final: minor (corrigido depois): arquivo com nome fora do padrão em conversas/ quebra o chrono -c (ValueError)
- Final: minor (corrigido depois): chat com saída redirecionada (chrono | tee log) grava um código de cor depois de cada prompt
- Final: minor (corrigido depois): links [texto](url) viram link clicável (OSC 8) e a URL some em terminais que não suportam
- Final: Ruling: conexão que cai entre pedaços parece resposta terminada — fica; com o Ollama local é raro — custo se errado: resposta parcial salva sem aviso
- Final: Ruling: traceback numa linha inválida do Ollama — fica (o Ollama não manda isso); cursor e eco agora voltam ao normal — custo se errado: mensagem técnica em inglês
- Final: Ruling: % de contexto depois da 1ª pergunta — fica; a API real mostrou prompt_eval_count contando também os tokens em cache — custo se errado: % um pouco menor que o real
- Final: Ruling: espaços à direita nas linhas, largura dos símbolos ⏱ ⚡ ▤ — ficam; invisíveis no Terminal do app — custo se errado: alinhamento torto em outro terminal
- Final: Ruling: chat com saída redirecionada desenha caixas no arquivo; shebang depende do python3 do PATH; Ctrl+C ao abrir sai com 130; ~~~ não reconhecido; 'continuação de <agora>' depois de /modelo — ficam, casos raros ou cosméticos
- Final: Ruling: texto 'carregando o modelo…' aparece mesmo com o modelo já carregado — fica, é o texto do desenho; sugestão do revisor levada ao Lucas

## Detalhes menores corrigidos depois (a pedido do Lucas)

- Bloco de código mantém a margem de cima: Barra só pula linhas vazias sem fundo colorido — test_bloco_de_codigo_mantem_margem_de_cima RED→GREEN
- Continuação recuada de item de lista fica no mesmo bloco — test_continuacao_de_item_de_lista_fica_no_bloco RED→GREEN
- Ruling: separar_blocos só fecha um bloco quando a linha seguinte começa a chegar (é preciso saber se ela vem recuada); o teste antigo que esperava separar_blocos("a\n\n") == (["a"], "") mudou — custo se errado: o parágrafo é formatado um pedaço de resposta mais tarde
- Nome de modelo sem etiqueta casa com ":latest" (mesmo_modelo) — test_nome_de_modelo_sem_etiqueta RED→GREEN
- Conversa com nome fora do padrão usa a data de modificação no cabeçalho — test_conversa_com_nome_fora_do_padrao RED→GREEN
- Código que desliga a cor só é escrito quando a saída é a tela — test_prompt_nao_suja_saida_redirecionada RED→GREEN
- Links mostram o endereço entre parênteses (hyperlinks=False) — test_link_mostra_o_endereco RED→GREEN
- Suíte: 41/41 em duas rodadas; conferido no Terminal do app com o modelo real
