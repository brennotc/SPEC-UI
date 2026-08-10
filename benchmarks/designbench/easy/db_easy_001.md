---
id: db_easy_001
benchmark_name: DesignBench
complexity: Easy
multimodal: true
---
## Prompt

Construa um front-end para um timer Pomodoro. Só faça uma página com fundo branco, header vermelho claro com a logo de um tomate e Pomodoro escrito no canto superior esquerdo. No centro da página, um círculo com uma borda que troca de cor: vermelho para Foco Total, Verde para Pausa Curta e Azul para Pausa Longa. Dentro do círculo tem o tempo no formato 00:00 que vai decrescendo. Em cima do número tem o nome do período do Pomodoro e abaixo dos números tem um símbolo redondo de play/pause. Se o usuário clicar no botão ele dá play se o timer estiver parado ou dá pause se o timer estiver rodando. Na parte de baixo tem uma linha de divisão em cinza, embaixo dela tem o tempo que está configurado para cada parte do pomodoro. O default é 25 minutos para Foco total, 5 minutos para pausa curta e 15 minutos para Pausa longa. O usuário pode editar o tempo de cada um deles porque o tempo está dentro de um input. Ao final de cada parte do pomodoro, o site pode realizar um aviso sonoro.

## Specification

# 1. ESCOPO E DELIMITAÇÃO DE FRONTEIRAS (SCOPE & BOUNDARIES)

- Dentro do Escopo (In-Scope):

    - Aplicação de página única (SPA) para um Timer Pomodoro.
    - Três modos de temporizador: Foco Total, Pausa Curta e Pausa Longa.
    - Troca dinâmica de cores da borda do círculo conforme o modo ativo.
    - Inputs para edição dos tempos de cada modo.
    - Disparo de alerta sonoro ao zerar a contagem.
    - Pensado para o usuário entrar no site e já começar a usar sem se preocupar em salvar o estadoao qualquer informação dele para o futuro.

- Fora do Escopo (Explicit Out-of-Scope):

    - Histórico de sessões ou estatísticas de uso.
    - Persistência de dados em banco ou localStorage.
    - Sistema de login/autenticação ou múltiplas rotas.

# 2. CONTRATO DE DADOS E TIPAGEM (DATA CONTRACT & TYPES)

```typescript
type PomodoroMode = 'focus' | 'shortPause' | 'longPause';

interface TimerConfig {
  focus: number;       // time in seconds. default 1500 (25 minutes)
  shortPause: number; // time in seconds. default 300 (5 minutes)
  longPause: number; // time in seconds. default 900 (15 minutes)
}

interface PomodoroState {
  currentMode: PomodoroMode;
  timeRemainingInSeconds: number;
  isRunning: boolean;
  config: TimerConfig;
}
```

# 3. MATRIZ DE ESTADOS DA INTERFACE (UI STATE MACHINE)

- Mapeamento de Cores:

    - Modo Foco Total: #D74747.
    - Modo Pausa Curta: #658B5C.
    - Modo Pausa Longa: #5684D9.
    - Cinza padrão: #716C6C.
    - Vermelho header: #E56060.

    O círculo central muda de cor de acordo com o modo atual.

- Estados de Execução (Timer State):

    - Parado: Inputs de configuração de tempo estão habilitados para edição.
    - Rodando: Inputs de configuração ficam desabilitados durante a contagem.
    - Finalizado: Quando o tempo chega a 00:00, emite um som (audio.play()) e o timer retorna ao estado pausado.

- Formatadores:

    - O tempo exibido dentro do círculo e dos inputs de configuração de cada modo devem ter obrigatoriamente a formatação MM:SS (com zero à esquerda, ex: 05:00).

# 4. RESTRIÇÕES TÉCNICAS E ESTILIZAÇÃO (TECHNICAL CONSTRAINTS)

- Tech Stack: Angular 20+ (Standalone Components, TypeScript), Tailwind CSS para estilização.

- Ícones: Use a biblioteca ng-icons (ícones: Play/Pause juntos dentro de um círculo preenchido e um ícone para representar o tomate no header).

