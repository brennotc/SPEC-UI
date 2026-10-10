"""Montagem do pedido enviado ao modelo.

O ENVELOPE (system prompt) é idêntico em todas as células: só descreve a stack fixa, os
arquivos permitidos, o formato de saída e a precedência das restrições técnicas. Nada sobre
a interface: tudo o que construir vem apenas do texto do usuário (prompt, spec ou prompt livre).

Histórico do envelope (mudar o texto exige novo ENVELOPE_VERSION e invalida execuções anteriores):
  1 - primeira redação (sem a cláusula de precedência da stack).
  2 - acrescenta: restrições técnicas prevalecem sobre pedidos de tecnologia no texto do usuário.
"""

from pathlib import Path

from specui.models import Modality, PromptPackage, PromptSource, ScaffoldInfo, Task
from specui.tasks import sha256_bytes, sha256_text

ENVELOPE_VERSION = "2"

_ENVELOPE_TEMPLATE = """\
Você é um desenvolvedor front-end sênior. Implemente a interface pedida pelo usuário dentro de um projeto Angular que já existe e é fixo. Você só escreve arquivos de código: não cria o projeto nem instala nada.

PROJETO FIXO
- Angular {angular_version} (Standalone Components, TypeScript) com Tailwind CSS já configurado: as utilidades do Tailwind funcionam em templates e componentes. Sem roteamento e sem SSR.
- Pacotes instalados (são os únicos disponíveis; nenhuma dependência nova pode ser adicionada):
{packages}
- O ponto de entrada é fixo: main.ts faz bootstrapApplication(App) importando a classe App de src/app/app.ts. Portanto src/app/app.ts DEVE exportar `export class App`, um componente standalone com seletor `app-root`.

ARQUIVOS PERMITIDOS
- Qualquer arquivo dentro de src/app/ com extensão .ts, .html ou .css (você pode criar componentes adicionais) e, opcionalmente, src/styles.css (estilos globais, carregados depois do Tailwind).
- Não altere package.json, angular.json, tsconfig*, index.html nem main.ts. Arquivos fora das áreas permitidas são ignorados.
- Não escreva testes: eles não serão executados.

AMBIENTE DE EXECUÇÃO
- Não há acesso à rede em tempo de execução. Fontes e ícones devem vir dos pacotes instalados (por exemplo @fontsource/* e @ng-icons/*); `@import url(...)`, `<link>` ou `<script>` externos não carregam.

PRECEDÊNCIA
- Estas restrições técnicas prevalecem sobre qualquer pedido de tecnologia no texto do usuário (por exemplo React, Vue, HTML puro, Bootstrap): implemente o que foi pedido dentro desta stack.

FORMATO DA RESPOSTA
- Responda somente com blocos de código cercados, um por arquivo, com o caminho no texto de abertura do bloco:

```ts file=src/app/app.ts
// conteúdo do arquivo
```

- Use ts, html ou css conforme a extensão do arquivo. Não escreva nenhum texto fora dos blocos.
"""


def render_envelope(scaffold: ScaffoldInfo) -> str:
    """Texto do envelope para um scaffold. Depende só do scaffold, nunca da célula."""
    packages = "\n".join(
        f"  - {name}@{version}" for name, version in sorted(scaffold.packages.items())
    )
    return _ENVELOPE_TEMPLATE.format(angular_version=scaffold.angular_version, packages=packages)


def _validate(task: Task, source: PromptSource, modality: Modality) -> None:
    if source.task_id != task.id:
        raise ValueError(
            f"prompt '{source.prompt_id}' é da tarefa '{source.task_id}', não de '{task.id}'"
        )
    if modality == "multimodal" and not Path(task.image_path).is_file():
        raise FileNotFoundError(
            f"modalidade multimodal exige o PNG da tarefa '{task.id}': {task.image_path}"
        )


def build_messages(
    task: Task,
    source: PromptSource,
    modality: Modality,
    scaffold: ScaffoldInfo,
) -> PromptPackage:
    """Monta o pedido: envelope + texto do prompt (+ PNG quando multimodal).

    `user_text` é exatamente `source.text`: a seção ## Prompt (no_spec), a seção
    ## Specification (with_spec) ou o texto livre do participante.
    """
    _validate(task, source, modality)
    system = render_envelope(scaffold)
    image_path = task.image_path if modality == "multimodal" else None
    image_sha = task.image_sha256 if modality == "multimodal" else None

    material = system + "\n" + source.text
    if image_sha:
        material += "\n" + image_sha
    return PromptPackage(
        system=system,
        user_text=source.text,
        image_path=image_path,
        image_sha256=image_sha,
        modality=modality,
        envelope_version=ENVELOPE_VERSION,
        envelope_sha256=sha256_text(ENVELOPE_VERSION + "\n" + system),
        prompt_sha256=sha256_bytes(material.encode("utf-8")),
    )
