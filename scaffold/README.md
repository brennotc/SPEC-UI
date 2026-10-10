# Scaffold Angular (fixo)

Projeto base idêntico em todas as execuções. O modelo **não** cria projeto nem instala nada: só escreve
arquivos em `src/app/` (e, opcionalmente, `src/styles.css`, que o harness grava como
`src/app.styles.css`). Qualquer mudança aqui exige novo `SCAFFOLD_VERSION` e invalida resultados anteriores
(o hash do lockfile e o da árvore são gravados em cada `record.json`).

## Como foi criado (uma vez)

```bash
cd scaffold
npx -y -p @angular/cli@20 ng new angular-base --interactive=false --standalone --style=css \
    --routing=false --ssr=false --skip-git --skip-tests --strict --package-manager=npm --skip-install
cd angular-base
npm install --save-exact @ng-icons/core@32 @ng-icons/heroicons@32 @ng-icons/lucide@32 \
    @fontsource/inter @fontsource/roboto @fontsource/poppins
npm install --save-dev --save-exact tailwindcss@4 @tailwindcss/postcss@4 postcss
```

Depois: todas as versões em `package.json` fixadas na versão exata instalada (sem `^`/`~`), lockfile
regenerado, e o projeto enxugado (sem Karma/Jasmine, sem `public/`, sem README do CLI, componente raiz vazio,
`index.html` neutro, `app.config.ts` removido, `main.ts` com `bootstrapApplication(App, …)`).

- `@ng-icons` **32.x** é a última série que aceita Angular 20 (a 33+ exige Angular 21 ou mais).
- `src/styles.css` é fixo: `@import "tailwindcss"; @import "./app.styles.css";`.
- `angular.json`: só o alvo `build` (`dist/app`, sem budgets), cache compartilhado em `../.angular-cache`.
- `.gitignore` interno evita que o Tailwind (detecção automática de fontes) varra `dist/` e `.angular/`.

## Uso

O harness (`specui/harness/scaffold.py`) instala `node_modules` uma vez em `<workspace>/shared` (`npm ci`),
copia o scaffold para `<workspace>/<run_id>` por execução e liga o `node_modules` por junction.
Verifique com `specui scaffold-check`.
