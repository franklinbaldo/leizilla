<script lang="ts">
  // Linha do tempo por dispositivo — apenas o que o dataset registra hoje.
  // A consolidação temporal entre normas (S5) ainda não existe; dizemos isso.
  import type { LeiRow } from '../../lib/db';
  import { breadcrumb } from '../../lib/format';
  import { fmtDate, groupHistorico, inicioTipoLabel } from './model';

  let { rows }: { rows: LeiRow[] } = $props();

  const historico = $derived(groupHistorico(rows));
</script>

<p class="aviso-s5">
  <strong>Linha do tempo parcial</strong> — a consolidação temporal entre normas
  (estágio S5) ainda não foi implementada; alterações podem estar ausentes.
</p>

{#if historico.length === 0}
  <p>
    Nenhum dispositivo desta norma tem mais de uma versão registrada no dataset:
    todo o texto está na redação original conhecida.
  </p>
{:else}
  <p>
    {historico.length}
    dispositivo{historico.length !== 1 ? 's' : ''} com histórico de versões:
  </p>
  {#each historico as grupo (grupo.path)}
    <section class="historico">
      <h4><a href={`#${grupo.path}`}>{breadcrumb(grupo.path)}</a></h4>
      <ul>
        {#each grupo.versions as v (v.versao_id)}
          <li>
            <span class="periodo">
              de <strong>{fmtDate(v.em)}</strong>
              até <strong>{v.ate == null ? 'vigente' : fmtDate(v.ate)}</strong>
            </span>
            <span class="inicio">— {inicioTipoLabel(v.inicio_tipo)}</span>
            {#if v.alterado_por}
              <span class="alterado">— alterado por <code>{v.alterado_por}</code></span>
            {/if}
          </li>
        {/each}
      </ul>
    </section>
  {/each}
{/if}

<style>
  .aviso-s5 {
    padding: 0.5rem 0.75rem;
    border-left: 4px solid var(--pico-muted-border-color, #999);
    background: var(--pico-card-sectioning-background-color, rgba(128, 128, 128, 0.08));
    border-radius: var(--pico-border-radius, 4px);
    font-size: 0.9em;
  }
  .historico {
    margin-bottom: 0.75rem;
  }
  .historico h4 {
    margin-bottom: 0.25rem;
    font-size: 1em;
  }
  .historico ul {
    margin-bottom: 0;
  }
  .historico li {
    font-size: 0.92em;
  }
  .inicio,
  .alterado {
    color: var(--pico-muted-color, #666);
  }
  .alterado code {
    font-size: 0.9em;
    word-break: break-all;
  }
</style>
