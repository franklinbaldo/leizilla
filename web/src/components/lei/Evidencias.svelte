<script lang="ts">
  // Superfície de auditoria: estágio do funil, fontes (IA), integridade por
  // dispositivo e os sidecars de parse. Links honestos: ids raw vivem dentro
  // de itens-balde (ADR-0010/0011), então resolvemos por busca no IA.
  import type { LeiRow } from '../../lib/db';
  import {
    STAGES,
    breadcrumb,
    iaDetailsUrl,
    lawXmlUrl,
    parsedMetaUrl,
  } from '../../lib/format';
  import { aggregateFontes, copyText, currentRows, iaSearchUrl } from './model';

  let { rows, leiId }: { rows: LeiRow[]; leiId: string } = $props();

  const s4 = STAGES.find((s) => s.id === 'S4')!;
  const fontes = $derived(aggregateFontes(rows));
  const vigentes = $derived(
    currentRows(rows).sort(
      (a, b) =>
        Number(a.dispositivo_ordem) - Number(b.dispositivo_ordem) ||
        a.dispositivo_path.localeCompare(b.dispositivo_path),
    ),
  );
  const temDivergencia = $derived(rows.some((r) => r.tem_divergencia));

  let copiedHash = $state<string | null>(null);
  let copyTimer: ReturnType<typeof setTimeout> | undefined;
  async function copiarHash(key: string, hash: string) {
    if (!(await copyText(hash))) return;
    copiedHash = key;
    clearTimeout(copyTimer);
    copyTimer = setTimeout(() => {
      copiedHash = null;
    }, 1600);
  }
</script>

<h4>Estágio de processamento</h4>
<p>
  <span class="badge-estagio">{s4.id} · {s4.label}</span>
</p>
<p>{s4.description}</p>
<p>
  As evidências dos estágios anteriores — documento original arquivado (S1),
  identificação (S2) e texto extraído (S3) — vivem no Internet Archive, nos
  itens de fonte listados abaixo.
</p>

<h4>Fontes</h4>
{#if fontes.length === 0}
  <p>Nenhuma fonte registrada nas versões deste dataset.</p>
{:else}
  <ul class="fontes">
    {#each fontes as fonte (fonte.ia_id)}
      <li>
        <code>{fonte.ia_id}</code>
        —
        <a href={iaSearchUrl(fonte.ia_id)} target="_blank" rel="noopener noreferrer">
          localizar evidência no IA
        </a>
        {#if fonte.diverge}
          <mark class="diverge">fontes divergem</mark>
          {#each fonte.textos_divergentes as texto}
            <details>
              <summary>texto divergente registrado</summary>
              <blockquote class="texto-divergente">{texto}</blockquote>
            </details>
          {/each}
        {/if}
      </li>
    {/each}
  </ul>
  <p class="nota">
    <small>
      Os identificadores lógicos apontam para arquivos dentro de itens-balde
      por faixa no Internet Archive (ADR-0010/0011); por isso o link é uma
      busca, não um endereço direto — o endereço direto poderia não existir.
    </small>
  </p>
{/if}

<h4>Integridade</h4>
<p>
  {#if temDivergencia}
    <mark class="diverge">Há divergência entre fontes em ao menos uma versão.</mark>
  {:else}
    Nenhuma divergência entre fontes registrada nas versões desta norma.
  {/if}
</p>
<details>
  <summary>
    Hash do texto por dispositivo vigente ({vigentes.length})
  </summary>
  <div class="tabela-scroll">
    <table>
      <thead>
        <tr>
          <th scope="col">Dispositivo</th>
          <th scope="col">sha256 do texto</th>
          <th scope="col">Fontes</th>
          <th scope="col">Divergência</th>
        </tr>
      </thead>
      <tbody>
        {#each vigentes as row (row.dispositivo_path)}
          <tr>
            <td><a href={`#${row.dispositivo_path}`}>{breadcrumb(row.dispositivo_path)}</a></td>
            <td>
              {#if row.hash_texto}
                <button
                  type="button"
                  class="hash"
                  title={`Copiar sha256 completo: ${row.hash_texto}`}
                  onclick={() => copiarHash(row.dispositivo_path, row.hash_texto ?? '')}
                >
                  <code>
                    {copiedHash === row.dispositivo_path
                      ? 'copiado!'
                      : `${row.hash_texto.slice(0, 12)}…`}
                  </code>
                </button>
              {:else}
                —
              {/if}
            </td>
            <td>{Number(row.num_fontes)}</td>
            <td>{row.tem_divergencia ? 'sim' : 'não'}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
</details>

<h4>Trilhas de auditoria</h4>
<ul>
  <li>
    <a href={iaDetailsUrl(leiId)} target="_blank" rel="noopener noreferrer">
      Item estruturado no Internet Archive
    </a>
    — <code>{leiId}</code>
  </li>
  <li>
    <a href={lawXmlUrl(leiId)} target="_blank" rel="noopener noreferrer">
      XML canônico (law.xml)
    </a>
  </li>
  <li>
    <a href={parsedMetaUrl(leiId)} target="_blank" rel="noopener noreferrer">
      Metadados do parse (parsed_meta.json)
    </a>
    — contém o grau de confiança da estruturação, o modelo usado e o timestamp
    do parse.
  </li>
</ul>
<p class="nota">
  <small>
    O grau de confiança e a data de captura não estão neste dataset: vivem
    nesses arquivos auxiliares publicados junto do item estruturado.
  </small>
</p>

<style>
  h4 {
    margin: 1.25rem 0 0.5rem;
    font-size: 1.05em;
  }
  .badge-estagio {
    display: inline-block;
    padding: 0.15rem 0.6rem;
    border: 1px solid var(--pico-primary, #0172ad);
    border-radius: var(--pico-border-radius, 4px);
    color: var(--pico-primary, #0172ad);
    font-weight: 600;
    font-size: 0.9em;
  }
  .fontes code {
    word-break: break-all;
  }
  .diverge {
    margin-left: 0.35rem;
    font-size: 0.85em;
  }
  .texto-divergente {
    white-space: pre-line;
    font-size: 0.9em;
  }
  .nota {
    color: var(--pico-muted-color, #666);
  }
  .tabela-scroll {
    overflow-x: auto;
  }
  table {
    font-size: 0.88em;
  }
  .hash {
    /* botão-texto discreto, sem cara de botão do Pico */
    display: inline;
    width: auto;
    margin: 0;
    padding: 0;
    background: transparent;
    border: none;
    box-shadow: none;
    color: inherit;
    cursor: pointer;
  }
  .hash code {
    white-space: nowrap;
  }
  .hash:hover code,
  .hash:focus code {
    outline: 1px solid var(--pico-primary, #0172ad);
  }
</style>
