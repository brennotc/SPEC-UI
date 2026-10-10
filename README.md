# SPEC-UI: uma especificação formal ajuda um designer a obter melhor código de front-end?

Framework de avaliação **100 % automática** de front-end gerado por LLMs a partir de (a) um pedido em texto simples e
(b) o mesmo pedido como especificação formal, com ou sem a imagem do design do Figma. Nenhuma nota vem de juiz LLM, de
agente LLM ou de pessoa: só métricas de três artigos revisados por pares.

| Artigo | O que entra aqui |
|---|---|
| **Design2Code** (NAACL 2025) <https://arxiv.org/pdf/2403.03163> | Block-Match, Text, Position, Color por bloco de texto contra o design do Figma (com fusão de blocos vizinhos, apêndice C) e CLIP com o texto removido |
| **Figma2Code** (ICLR 2026) <https://arxiv.org/pdf/2604.13648> | VES (cosseno DINOv2 render × design), MAE e qualidade de código: RUR, APR, FU, BC, STR, AVU, ISR, CCR |
| **WebGen-Bench** (NeurIPS 2025) <https://arxiv.org/pdf/2505.03733> | Nota funcional por casos de teste (Task → Expected Result), YES / PARTIAL / NO, `Accuracy = (Y + 0,5·P) / N`, executada por scripts Playwright **determinísticos** (não por agente) |

Os três artigos estão referenciados pelo arXiv (links acima); os PDFs **não** estão no repositório. Os dois artigos que o desenho
anterior usava (DesignBench e UI-Bench) ficam em [docs/papers/descartados/](docs/papers/descartados/) só como registro. O contexto da decisão de abandonar o juiz LLM está em
[docs/contexto-benchmarks-spec-ui.md](docs/contexto-benchmarks-spec-ui.md).

---

## 1. Pergunta, métrica primária e hipóteses

**Pergunta.** Dar ao modelo uma especificação formal (`## Specification`) em vez do pedido em prosa (`## Prompt`) melhora o
front-end gerado? E isso muda com a complexidade do sistema (easy, medium, hard) e com a presença da imagem do design?

- **Métrica primária:** `accuracy_a`, a nota funcional dos casos de **nível A** (derivados só do `## Prompt`), na análise
  **por intenção de tratar (ITT)**: toda geração tentada entra no denominador; `format_failure`, `contract_failure`,
  `nonexecutable`, `refusal` e `truncated` valem 0.
- **Contraste principal (único):** efeito médio da spec **por modelo** = média, sobre tarefa × modalidade, de
  `média(with_spec) − média(no_spec)`, com IC de 95 % por bootstrap estratificado e teste de permutação estratificado.
  Todas as outras métricas e contrastes são secundários ou exploratórios.

**Hipóteses.**

1. **H1 (efeito da spec):** `with_spec` aumenta `accuracy_a` (ITT) em relação a `no_spec`.
2. **H2 (interação spec × modalidade):** o benefício da spec é menor quando o modelo também recebe a imagem (a imagem já carrega
   parte do que a spec descreve).
3. **H3 (fidelidade × manutenibilidade):** a spec muda a fidelidade visual (Design2Code, VES) e a qualidade de código
   (Figma2Code) em sentidos possivelmente distintos.
4. **H4 (consistência, exige k ≥ 2 modelos):** o efeito da spec segue a mesma tendência **nos modelos testados**. Redação
   padrão: "nos modelos testados"; nunca "independentemente do modelo". Interação não significativa **não** é evidência de
   igualdade. Com um único gerador, H4 não é testada.

## 2. Desenho do experimento

3 tarefas × fonte do pedido (`no_spec` = só `## Prompt`; `with_spec` = só `## Specification`) × modalidade (`text` | `multimodal` =
texto + PNG do Figma) × **modelo gerador** (hoje k = 1: `gemini-3.8-flash`, id fixo; outros modelos Gemini podem ser acrescentados em
`configs/default.yaml`) = 12·k células, cada uma com N
repetições **independentes** (padrão 5). A saída do modelo são arquivos dentro de um **scaffold Angular 20 fixo** (Tailwind 4 +
ng-icons), com um envelope (system prompt) idêntico em todas as células. Por isso não há pareamento por índice de repetição.

