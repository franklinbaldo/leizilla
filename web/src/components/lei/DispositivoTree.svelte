<script lang="ts">
  // Árvore recursiva do texto vigente. Cada dispositivo tem id={path} para
  // deep-link (#art-5-par-2) e ações de cópia (link estável / citação).
  import Self from './DispositivoTree.svelte';
  import { rotulo, citation } from '../../lib/format';
  import {
    ORGANIZACIONAIS,
    absoluteLeiUrl,
    copyText,
    fmtDate,
    type DispositivoNode,
  } from './model';

  let {
    nodes,
    leiId,
    highlight = null,
    depth = 0,
  }: {
    nodes: DispositivoNode[];
    leiId: string;
    highlight?: string | null;
    depth?: number;
  } = $props();

  // Feedback "copiado!" — uma chave `${path}|${acao}` por vez, neste nível.
  let copied = $state<string | null>(null);
  let copyTimer: ReturnType<typeof setTimeout> | undefined;

  async function copiar(key: string, text: string) {
    const ok = await copyText(text);
    if (!ok) return;
    copied = key;
    clearTimeout(copyTimer);
    copyTimer = setTimeout(() => {
      copied = null;
    }, 1600);
  }

  function headingLevel(d: number): number {
    // Seções da página usam h2/h3; agrupadores da lei começam em h4.
    return Math.min(6, 4 + d);
  }
</script>

{#each nodes as node (node.row.dispositivo_path)}
  {@const row = node.row}
  {@const path = row.dispositivo_path}
  {@const organizacional = ORGANIZACIONAIS.has(row.dispositivo_tipo)}
  <div
    id={path}
    class="dispositivo"
    class:organizacional
    class:revogado={row.dispositivo_revogado}
    class:destaque={highlight === path}
  >
    {#if organizacional}
      <p class="org-heading" role="heading" aria-level={headingLevel(depth)}>
        <strong>{rotulo(path)}</strong>
        {#if row.texto}<span class="org-titulo">{row.texto}</span>{/if}
      </p>
    {:else}
      <p class="texto-dispositivo">
        <strong class="rotulo">{rotulo(path)}</strong>
        {#if row.texto}
          <span class="corpo">{row.texto}</span>
        {:else}
          <em class="sem-texto">sem texto disponível nesta versão</em>
        {/if}
      </p>
    {/if}

    {#if row.dispositivo_revogado}
      <p class="nota-revogado">
        Revogado{row.dispositivo_revogado_em ? ` em ${fmtDate(row.dispositivo_revogado_em)}` : ''}{row.dispositivo_revogado_tipo
          ? ` (${row.dispositivo_revogado_tipo})`
          : ''}{#if row.dispositivo_revogado_por}{' por '}<code
            >{row.dispositivo_revogado_por}</code
          >{/if}.
      </p>
    {/if}

    <span class="acoes">
      <button
        type="button"
        class="acao"
        onclick={() => copiar(`${path}|link`, absoluteLeiUrl(leiId, path))}
        title="Copiar link permanente deste dispositivo"
      >
        {copied === `${path}|link` ? 'copiado!' : 'copiar link'}
      </button>
      <button
        type="button"
        class="acao"
        onclick={() => copiar(`${path}|citar`, citation(row))}
        title="Copiar citação deste dispositivo"
      >
        {copied === `${path}|citar` ? 'copiado!' : 'citar'}
      </button>
    </span>

    {#if node.children.length > 0}
      <div class="filhos">
        <Self nodes={node.children} {leiId} {highlight} depth={depth + 1} />
      </div>
    {/if}
  </div>
{/each}

<style>
  .dispositivo {
    position: relative;
    margin: 0 0 0.25rem;
    padding: 0.25rem 0.5rem;
    border-radius: var(--pico-border-radius, 4px);
    scroll-margin-top: 1rem;
    line-height: 1.65;
  }
  .dispositivo:hover,
  .dispositivo:focus-within {
    background: var(--pico-form-element-background-color, rgba(128, 128, 128, 0.06));
  }
  .destaque {
    background: var(--pico-primary-focus, rgba(2, 154, 232, 0.18));
    outline: 2px solid var(--pico-primary, #0172ad);
    outline-offset: 1px;
  }
  .destaque:hover,
  .destaque:focus-within {
    background: var(--pico-primary-focus, rgba(2, 154, 232, 0.18));
  }

  .texto-dispositivo,
  .org-heading {
    margin: 0;
  }
  .rotulo {
    margin-right: 0.35rem;
  }
  .corpo {
    white-space: pre-line;
  }
  .sem-texto {
    color: var(--pico-muted-color, #777);
  }

  .org-heading {
    margin-top: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.02em;
    text-align: center;
    font-size: 0.95em;
  }
  .org-titulo {
    display: block;
    font-weight: 600;
  }

  .revogado > .texto-dispositivo,
  .revogado > .org-heading {
    opacity: 0.6;
    text-decoration: line-through;
  }
  .nota-revogado {
    margin: 0.1rem 0 0;
    font-size: 0.82em;
    color: var(--pico-muted-color, #777);
  }
  .nota-revogado code {
    font-size: 0.95em;
    word-break: break-all;
  }

  .acoes {
    position: absolute;
    top: 0.2rem;
    right: 0.3rem;
    display: none;
    gap: 0.25rem;
  }
  .dispositivo:hover > .acoes,
  .dispositivo:focus-within > .acoes {
    display: inline-flex;
  }
  .acao {
    /* botão discreto — sobrescreve o default do Pico */
    display: inline-block;
    width: auto;
    margin: 0;
    padding: 0.05rem 0.45rem;
    font-size: 0.72rem;
    line-height: 1.4;
    background: var(--pico-card-background-color, var(--pico-background-color, transparent));
    color: var(--pico-muted-color, #555);
    border: 1px solid var(--pico-muted-border-color, #ccc);
    border-radius: var(--pico-border-radius, 4px);
    box-shadow: none;
  }
  .acao:hover,
  .acao:focus {
    color: var(--pico-primary, #0172ad);
    border-color: var(--pico-primary, #0172ad);
    background: var(--pico-card-background-color, var(--pico-background-color, transparent));
  }

  .filhos {
    margin-left: 1.25rem;
  }
  .organizacional > .filhos {
    margin-left: 0;
  }

  @media (max-width: 640px) {
    .filhos {
      margin-left: 0.75rem;
    }
    /* Sem hover em touch: ações sempre visíveis, discretas */
    .acoes {
      display: inline-flex;
      position: static;
      margin-left: 0.5rem;
    }
  }
</style>