- Layout & Estilização:

    - Fundo: Página com fundo branco.
    - Texto: fonte Inter.
    - Header: Posicionado no topo, fundo Vermelho header 70px de altura, alinhado à esquerda com o ícone do tomate e o texto "Pomodoro", os dois em branco.
    - Centro: Círculo de 503px X 503px com borda fina e interior vazado centralizado contendo dentro da parte vazada:

        - Nome do período no topo fonte tamanho 36.
        - Tempo formatado 00:00 no meio fonte tamanho 128.
        - Botão circular de Play/Pause na parte inferior interna do círculo.

    - Rodapé / Configurações: Linha divisória Cinza padrão horizontal. Abaixo da linha, 3 campos de entrada (<input type="number">) para edição dos tempos padrão (25, 5 e 15 minutos). Foco Total no canto inferior esquerdo alinhado horizontalmente com a logo da página. Os três campos tem formato "[Nome do Modo]: retângulo 89px x 40px contendo o input com o tempo configurado para o modo".O nome do modo e do fundo do retângulo são na cor do respectivo modo. A fonte do input é branco. Pausa curta fica alinhado horizontalmente com o centro da página e Pausa longa fica alinhado horizontalmente no lado oposto de Foco total.
    - Áudio: Utilizar a API nativa Web Audio ou new Audio() via HTML5 para a emissão do som ao finalizar.

# 5. NORMAS DE QUALIDADE E ACESSIBILIDADE (COMPLIANCE & A11Y)

- Semântica HTML: Estruturar a página usando <header>, <main> e <section>.
- Rótulos de Acessibilidade (ARIA):

    - O botão de Play/Pause deve alternar dinamicamente o aria-label entre "Iniciar temporizador" e "Pausar temporizador".
    - Os <input> dos tempos de configuração devem ter elementos <label> associados explicitamente via atributo htmlFor.

- Suporte a Teclado: Elementos interativos devem exibir anel de foco visível.

# 6. CRITÉRIOS DE VERIFICAÇÃO E TESTES (VERIFICATION CONTRACT)

- Forneça a suíte completa de testes End-to-End (E2E) utilizando Cypress. Os testes devem tratar a aplicação Angular como caixa-preta, validando os seguintes fluxos e estados de interface:

    1. **Estado Inicial e Interface:**
    - Verificar se o fundo da página é branco.
    - Validar a presença do `<header>` com o ícone do tomate (via `ng-icons`) e o texto "Pomodoro".
    - Confirmar se o tempo inicial exibido é `25:00` com a borda do círculo na cor vermelha (Modo Foco Total).
    - Validar se os 3 inputs contêm os valores padrão: 25 (Foco), 5 (Pausa Curta) e 15 (Pausa Longa).

    2. **Fluxo do Timer (Play/Pause e Manipulação do Tempo):**
    - Utilizar `cy.clock()` para congelar e simular a passagem de tempo.
    - Clicar no botão de Play/Pause (ícone `ng-icons`) e disparar o temporizador.
    - Usar `cy.tick(3000)` para avançar 3 segundos e verificar se o visor atualizou para `24:57`.
    - Clicar novamente no botão para pausar e garantir que o tempo pare de decrementar.

    3. **Edição das Configurações de Tempo:**
    - Com o timer pausado, alterar o input de "Foco Total" de 25 para 30.
    - Verificar se o contador principal é atualizado para `30:00`.
    - Garantir que, durante a execução do timer (`isRunning === true`), os campos de `<input>` fiquem desabilitados (`[disabled]`).

    4. **Troca de Modos e Troca Dinâmica de Cores:**
    - Validar a mudança visual da borda do círculo conforme o modo ativo:
        - Vermelho no modo *Foco Total*.
        - Verde no modo *Pausa Curta*.
        - Azul no modo *Pausa Longa*.

    5. **Finalização do Ciclo e Alerta Sonoro:**
    - Usar `cy.tick()` para avançar o tempo restante até `00:00`.
    - Garantir que o evento de término seja disparado e validar que a chamada do alerta sonoro (`HTMLAudioElement.prototype.play`) foi executada.