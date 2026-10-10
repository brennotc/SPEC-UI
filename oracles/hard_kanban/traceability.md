# Rastreabilidade: hard_kanban

_Gerado por `specui oracle-matrix`; não edite._

| Requisito | Texto | Cat. | Fonte | Casos | Status |
|---|---|---|---|---|---|
| H-01 | uma página com fundo cinza, header verde com ícone de lista e escrito "Kanban" no canto superior esquerdo | a | image | H-A-01 | coberto |
| H-02 | Todo o restante da tela é ocupado por quatro colunas de mesma largura | a | image | H-A-02 | coberto |
| H-03 | Cada coluna tem um título e uma cor associada. Da esquerda para a direita, "Para Fazer" (azul), "Em Progresso" (laranja), "Feito" (roxo) e "Aprovado" (verde) | a | image | H-A-02 | coberto |
| H-04 | Cada coluna tem um header com o título em branco com a determinada cor mais forte e o restante da coluna é da respectiva cor só que num tom mais fraco | a | image | H-A-03 | coberto |
| H-05 | Cada coluna possui cards quadrados off-white com bordas arredondadas. No canto superior direito de cada card há o ícone de um lápis azul e de uma lixeira vermelha. No centro, a descrição da tarefa em preto | a | image | H-A-08, H-A-09 | coberto |
| H-06 | A primeira coluna é a única que tem o desenho de um card esmaecido no final da coluna com um contorno dashed e um ícone de + no centro em cinza | a | image | H-A-04 | coberto |
| H-07 | Se o usuário clicar nesse +, o cartão fica na cor dos restantes e surge um input no centro para escrever a descrição; no lugar dos ícones, um "check" verde e um "X" vermelho | a | behavior | H-A-05 | coberto |
| H-08 | Se clicar no "check" ele confirma a criação do card | a | behavior | H-A-06 | coberto |
| H-09 | Se clicar no X, ele cancela a adição e o card volta para o estado inicial esmaecido | a | behavior | H-A-07 | coberto |
| H-10 | o ícone de uma lixeira vermelha para deletar | a | behavior | H-A-10 | coberto |
| H-11 | o ícone de um lápis azul para editar (o mecanismo de edição não é descrito) | c | behavior | H-A-15 (pendente) | pendente (PD-H2) |
| H-12 | O usuário pode mover o card (drag-and-drop) apenas uma etapa da coluna à direita | a | behavior | H-A-11 | coberto |
| H-13 | de "Para fazer", só pode ir para "Em Progresso" e assim sucessivamente (não pode pular etapas à direita) | a | behavior | H-A-12 | coberto |
| H-14 | Há a possibilidade de voltar para o lado esquerdo. Nesse caso, pode mover quantos passos quiser para à esquerda | a | behavior | H-A-13 | coberto |
| H-15 | Também pode mover o card para cima e para baixo dentro da mesma coluna para reordenar os cards daquela coluna | a | behavior | H-A-14 | coberto |
| H-S01 | Header de 70 px, fundo #105610, ícone e texto "Kanban" brancos; fundo geral #D7CFCF | s | spec_only | H-B-01 | nível B |
| H-S02 | Cabeçalho e corpo das colunas: #0B73B7/#9FBACC, #B77A0B/#CCB59F, #440BB7/#AA9FCC, #105610/#C5CC9F; largura mínima 340 px | s | spec_only | H-B-02 | nível B |
| H-S03 | Card de criação: opacity-70, borda dashed cinza #656060, ícone + cinza | s | spec_only | H-B-03 | nível B |
| H-S04 | Cards de 274 x 191 px, fundo #D7CFCF, descrição preta 24 px centralizada, lápis azul, lixeira #B50000 | s | spec_only | H-B-04 | nível B |
| H-S05 | Modo de criação: input centralizado com aria-label "Descrição da nova tarefa"; check verde #105610 e X vermelho #B50000 | s | spec_only | H-B-05 | nível B |
| H-S06 | Confirmar insere o card como ÚLTIMO da coluna "Para Fazer" e o placeholder volta a 70% de opacidade | s | spec_only | H-B-06 | nível B |
| H-S07 | Lápis transforma o texto em campo editável com check (salva) e X (descarta a edição) | s | spec_only | H-B-07 | nível B |
| H-S08 | Semântica: <header>, <main>, <section> por coluna e <article> por card | s | spec_only | H-B-08 | nível B |
| H-S09 | Botões só de ícone (lápis, lixeira, plus, check, X) têm aria-label descritivo | s | spec_only | H-B-09 | nível B |
| H-S10 | Tab alcança botões, placeholder e campos com anel de foco visível | s | spec_only | H-B-10 | nível B |
