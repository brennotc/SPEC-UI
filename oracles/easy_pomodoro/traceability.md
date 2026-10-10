# Rastreabilidade: easy_pomodoro

_Gerado por `specui oracle-matrix`; não edite._

| Requisito | Texto | Cat. | Fonte | Casos | Status |
|---|---|---|---|---|---|
| E-01 | uma página com fundo branco | a | image | E-A-03 | coberto |
| E-02 | header vermelho claro com a logo de um tomate e Pomodoro escrito no canto superior esquerdo | a | image | E-A-02 | coberto |
| E-03 | No centro da página, um círculo com uma borda que troca de cor: vermelho para Foco Total (o modo inicial) | a | image | E-A-04, E-A-11 | coberto |
| E-04 | Em cima do número tem o nome do período do Pomodoro | a | behavior | E-A-01, E-A-04 | coberto |
| E-05 | o tempo no formato 00:00 que vai decrescendo | a | behavior | E-A-01, E-A-05 | coberto |
| E-06 | abaixo dos números tem um símbolo redondo de play/pause. Se o usuário clicar no botão ele dá play se o timer estiver parado ou dá pause se estiver rodando | a | behavior | E-A-01, E-A-05, E-A-06 | coberto |
| E-07 | Na parte de baixo tem uma linha de divisão em cinza, embaixo dela tem o tempo que está configurado para cada parte do pomodoro | a | image | E-A-07 | coberto |
| E-08 | O default é 25 minutos para Foco total, 5 minutos para pausa curta e 15 minutos para Pausa longa | a | behavior | E-A-07 | coberto |
| E-09 | O usuário pode editar o tempo de cada um deles porque o tempo está dentro de um input | a | behavior | E-A-08 | coberto |
| E-10 | um círculo com uma borda que troca de cor: vermelho para Foco Total, Verde para Pausa Curta e Azul para Pausa Longa (a troca de modo não tem mecanismo descrito) | c | image | E-A-10 (pendente) | pendente (PD-E2) |
| E-11 | Ao final de cada parte do pomodoro, o site pode realizar um aviso sonoro | c | behavior | — | pendente (PD-E5) |
| E-12 | Dentro do círculo tem o tempo no formato 00:00 que vai decrescendo (a contagem termina sem valores negativos) | a | behavior | E-A-09 | coberto |
| E-S01 | Header: fundo #E56060, 70px de altura, ícone do tomate e texto "Pomodoro" em branco | s | spec_only | E-B-01 | nível B |
| E-S02 | Círculo de 503px x 503px; nome do período fonte 36; tempo fonte 128; texto em Inter | s | spec_only | E-B-02 | nível B |
| E-S03 | Cores dos modos: Foco #D74747, Pausa Curta #658B5C, Pausa Longa #5684D9; cinza #716C6C | s | spec_only | E-B-03, E-B-10 | nível B |
| E-S04 | Rodando: inputs de configuração desabilitados; parado: habilitados | s | spec_only | E-B-04 | nível B |
| E-S05 | Semântica HTML: <header>, <main> e <section> | s | spec_only | E-B-05 | nível B |
| E-S06 | aria-label do botão alterna entre "Iniciar temporizador" e "Pausar temporizador" | s | spec_only | E-B-06 | nível B |
| E-S07 | Inputs de configuração com <label> associado (htmlFor) | s | spec_only | E-B-07 | nível B |
| E-S08 | Elementos interativos exibem anel de foco visível | s | spec_only | E-B-08 | nível B |
| E-S09 | Rodapé: três campos "[Nome do Modo]: retângulo 89px x 40px" na cor do modo, fonte branca, alinhados à esquerda/centro/direita | s | spec_only | E-B-09 | nível B |
| E-S10 | Os campos de configuração são <input type="number"> | s | spec_only | E-B-05 | nível B |
| E-S11 | Finalizado: emite som (audio.play()) e o timer retorna ao estado pausado | s | spec_only | E-B-11 | nível B |
