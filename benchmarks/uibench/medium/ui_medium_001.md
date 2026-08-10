---
id: ui_medium_001
benchmark_name: UI-Bench
complexity: Medium
multimodal: false
---
## Prompt

Construa um front-end para uma lista de tarefas para fazer. Só faça uma página com fundo preto, header azul com ícone de lista e escrito "Tarefas Para Fazer" no canto superior esquerdo. Abaixo da header, alinhado a esquerda também um filtro de Data e um do lado o de Prioridade. O filtro de data é um input com uma máscara de data e o de Prioridade é um input de seleção. Abaixo da linha dos filtros, começa uma lista agrupada por dias, começando por Hoje, seguida por Amanhã e depois os dias escritos.Cada grupo tem uma lista de tarefas. O primeiro item da lista é a prioridade que está dentro de um retângulo. O vermelho tem escrito URGENTE dentro, o verde tem escrito RELAXA dentro e o amarelo tem escrito MÉDIO dentro. O respectivo texto escrito dentro é em branco. No lado direito da prioridade tem uma checkbox para marcar se a tarefa foi feita ou não. Do lado direito temos o nome da tarefa e no final da linha na extremidade direita tem os ícones de lápis e lixeira para editar a tarefa ou excluir. Se a lista for maior que o espaço disponível, faz um scroll só na lista.Na parte de baixo tem uma linha branca que separa da lista. Abaixo da linha, no canto esquerdo tem escrito  "Nova tarefa:" seguido de um input vazio com máscara de data, no lado direito tem um input de seleção escrito "Prioridade" e do lado direito um longo input com label "Descrição da tarefa". Por fim, no extremo do lado direito tem um ícone de +. Quando o usuário preencher esses ítens, e clicar no ícone de + ele adiciona uma nova tarefa à lista.

## Specification

# 1. ESCOPO E DELIMITAÇÃO DE FRONTEIRAS (SCOPE & BOUNDARIES)

- Dentro do Escopo (In-Scope):

    - Criar uma aplicação de página única (SPA) para gerenciamento de uma lista de tarefas agrupada por datas, com opções de filtragem e edição.
    - Exibição de tarefas agrupadas por dias ("Hoje", "Amanhã" e datas subsequentes).
    - Filtragem de tarefas por data e por prioridade.
    - Adição de novas tarefas via formulário no rodapé da página.
    - Marcar/desmarcar tarefas como concluídas, editar e excluir tarefas existentes.
    - Rolagem vertical contida exclusivamente na área da lista de tarefas.
    - Ordenar as tarefas da mais prioritária para menos prioritária.

- Fora do Escopo (Explicit Out-of-Scope):

    - Integração com APIs externas ou backend em nuvem (utilizar gerenciamento de estado em memória no Angular).
    - Autenticação de usuários, rotas múltiplas ou persistência em banco de dados.
    - Funcionalidade de arrastar e soltar (drag-and-drop).

# 2. CONTRATO DE DADOS E TIPAGEM (DATA CONTRACT & TYPES)

```typescript
export type PriorityLevel = 'URGENTE' | 'MÉDIO' | 'RELAXA';

export interface Task {
  id: string;
  description: string;
  dueDate: string; // Formato YYYY-MM-DD
  priority: PriorityLevel;
  completed: boolean;
}

export interface TaskGroup {
  groupTitle: string; // "Hoje", "Amanhã" ou a data formatada
  dateKey: string;
  tasks: Task[];
}

export interface TaskFilter {
  date?: string;
  priority?: PriorityLevel | 'TODAS';
}
```

# 3. MATRIZ DE ESTADOS DA INTERFACE (UI STATE MACHINE)

- Mapeamento de Cores:

    - Prioridade URGENTE: #FF0000.
    - Prioridade MÉDIO: #8D8A31.
    - Modo Pausa Longa: #0F633F.
    - Cinza: #D5D0D0.
    - Azul header: #60C2E5.

