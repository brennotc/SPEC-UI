# Relatório de falhas do piloto

Preencha a coluna `classification` em `failure_report.csv` com: `test_defect`, `adapter_gap`, `model_defect`, `ambiguity`.
Só `test_defect` e `adapter_gap` autorizam mudar `oracles/` (registre em `oracles/CHANGELOG.md`).

## Taxas por modelo

| modelo | execuções | status | formato ok | contrato ok (sobre formato) | build ok (sobre contrato) | executável | truncadas | recusas |
|---|---|---|---|---|---|---|---|---|
| google:gemini-3.8-flash | 12 | done=12 | 12/12 | 12/12 | 12/12 | 12/12 | 0 | 0 |

## Nota funcional por execução

| execução | status | accuracy_a | accuracy_b |
|---|---|---|---|
| easy_pomodoro-no_spec__text__google__r0__20261009T220520 | done | 1.00 | 0.55 |
| easy_pomodoro-no_spec__multimodal__google__r0__20261009T220752 | done | 1.00 | 0.50 |
| medium_tarefas-no_spec__text__google__r0__20261009T221002 | done | 0.96 | 0.43 |
| medium_tarefas-no_spec__multimodal__google__r0__20261009T221154 | done | 0.92 | 0.68 |
| hard_kanban-no_spec__text__google__r0__20261009T230052 | done | 0.96 | 0.55 |
| hard_kanban-no_spec__multimodal__google__r0__20261009T230251 | done | 1.00 | 0.60 |
| easy_pomodoro-with_spec__text__google__r0__20261009T230445 | done | 1.00 | 0.95 |
| easy_pomodoro-with_spec__multimodal__google__r0__20261010T011013 | done | 1.00 | 0.95 |
| medium_tarefas-with_spec__text__google__r0__20261009T231652 | done | 1.00 | 0.89 |
| medium_tarefas-with_spec__multimodal__google__r0__20261009T231918 | done | 1.00 | 0.96 |
| hard_kanban-with_spec__text__google__r0__20261009T232145 | done | 1.00 | 0.95 |
| hard_kanban-with_spec__multimodal__google__r0__20261009T232421 | done | 1.00 | 0.95 |

## Casos que não deram YES


### easy_pomodoro-no_spec__text__google__r0__20261009T220520
`specui serve --run-id easy_pomodoro-no_spec__text__google__r0__20261009T220520` abre este app no navegador.

- `E-B-01` **PARTIAL**: fundo #E56060 (ΔE ≤ 5) :: fundo=(255, 226, 226) | texto 'Pomodoro' branco :: (130, 24, 26) | ícone do tomate branco :: cor=(30, 41, 57)
- `E-B-02` **PARTIAL**: círculo de 503 × 503 px :: caixa=Box(x=544, y=183, w=352, h=352) | tempo com fonte 128 px | nome do período com fonte 36 px
- `E-B-03` **NO**: borda do círculo #D74747 (ΔE ≤ 5) :: borda=(231, 0, 11) | linha divisória #716C6C (ΔE ≤ 5) :: linhas=[(209, 213, 220), (243, 244, 246)]
- `E-B-04` **PARTIAL**: rodando: todos desabilitados
- `E-B-06` **NO**: parado: aria-label 'Iniciar temporizador' :: Iniciar timer | rodando: aria-label 'Pausar temporizador' :: Pausar timer
- `E-B-09` **PARTIAL**: Foco Total: retângulo de 89 × 40 px :: retângulo=(426.546875, 777, 96, 46) | Foco Total: fundo na cor do modo :: fundo=(249, 250, 251) | Foco Total: fonte do input branca :: cor=(30, 41, 57) | Pausa Curta: retângulo de 89 × 40 px :: retângulo=(655.875, 777, 96, 46) | Pausa Curta: fundo na cor do modo :: fundo=(249, 250, 251) | Pausa Curta: fonte do input branca :: cor=(30, 41, 57) | Pausa Longa: retângulo de 89 × 40 px :: retângulo=(885.203125, 777, 96, 46) | Pausa Longa: fundo na cor do modo :: fundo=(249, 250, 251) | Pausa Longa: fonte do input branca :: cor=(30, 41, 57) | Foco Total alinhado à logo (±24 px) :: x=448.9375 logo=24
- `E-B-10` **PARTIAL**: rótulo na cor do modo (ΔE ≤ 5) :: cor=(54, 65, 83)
- `E-B-11` **PARTIAL**: o som foi tocado ao zerar :: plays=0

