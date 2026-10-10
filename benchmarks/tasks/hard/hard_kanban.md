---
id: hard_kanban
complexity: Hard
---
## Prompt

Construa um front-end para um dashboard de organização de Kanban. Só faça uma página com fundo cinza, header verde com ícone de lista e escrito "Kanban" no canto superior esquerdo. Todo o restante da tela é ocupado por quatro colunas de mesma largura. Cada coluna tem um título e uma cor associada. Da esquerda para a direita, a primeira é "Para Fazer" com azul, a segunda é "Em Progresso" com laranja, a terceira é "Feito" com roxo e a última é "Aprovado" com verde. Cada coluna tem um header com o título em branco com a determinada cor mais forte e o restante da coluna é da respectiva cor só que num tom mais fraco. Cada coluna possui cards quadrados off-white com bordas arredondadas. No canto superior direito de cada card há o ícone de um lápis azul para editar e um ícone de lixeira vermelha para deletar. No centro, tem a descrição da tarefa em preto. A primeira coluna é a única que tem o desenho de um card esmaecido no final da coluna com um contorno dashed e um ícone de + no centro em cinza. Se o usuário clicar nesse +, ele faz uma animação que deixa o cartão na cor dos restantes e um input no centro do cartão para escrever a descrição. No local que nos  cards normais ficam os ícones dos cards, tem um ícone de "check" em verde e um "X" em vermelho. Se clicar no "check" ele confirma a criação do card. Se clicar no X, ele cancela a adição e o card volta para o estado inicial esmaecido. O usuário pode mover o card (drag-and-drop) apenas uma etapa da coluna à direita. Ou seja, de "Para fazer", só pode ir para "Em Progresso" e assim sucessivamente. Há a possibilidade de voltar para o lado esquerdo. Nesse caso, pode mover quantos passos quiser para à esquerda. Também pode mover o card para cima e para baixo dentro da mesma coluna para reordenar os cards daquela coluna.

## Specification

# 1. ESCOPO E DELIMITAÇÃO DE FRONTEIRAS (SCOPE & BOUNDARIES)

- Dentro do Escopo (In-Scope):

    - Criar uma aplicação de página única (SPA) para um dashboard de organização Kanban com 4 colunas fixas.
    - Renderização do Header verde com ícone de lista e título "Kanban".
    - Renderização de 4 colunas de mesma largura com identidades visuais próprias (cabeçalho forte e corpo fraco): "Para Fazer" (azul), "Em Progresso" (laranja), "Feito" (roxo) e "Aprovado" (verde).
    - Renderização de cards quadrados off-white com bordas arredondadas, contendo botões de ação (editar em azul, deletar em vermelho) e a descrição centralizada em preto.
    - Mecanismo de criação de novo card na coluna "Para Fazer" via card esmaecido com contorno dashed e ícone de +.
    - Animação e transição do card de criação para o estado de edição com campos e ícones de confirmação (check verde) e cancelamento (X vermelho).
    - Edição inline e exclusão de cards existentes.
    - Regras estritas de movimentação entre colunas: permissão de avanço de apenas 1 etapa para a direita e recuo de N etapas para a esquerda.
    - Funcionalidade de arrastar e soltar (drag-and-drop) para movimentar os cards de uma coluna para outra seguindo o que é permitido.

- Fora do Escopo (Explicit Out-of-Scope):

    - Integração com APIs externas ou backend em nuvem (utilizar gerenciamento de estado em memória no Angular via Signals/RxJS).
    - Autenticação de usuários, rotas múltiplas ou persistência em banco de dados relacional/NoSQL.
    - O foco é na aplicação front-end, não é necessário pensar no back-end.
    

# 2. CONTRATO DE DADOS E TIPAGEM (DATA CONTRACT & TYPES)

```typescript
export type ColumnId = 'para-fazer' | 'em-progresso' | 'feito' | 'aprovado';

export interface KanbanCard {
  id: string;
  description: string;
  columnId: ColumnId;
  createdAt: string;
}

export interface ColumnConfig {
  id: ColumnId;
  title: string;
  headerColorClass: string;
  bodyColorClass: string;
}

export interface NewCardState {
  isCreating: boolean;
  tempDescription: string;
}
```

# 3. MATRIZ DE ESTADOS DA INTERFACE (UI STATE MACHINE)

