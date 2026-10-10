# Changelog dos oráculos

Toda mudança em `oracles/` depois do congelamento exige nova versão (tag `oracle-vN`, `VERSION` igual à tag)
e reexecução das células afetadas. Só `test_defect` e `adapter_gap` do piloto justificam edição (ver README).

## oracle-v1 (rascunho, ainda sem tag)
- Suítes de `easy_pomodoro`, `medium_tarefas` e `hard_kanban`, níveis A (derivado só do `## Prompt`) e B (exigências da spec).
- Decisões pendentes PD-E1..E5, PD-M1..M5, PD-H1..H5 decididas segundo as regras 1/2/3 (`pending.yaml` de cada tarefa).
- Ainda não executadas contra implementações reais: o piloto com os geradores classifica as falhas
  (`test_defect` | `model_defect` | `ambiguity` | `adapter_gap`) e só as duas primeiras categorias editam os testes.

### Correções do piloto 1 (gemini-3.8-flash, 1 repetição, 2026-10-09)
Cada item foi confirmado abrindo o código/app gerado: o app fazia o que o prompt pede e o teste errava.

- **adapter_gap: leitura de cores** (`common/colors.py`, `common/locators.py`, `common/probes.py`, `easy_pomodoro/*`,
  `hard_kanban/level_b.py`; também `specui/harness/js/dom_blocks.js`, usado pela métrica Color do Design2Code). O Tailwind 4
  calcula cores em `oklch`/`oklab`; os leitores só entendiam `rgb()` e devolviam `None` ou o fundo branco do body. Agora o
  navegador converte qualquer cor para sRGB pintando 1 pixel num canvas (`RGBA_JS`, `computed_color`).
- **test_defect: `M-A-05`** (`medium_tarefas/helpers.py::heading_y`): recompilava uma regex já compilada (`ValueError`).
- **test_defect: `M-B-07` e outros** (`common/locators.py::row_actions`, `medium_tarefas/helpers.py::badge_in/checkbox_in`):
  linha ausente virava `AttributeError` em vez de asserção falha.
- **adapter_gap: linha da tarefa** (`common/locators.py::row_of`): o menor ancestral com checkbox podia ser só a metade
  esquerda da linha (badge + checkbox + nome), deixando lápis e lixeira de fora. Agora: o menor ancestral com UM checkbox e
  ao menos um botão que não seja o próprio checkbox (`<button role="checkbox">` existe).
- **adapter_gap: elementos abaixo da área visível** (`hard_kanban/helpers.py::placeholder`, `drag_target`, `bring_into_view`):
  cards grandes empurram o card de criação e os cards arrastados para fora da tela; o clique, a medição e o arrasto caíam
  fora do viewport. Agora o teste rola até o elemento antes de clicar, medir ou arrastar, e o ponto de soltura fica na tela.
- **test_defect: `H-A-06`, `H-B-06`**: caixas medidas antes e depois de rolar a página eram comparadas entre si; agora rola
  primeiro e mede depois.
- **adapter_gap: `H-A-14`**: arrastava o 3º card até o 1º, que não cabem juntos na tela; agora arrasta o 2º sobre o 1º
  (vizinhos). O requisito (reordenar dentro da coluna) é o mesmo.
- **test_defect: `H-A-04`** (regra 2): exigia `opacity` CSS e um "+" em texto, que são o mecanismo da spec (`opacity-70`).
  O prompt só diz "card esmaecido com um ícone de + no centro": o nível A aceita opacidade OU fundo/contorno translúcidos, e
  um "+" em texto, botão ou ícone (svg/img) no centro do card. A opacidade de 70 % continua exigida no nível B (`H-B-03`).

### Classificação do pesquisador (piloto 1)
- `model_defect` (sem mudança no oráculo): `M-A-06` (badge MÉDIO laranja-âmbar, 36°, não é amarelo), `M-A-12` (linha cinza,
  não branca), `H-A-03` no Kanban no_spec texto (corpo de "Feito" quase branco, 250,245,255, não é roxo).
- **PD-C1** (cinza tingido é cinza) e **PD-C2** (margem de ±5° nos limites das faixas de matiz), em `common/colors.py`
  (`GRAY_MAX_CHROMA`, `HUE_TOLERANCE`, `hue_matches`) e nos testes de nível A das três tarefas; registradas em cada `pending.yaml`.
  Efeito no piloto: `H-A-01` (cinza-azulado), `H-A-05/08/10` (vermelho-rosado a 344°) e `H-A-03` no Kanban no_spec
  multimodal (lilás a 249°) passam.