- Estado Inicial / Padrão:

    - Renderizar o fundo geral da tela em preto.
    - Apresentar a lista dividida por grupos cronológicos ("Hoje", "Amanhã", etc.).

- Badges de Prioridade (Layout da Tarefa):

    - Prioridade URGENTE: Retângulo 146px x 36px com respectivo fundo do mapeamento de Cores e texto branco com o termo "URGENTE".
    - Prioridade MÉDIO: Retângulo 146px x 36px com respectivo fundo do mapeamento de Cores e texto branco com o termo "MÉDIO".
    - Prioridade RELAXA: Retângulo 146px x 36px com respectivo fundo do mapeamento de Cores e texto branco com o termo "RELAXA".

- Comportamento da Lista e Ações:

    - Checkbox: Ao clicar no checkbox do item, alterar a propriedade completed. Tarefas concluídas devem exibir texto tachado e opacidade reduzida.
    - Ícone de Lixeira: Ao clicar, remover a tarefa imediatamente do seu grupo correspondente.
    - Ícone de Lápis: Ao clicar, a linha se transforma com as configurações da linha de adição com o campo de data, prioridade e descrição preenchidos com as informações atuais. Os ícones de lápis e lixeira dão lugar ao ícone de "check". Ao mudar alguma informação e clicar no ícone de check, volta para o modo de exibição com as informações atualizadas.
    - Estouro de Lista: Se a lista de tarefas ultrapassar o espaço vertical útil da tela, o scroll deve ocorrer apenas no container da lista, mantendo o Header, os Filtros e o Formulário de Adição fixos na tela.

- Estado de Filtragem:

    - Ao alterar os inputs de filtro (Data ou Prioridade) localizados abaixo do Header, a lista deve ocultar os itens que não correspondem aos critérios selecionados. Prioridade tem que ter um item "Selecione" ouneutro para se o usuário quiser retirar o filtro de Prioridade. Assim como se o usuário apagar a data do input de data, ele tira o filtro de data.

- Estado de Adição (Formulário do Rodapé):

    - Ao preencher a data, selecionar a prioridade, digitar a descrição e clicar no ícone de +, adicionar a nova tarefa ao grupo correspondente.
    - Limpar os inputs do formulário após a inserção bem-sucedida.

- Formatadores:

    - Data sempre no formato "DD/MM/AAAA".

# 4. RESTRIÇÕES TÉCNICAS E ESTILIZAÇÃO (TECHNICAL CONSTRAINTS)

- Tech Stack: Angular 20+ (utilizando exclusivamente Standalone Components, Signals/RxJS e TypeScript), estilizado com Tailwind CSS.

- Ícones: Utilizar a biblioteca ng-icons para renderizar:

    - Ícone de lista no Header.
    - Ícones de Lápis (edição) e Lixeira (exclusão) em cada linha de tarefa. Ícone de "check" ao entrar no modo de edição da lista.
    - Ícone de + (adicionar) no botão do formulário de criação.