| Tarefa | Complexidade | Pasta |
|---|---|---|
| `easy_pomodoro` | easy | [benchmarks/tasks/easy/](benchmarks/tasks/easy/) |
| `medium_tarefas` | medium | [benchmarks/tasks/medium/](benchmarks/tasks/medium/) |
| `hard_kanban` | hard | [benchmarks/tasks/hard/](benchmarks/tasks/hard/) |

**Prompts livres** (`free`, extensão prevista): prompts escritos por participantes para a mesma imagem. O grau de especificação
vira variável contínua, medida no texto (cobertura de requisitos, densidade de restrições).

**Limitações assumidas.**

- Dificuldade e tarefa estão confundidas (uma tarefa por nível).
- A spec é 4–6× mais longa que o prompt: o efeito mistura "mais informação" com "informação formal".
- **Um único gerador (Gemini 3.8 Flash):** os resultados valem para esse modelo. A consistência do efeito entre modelos (H4)
  só pode ser estudada acrescentando outro modelo ao config (k ≥ 2); o fator modelo testa robustez, não compara modelos.
- Uma tentativa por célula (EXEC@1, sem rodada de correção).

## 3. O que NÃO é usado, e por quê

- **Juiz LLM / agente LLM:** a maior crítica ao desenho anterior. Notas de um modelo avaliando outro não são reprodutíveis nem
  auditáveis. O WebGen-Bench original usa um agente; aqui o mesmo protocolo (Task → Expected Result, YES/PARTIAL/NO) é executado por
  **scripts Playwright escritos antes do experimento**.
- **Nota humana:** só entra como *classificação de falhas do piloto* (quem edita o oráculo), nunca como nota dos resultados.
- **Rubricas ponderadas (40/30/30 do código antigo):** sem respaldo; removidas.
- **UI-Bench / DesignBench como datasets:** eram cópias byte-idênticas das mesmas 3 tarefas; removidos. Só as métricas dos artigos ficam.

## 4. Organização do repositório

```
benchmarks/tasks/<nível>/<id>.md|.png   tarefas (frontmatter: id, complexity) e o design do Figma
benchmarks/tasks/figma_frames.yaml      tarefa → node_id do Figma → png
benchmarks/free_prompts/<coleta>/       collection.yaml + prompts.jsonl (anônimo)
configs/default.yaml  pilot.yaml        experimento principal e piloto
scaffold/angular-base/                  Angular 20 + Tailwind 4 + ng-icons; package-lock.json versionado
oracles/                                suítes Playwright (instrumento de medida) + requirements.yaml + pending.yaml
references/figma/                       nodes.raw.json (uma chamada à API), blocks.json (derivado)
specui/                                 pacote (cli, config, models, prompting, pipeline, llm/, codegen/, harness/, metrics/, oracle/, analysis/)
scripts/fetch_figma.py                  chamada única ao Figma; nunca chamada pelo pipeline
dashboard/app.py                        painel Streamlit
tests/                                  pytest (rápidos por padrão; `-m slow` usa navegador/Node/modelos)
results/                                saída (INTEIRA fora do git)
```

## 5. Instalação

Python 3.12 e Node 22 (`.nvmrc`).

```bash
python -m venv .venv && .venv\Scripts\activate          # Windows
pip install -e . -r requirements.txt -r requirements-dev.txt   # versões mínimas; para o ambiente exato do piloto:
# pip install -r requirements.lock && pip install -e . --no-deps
pip install -r requirements-ml.txt                       # DINOv2/CLIP (torch-cpu); sem isso VES/CLIP ficam null com o motivo
pip install -r requirements-ocr.txt                      # opcional: referência por OCR quando falta o JSON do Figma
playwright install chromium
cp .env.example .env                                     # GEMINI_API_KEY[_1..9], FIGMA_TOKEN, FIGMA_FILE_KEY
specui scaffold-check                                    # npm ci uma vez e build do projeto vazio
specui check-model                                       # confirma os ids dos dois modelos (recusa alias -latest/-preview)
```