### easy_pomodoro-no_spec__multimodal__google__r0__20261009T220752
`specui serve --run-id easy_pomodoro-no_spec__multimodal__google__r0__20261009T220752` abre este app no navegador.

- `E-B-01` **PARTIAL**: altura de 70 px :: altura=61
- `E-B-02` **PARTIAL**: círculo de 503 × 503 px :: caixa=Box(x=530, y=256, w=380, h=380) | tempo com fonte 128 px | nome do período com fonte 36 px
- `E-B-03` **PARTIAL**: linha divisória #716C6C (ΔE ≤ 5) :: linhas=[(209, 213, 220)]
- `E-B-04` **PARTIAL**: rodando: todos desabilitados
- `E-B-05` **PARTIAL**: todos são type=number
- `E-B-06` **NO**: parado: aria-label 'Iniciar temporizador' :: Iniciar Pomodoro | rodando: aria-label 'Pausar temporizador' :: Pausar Pomodoro
- `E-B-07` **NO**: input 1 tem <label> associado :: labels=0 | input 2 tem <label> associado :: labels=0 | input 3 tem <label> associado :: labels=0
- `E-B-09` **PARTIAL**: Foco Total: retângulo de 89 × 40 px :: retângulo=(236.984375, 852, 72, 28) | Pausa Curta: retângulo de 89 × 40 px :: retângulo=(727.90625, 852, 72, 28) | Pausa Curta: fundo na cor do modo :: fundo=(77, 128, 85) | Pausa Longa: retângulo de 89 × 40 px :: retângulo=(1224, 852, 72, 28) | Foco Total alinhado à logo (±24 px) :: x=144 logo=24
- `E-B-11` **PARTIAL**: o som foi tocado ao zerar :: plays=0

### medium_tarefas-no_spec__text__google__r0__20261009T221002
`specui serve --run-id medium_tarefas-no_spec__text__google__r0__20261009T221002` abre este app no navegador.

- `M-A-06` **PARTIAL**: badge MÉDIO com fundo yellow :: fundo=(254, 154, 0)
- `M-B-01` **NO**: altura de 70 px :: Box(x=0, y=0, w=1440, h=64) | fundo #60C2E5 (ΔE ≤ 5) :: fundo=(21, 93, 252) | texto do título preto :: cor=(255, 255, 255) | ícone preto :: cor=(255, 255, 255)
- `M-B-02` **NO**: filtro de data: 170 × 55 px :: Box(x=67.328125, y=80.5, w=128, h=34) | filtro de data: fundo cinza #D5D0D0 :: (24, 24, 27) | filtro de data: texto preto :: (255, 255, 255) | filtro de prioridade: 170 × 55 px :: Box(x=298.140625, y=80, w=97, h=35) | filtro de prioridade: fundo cinza #D5D0D0 :: (24, 24, 27) | filtro de prioridade: texto preto :: (255, 255, 255) | rótulo 'data\s*:' a 32 px | rótulo 'prioridade\s*:' a 32 px | o select de filtro tem 'Selecione' como padrão
- `M-B-03` **PARTIAL**: badge URGENTE: 146 × 36 px :: Box(x=97, y=432, w=96, h=28) | badge URGENTE: fundo do mapeamento (ΔE ≤ 5) :: (231, 0, 11) | badge MÉDIO: 146 × 36 px :: Box(x=97, y=506, w=96, h=28) | badge MÉDIO: fundo do mapeamento (ΔE ≤ 5) :: (254, 154, 0) | badge RELAXA: 146 × 36 px :: Box(x=97, y=580, w=96, h=28) | badge RELAXA: fundo do mapeamento (ΔE ≤ 5) :: (0, 153, 102)
- `M-B-04` **PARTIAL**: título do dia na cor do header (ΔE ≤ 5) :: (80, 162, 255) | título do dia a 32 px | linha branca de 1327 px (grupo) :: larguras=[1440] | linha branca de 1247 px (tarefa) :: larguras=[1440]
- `M-B-06` **NO**: lápis na cor do header (ΔE ≤ 5) :: (159, 159, 169) | lixeira em vermelho (ΔE ≤ 5) :: (159, 159, 169)
- `M-B-07` **PARTIAL**: mudar a prioridade para RELAXA | a badge mostra RELAXA
- `M-B-08` **PARTIAL**: data vazia | prioridade volta ao item neutro :: índice=1
- `M-B-09` **NO**: URGENTE, MÉDIO, RELAXA de cima para baixo :: ['Ordem relaxa', 'Ordem medio', 'Ordem urgente']
- `M-B-10` **PARTIAL**: o filtro tem o item neutro 'Selecione' | voltar para 'Selecione' :: ValueError: o controle não aceitou o valor | sem filtro de prioridade a lista completa volta | apagar a data restaura a lista
- `M-B-11` **PARTIAL**: todo input/select tem label ou aria-label :: sem nome=3
- `M-B-13` **PARTIAL**: controles do tipo 'checkbox' mostram anel de foco :: [False, False, False, False, False, False, False, False, False, False, False]
- `M-B-14` **PARTIAL**: campo de data cinza #D5D0D0 :: (24, 24, 27) | campo de prioridade cinza #D5D0D0 :: (24, 24, 27) | campo de descrição cinza #D5D0D0 :: (24, 24, 27) | o + usa o azul do header :: (255, 255, 255) | há uma linha cinza acima do rodapé :: [(745, (39, 39, 42)), (827, (255, 255, 255))]

