<script lang="ts">
  // Página da lei — /lei/?id={lei_id}, deep-link por hash (#art-5-par-2).
  // Ilha client:only: location/document existem por construção.
  import { getLeiRows, type LeiRow } from '../../lib/db';
  import { formatEnte, leiTitle, withBase } from '../../lib/format';
  import DatasetUnavailable from '../DatasetUnavailable.svelte';
  import DispositivoTree from './DispositivoTree.svelte';
  import Versoes from './Versoes.svelte';
  import Evidencias from './Evidencias.svelte';
  import Dados from './Dados.svelte';
  import { buildTree, copyText, fmtDate } from './model';

  const leiId = new URLSearchParams(location.search).get('id')?.trim() ?? '';

  let rows = $state<LeiRow[]>([]);
  let loading = $state(Boolean(leiId));
  let error = $state<unknown>(null);

  // Dispositivo destacado pelo hash (deep-link); atualiza em hashchange.
  let highlight = $state<string | null>(null);

  const meta = $derived(rows[0] ?? null);
  const texto = $derived(buildTree(rows));
  const paths = $derived(new Set(rows.map((r) => r.dispositivo_path)));

  $effect(() => {
    if (!leiId) return;
    let cancelled = false;
    getLeiRows(leiId).then(
      (result) => {
        if (cancelled) return;
        rows = result;
        loading = false;
      },
      (err) => {
        if (cancelled) return;
        error = err;
        loading = false;
      },
    );
    return () => {
      cancelled = true;
    };
  });

  // Título do documento após carregar — mesmo padrão do Layout ("… — Leizilla").
  $effect(() => {
    if (meta) document.title = `${leiTitle(meta)} — Leizilla`;
  });

  function resolveHash(scroll: boolean) {
    const raw = location.hash.slice(1);
    if (!raw) return;
    let path: string;
    try {
      path = decodeURIComponent(raw);
    } catch {
      path = raw;
    }
    if (!paths.has(path)) return; // âncoras de seção etc.: deixa o browser agir
    highlight = path;
    if (scroll) {
      document.getElementById(path)?.scrollIntoView({ block: 'start' });
    }
  }

  // Deep-link inicial: depois que a árvore renderizou (efeitos rodam pós-DOM).
  $effect(() => {
    if (loading || error || rows.length === 0) return;
    const raf = requestAnimationFrame(() => resolveHash(true));
    return () => cancelAnimationFrame(raf);
  });

  $effect(() => {
    const onHash = () => resolveHash(false);
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  });

  // Cópia da URN-LEX no cabeçalho.
  let urnCopiada = $state(false);
  let urnTimer: ReturnType<typeof setTimeout> | undefined;
  async function copiarUrn(urn: string) {
    if (!(await copyText(urn))) return;
    urnCopiada = true;
    clearTimeout(urnTimer);
    urnTimer = setTimeout(() => {
      urnCopiada = false;
    }, 1600);
  }
</script>

