# Rastreabilidade: medium_tarefas

_Gerado por `specui oracle-matrix`; não edite._

| Requisito | Texto | Cat. | Fonte | Casos | Status |
|---|---|---|---|---|---|
| M-01 | uma página com fundo preto, header azul com ícone de lista e escrito "Tarefas Para Fazer" no canto superior esquerdo | a | image | M-A-01 | coberto |
| M-02 | Abaixo da header, alinhado a esquerda também um filtro de Data e um do lado o de Prioridade. O filtro de data é um input com uma máscara de data e o de Prioridade é um input de seleção | a | image | M-A-02 | coberto |
| M-03 | uma lista agrupada por dias, começando por Hoje, seguida por Amanhã e depois os dias escritos | a | behavior | M-A-05 | coberto |
| M-04 | O primeiro item da lista é a prioridade que está dentro de um retângulo. O vermelho tem escrito URGENTE, o verde RELAXA e o amarelo MÉDIO, texto em branco | a | image | M-A-06 | coberto |
| M-05 | No lado direito da prioridade tem uma checkbox para marcar se a tarefa foi feita ou não | a | behavior | M-A-07 | coberto |
| M-06 | o nome da tarefa e no final da linha na extremidade direita tem os ícones de lápis e lixeira | a | image | M-A-08 | coberto |
| M-07 | lixeira para excluir a tarefa | a | behavior | M-A-08 | coberto |
| M-08 | lápis para editar a tarefa (o mecanismo de edição não é descrito) | c | behavior | M-A-13 (pendente) | pendente (PD-M3) |
| M-09 | Se a lista for maior que o espaço disponível, faz um scroll só na lista | a | behavior | M-A-09 | coberto |
| M-10 | Na parte de baixo tem uma linha branca que separa da lista. Abaixo da linha, "Nova tarefa:" seguido de um input vazio com máscara de data, um input de seleção "Prioridade", um longo input com label "Descrição da tarefa" e, no extremo direito, um ícone de + | a | image | M-A-03, M-A-12 | coberto |
| M-11 | Quando o usuário preencher esses ítens, e clicar no ícone de + ele adiciona uma nova tarefa à lista | a | behavior | M-A-04, M-A-12 | coberto |
| M-12 | um filtro de Data e um do lado o de Prioridade (o comportamento do filtro: só as tarefas que correspondem ficam na lista) | a | behavior | M-A-10, M-A-11 | coberto |
| M-S01 | Header de 70 px, fundo #60C2E5, ícone e texto "Tarefas Para Fazer" em preto | s | spec_only | M-B-01 | nível B |
| M-S02 | Filtros: textos "Data:" e "Prioridade:" em cinza tamanho 32; campos em retângulos cinza 170 x 55, texto preto; select com "Selecione" | s | spec_only | M-B-02 | nível B |
| M-S03 | Título do dia em azul do header, tamanho 32; linhas brancas de 1327 px (grupo) e 1247 px (tarefa) | s | spec_only | M-B-04 | nível B |
| M-S04 | Badges 146 x 36 px com fundos #FF0000, #8D8A31 e #0F633F e texto branco | s | spec_only | M-B-03 | nível B |
| M-S05 | Tarefas concluídas exibem texto tachado e opacidade reduzida | s | spec_only | M-B-05 | nível B |
| M-S06 | Lápis em azul do header e lixeira em vermelho URGENTE | s | spec_only | M-B-06 | nível B |
| M-S07 | Lápis: a linha vira a linha de adição preenchida, lápis/lixeira dão lugar ao check; ao confirmar, volta com os dados atualizados | s | spec_only | M-B-07 | nível B |
| M-S08 | Após adicionar com sucesso, os inputs do formulário são limpos | s | spec_only | M-B-08 | nível B |
| M-S09 | Ordenar as tarefas da mais prioritária para a menos prioritária | s | spec_only | M-B-09 | nível B |
| M-S10 | Prioridade tem um item "Selecione" neutro que remove o filtro; apagar a data remove o filtro de data | s | spec_only | M-B-10 | nível B |
| M-S11 | Botões só de ícone têm aria-label descritivo (ex.: "Excluir tarefa") | s | spec_only | M-B-11 | nível B |
| M-S12 | <input> e <select> do formulário e dos filtros têm <label> ou aria-label | s | spec_only | M-B-11 | nível B |
| M-S13 | Semântica: <header>, <main>, <section> e <footer> (ou <form>) | s | spec_only | M-B-12 | nível B |
| M-S14 | Navegação por Tab com anel de foco visível | s | spec_only | M-B-13 | nível B |
| M-S15 | Data sempre no formato DD/MM/AAAA | s | spec_only | M-B-04 | nível B |
| M-S16 | Rodapé: linha cinza, "Nova tarefa:" à esquerda, campos cinza #D5D0D0, botão + azul do header na extremidade direita | s | spec_only | M-B-14 | nível B |