### medium_tarefas-no_spec__multimodal__google__r0__20261009T221154
`specui serve --run-id medium_tarefas-no_spec__multimodal__google__r0__20261009T221154` abre este app no navegador.

- `M-A-12` **NO**: há uma linha clara logo acima do rodapé :: linhas=[(837, (113, 113, 123))]
- `M-B-01` **PARTIAL**: altura de 70 px :: Box(x=0, y=0, w=1440, h=56) | fundo #60C2E5 (ΔE ≤ 5) :: fundo=(82, 178, 229)
- `M-B-02` **PARTIAL**: filtro de data: 170 × 55 px :: Box(x=68.953125, y=72.5, w=112, h=28) | filtro de data: fundo cinza #D5D0D0 :: (200, 206, 214) | filtro de prioridade: 170 × 55 px :: Box(x=298.5, y=72, w=128, h=29) | filtro de prioridade: fundo cinza #D5D0D0 :: (200, 206, 214) | rótulo 'data\s*:' a 32 px | rótulo 'prioridade\s*:' a 32 px
- `M-B-03` **PARTIAL**: badge URGENTE: 146 × 36 px :: Box(x=20, y=317, w=84, h=24) | badge MÉDIO: 146 × 36 px :: Box(x=20, y=366, w=84, h=24) | badge RELAXA: 146 × 36 px :: Box(x=20, y=415, w=84, h=24)
- `M-B-04` **PARTIAL**: título do dia na cor do header (ΔE ≤ 5) :: (82, 178, 229) | título do dia a 32 px | linha branca de 1327 px (grupo) :: larguras=[] | linha branca de 1247 px (tarefa) :: larguras=[]
- `M-B-05` **PARTIAL**: a opacidade fica reduzida :: 1.0 -> 1.0
- `M-B-09` **NO**: URGENTE, MÉDIO, RELAXA de cima para baixo :: ['Ordem relaxa', 'Ordem medio', 'Ordem urgente']
- `M-B-11` **PARTIAL**: todo input/select tem label ou aria-label :: sem nome=5
- `M-B-14` **PARTIAL**: campo de data cinza #D5D0D0 :: (200, 206, 214) | campo de prioridade cinza #D5D0D0 :: (200, 206, 214) | campo de descrição cinza #D5D0D0 :: (200, 206, 214) | o + usa o azul do header :: (82, 178, 229)

### hard_kanban-no_spec__text__google__r0__20261009T230052
`specui serve --run-id hard_kanban-no_spec__text__google__r0__20261009T230052` abre este app no navegador.

