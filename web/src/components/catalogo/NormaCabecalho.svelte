<script lang="ts">
  // Cabeçalho oficial de uma norma (ADR-0017): título, data, ementa e situação lidos do
  // índice da Casa Civil, o estágio que o Leizilla alcançou e os links para os arquivos.
  // Nada aqui vem de OCR nem de modelo.
  import {
    ESTAGIO_DESCRICAO,
    ESTAGIO_ROTULO,
    RENDICAO_ROTULO,
    SITUACAO_DESCRICAO,
    estagioDe,
    parseArquivos,
    situacaoRotulo,
    tipoRotulo,
    type CatalogoRow,
  } from '../../lib/catalogo';
  import { formatDate, iaDetailsUrl } from '../../lib/format';

  let {
    row,
    compacto = false,
  }: { row: CatalogoRow; compacto?: boolean } = $props();

  const estagio = $derived(estagioDe(row));
  const situacao = $derived(situacaoRotulo(row.situacao_norma));
  const arquivos = $derived(parseArquivos(row.arquivos));
</script>

<section class="catalogo-cabecalho" aria-label="Dados do índice oficial">
  {#if !compacto}
    <hgroup>
      <h2>{row.titulo}</h2>
      <p>
        {tipoRotulo(row.tipo)}{#if row.data}
          · data do ato {formatDate(row.data)}{/if}
      </p>
    </hgroup>
  {:else}
    <p class="compacto-titulo">
      <strong>Índice oficial:</strong>
      {row.titulo}
    </p>
  {/if}

  <p class="selos">
    <span class="selo selo-estagio" title={ESTAGIO_DESCRICAO[estagio]}>
      {ESTAGIO_ROTULO[estagio]}
    </span>
    {#if situacao}
      <span
        class="selo selo-situacao"
        title={SITUACAO_DESCRICAO[row.situacao_norma ?? ''] ?? ''}
      >
        {situacao}
      </span>
    {/if}
    {#if row.identidade_incerta}
      <span
        class="selo selo-incerta"
        title="O número desta norma no índice oficial diverge do nome do arquivo e não pôde ser confirmado."
      >
        Identidade incerta
      </span>
    {/if}
  </p>

  {#if row.ementa}
    <p class="ementa">{row.ementa}</p>
  {:else}
    <p class="ementa sem-ementa">O índice oficial não traz ementa para esta norma.</p>
  {/if}

  <p class="acoes">
    {#if row.url_ia}
      <a href={row.url_ia} target="_blank" rel="noopener noreferrer">Cópia preservada no Internet Archive (PDF)</a>
    {/if}
    {#if row.ia_item && row.url_ia}
      <a href={iaDetailsUrl(row.ia_item)} target="_blank" rel="noopener noreferrer">item no Internet Archive</a>
    {/if}
  </p>

  {#if arquivos.length > 0}
    <details class="arquivos">
      <summary>
        {arquivos.length === 1 ? 'Arquivo no índice oficial' : `${arquivos.length} arquivos no índice oficial`}
      </summary>
      <ul>
        {#each arquivos as a (a.url)}
          <li>
            <a href={a.url} target="_blank" rel="noopener noreferrer">{a.nome}</a>
            <small>({RENDICAO_ROTULO[a.rendicao] ?? a.rendicao})</small>
          </li>
        {/each}
      </ul>
    </details>
  {:else if !row.url_ia}
    <p class="sem-arquivo">O índice oficial não lista arquivo para esta norma.</p>
  {/if}

  <p class="nota-fonte">
    <small>
      Título, data, ementa e situação vêm do índice oficial da Casa Civil de Rondônia
      {#if row.catalogo_obtido_em}(lido em {formatDate(row.catalogo_obtido_em)}){/if}; o
      Leizilla não os interpreta. "Revogada" ou "retificada" é a marca do índice, não uma
      conclusão sobre a vigência.
    </small>
  </p>
</section>

<style>
  .catalogo-cabecalho {
    margin-bottom: 1.25rem;
    overflow-wrap: anywhere;
  }
  .catalogo-cabecalho hgroup {
    margin-bottom: 0.5rem;
  }
  .compacto-titulo {
    margin-bottom: 0.4rem;
  }
  .selos {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    margin-bottom: 0.6rem;
  }
  .selo {
    display: inline-block;
    padding: 0.1rem 0.5rem;
    border: 1px solid var(--pico-muted-border-color, #bbb);
    border-radius: var(--pico-border-radius, 4px);
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    white-space: nowrap;
  }
  .selo-estagio {
    border-color: var(--pico-primary, #0172ad);
    color: var(--pico-primary, #0172ad);
  }
  .selo-situacao {
    border-color: var(--pico-del-color, #c0392b);
    color: var(--pico-del-color, #c0392b);
  }
  .selo-incerta {
    border-style: dashed;
  }
  .ementa {
    line-height: 1.55;
    margin-bottom: 0.6rem;
  }
  .sem-ementa,
  .sem-arquivo {
    font-style: italic;
    color: var(--pico-muted-color);
  }
  .acoes {
    display: flex;
    flex-wrap: wrap;
    gap: 0.3rem 1.2rem;
    margin-bottom: 0.4rem;
  }
  .arquivos {
    margin-bottom: 0.4rem;
  }
  .arquivos ul {
    margin: 0.3rem 0 0;
  }
  .nota-fonte {
    color: var(--pico-muted-color);
    margin: 0.4rem 0 0;
  }
</style>