{#if !leiId}
  <article>
    <header><strong>Nenhuma norma selecionada</strong></header>
    <p>
      Esta página mostra uma norma específica e precisa do parâmetro
      <code>id</code> na URL (ex.: <code>/lei/?id=leizilla-ro-lei-00001</code>).
    </p>
    <p><a href={withBase('/')}>Voltar à busca</a></p>
  </article>
{:else if error}
  <DatasetUnavailable {error} />
{:else if loading}
  <p aria-busy="true">Carregando a norma…</p>
{:else if rows.length === 0}
  <article>
    <header><strong>Norma não encontrada no dataset publicado</strong></header>
    <p>
      Não há linhas para <code>{leiId}</code> no dataset atual. O dataset cobre
      apenas as normas que já alcançaram o estágio S4 (texto estruturado e
      validado); documentos apenas arquivados ou identificados ainda não
      aparecem aqui.
    </p>
    <p>
      <a
        href={`https://archive.org/search?query=${encodeURIComponent(leiId)}`}
        target="_blank"
        rel="noopener noreferrer"
      >
        Procurar evidências no Internet Archive
      </a>
      &nbsp;·&nbsp;
      <a href={withBase('/')}>Voltar à busca</a>
    </p>
  </article>
{:else if meta}
  <header class="lei-header">
    <hgroup>
      <h2>{leiTitle(meta)}</h2>
      <p>
        <span class="badge-ente">{formatEnte(meta.ente)}</span>
        {#if meta.data_publicacao}
          · Publicada em {fmtDate(meta.data_publicacao)}
        {/if}
        · Compilação vigente em {fmtDate(meta.vigente_em)}
      </p>
    </hgroup>

    {#if meta.urn_lex_lei}
      <p class="urn">
        <code>{meta.urn_lex_lei}</code>
        <button
          type="button"
          class="copiar-urn"
          onclick={() => copiarUrn(meta.urn_lex_lei ?? '')}
          title="Copiar URN-LEX"
        >
          {urnCopiada ? 'copiado!' : 'copiar'}
        </button>
      </p>
    {/if}

    {#if meta.lei_revogada}
      <article class="banner-revogada" role="alert">
        <strong>Norma revogada</strong>
        {#if meta.lei_revogada_em}em {fmtDate(meta.lei_revogada_em)}{/if}
        {#if meta.lei_revogada_tipo}({meta.lei_revogada_tipo}){/if}
        {#if meta.lei_revogada_por}, por <code>{meta.lei_revogada_por}</code>{/if}.
        O texto abaixo é mantido para consulta histórica.
      </article>
    {/if}
  </header>

  <nav class="secoes" aria-label="Seções desta página">
    <a href="#pagina-texto">Texto</a>
    <a href="#pagina-versoes">Versões</a>
    <a href="#pagina-evidencias">Evidências</a>
    <a href="#pagina-dados">Dados</a>
  </nav>

  <section id="pagina-texto" aria-labelledby="titulo-secao-texto">
    <h3 id="titulo-secao-texto">Texto</h3>
    {#if texto.ementa}
      <p class="ementa" id={texto.ementa.dispositivo_path}>
        {texto.ementa.texto ?? ''}
      </p>
    {/if}
    {#if texto.roots.length > 0}
      <div class="documento">
        <DispositivoTree nodes={texto.roots} {leiId} {highlight} />
      </div>
    {:else if !texto.ementa}
      <p>Nenhum dispositivo vigente registrado para esta norma.</p>
    {/if}
  </section>

  <section id="pagina-versoes" aria-labelledby="titulo-secao-versoes">
    <h3 id="titulo-secao-versoes">Versões</h3>
    <Versoes {rows} />
  </section>

  <section id="pagina-evidencias" aria-labelledby="titulo-secao-evidencias">
    <h3 id="titulo-secao-evidencias">Evidências</h3>
    <Evidencias {rows} {leiId} />
  </section>

  <section id="pagina-dados" aria-labelledby="titulo-secao-dados">
    <h3 id="titulo-secao-dados">Dados</h3>
    <Dados {rows} {leiId} />
  </section>
{/if}

<style>
  .lei-header {
    margin-bottom: 0.5rem;
  }
  .lei-header hgroup {
    margin-bottom: 0.5rem;
  }
  .badge-ente {
    display: inline-block;
    padding: 0.1rem 0.5rem;
    border: 1px solid var(--pico-muted-border-color, #bbb);
    border-radius: var(--pico-border-radius, 4px);
    font-size: 0.82em;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }
  .urn {
    margin: 0 0 0.5rem;
    font-size: 0.85em;
  }
  .urn code {
    word-break: break-all;
  }
  .copiar-urn {
    display: inline-block;
    width: auto;
    margin: 0 0 0 0.4rem;
    padding: 0.05rem 0.45rem;
    font-size: 0.72rem;
    line-height: 1.4;
    background: transparent;
    color: var(--pico-muted-color, #555);
    border: 1px solid var(--pico-muted-border-color, #ccc);
    border-radius: var(--pico-border-radius, 4px);
    box-shadow: none;
  }
  .copiar-urn:hover,
  .copiar-urn:focus {
    color: var(--pico-primary, #0172ad);
    border-color: var(--pico-primary, #0172ad);
  }

  .banner-revogada {
    margin: 0.75rem 0;
    padding: 0.6rem 0.9rem;
    border-left: 4px solid var(--pico-del-color, #c62828);
    background: var(--pico-card-sectioning-background-color, rgba(198, 40, 40, 0.08));
  }
  .banner-revogada code {
    word-break: break-all;
  }

  .secoes {
    display: flex;
    gap: 1rem;
    flex-wrap: wrap;
    margin: 0.75rem 0 1rem;
    padding-bottom: 0.4rem;
    border-bottom: 1px solid var(--pico-muted-border-color, #ddd);
    font-size: 0.95em;
  }
  .secoes a {
    text-decoration: none;
    font-weight: 600;
  }

  section {
    scroll-margin-top: 1rem;
    margin-bottom: 1.75rem;
  }
  h3 {
    margin-bottom: 0.6rem;
    font-size: 1.2em;
  }

  .ementa {
    font-style: italic;
    padding: 0.5rem 0.75rem;
    border-left: 4px solid var(--pico-primary, #0172ad);
    background: var(--pico-card-sectioning-background-color, rgba(128, 128, 128, 0.06));
    border-radius: var(--pico-border-radius, 4px);
    scroll-margin-top: 1rem;
    white-space: pre-line;
  }
  .documento {
    line-height: 1.65;
  }
</style>