`requirements.lock` é o `pip freeze` do ambiente do piloto 1 (Playwright 1.62.0 → Chromium 151.0.7922.34, torch 2.14.1, transformers 5.19.0);
`playwright` é a única dependência pinada em `requirements.txt`, porque a versão define o navegador. Windows: `git config core.longpaths true`. O `workspace_dir` tem padrão por plataforma (`C:/specui-work` no Windows, curto de propósito por causa do limite de caminho; `~/.cache/specui-work` nas demais) e pode ser trocado na configuração.

A instalação é **editável** (`pip install -e .`): `oracles/`, `configs/`, `benchmarks/` e `scaffold/` não são empacotados, são lidos do repositório. Python 3.12 é exigido (`requires-python` em `pyproject.toml`; o harness usa `os.path.isjunction`).

## 6. Tarefas, requisitos e rastreabilidade

Cada tarefa tem `oracles/<tarefa>/requirements.yaml`: cada requisito cita o `## Prompt` (ou a spec), tem categoria
(`a` testável do prompt · `b` só visual · `c` ambíguo, com pendência · `s` só da spec), `info_source` (`image` | `behavior` |
`spec_only`) e `mention_patterns` (regex PT-BR para medir cobertura em prompts livres). `specui oracle-matrix` gera
`traceability.md` (requisito × caso) e **falha** se um requisito `a` ficar sem caso.