- `H-A-03` **PARTIAL**: 'Feito': corpo da mesma família de cor :: (250, 245, 255)
- `H-B-01` **PARTIAL**: fundo #105610 (ΔE ≤ 5) :: (0, 122, 85) | fundo geral #D7CFCF (ΔE ≤ 5) :: [(226, 232, 240), (226, 232, 240), (226, 232, 240), (255, 255, 255)]
- `H-B-02` **NO**: 'Para Fazer': cabeçalho com a cor forte do mapeamento :: (21, 93, 252) | 'Para Fazer': largura ≥ 340 px :: 328 | 'Para Fazer': corpo com a cor fraca do mapeamento :: (239, 246, 255) | 'Em Progresso': cabeçalho com a cor forte do mapeamento :: (245, 74, 0) | 'Em Progresso': largura ≥ 340 px :: 328 | 'Em Progresso': corpo com a cor fraca do mapeamento :: (255, 248, 237) | 'Feito': cabeçalho com a cor forte do mapeamento :: (152, 16, 250) | 'Feito': largura ≥ 340 px :: 328 | 'Feito': corpo com a cor fraca do mapeamento :: (250, 245, 255) | 'Aprovado': cabeçalho com a cor forte do mapeamento :: (0, 153, 102) | 'Aprovado': largura ≥ 340 px :: 328 | 'Aprovado': corpo com a cor fraca do mapeamento :: (236, 252, 245)
- `H-B-03` **PARTIAL**: opacidade de 70 % :: 0.75 | cor da borda #656060 (ΔE ≤ 8) :: ['rgba(212, 212, 212, 1.000)', 'dashed'] | o + é cinza :: (0, 0, 0)
- `H-B-04` **PARTIAL**: 274 × 191 px :: Box(x=41, y=604, w=296, h=296) | fundo #D7CFCF (ΔE ≤ 5) :: (250, 249, 246) | descrição a 24 px | lixeira #B50000 (ΔE ≤ 5) :: (236, 0, 63)
- `H-B-05` **NO**: aria-label do input 'Descrição da nova tarefa' :: None | check na cor verde do header (ΔE ≤ 5) :: (0, 153, 102) | X em #B50000 (ΔE ≤ 5) :: (236, 0, 63)
- `H-B-06` **PARTIAL**: o card de criação volta a 70 % de opacidade :: 0.758236
- `H-B-08` **PARTIAL**: há um <article> por card :: 0

### hard_kanban-no_spec__multimodal__google__r0__20261009T230251
`specui serve --run-id hard_kanban-no_spec__multimodal__google__r0__20261009T230251` abre este app no navegador.

- `H-B-01` **PARTIAL**: altura de 70 px :: Box(x=0, y=0, w=1440, h=52)
- `H-B-02` **PARTIAL**: 'Para Fazer': largura ≥ 340 px :: 336 | 'Em Progresso': largura ≥ 340 px :: 336 | 'Feito': largura ≥ 340 px :: 336 | 'Aprovado': cabeçalho com a cor forte do mapeamento :: (27, 103, 26) | 'Aprovado': largura ≥ 340 px :: 336
- `H-B-03` **PARTIAL**: opacidade de 70 % :: 1.0 | o + é cinza :: None
- `H-B-04` **PARTIAL**: 274 × 191 px :: Box(x=38, y=442, w=308, h=140) | descrição a 24 px
- `H-B-05` **NO**: aria-label do input 'Descrição da nova tarefa' :: None | check na cor verde do header (ΔE ≤ 5) :: (0, 153, 102) | X em #B50000 (ΔE ≤ 5) :: (236, 0, 63)
- `H-B-06` **PARTIAL**: o card de criação volta a 70 % de opacidade :: 1.0
- `H-B-09` **PARTIAL**: + com nome acessível

### easy_pomodoro-with_spec__text__google__r0__20261009T230445
`specui serve --run-id easy_pomodoro-with_spec__text__google__r0__20261009T230445` abre este app no navegador.

- `E-B-09` **PARTIAL**: Foco Total alinhado à logo (±24 px) :: x=112 logo=32

### easy_pomodoro-with_spec__multimodal__google__r0__20261010T011013
`specui serve --run-id easy_pomodoro-with_spec__multimodal__google__r0__20261010T011013` abre este app no navegador.

- `E-B-09` **PARTIAL**: Foco Total alinhado à logo (±24 px) :: x=128 logo=48

### medium_tarefas-with_spec__text__google__r0__20261009T231652
`specui serve --run-id medium_tarefas-with_spec__text__google__r0__20261009T231652` abre este app no navegador.

- `M-B-01` **PARTIAL**: ícone preto :: cor=(255, 255, 255)
- `M-B-08` **PARTIAL**: data vazia
- `M-B-14` **PARTIAL**: o + usa o azul do header :: (255, 255, 255)

### medium_tarefas-with_spec__multimodal__google__r0__20261009T231918
`specui serve --run-id medium_tarefas-with_spec__multimodal__google__r0__20261009T231918` abre este app no navegador.

- `M-B-01` **PARTIAL**: ícone preto :: cor=(255, 255, 255)

### hard_kanban-with_spec__text__google__r0__20261009T232145
`specui serve --run-id hard_kanban-with_spec__text__google__r0__20261009T232145` abre este app no navegador.

- `H-B-03` **PARTIAL**: o + é cinza :: (26, 26, 26)

### hard_kanban-with_spec__multimodal__google__r0__20261009T232421
`specui serve --run-id hard_kanban-with_spec__multimodal__google__r0__20261009T232421` abre este app no navegador.

- `H-B-03` **PARTIAL**: o + é cinza :: (0, 0, 0)
