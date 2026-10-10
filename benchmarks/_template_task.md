---
id: easy_exemplo
complexity: Easy
---
<!--
  Modelo de tarefa do SPEC-UI. O loader (specui/tasks.py) lê só `id` e `complexity` (Easy | Medium | Hard) do frontmatter.
  Onde salvar: benchmarks/tasks/<easy|medium|hard>/<id>.md, com o design do Figma no MESMO diretório como <id>.png
  (1440x900, escala 1x) e uma entrada em benchmarks/tasks/figma_frames.yaml (tarefa -> node_id do frame -> png).
  A modalidade (text | multimodal) NAO e propriedade da tarefa: e um fator do experimento (o PNG so vai ao modelo em multimodal).
  Os oraculos da tarefa ficam em oracles/<id>/ (requirements.yaml, pending.yaml, level_a.py, level_b.py).
-->
## Prompt

Descricao curta e vaga do que construir, sem especificacao tecnica. E exatamente o texto que o modelo recebe na condicao no_spec.

## Specification

Requisitos detalhados: escopo, contrato de dados, estados da interface, cores, medidas, tipografia, acessibilidade e criterios de
aceitacao. E exatamente o texto que o modelo recebe na condicao with_spec (nunca junto com o Prompt).