- Mapeamento de Cores:

    - Fundo Geral: #D7CFCF.
    - Coluna "Para Fazer": Cabeçalho Azul Forte: #0B73B7, Corpo Azul Claro: #9FBACC. 
    - Coluna "Em Progresso": Cabeçalho Laranja Forte: #B77A0B, Corpo Laranja Claro: #CCB59F.
    - Coluna "Feito": Cabeçalho Roxo Forte: #440BB7, Corpo Roxo Claro: #AA9FCC.
    - Coluna "Aprovado": Cabeçalho Verde Forte: #105610, Corpo Verde Claro: #C5CC9F.
    - Card: #D7CFCF.
    - Ícone Excluir / X de Cancelar: #B50000.
    - Verde header: #105610.
    - Cinza: #656060.

- Estado Inicial / Padrão:

    - Tela com fundo geral ocupando 100% da viewport.
    - Header verde fixo no topo com o texto "Kanban" e ícone de lista no canto superior esquerdo em branco.
    - 4 colunas dispostas lado a lado com larguras idênticas (340px) ocupando o restante da tela.
    - Coluna "Para Fazer" contendo os cards existentes e obrigatoriamente o card de adição esmaecido (70% da opacidade da cor de um card normal) no final da coluna.

- Comportamento dos Cards Normais:

    - Formato 274px x 191px e bordas arredondadas.
    - Canto superior direito: Ícone de lápis em azul (editar) e ícone de lixeira em vermelho (deletar).
    - Centro: Descrição da tarefa em texto preto tamanho 24 centralizado.
    - Ações de Movimentação: Drag-and-drop nos cards que permitem mover o card:
        - Para a direita: Habilitado APENAS para a coluna imediatamente adjacente (ex: "Para Fazer" -> "Em Progresso"). O drag-and-drop faz o card voltar para o estado inicial se tentar pular etapas.
        - Para a esquerda: Habilitado para QUALQUER coluna à esquerda (ex: "Aprovado" -> "Para Fazer", "Aprovado" -> "Em Progresso").
        - Para cima e para baixo: ordenar a importância dos cards dentro da coluna.


- Estado de Criação de Card (Exclusivo da Coluna "Para Fazer"):

    - Estado Repouso (Placeholder): Card no final da coluna com estilo esmaecido (opacity-70), borda pontilhada (dashed 10) cinza e um ícone de + cinza no centro.
    - Ação de Clique no +: Dispara uma animação de transição suave que altera a cor e a opacidade para a cor do card normal (off-white com bordas sólidas).

    - Estado Edição de Novo Card:

        - Um <input> surge centralizado para o usuário digitar a descrição da tarefa.
        - No canto superior direito, os ícones normais dão lugar a um ícone de "check" verde header e um "X" vermelho.

    - Ação de Confirmação (Check): Valida a criação do card com o texto digitado, insere o novo card como último da lista da coluna "Para Fazer" e retorna o card de criação ao estado placeholder esmaecido.
    - Ação de Cancelamento (X): Limpa o input, cancela a operação e retorna o card imediatamente ao estado placeholder esmaecido.

- Comportamento de Edição e Exclusão:

    - Lixeira: Remove o card imediatamente do estado global/memória.
    - Lápis: Transforma o texto central em um campo de texto editável e exibe o botão de confirmação (check) para salvar a nova descrição e o X para cancelar a edição.

# 4. RESTRIÇÕES TÉCNICAS E ESTILIZAÇÃO (TECHNICAL CONSTRAINTS)

- Tech Stack: Angular 20 (utilizando exclusivamente Standalone Components, Signals/RxJS e TypeScript), estilizado com Tailwind CSS 4.
- Ícones: Utilizar a biblioteca ng-icons (pacotes instalados: @ng-icons/core, @ng-icons/heroicons e @ng-icons/lucide) para renderizar:

    - Ícone de lista no Header.
    - Ícones de Lápis (edição) e Lixeira (exclusão) em cada card. Ícone de "check" verde e X vermelho ao entrar no modo de adição/edição da lista.
    - Ícone de + (adicionar) cinza no botão do card de criação.

- Layout & Estilização:

    - Fundo: Página com fundo geral.
    - Texto: fonte Inter.
    - Header: Posicionado no topo, fundo verde header 70px de altura, alinhado à esquerda com o ícone da lista e o texto "Kanban", os dois em branco.
    - Área Principal: Container flexível dividindo a tela em 4 colunas de largura idêntica (min-width=340px).

    - Estrutura das Colunas:

        - Cada coluna possui um cabeçalho com fundo da cor forte correspondente e texto do título em branco.
        - O corpo da coluna possui o fundo da respectiva cor em tom fraco/suave estendido verticalmente.

    - Cards:

        - Bordas arredondadas.
        - Layout interno flex/grid mantendo o botão de ação no topo direito e o texto centralizado.

# 5. NORMAS DE QUALIDADE E ACESSIBILIDADE (COMPLIANCE & A11Y)