### Protocolo de pontuação (revisão S2, `specui/oracle/protocol.py`)
- **test_defect (protocolo)**: `act` bem-sucedido e `require` que passa deixam de pontuar: viram **passos** (`status="step"`,
  `n_steps` no `CaseOutcome`). Só `ok`/`eventually` pontuam (o *Expected Result* do WebGen-Bench); `act` que falha continua `fail`
  e `require` que falha continua encerrando o caso em NO (`blocked`). Motivo: com ação e pré-condição pontuando, uma feature
  inteiramente quebrada valia 0,5 (PARTIAL) em vez de 0; 63 dos 140 pares da mutação do piloto 1 saíram WEAK por isso.
- `oracle-lint` passa a exigir ao menos um `t.ok`/`t.eventually` por caso (senão o caso daria NO por "sem asserção pontuada").
  Nas três suítes: 0 casos acusados. Nenhum caso foi alterado neste item (as promoções a `require` vêm nos itens seguintes).

### Efeito principal como pré-condição (revisão S2/S3/S4, PD-C3; um item por tarefa)
Sob o protocolo de passos (acima), cada caso abaixo passa a ter o efeito principal como `require` e só o que vem depois como
`ok`. Classe: **test_defect** (o caso dava PARTIAL a um app em que a feature não funciona). Mutação esperada: KILLED (era WEAK).

- **easy_pomodoro**: `E-A-05` "visor mostra 24:57" (era `eventually`) vira `require`; `E-A-08` "o input guarda 30" vira
  `require` e as duas leituras do prompt (30:00 imediato, ou 29:59 após play) viram uma única asserção; `E-A-09` "a contagem
  chegou a decrescer" vira `require` (antes dos invariantes "sempre MM:SS" e "nenhum erro de página", que passam com o timer
  parado). MUT-E1/E2/E4 sobre E-A-05/08/09: WEAK → KILLED.
- **medium_tarefas**: `M-A-04` "o nome da tarefa aparece em uma linha com checkbox" vira `require` (badge e título "Hoje" ficam como
  invariantes); `M-A-09` "existe um contêiner com rolagem vertical própria" vira `require` (página sem rolagem fica como
  invariante); `M-A-10` "a tarefa RELAXA fica oculta" vira `require` ("a URGENTE continua visível" é o invariante); `M-A-11`
  "ao menos uma tarefa de outro dia fica oculta" vira `require` e passa a vir antes de "a filtrada continua visível" e "sem
  filtro as três voltam". Sob um filtro inerte esses casos davam 5/6 e 8/9 (PARTIAL); agora NO. MUT-M1/M2/M3/M5 (M-A-04/09):
  WEAK → KILLED; em M-A-10/11 o KILLED atual vinha da criação de tarefas falhar, e o MUT-M8 (próximo item) passa a exercitar o filtro.