- Layout & Estilização:

    - Fundo: Página com fundo preto.
    - Texto: fonte Inter.
    - Header: Posicionado no topo, fundo Azul header 70px de altura, alinhado à esquerda com o ícone da lista e o texto "Tarefas Para fazer", os dois em preto.
    - Linha de Filtros: Posicionada abaixo do Header, alinhada à esquerda. Contém:

        - Texto "Data:" em cinza tamanho 32 e Input de filtro de Data (com máscara/formato de data) em um retângulo cinza de 170px x 55px e texto do input em preto.
        - Texto "Prioridade:" em cinza tamanho 32 e Input de seleção (<select>) de filtro de Prioridade ao lado em um retângulo cinza de 170px x 55px e texto do input em preto com default "Selecione".

    - Área Central (Lista): Agrupada por dias. O texto do dia em Azul Header e tamanho 32. Separado do grupo por uma linha branca de 1327px que começa alinhado horizontalmente com o ícone de lista da header.

        - Estrutura de cada linha de tarefa: Cada linha de tarefa é separada por uma linha branca de 1247px que começa alinhada horizontalmente ao título do dia.
        [Retângulo de Prioridade] [Checkbox em branco se deselecionado] [Nome/Descrição da Tarefa em branco] ------ [Lápis em azul header] [Lixeira em vermelho Prioridade URGENTE]
    
    - Divisória e Rodapé de Criação:

        - Linha cinza horizontal separando a lista do rodapé.
        - Abaixo da linha: Texto "Nova tarefa:" à esquerda, seguido por um <input> cinza vazio com máscara de data, um <select> cinza de "Prioridade", um <input> cinza longo com a label "Descrição da tarefa" e o botão com ícone de + azul header na extremidade direita.

# 5. NORMAS DE QUALIDADE E ACESSIBILIDADE (COMPLIANCE & A11Y)

- Semântica HTML: Estruturar a página usando <header>, <main>, <section> e <footer> (ou <form>).
- Rótulos de Acessibilidade (ARIA):

    - Os botões interativos compostos apenas por ícones (Lápis, Lixeira, Adicionar) devem conter atributos aria-label descritivos (ex: aria-label="Excluir tarefa").
    - Os elementos <input> e <select> do formulário e dos filtros devem possuir <label> associadas ou aria-label definidos.

- Suporte a Teclado: Garantir que todos os campos editáveis, botões e checkboxes sejam navegáveis via tecla Tab com anel de foco visível.

# 6. CRITÉRIOS DE VERIFICAÇÃO E TESTES (VERIFICATION CONTRACT)

- Forneça a suíte completa de testes End-to-End (E2E) utilizando Cypress. Os testes devem tratar a aplicação Angular como caixa-preta, validando os seguintes fluxos e estados de interface:

    1. **Layout Inicial e Estrutura Visual:**
    - Validar que o fundo da página possui a classe/estilo de cor preta.
    - Verificar a exibição do Header azul contendo o texto "Tarefas Para Fazer" e o ícone de lista (ng-icons).
    - Confirmar se a lista inicial apresenta os cabeçalhos de grupos esperados ("Hoje", "Amanhã").

    2. **Validação das Badges de Prioridade:**
    - Verificar se as tarefas rotuladas como URGENTE possuem o fundo vermelho e o texto em branco.
    - Verificar se as tarefas rotuladas como MÉDIO possuem o fundo amarelo e o texto em branco.
    - Verificar se as tarefas rotuladas como RELAXA possuem o fundo verde e o texto em branco.

    3. **Fluxo de Adição de Nova Tarefa:**
    - Preencher o formulário do rodapé: inserir a data, selecionar a prioridade "URGENTE" e digitar a descrição "Testar prompt Spec-Driven".
    - Clicar no botão com o ícone de +.
    - Validar se a nova tarefa foi inserida corretamente no grupo correspondente da lista com a badge e nome corretos.
    - Confirmar que os inputs do formulário de adição foram limpos após a inserção.

    4. **Ações da Tarefa (Concluir e Excluir):**
    - Clicar no checkbox de uma tarefa e verificar se a classe de conclusão/tachado foi aplicada.
    - Clicar no ícone de lixeira de uma tarefa e confirmar que o elemento foi removido do DOM/lista.

    5. **Testes de Filtragem:**
    - Selecionar a prioridade "URGENTE" no filtro superior e validar que apenas as tarefas urgentes permanecem visíveis.
    - Limpar o filtro e garantir que a lista completa retorne ao estado original.

    6. **Comportamento de Rolagem:**
    - Adicionar ou mockar múltiplos itens na lista até exceder a altura da tela e validar que o container da lista possui a propriedade de scroll vertical, mantendo o Header e o formulário fixos.