<script lang="ts">
  import type { LeiRow } from '../lib/db.ts';

  let {
    row,
    searchTerm = '',
    onSelect,
  }: {
    row: LeiRow;
    searchTerm?: string;
    onSelect?: (row: LeiRow) => void;
  } = $props();

  const enteLabel: Record<string, string> = {
    ro: 'Rondônia',
    federal: 'Federal',
    sp: 'São Paulo',
  };

  const isRevogado = row.ate != null;
  const yearStr = row.em instanceof Date
    ? String(row.em.getFullYear())
    : (row.em ? String(row.em).slice(0, 4) : null);

  function escapeHtml(s: string): string {
    return s
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function highlight(text: string | null, term: string): string {
    const safe = escapeHtml(text ?? '');
    if (!safe) return '(sem texto)';
    if (!term.trim()) return safe;
    const termRe = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return safe.replace(
      new RegExp(termRe, 'gi'),
      (m) => `<mark>${escapeHtml(m)}</mark>`,
    );
  }

  const preview = $derived.by(() => {
    const text = row.texto_normalizado;
    const short = text && text.length > 200 ? text.slice(0, 200) + '…' : text;
    return highlight(short, searchTerm);
  });

  function handleClick() {
    onSelect?.(row);
  }
</script>

<article
  class:revogado={isRevogado}
  onclick={handleClick}
  role="button"
  tabindex="0"
  onkeydown={(e) => e.key === 'Enter' && handleClick()}
  aria-label="Ver detalhes de {row.lei_id}"
>
  <header>
    <div class="law-id">
      <strong>{row.lei_id}</strong>
      {#if row.dispositivo_path !== 'ementa'}
        <small class="path">&sect; {row.dispositivo_path}</small>
      {/if}
    </div>
    <div class="meta">
      {#if row.ente}
        <span class="badge ente">{enteLabel[row.ente] ?? row.ente}</span>
      {/if}
      {#if row.dispositivo_tipo}
        <span class="badge tipo">{row.dispositivo_tipo}</span>
      {/if}
      {#if yearStr}
        <span class="badge date">{yearStr}</span>
      {/if}
      {#if isRevogado}
        <span class="badge revogado-badge">revogado</span>
      {/if}
    </div>
  </header>
  <!-- eslint-disable-next-line svelte/no-at-html-tags -->
  <p>{@html preview}</p>
</article>

<style>
  article {
    background: var(--glass-bg, rgba(255, 255, 255, 0.05));
    border: 1px solid var(--glass-border, rgba(255, 255, 255, 0.1));
    backdrop-filter: var(--glass-blur, blur(12px));
    -webkit-backdrop-filter: var(--glass-blur, blur(12px));
    border-radius: 0.75rem;
    padding: 1rem;
    cursor: pointer;
    transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
    margin: 0;
  }

  article:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3),
      0 0 0 1px var(--accent-glow, rgba(124, 58, 237, 0.3));
    border-color: var(--accent-light, #a78bfa);
  }

  article:focus-visible {
    outline: 2px solid var(--accent-light, #a78bfa);
    outline-offset: 2px;
  }

  article.revogado {
    opacity: 0.55;
  }

  header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 0.5rem;
    flex-wrap: wrap;
    margin-bottom: 0.5rem;
    padding: 0;
    background: none;
    border: none;
  }

  .law-id {
    display: flex;
    align-items: center;
    gap: 0.4rem;
  }

  .path {
    color: var(--pico-muted-color);
    font-size: 0.8rem;
  }

  .meta {
    display: flex;
    gap: 0.3rem;
    flex-wrap: wrap;
    align-items: center;
  }

  .badge {
    font-size: 0.7rem;
    padding: 0.15rem 0.45rem;
    border-radius: 999px;
    white-space: nowrap;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }

  .badge.ente {
    background: rgba(124, 58, 237, 0.2);
    color: #c4b5fd;
    border: 1px solid rgba(124, 58, 237, 0.3);
  }

  .badge.tipo {
    background: rgba(59, 130, 246, 0.15);
    color: #93c5fd;
    border: 1px solid rgba(59, 130, 246, 0.25);
  }

  .badge.date {
    background: rgba(16, 185, 129, 0.15);
    color: #6ee7b7;
    border: 1px solid rgba(16, 185, 129, 0.25);
  }

  .badge.revogado-badge {
    background: rgba(239, 68, 68, 0.15);
    color: #fca5a5;
    border: 1px solid rgba(239, 68, 68, 0.25);
  }

  p {
    margin: 0;
    font-size: 0.9rem;
    line-height: 1.5;
    color: var(--pico-muted-color);
    overflow: hidden;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
  }

  :global(mark) {
    background: rgba(250, 204, 21, 0.3);
    color: #fde68a;
    border-radius: 2px;
    padding: 0 1px;
  }
</style>