- **hard_kanban**: `H-A-04` "existe um card com contorno dashed na primeira coluna" vira `require` (as três "a coluna X não tem
  card dashed" passavam vacuamente: um app SEM card esmaecido dava 4 passam / 3 falham = PARTIAL; agora NO); `H-A-06` criar os
  dois cards (`need_cards`, em vez de `act` + `_must`) é o efeito principal; `H-A-11` "o card muda para Em Progresso" vira
  `require` ("o card só existe uma vez" passa com o app inerte); `H-A-14` "arrastar B para cima do A reordena" vira `require`
  ("mesma coluna" e "nenhum card se perdeu" passam com o app inerte). MUT-H1/H2/H3 sobre H-A-06/11/14: WEAK → KILLED.
- **Mutação nova MUT-M8 `neutralize_filters`** (`specui/oracle/mutations.py`, alvos M-A-10 e M-A-11): os controles de filtro
  (faixa abaixo do header) deixam de reagir e o formulário do rodapé segue funcionando. MUT-M2/M3 derrubavam `need_tasks` e o
  KILLED vinha da criação de tarefas falhando; o MUT-M8 exercita a filtragem em si.

### Relógio fixo com fonte única (revisão I1)
- **adapter_gap**: `oracles/common/dates.py::TODAY` e `oracles/easy_pomodoro/helpers.py::PAUSE_AT` eram cópias literais de
  10/03/2026 e 10:01; agora derivam de `specui/clock.py` (a mesma fonte do runner, do render e da configuração). Valores
  idênticos; nenhuma mudança de comportamento nas suítes. `RunConfig` recusa qualquer `clock_epoch_iso` diferente do relógio
  fixo, porque a suíte medium cria tarefas para "hoje" a partir dele.

### PD-H6: isenção do matiz do corpo de "Aprovado" (revisão I2)
- **ambiguity / decisão de protocolo** (`hard_kanban/pending.yaml`): H-A-03 já pulava a checagem de matiz do corpo de "Aprovado",
  porque o `#C5CC9E` da spec cai na faixa do amarelo; era conhecimento da spec dentro de um teste "derivado só do prompt" sem
  registro. Agora é PD-H6 (regra 3): no nível A só a luminância nessa coluna; o matiz continua nas outras três. Vale igual para
  no_spec e with_spec. Sem mudança de comportamento.

### mention_patterns (revisão I3)
- **adapter_gap**: `H-13` não casava com a `## Specification` (que diz "Tentativa de Pular Etapas" e "apenas 1 etapa", não "não pode
  pular"); ganhou `pular\s+etapas` e `apenas\s+(?:1|uma)\s+etapa|imediatamente\s+adjacente`. `E-01` trocou o padrão inerte
  `p[áa]gina\s+branca` (não casava com nenhum dos dois textos) por variantes plausíveis em prompts livres. Antes da coleta de
  prompts livres, então sem efeito em dados; muda o hash de `mention_patterns`. Teste novo: a spec cobre 100 % dos requisitos com
  padrão e o prompt cobre 100 % dos de categoria a/c, nas três tarefas.

### Reavaliação do piloto 1 depois das mudanças acima (2026-10-10, `evaluate --groups functional` nos 12 runs do Gemini + `mutate`)
Sem chamada a API; o oráculo que rodou é o hash `d7c7b3be…` (antes `94b727c0…`/`d41f9cdc…`). Baseline em `docs/pilot-1/antes/`.
- **accuracy_a mudou em 1 célula**: medium no_spec multimodal, 0,958 → 0,917 (M-A-12 PARTIAL → NO; já classificado `model_defect`:
  a linha acima do rodapé é cinza, não branca; o 0,5 anterior vinha do `require("existe o rodapé")`, que passou a ser passo).
- **accuracy_b caiu nas 6 células no_spec** (with_spec inalterado), 12 casos PARTIAL → NO, todos já falhas do modelo: easy
  multimodal `E-B-06`, `E-B-07`; easy texto `E-B-03`, `E-B-06`; medium multimodal `M-B-09`; medium texto `M-B-01`, `M-B-02`,
  `M-B-06`, `M-B-09`; hard texto e multimodal `H-B-05` (2). Nenhum caso que era YES mudou; nenhum caso virou NO bloqueado.
- **n_total de A: 48 / 99 / 113 → 25 / 50 / 71** (easy / medium / hard): as ações e pré-condições que deram certo saíram da
  pontuação (viraram passos).
- **Mutação**: 76 KILLED / 63 WEAK / 1 NOT_APPLIED → **136 KILLED / 10 WEAK / 2 NOT_APPLIED / 0 SURVIVED** (148 linhas, 8 delas do
  MUT-M8, todas KILLED). Os 13 pares previstos (MUT-E1/E2/E4, M1/M2/M3/M5, H1/H2/H3 sobre E-A-05/08/09, M-A-04/09, H-A-06/11/14)
  foram de WEAK para KILLED nos 4 runs. Os WEAK que restam são os previstos como PARTIAL legítimo (MUT-M6×M-A-05 ×4, MUT-E6×E-A-01
  ×3, MUT-H4×H-A-03 ×3). Diferença para a previsão (11 WEAK / 1 NOT_APPLIED): em MUT-E6×E-A-01 o run easy no_spec texto teve
  baseline NO na rodada de mutação (NOT_APPLIED) embora o `record.json` e 33 execuções isoladas deem YES: ver `docs/revisoes/`.
- **Correção da diferença acima (mutação refeita depois do ajuste do runner)**: com o runner esperando a mesma sequência do render
  inicial e o baseline detalhado em `sensitivity_baseline.csv`, a mutação deu **136 KILLED / 11 WEAK / 1 NOT_APPLIED / 0 SURVIVED**
  (148 linhas), exatamente a previsão. O único NOT_APPLIED é MUT-H4×H-A-03 no run hard no_spec texto, cujo baseline é PARTIAL
  (`'Feito': corpo da mesma família de cor :: (250, 245, 255)`, `model_defect` já classificado). Os 11 WEAK são os PARTIAL legítimos:
  MUT-E6×E-A-01 ×4, MUT-M6×M-A-05 ×4, MUT-H4×H-A-03 ×3. O baseline NO de E-A-01 da rodada anterior não foi reproduzido em 50
  rodadas com Chromium novo antes da correção nem em 20 depois (`docs/pilot-1/corrida-E-A-01-*.txt`); a confirmação da previsão
  (11 WEAK / 1 NOT_APPLIED) só veio depois do ajuste do runner.