As alterações feitas nos `.md` das tarefas: frontmatter reduzido a `id` e `complexity`; stack declarada (Angular 20, Tailwind 4,
ng-icons com os pacotes instalados); pedido de suíte Cypress removido; três defeitos de spec corrigidos
(medium §3 "Pausa Longa" → "RELAXA"; medium §4 "Para fazer" → "Para Fazer"; hard §3 documentado como **não** defeito: o card
(#D7CFCF) fica sobre o corpo das colunas, não sobre o fundo geral). O texto de `## Prompt` não foi alterado.

## 7. Figma

`python scripts/fetch_figma.py --dry-run` imprime a URL; sem `--dry-run` faz **uma** requisição (`GET /v1/files/:key/nodes`) e
grava `references/figma/nodes.raw.json` (o plano Starter permite poucas chamadas por mês); recusa sobrescrever sem `--force` e
recusa node ids `TODO`. `specui figma-derive` gera `blocks.json` offline (nós TEXT: `characters`, caixa, cor, tamanho) e valida a
escala (frame 1440×900 == PNG). Preencha os `node_id` em [benchmarks/tasks/figma_frames.yaml](benchmarks/tasks/figma_frames.yaml).

## 8. Envelope e scaffold

O envelope (`ENVELOPE_VERSION = "2"`) descreve só a stack e o contrato (arquivos permitidos, proibições, "testes não serão
executados", formato de saída, **sem rede em runtime**, e a cláusula de que as restrições técnicas **prevalecem** sobre qualquer
pedido de tecnologia do usuário). Nada sobre a interface. Formato de saída: blocos ```` ```ts file=src/app/app.ts ````. O contrato exige
`export class App` em `src/app/app.ts`. O `styles.css` do scaffold é fixo; o do modelo vira `src/app.styles.css`.

Statuses: `done`, `format_failure`, `contract_failure`, `truncated` (antes do parser), `refusal`, `nonexecutable` (build/render),
e as falhas de infraestrutura `api_error` (a célula é refeita), `metric_error` (resolver com `specui evaluate`) e
`model_mismatch` (modelo devolvido ≠ solicitado: a célula é refeita; **se repetir, o run é interrompido** com
`ModelMismatchError`, checkpoint intacto). Não existe fallback de modelo nem de provedor.

Todo record grava `finish_reason` (o motivo de parada devolvido pelo provedor). `RECITATION`, `SAFETY`, `PROHIBITED_CONTENT`, `BLOCKLIST`, `SPII` e `IMAGE_SAFETY` (e o bloqueio do prompt) são motivos de
recusa e valem `refusal`; `MAX_TOKENS` vale `truncated`. Exceção de **infraestrutura** no build ou no render
(disco, navegador fechado, `OSError`) vira `metric_error` **gravado** (a resposta paga já está em `response.raw.txt`) e a execução segue
para a próxima célula. Já o app que não carrega em 30 s é falha do app: `render_ok = false` e status `nonexecutable`. Se a extração do DOM falhar
com o render ok, Design2Code e CLIP ficam `null` com a nota no record (zero só vale para página realmente vazia).

## 9. Execução

```bash
specui smoke                                  # ponta a ponta com o gerador simulado (sem API)
specui pilot                                  # todos os geradores, 1 repetição → results/pilot/ (fora da análise)
specui run                                    # experimento principal (retoma pelo manifest)
specui run --reps 2 --tasks easy --modalities text --generators google
specui evaluate --all --groups functional     # recalcula métricas SEM LLM e SEM rebuild
specui analyze                                # contrastes, itens, livres → results/aggregate/report.md
specui export --out export/specui-AAAA-MM-DD.zip   # opcional, para depósito com DOI
streamlit run dashboard/app.py
```

Ordem das células: **rep-major** (camadas completas por repetição). Chaves do Gemini: no limite **por minuto** o cliente espera e
alterna entre `GEMINI_API_KEY`, `GEMINI_API_KEY_1..9`; quando a cota **diária** de uma chave acaba, ela sai da rotação e a execução
segue com a próxima. Só quando todas esgotam a execução para; o progresso fica salvo e é retomado no mesmo comando. Atenção: chaves
do **mesmo projeto** do Google Cloud dividem a mesma cota, então só chaves de projetos diferentes somam cota. A execução principal **só inicia** com o oráculo congelado (seção 11).

`specui smoke`, `run --mock` e `pilot --mock` gravam em `results/smoke/`, nunca em `results/pilot/` nem na execução principal; o gerador simulado
nunca entra em `evaluate` (salvo `--include-mock`) nem em `analyze` (que o recusa). `specui evaluate` em `run_kind: main` com o grupo
`functional` **recusa** (exit 2) se o oráculo não estiver congelado (árvore suja, sem tag ou `oracles/VERSION` diferente da tag).

## 10. Métricas (por artigo)

**Design2Code** (condicionais: só quem renderiza). `block_match` = área dos blocos pareados / área de todos os blocos dos dois lados;
`text` = similaridade de Sørensen-Dice dos pares; `position` = 1 − max(|Δx|,|Δy|) dos centros normalizados; `color` = 1 − ΔE2000/100
(limitado a [0,1]); `clip_inpainted` = cosseno CLIP ViT-B/32 dos screenshots com o texto removido por inpainting. O pareamento
é húngaro com busca de **fusão de blocos vizinhos** (apêndice C); `n_merged_ref/gen` são registrados e `pairs.json` guarda pares e
fusões para o overlay do painel. Direção: ↑.

**Figma2Code.** `ves_dinov2` (cosseno DINOv2-base, ↑); `mae` (erro absoluto médio de pixels em [0,1], ↓); `ssim` (secundária).
Qualidade de código sobre o DOM renderizado e o CSS (escopo: dentro de `app-root`, sem `<svg>`, `ng-*`/`cdk-*`; camadas `theme`/`base`
do Tailwind fora): **RUR** unidades relativas (↑), **APR** posicionamento absoluto (↓), **FU** containers flex/grid (↑), **BC**
faixas de viewport cobertas (↑), **STR** elementos semânticos (↑), **AVU** classes de valor arbitrário (↓), **ISR** estilo inline
(↓), **CCR** classes customizadas reutilizadas (↑). Numeradores e denominadores ficam em `counts`.

**WebGen-Bench.** `accuracy_a` (primária), `accuracy_b` (diagnóstica, exigências da spec) e `accuracy_a_restricted` (só os casos cujos
requisitos eram inferíveis do material mostrado ao participante; igual a `accuracy_a` em `no_spec`/`with_spec`).

**Insumo (`InputSpecMetrics`, para todo prompt):** caracteres/palavras, densidade de restrições (hex, px, defaults, aria, tags),
cobertura de requisitos por `info_source`, marcadores de estrutura, referências à imagem e **`stack_requests`** (React, Vue, HTML
puro, Bootstrap...). Custo: tokens de entrada/saída/raciocínio e latência.

**Métrica não calculada fica `null` com o motivo em `errors`: nunca 0.**

## 11. Oráculos

Cada caso é um par (Task, Expected Result) com script Playwright determinístico: relógio falso instalado **antes** do `goto`, avanço
com `run_for`, `reduced_motion`, rede bloqueada fora da origem local, espiões de áudio. Seletores semânticos (papel, rótulo, texto,
geometria que o prompt dá); `oracle-lint` rejeita `#id`, `.classe`, `data-testid` e caso sem asserção.

- **O que pontua:** só o *Expected Result* (`ok` e `eventually`). A *Task* (`act`) e as pré-condições (`require`) que **passam** são
  **passos** (status `step`): ficam fora do numerador e do denominador e são contadas em `n_steps`. `act` ou `require` que **falha** é
  falha pontuada; `require` que falha ainda bloqueia o caso. Quando o efeito principal da funcionalidade é pré-condição (`require`) das
  asserções de invariante, uma funcionalidade quebrada dá NO, não PARTIAL (regra PD-C3 em `oracles/<tarefa>/pending.yaml`). Caso sem
  nenhuma asserção pontuada dá NO, e o `oracle-lint` exige ≥ 1 `ok`/`eventually` por caso não pendente.
- **Resultado:** YES (todas as asserções pontuadas passam), PARTIAL (≥ 1 passa e ≥ 1 falha), NO (nenhuma passa, exceção ou pré-condição
  que falhou: `blocked=true`, vale 0 e fica no denominador). Asserções `PENDING` ficam fora do numerador e do denominador.
- **Níveis:** A (só do `## Prompt`; nota **principal**) e B (exigências específicas da spec: hex ΔE ≤ 5, medidas, ARIA, semântica,
  foco, áudio; diagnóstica).
- **Regra de decisão das pendências** (o `## Prompt` não muda, logo uma decisão não pode criar requisito que ele não contém):
  1. o prompt admite mais de uma leitura → o nível A aceita qualquer leitura consistente (ex.: input `25` ou `25:00`);
  2. o prompt não descreve o mecanismo → testa-se só o observável; o resto sai do nível A e é declarado "não testável a partir do prompt"
     (ex.: como trocar de modo, o que o lápis faz);
  3. exigência específica da spec → nível B (ex.: hex exato).
  Cada decisão está em `oracles/<tarefa>/pending.yaml`; o hash entra na proveniência.
- **Dados criados pela UI:** os testes criam as próprias tarefas/cards; dados iniciais do app não afetam nenhuma asserção.
- **Piloto:** todos os geradores, N = 1, em `results/pilot/`. As falhas são classificadas **por você** em `test_defect` |
  `model_defect` | `ambiguity` | `adapter_gap`; só `test_defect` e `adapter_gap` editam o oráculo (registrado em
  `oracles/CHANGELOG.md`). O oráculo **nunca foi exercitado contra uma implementação real** antes do piloto: não há implementação
  de referência das tarefas, de propósito.
- **Mutação** (`specui mutate`): sobre saídas do piloto que deram YES, estraga o app em tempo de execução (remover elementos, engolir
  cliques, congelar timers, somente leitura, remover rolagem, quebrar DnD, trocar texto) e confirma que o caso deixa de dar YES.
  `sensitivity.csv`: `KILLED` | `WEAK` | `SURVIVED` | `NOT_APPLIED`. Caso que sobrevive é revisto antes do congelamento.
  `sensitivity_baseline.csv` guarda o resultado de cada caso-alvo no app intacto (diagnóstico de todo `NOT_APPLIED`). `MUT-M8`
  (`neutralize_filters`) desliga só os controles de filtro, sem derrubar a criação de tarefas (M-A-10, M-A-11).
- **Piloto 1 (`oracle-v1`, `google:gemini-3.8-flash`, 12 células):** 148 pares oráculo × mutação: **136 KILLED, 11 WEAK, 1 NOT_APPLIED,
  0 SURVIVED**. Os 11 WEAK são casos multi-requisito em que PARTIAL é intencional (E-A-01, M-A-05, H-A-03); o NOT_APPLIED é
  MUT-H4 × H-A-03 num run cujo baseline já era PARTIAL. `accuracy_a` mudou em 1 das 12 células (medium, `no_spec`, multimodal:
  0,958 → 0,917); `accuracy_b` caiu nas 6 células `no_spec` e ficou igual nas `with_spec`; `n_total` do nível A por run caiu
  (48/99/113 → 25/50/71) porque passos deixaram de pontuar. A evidência (records, capturas, relatórios, baseline anterior) está em
  [docs/pilot-1/](docs/pilot-1/README.md); o registro por classe de mudança, em `oracles/CHANGELOG.md`.
- **Congelamento:** `git tag oracle-v1` na árvore atual de `oracles/` (e `oracles/VERSION` igual à tag). A execução principal recusa
  `dirty`/sem tag; cada record grava tag, hash da árvore, hash do conteúdo, hash de `pending.yaml` e de `mention_patterns`, e as
  versões do Playwright e do Chromium. Qualquer mudança exige nova tag e reexecução; `analyze` recusa misturar tags.
  `oracles/registry.yaml` é informativo (nenhum código o lê) e permanece porque `oracles/` está congelado.

## 12. Análise

`specui analyze` (os dois conjuntos; **ITT primeiro**):

- **ITT:** toda geração tentada, exceto `api_error`, `metric_error` e `model_mismatch` (fora de qualquer conjunto). **Condicional:**
  só `executable`, sempre acompanhado da taxa de executabilidade.
- **Contraste principal por modelo:** bootstrap estratificado (10 000 réplicas, percentil; reamostra dentro de cada tarefa × modalidade
  × fonte) e permutação estratificada (10 000, p bicaudal). As gerações são independentes: nada de pareamento por repetição.
- **Secundários:** Δ por tarefa × modalidade × modelo; OLS com erros HC3 (`nota ~ spec*modalidade + tarefa + modelo + spec:modelo`).
- **Consistência entre modelos (só com k ≥ 2):** sinal do Δ por estrato, diferença entre efeitos (todos os pares) com IC, gráfico forest e **TOST**
  opcional com margem `analysis.equivalence_margin` (gravada em `results/run_meta.json` no início da execução principal e não pode
  mudar depois; `null` → o teste não roda e o relatório diz por quê).
- **Itens:** `flag_floor` / `flag_ceiling`, `blocked_rate`, discriminação por spec/modalidade/modelo, nota com e sem os casos marcados.
- **Livres:** regressão da nota sobre cobertura e densidade com erros agrupados por participante, ITT por padrão, `accuracy_a_restricted`.
- **`contract_failure`** por fonte do prompt, nos livres cruzada com `stack_requests`.
- `analyze` **recusa**: runs `metric_error` em `main` (lista quais), versões diferentes do oráculo, hashes de `mention_patterns`
  diferentes nas análises de livres, margem de equivalência alterada, runs do piloto, runs do gerador simulado e **navegadores
  diferentes** (`playwright_version` ou `browser_version`): reavaliar numa máquina ou Chromium diferente exige reavaliar todas as células.

## 13. Painel

`streamlit run dashboard/app.py` (lê só a execução principal): grade de células por modelo; contraste com IC por tarefa × modalidade ×
modelo e texto × multimodal; itens; qualidade de código × VES; inspeção de execução (design × render, pares/fusões, arquivos, build,
console, axe, prompt + sha); prompts livres.

## 14. `results/` e `record.json`

`results/` é **inteiramente ignorado pelo git** (sem negações). Cada `record.json` é autossuficiente (caminhos relativos, hashes de
prompt/imagem/envelope/scaffold/oráculo, id solicitado e devolvido, parâmetros enviados). `specui export` é um utilitário opcional,
fora do fluxo principal, para depositar os dados com DOI (`MANIFEST.json` com sha256).

### Prompts livres: coleta anônima

`collection.yaml` exige `anonymous: true` e `participants_informed: true` (o formulário informa o uso e a possível publicação anônima
dos textos). `specui prompts import --collection <id> --file respostas.csv --map map.yaml` gera ids `p001…`, **remove PII** do texto
(e-mail, telefone, nomes) e **lista cada remoção** em `import_report.md` para revisão; o perfil entra só em faixas amplas e valores fora
das faixas são recusados; o CSV bruto fica em `private/` (ignorado). O envelope declara que as restrições de stack prevalecem sobre
pedidos de outra tecnologia, e `stack_requests` mede quantos prompts pedem outra stack.

## 15. Reprodutibilidade

Versões exatas no `package.json` e `package-lock.json` commitado (Angular 20.3, Tailwind 4.3, ng-icons 32.5, fontsource); ids de modelo
fixos e verificados a cada geração; seeds `base_seed + rep`; temperatura do padrão do provedor (gravada `null`);
`config_sha256` (sem os caminhos da máquina), `repo_commit` (com `+dirty` se há qualquer mudança fora de `results/`) e o hash da árvore
do scaffold em cada record; relógio fixo em 10/03/2026 10:00 (`specui/clock.py`, fonte única; a configuração recusa outro valor).
A proveniência do oráculo (tag, hash da árvore e do conteúdo, `pending.yaml`, `mention_patterns`) e as versões do Playwright/Chromium são
**recalculadas em toda avaliação funcional**: o record sempre diz com qual oráculo e navegador a nota foi calculada, também após `specui evaluate`.

## 16. Ameaças à validade

- **Oráculos redigidos com apoio de um assistente de IA** (Claude Code, usado só na escrita do código, nunca como gerador nem como
  avaliador) podem refletir convenções de código gerado por LLM; mitigado por seletores semânticos, aceitação de leituras múltiplas
  (regra 1) e pela mutação/piloto, mas não eliminado.
- **Recusas e truncamento** valem 0 na ITT; as taxas são reportadas.
- **Oráculo não validado contra implementação real** antes do piloto; defeitos de teste são corrigidos só depois, com registro.
- **Teto da nota do nível A** (1,00 / 0,96 nas 12 células do piloto 1). O que no código do oráculo contribui para isso, declarado como
  ameaça e não corrigido: (a) PARTIAL vale 0,5, então asserções de invariante que passam com a funcionalidade quebrada davam piso de
  0,5 (tratado: passos não pontuam e o efeito principal é pré-condição, seção 11); (b) `find_play_button` aceita, sem nome acessível,
  qualquer botão abaixo do visor; (c) E-A-03 ("fundo branco") passa de graça com o `preflight` do Tailwind; (d) as faixas de matiz
  são largas (verde 76°–166°, azul 190°–251°) e somam ±5° (PD-C2) e o limite de croma do cinza; (e) a isenção de matiz do corpo
  de "Aprovado" em H-A-03 (PD-H6). No piloto, as únicas asserções A que caíram foram três leituras de cor (M-A-06, M-A-12, H-A-03),
  classificadas como `model_defect`.
- **Piso da nota funcional:** uma página branca sem relação com a tarefa já passa no caso "fundo branco" (≈ 0,1 de `accuracy_a` no smoke com o gerador simulado); a ITT atribui 0 só a falhas de geração/execução, não a apps vazios.
- **Pouca potência:** 3 tarefas × 2 modalidades × 5 repetições por modelo; os ICs refletem isso.
- **Confusão tarefa × dificuldade**, um único gerador, spec mais longa que o prompt (seção 2).

## 17. Referências

- Si et al., *Design2Code*, NAACL 2025. <https://arxiv.org/pdf/2403.03163>
- *Figma2Code*, ICLR 2026. <https://arxiv.org/pdf/2604.13648>
- Lu et al., *WebGen-Bench*, NeurIPS 2025. <https://arxiv.org/pdf/2505.03733>
- Artigos descartados (registro): [docs/papers/descartados/](docs/papers/descartados/) · contexto: [docs/contexto-benchmarks-spec-ui.md](docs/contexto-benchmarks-spec-ui.md)
