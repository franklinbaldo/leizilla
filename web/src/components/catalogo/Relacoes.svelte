<script lang="ts">
  // Relações entre normas (ADR-0017): o que esta norma altera/revoga e o que altera/revoga
  // esta norma, extraídas das ementas por regras. Relação sem norma correspondente no
  // catálogo aparece como texto, nunca como link.
  import { agruparRelacoes, type GrupoRelacao } from '../../lib/catalogo';
  import { getRelacoes, relacoesAvailable } from '../../lib/catalogoDb';

  let { normaId }: { normaId: string } = $props();

  let ativas = $state<GrupoRelacao[]>([]);
  let passivas = $state<GrupoRelacao[]>([]);
  let disponivel = $state(false);
  let carregando = $state(true);

  $effect(() => {
    let cancelado = false;
    carregando = true;
    relacoesAvailable()
      .then(async (ok) => {
        if (!ok) return null;
        return getRelacoes(normaId);
      })
      .then((rows) => {
        if (cancelado) return;
        disponivel = rows !== null;
        if (rows) {
          const g = agruparRelacoes(rows, normaId);
          ativas = g.ativas;
          passivas = g.passivas;
        }
        carregando = false;
      })
      .catch(() => {
        if (cancelado) return;
        disponivel = false;
        carregando = false;
      });
    return () => {
      cancelado = true;
    };
  });

  const total = $derived(
    ativas.reduce((n, g) => n + g.itens.length, 0) + passivas.reduce((n, g) => n + g.itens.length, 0),
  );
</script>

{#if disponivel && !carregando}
  <section class="relacoes" aria-labelledby="titulo-relacoes">
    <h3 id="titulo-relacoes">Relações com outras normas</h3>
    {#if total === 0}
      <p class="vazio">
        Nenhuma relação foi extraída das ementas para esta norma. Isso não quer dizer que
        não exista: só as formas usuais ("Altera a Lei nº…", "Revoga o Decreto nº…") são lidas.
      </p>
    {:else}
      {#each [...ativas, ...passivas] as grupo (grupo.rotulo)}
        <div class="grupo">
          <h4>{grupo.rotulo}</h4>
          <ul>
            {#each grupo.itens as item (item.id)}
              <li>
                {#if item.href}
                  <a href={item.href}>{item.titulo}</a>
                {:else}
                  <span class="sem-link">{item.titulo}</span>
                {/if}
                {#if item.parcial && (item.verbo === 'revoga' || item.verbo === 'altera')}
                  <small>(dispositivos)</small>
                {/if}
                {#if item.nota}
                  <small class="nota">— {item.nota}</small>
                {/if}
                {#if item.fonteIndice}
                  <small class="nota" title="Anotação editorial do índice oficial na ementa da norma revogada.">— anotação do índice</small>
                {/if}
              </li>
            {/each}
          </ul>
        </div>
      {/each}
    {/if}
    <p class="aviso-relacoes">
      <small>
        Relações extraídas automaticamente das ementas, por regras, sem ler o corpo das
        normas: podem estar incompletas. Referências que não correspondem a uma norma do
        índice oficial (leis federais, Constituição, normas ausentes) aparecem como texto,
        sem link.
      </small>
    </p>
  </section>
{/if}

<style>
  .relacoes {
    margin-bottom: 1.5rem;
    overflow-wrap: anywhere;
  }
  .grupo h4 {
    margin: 0.8rem 0 0.25rem;
    font-size: 1rem;
  }
  .grupo ul {
    margin: 0;
  }
  .sem-link {
    color: var(--pico-muted-color);
  }
  .nota,
  .vazio,
  .aviso-relacoes {
    color: var(--pico-muted-color);
  }
</style>
