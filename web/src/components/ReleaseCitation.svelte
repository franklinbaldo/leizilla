<script lang="ts">
  // issue #175: DATASET_IA_ITEM é o ponteiro MUTÁVEL (`-latest`) — nunca cite esse
  // item por si só, porque o conteúdo por trás dele muda a cada release agendada.
  // Este componente resolve, em runtime, o identifier IMUTÁVEL que o ponteiro aponta
  // (publisher.upload_dataset publica um item novo por release, nunca reaproveitado) e
  // usa esse identifier na citação. Fail-open: sem resolução, cai numa citação genérica
  // que não finge precisão sobre qual release exata está em vigor.
  import { fetchLatestPointer, DATASET_PARQUET_URL, DATASET_IA_ITEM, type LatestPointer } from '../lib/db';
  import { iaDetailsUrl } from '../lib/format';

  let pointer = $state<LatestPointer | null>(null);
  let checked = $state(false);

  $effect(() => {
    let cancelled = false;
    fetchLatestPointer().then((p) => {
      if (!cancelled) {
        pointer = p;
        checked = true;
      }
    });
    return () => {
      cancelled = true;
    };
  });

  const gitShaShort = $derived(pointer?.git_sha ? pointer.git_sha.slice(0, 8) : null);
</script>

<p>
  <strong>Como citar:</strong> <em>Leizilla — legislação pública preservada, estruturada e
  auditável.</em> Dataset Parquet <code>versoes</code>, Internet Archive
  {#if pointer}
    (release imutável <a href={iaDetailsUrl(pointer.identifier)} rel="external"
      ><code>{pointer.identifier}</code></a
    >{#if gitShaShort}, commit <code>{gitShaShort}</code>{/if}). Disponível em
    <a href={pointer.parquet_url} rel="external">{pointer.parquet_url}</a>.
  {:else if checked}
    {#if DATASET_IA_ITEM}
      (item <code>{DATASET_IA_ITEM}</code>)
    {/if}
    . Disponível em <a href={DATASET_PARQUET_URL} rel="external">{DATASET_PARQUET_URL}</a>.
    <small
      >Não foi possível resolver a release imutável específica agora (rede indisponível ou
      dataset ainda não publicado) — o link acima aponta para o ponteiro da release
      corrente, que muda a cada publicação; para citar um snapshot fixo, use o
      <code>identifier</code> de <a href="{DATASET_PARQUET_URL.replace('versoes.parquet', 'latest.json')}" rel="external">latest.json</a>.</small
    >
  {:else}
    . Disponível em <a href={DATASET_PARQUET_URL} rel="external">{DATASET_PARQUET_URL}</a>.
  {/if}
</p>