- Semântica HTML: Estruturar a página usando <header>, <main>, <section> para cada coluna e <article> para cada card de tarefa.
- Rótulos de Acessibilidade (ARIA):

    - Os botões interativos compostos apenas por ícones (Lápis, Lixeira, Plus, Check, X, Mover) devem conter atributos aria-label descritivos (ex: aria-label="Mover tarefa para Em Progresso", aria-label="Excluir tarefa").
    - O campo de input de nova tarefa deve possuir atributo aria-label="Descrição da nova tarefa".

- Suporte a Teclado: Garantir que os botões dos cards, o placeholder de adição e os campos de texto sejam navegáveis via tecla Tab com anel de foco visível.

# 6. CRITÉRIOS DE VERIFICAÇÃO E TESTES (VERIFICATION CONTRACT)

- Critérios de aceitação, verificados externamente tratando a aplicação Angular como caixa-preta (não escreva nem entregue testes). A aplicação deve satisfazer os seguintes fluxos e estados de interface:

    1. **Layout Inicial, Dimensões e Mapeamento de Cores:**
        - Validar que o fundo geral da aplicação possui a cor `#D7CFCF`.
        - Verificar a exibição do Header verde (`#105610`) com 70px de altura, contendo o ícone de lista e o texto "Kanban" ambos na cor branca.
        - Confirmar a presença das 4 colunas com largura mínima de 340px, validando o contraste exato entre cabeçalho (cor forte) e corpo (cor fraca):
            - "Para Fazer": Cabeçalho `#0B73B7` e Corpo `#9FBACC`.
            - "Em Progresso": Cabeçalho `#B77A0B` e Corpo `#CCB59F`.
            - "Feito": Cabeçalho `#440BB7` e Corpo `#AA9FCC`.
            - "Aprovado": Cabeçalho `#105610` e Corpo `#C5CC9F`.
        - Validar a presença do card de criação esmaecido exclusivamente no final da coluna "Para Fazer", confirmando a opacidade de 70% (`opacity-70`), a borda pontilhada (`dashed 10`) na cor cinza (`#656060`) e o ícone de `+` cinza no centro.
        - Confirmar que os cards normais possuem as dimensões de 274px x 191px, fundo `#D7CFCF`, descrição em texto preto centralizado (tamanho 24), ícone de lápis em azul e lixeira em vermelho (`#B50000`).

    2. **Fluxo de Criação de Card (Coluna "Para Fazer"):**
        - Clicar no card de adição esmaecido (ícone `+` cinza).
        - Verificar a transição suave para o modo de edição, confirmando a exibição do `<input>` centralizado e dos ícones no topo direito: "check" verde header (`#105610`) e "X" vermelho (`#B50000`).
        - Preencher a descrição "Novo Card de Teste" e clicar no "check" verde.
        - Validar se o novo card foi inserido como o **último item da lista** da coluna "Para Fazer" e se o card de criação retornou ao estado placeholder esmaecido (70% de opacidade).
        - Testar o cancelamento: Clicar no `+`, digitar um texto, clicar no "X" vermelho e confirmar que o card NÃO foi adicionado e o formulário retornou ao estado inicial.

    3. **Edição e Cancelamento de Edição de Cards:**
        - Clicar no ícone de lápis azul de um card existente.
        - Confirmar que a descrição se transforma em um `<input>` editável e exibe os ícones de "check" verde e "X" vermelho no topo direito.
        - Alterar o texto e clicar no "check" verde: validar se a descrição foi atualizada na interface.
        - Clicar no lápis azul novamente, alterar o texto e clicar no "X" vermelho: validar se a edição foi descartada e a descrição original foi mantida.

    4. **Exclusão de Cards:**
        - Clicar no ícone da lixeira vermelha (`#B50000`) de um card e confirmar que o elemento foi imediatamente removido da coluna e do estado global/memória.

    5. **Regras de Drag-and-Drop (Movimentação e Reordenação):**
        - **Avanço de 1 Etapa à Direita (Permitido):** Realizar o drag-and-drop de um card da coluna "Para Fazer" para "Em Progresso" e validar que o card mudou de coluna.
        - **Tentativa de Pular Etapas à Direita (Proibido / Snap Back):** Realizar o drag-and-drop de um card da coluna "Para Fazer" diretamente para "Feito" ou "Aprovado" e validar que o card retorna automaticamente à sua posição inicial.
        - **Recuo de N Etapas à Esquerda (Permitido):** Realizar o drag-and-drop de um card da coluna "Aprovado" para "Para Fazer" (recuo de 3 etapas) e validar que a transferência ocorre com sucesso.
        - **Reordenação Vertical na Mesma Coluna:** Arrastar um card para cima ou para baixo dentro da mesma coluna e validar que a ordem visual e de prioridade dos cards foi alterada.