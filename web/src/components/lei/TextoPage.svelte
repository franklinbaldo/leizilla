<script lang="ts">
  // Leitura de uma norma pela camada de texto (ADR-0015): OCR verbatim do
  // Internet Archive, sem estrutura. O texto nunca é alterado aqui — as âncoras
  // de artigo só dividem o texto em trechos com id, e só quando a sequência fecha.
  import { getStructuredLeiId, getTexto, type TextoRow } from '../../lib/db';
  import { formatDate, formatEnte, iaDetailsUrl, leiTitle, leiUrl, withBase } from '../../lib/format';
  import {
    ocrEhProprio,
    paragrafos,
    parseAncoras,
    parseOutrasRendicoes,
    rotuloRendicao,
    segmentar,
  } from '../../lib/textos';
  import DatasetUnavailable from '../DatasetUnavailable.svelte';

  // `embedded`: a página da norma (catálogo oficial) já mostra o título; aqui só o texto.
  let { textoId, embedded = false }: { textoId: string; embedded?: boolean } = $props();

  let row = $state<TextoRow | null>(null);
  let estruturadaId = $state<string | null>(null);
  let loading = $state(true);
  let error = $state<unknown>(null);
  // Apresentação: por padrão as quebras simples do OCR (uma palavra por linha em
  // originais datilografados) são recolhidas pelo CSS; o texto no DOM é o mesmo.
  let quebrasOriginais = $state(false);

  const titulo = $derived(
    row
      ? leiTitle({ tipo_lei: row.tipo, numero_lei: String(row.numero), ano_lei: null })
      : '',
  );
  const segmentos = $derived(
    row
      ? segmentar(row.texto, row.artigos_fecham ? parseAncoras(row.ancoras) : [])
      : [],
  );
  const artigos = $derived(segmentos.filter((s) => s.id !== null));
  // OCR feito pelo próprio Leizilla (ADR-0019), quando o IA não tem texto deste documento.
  const ocrProprio = $derived(row ? ocrEhProprio(row.ocr_motor) : false);
  // Rendição do arquivo exibido e os outros arquivos da norma (ADR-0015, adendo 2026-11-18).
  const compilada = $derived(row?.rendicao === 'compilada');
  const outras = $derived(row ? parseOutrasRendicoes(row.outras_rendicoes) : []);
  const publicadaPor = $derived(row?.fonte === 'casacivil' ? 'pela Casa Civil' : 'pela fonte oficial');

  $effect(() => {
    let cancelled = false;
    Promise.all([getTexto(textoId), getStructuredLeiId(textoId).catch(() => null)]).then(
      ([texto, leiId]) => {
        if (cancelled) return;
        row = texto;
        estruturadaId = leiId;
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

  $effect(() => {
    if (row && !embedded) document.title = `${titulo} — Leizilla`;
  });

  // Deep-link (#art-5): os alvos só existem depois do render.
  $effect(() => {
    if (!row || artigos.length === 0 || !location.hash) return;
    const raf = requestAnimationFrame(() => {
      let id = location.hash.slice(1);
      try {
        id = decodeURIComponent(id);
      } catch {
        /* usa o hash cru */
      }
      document.getElementById(id)?.scrollIntoView({ block: 'start' });
    });
    return () => cancelAnimationFrame(raf);
  });
</script>

{#if error}
  <DatasetUnavailable {error} />
{:else if loading}
  <p aria-busy="true">Carregando o texto da norma…</p>
{:else if !row && embedded}
  <p class="sem-texto-embutido">
    O texto desta norma ainda não foi publicado na camada de texto.
  </p>
{:else if !row}
  <article>
    <header><strong>Texto não encontrado</strong></header>
    <p>
      Não há texto publicado para <code>{textoId}</code>. A camada de texto cobre as
      normas que já têm OCR no Internet Archive; documentos apenas arquivados ainda
      não aparecem aqui.
    </p>
    {#if estruturadaId}
      <p><a href={leiUrl(estruturadaId)}>Abrir a versão estruturada desta norma</a></p>
    {/if}
    <p>
      <a
        href={`https://archive.org/search?query=${encodeURIComponent(textoId)}`}
        target="_blank"
        rel="noopener noreferrer"
      >
        Procurar evidências no Internet Archive
      </a>
      &nbsp;·&nbsp;
      <a href={withBase('/')}>Voltar à busca</a>
    </p>
  </article>
{:else}
  <header class="texto-header">
    {#if embedded}
      <p>
        <span class="selo">{formatEnte(row.ente)}</span>
        <span class="selo selo-nao-estruturado">Texto não estruturado</span>
        <span class="selo selo-rendicao">{rotuloRendicao(row.rendicao)}</span>
      </p>
    {:else}
      <hgroup>
        <h2>{titulo}</h2>
        <p>
          <span class="selo">{formatEnte(row.ente)}</span>
          <span class="selo selo-nao-estruturado">Texto não estruturado</span>
          <span class="selo selo-rendicao">{rotuloRendicao(row.rendicao)}</span>
        </p>
      </hgroup>
    {/if}

    <article class="aviso">
      <p>
        Este é o texto extraído por OCR {compilada ? 'do documento compilado' : 'do documento original'}, <strong>sem revisão
        e sem estrutura</strong>: pode conter erros de reconhecimento, e a divisão
        em dispositivos ainda não foi validada. Em caso de dúvida, vale o ato como
        publicado oficialmente.
      </p>
      {#if compilada}
        <p class="rendicao-compilada">
          Este é o <strong>texto compilado</strong>: a versão compilada publicada
          {publicadaPor}{#if row.capturado_em}, capturada em {formatDate(row.capturado_em)}{/if}.
          Não é uma consolidação feita ou conferida pelo Leizilla; a compilação pode trazer
          trechos anotados ou tachados (redações dadas, revogações).
        </p>
      {/if}
      {#if row.defeito_fonte}
        <p class="defeito-fonte" data-testid="defeito-fonte">
          <strong>Nota sobre o arquivo oficial:</strong> {row.defeito_fonte}
        </p>
      {/if}
      {#if ocrProprio}
        <p>
          Este texto foi feito pelo OCR do próprio Leizilla, porque o Internet Archive
          ainda não tem texto deste documento.
        </p>
      {/if}
      <p class="acoes">
        <a href={row.pdf_url} target="_blank" rel="noopener noreferrer">
          {compilada ? 'Abrir o PDF compilado no Internet Archive' : 'Abrir o PDF original no Internet Archive'}
        </a>
        {#if estruturadaId}
          &nbsp;·&nbsp;
          <a href={leiUrl(estruturadaId)}>Ver a versão estruturada desta norma</a>
        {/if}
      </p>
      {#if outras.length > 0}
        <p class="outras" data-testid="outras-rendicoes">
          Também preservado{outras.length > 1 ? 's' : ''} no Internet Archive:
          {#each outras as outra, i (outra.sha256)}
            {#if i > 0}&nbsp;·&nbsp;{/if}
            <a href={outra.pdf_url} target="_blank" rel="noopener noreferrer">
              PDF do {rotuloRendicao(outra.rendicao)}
            </a>
            {#if outra.texto_url}
              (<a href={outra.texto_url} target="_blank" rel="noopener noreferrer">texto</a>)
            {/if}
          {/each}
        </p>
      {/if}
    </article>
  </header>

  {#if artigos.length > 0}
    <details class="artigos">
      <summary>Ir para um artigo ({artigos.length})</summary>
      <nav aria-label="Artigos desta norma">
        {#each artigos as artigo (artigo.id)}
          <a href={`#${artigo.id}`}>{artigo.rotulo}</a>
        {/each}
      </nav>
    </details>
  {/if}

  <section aria-labelledby="titulo-texto">
    <h3 id="titulo-texto">Texto</h3>
    <label class="quebras">
      <input type="checkbox" bind:checked={quebrasOriginais} />
      Mostrar as quebras de linha do documento original
    </label>
    <div class="texto-ocr" class:original={quebrasOriginais}>
      {#each segmentos as segmento, i (i)}<span class="trecho" id={segmento.id ?? undefined}
          >{#each paragrafos(segmento.texto) as par, j (j)}<span class="par">{par}</span
            >{/each}</span
        >{/each}
    </div>
  </section>

  <section aria-labelledby="titulo-origem">
    <h3 id="titulo-origem">Origem do texto</h3>
    <dl class="origem">
      <dt>{compilada ? 'Documento compilado' : 'Documento original'}</dt>
      <dd>
        <a href={row.pdf_url} target="_blank" rel="noopener noreferrer">PDF</a>
        no item
        <a href={iaDetailsUrl(row.ia_item)} target="_blank" rel="noopener noreferrer">
          <code>{row.ia_item}</code>
        </a>
        {#if row.capturado_em}· capturado em {formatDate(row.capturado_em)}{/if}
      </dd>
      <dt>SHA-256 do documento</dt>
      <dd><code>{row.sha256_fonte}</code></dd>
      <dt>OCR</dt>
      <dd>
        {row.ocr_motor ?? 'motor não declarado pelo Internet Archive'}
        {#if row.ocr_derivado_em}· gerado em {formatDate(row.ocr_derivado_em)}{/if}
        {#if row.texto_url}
          ·
          <a href={row.texto_url} target="_blank" rel="noopener noreferrer">arquivo de texto</a>
        {/if}
      </dd>
      {#if row.sha256_texto}
        <dt>SHA-256 do texto</dt>
        <dd><code>{row.sha256_texto}</code></dd>
      {/if}
      <dt>Navegação por artigo</dt>
      <dd>
        {#if row.artigos_fecham}
          {row.artigos_total} marcadores de artigo localizados automaticamente; o
          texto não foi alterado.
        {:else}
          indisponível: a sequência de artigos não pôde ser confirmada neste texto.
        {/if}
      </dd>
    </dl>
  </section>
{/if}

<style>
  .sem-texto-embutido {
    color: var(--pico-muted-color);
  }
  .texto-header hgroup {
    margin-bottom: 0.5rem;
  }
  .selo {
    display: inline-block;
    padding: 0.1rem 0.5rem;
    border: 1px solid var(--pico-muted-border-color, #bbb);
    border-radius: var(--pico-border-radius, 4px);
    font-size: 0.82em;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }
  .selo-rendicao {
    text-transform: none;
    font-weight: 500;
  }
  .selo-nao-estruturado {
    border-color: var(--pico-primary, #0172ad);
    color: var(--pico-primary, #0172ad);
  }
  .aviso {
    margin: 0.75rem 0 1rem;
    padding: 0.6rem 0.9rem;
    border-left: 4px solid var(--pico-primary, #0172ad);
  }
  .aviso p {
    margin: 0 0 0.4rem;
  }
  .aviso .acoes,
  .aviso .outras {
    margin: 0 0 0.4rem;
  }
  .artigos {
    margin-bottom: 1rem;
  }
  .artigos nav {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem 0.9rem;
    font-size: 0.9em;
  }
  .artigos nav a {
    white-space: nowrap;
  }
  section {
    margin-bottom: 1.75rem;
  }
  h3 {
    margin-bottom: 0.6rem;
    font-size: 1.2em;
  }
  .quebras {
    font-size: 0.85em;
    color: var(--pico-muted-color);
    margin-bottom: 0.75rem;
  }
  .texto-ocr {
    overflow-wrap: anywhere;
    line-height: 1.6;
  }
  .texto-ocr .trecho,
  .texto-ocr .par {
    display: block;
  }
  .texto-ocr .par {
    margin-bottom: 0.6em;
  }
  .texto-ocr.original {
    white-space: pre-wrap;
  }
  .texto-ocr.original .trecho,
  .texto-ocr.original .par {
    display: inline;
    margin: 0;
  }
  .texto-ocr .trecho {
    scroll-margin-top: 1rem;
  }
  .texto-ocr .trecho:target {
    box-shadow: -0.6rem 0 0 -0.35rem var(--pico-primary, #0172ad);
  }
  .origem dt {
    font-weight: 600;
    font-size: 0.85em;
    color: var(--pico-muted-color);
  }
  .origem dd {
    margin: 0 0 0.6rem;
  }
  .origem code {
    word-break: break-all;
  }
</style>
