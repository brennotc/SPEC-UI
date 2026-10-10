# Piloto 1: evidência curada

Gerador: `google:gemini-3.8-flash` (1 repetição por célula; 12 células = 3 tarefas × 2 fontes × 2 modalidades).
Navegador: Chromium 151.0.7922.34 (Playwright 1.62.0). Oráculo: tag `oracle-v1`, hash do conteúdo
`d7c7b3be3ac2939b…`. **Estes dados são do piloto: não entram na análise** (que lê só `results/` da execução principal).

## O que há aqui

| caminho | conteúdo |
|---|---|
| `runs/<run_id>/` | por run: `record.json` (reavaliado com o oráculo final), `screenshot.png`, `response.raw.txt` (a resposta do modelo, de onde sai o código gerado) |
| `failure_report.{md,csv}` | os casos que não deram YES, com as asserções que falharam, para classificar (`test_defect`, `adapter_gap`, `model_defect`, `ambiguity`) |
| `sensitivity.csv` | mutação (remover elemento, bloquear clique, congelar timer...) sobre os apps que deram YES: KILLED / WEAK / SURVIVED / NOT_APPLIED |
| `sensitivity_baseline.csv` | o que cada caso-alvo fez no app intacto (outcome, bloqueio, asserções que falharam): explica todo NOT_APPLIED |
| `manifest.jsonl` | tentativas por célula (inclui os `api_error` refeitos), sem as linhas do gerador simulado |
| `antes/` | baseline ANTES do protocolo de passos (relatórios e os 12 `record.json` com o hash antigo `94b727c0…`; um deles, `d41f9cdc…`) |
| `corrida-E-A-01-*.txt` | reprodução da corrida de E-A-01 na mutação (Chromium novo por rodada): 20 + 30 antes da correção do runner (50/50 YES, não reproduziu) e 20 depois (20/20 YES) |

Fora do snapshot, de propósito: `dist/` (≈ 6,6 MB por run), `generated/` (está em `response.raw.txt`), `css_snapshot`, `axe`, `dom_blocks`,
`build.*`, `prompt.*` (deriváveis das tarefas) e o run do gerador simulado. Regenerar: `python scripts/snapshot_pilot.py`.

## Nota funcional por célula, antes → depois do protocolo de passos

`accuracy_a` é a métrica primária (nível A); `accuracy_b`, diagnóstica (exigências da spec). Antes: oráculo `94b727c0…`
(ações e pré-condições pontuavam). Depois: `oracle-v1` (só o resultado esperado pontua; o efeito principal é pré-condição). O `with_spec`
não mudou; no `no_spec`, 12 casos que eram PARTIAL (0,5 vindo de um passo que passou) viraram NO (falhas do modelo já classificadas).

| célula | accuracy_a | accuracy_b | n_total A | n_total B |
|---|---|---|---|---|
| easy/no_spec · multimodal | 1,000 → 1,000 | 0,591 → 0,500 | 48 → 25 | 62 → 43 |
| easy/no_spec · text | 1,000 → 1,000 | 0,636 → 0,545 | 48 → 25 | 62 → 43 |
| easy/with_spec · multimodal | 1,000 → 1,000 | 0,955 → 0,955 | 48 → 25 | 62 → 43 |
| easy/with_spec · text | 1,000 → 1,000 | 0,955 → 0,955 | 48 → 25 | 62 → 43 |
| medium/no_spec · multimodal | 0,958 → 0,917 | 0,714 → 0,679 | 99 → 50 | 97 → 63 |
| medium/no_spec · text | 0,958 → 0,958 | 0,571 → 0,429 | 99 → 50 | 98 → 65 |
| medium/with_spec · multimodal | 1,000 → 1,000 | 0,964 → 0,964 | 99 → 50 | 97 → 63 |
| medium/with_spec · text | 1,000 → 1,000 | 0,893 → 0,893 | 99 → 50 | 98 → 64 |
| hard/no_spec · multimodal | 1,000 → 1,000 | 0,650 → 0,600 | 113 → 71 | 72 → 47 |
| hard/no_spec · text | 0,964 → 0,964 | 0,600 → 0,550 | 113 → 71 | 72 → 47 |
| hard/with_spec · multimodal | 1,000 → 1,000 | 0,950 → 0,950 | 113 → 71 | 72 → 47 |
| hard/with_spec · text | 1,000 → 1,000 | 0,950 → 0,950 | 113 → 71 | 72 → 47 |

## Mutação

Antes: {'WEAK': 63, 'KILLED': 76, 'NOT_APPLIED': 1} (140 linhas). Depois: {'KILLED': 136, 'WEAK': 11, 'NOT_APPLIED': 1} (148 linhas, 8 delas do MUT-M8). Nenhum caso sobreviveu
a uma mutação-alvo. Os WEAK que restam são PARTIAL legítimos de casos com mais de um requisito independente (MUT-E6×E-A-01,
MUT-M6×M-A-05, MUT-H4×H-A-03). O único NOT_APPLIED é MUT-H4×H-A-03 no run hard no_spec texto, cujo baseline é PARTIAL (`model_defect`).

Decisões e correções do oráculo: `oracles/CHANGELOG.md`.

## Campos dos records que não refletem o código atual

Os 12 `runs/*/record.json` foram gerados em 2026-10-09/10 com o código de `b820545` (árvore suja, antes do refactor ser commitado) e
reavaliados depois com `specui evaluate --groups functional` (reavaliação só do grupo funcional: o estágio regrava `functional`, os campos
`oracle_*` e as versões do Playwright/Chromium; os demais campos continuam os da geração). Por isso:

- `repo_commit = b820545+dirty` é o commit da geração, não o da reavaliação nem o atual.
- `config_sha256` (`6822b0bd…`) foi calculado pela função antiga, que incluía os caminhos da máquina; não bate com o hash que o código atual
  calcula para a mesma configuração (`config_sha256` atual exclui `repo_root`, `workspace_dir`, `model_cache_dir`, `results_dir`,
  `benchmarks_dir`, `references_dir`, `oracles_dir` e `scaffold_dir`).
- `finish_reason` é `null` (o campo existe a partir do commit `fac1b50`).
- `embeddings.dinov2_model` e `embeddings.clip_model` têm só o nome do modelo, sem `@<sha do snapshot>` (a partir de `27cef6c`).
- `accuracy_b`/`n_total` dos records em `antes/` usam o oráculo `94b727c0…` (anterior ao protocolo de passos).
- Em `results/pilot/runs/` (fora do git) havia 4 pastas sem `record.json` (execuções interrompidas, só com `prompt.system.txt` e
  `prompt.user.txt`); foram apagadas em 2026-10-10. Os `manifest.jsonl` (aqui e em `results/pilot/`) continuam listando as tentativas que
  não geraram record.
- `failure_report.csv`: a coluna `classification` está preenchida só nas 3 linhas de nível A (`model_defect`, copiadas de
  `oracles/CHANGELOG.md`); as 59 linhas de nível B não têm classe por caso.
