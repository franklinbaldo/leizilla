<script lang="ts">
  import type { LeiRow } from '../lib/db.ts';

  let {
    row,
    searchTerm = '',
    onClose,
  }: {
    row: LeiRow;
    searchTerm?: string;
    onClose: () => void;
  } = $props();

  const iaUrl = `https://archive.org/details/${row.lei_id}`;

  const enteLabel: Record<string, string> = {
    ro: 'Rondônia',
    federal: 'Federal',
    sp: 'São Paulo',
  };

  const dateStr = row.em instanceof Date
    ? row.em.toISOString().slice(0, 10)
    : (row.em ? String(row.em).slice(0, 10) : null);

  const revokedStr = row.ate instanceof Date
    ? row.ate.toISOString().slice(0, 10)
    : (row.ate ? String(row.ate).slice(0, 10) : null);

  function escapeHtml(s: string): string {
    return s
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function highlight(text: string | null, term: string): string {
    const safe = escapeHtml(text ?? '');
    if (!safe) return '(sem texto OCR disponível)';
    if (!term.trim()) return safe;
    const termRe = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return safe.replace(
      new RegExp(termRe, 'gi'),
      (m) => `<mark>${escapeHtml(m)}</mark>`,
    );
  }

  const highlightedText = $derived(highlight(row.texto_normalizado, searchTerm));

  // Focus management: move focus into panel on open, restore on close.
  let panelEl: HTMLElement;
  let closeBtn: HTMLButtonElement;

  $effect(() => {
    const prev = document.activeElement as HTMLElement | null;
    closeBtn?.focus();
    return () => {
      prev?.focus();
    };
  });

  function focusableElements(): HTMLElement[] {
    return Array.from(
      panelEl?.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ) ?? [],
    );
  }

  function handlePanelKeydown(e: KeyboardEvent) {
    if (e.key !== 'Tab') return;
    const els = focusableElements();
    if (els.length === 0) return;
    const first = els[0];
    const last = els[els.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  function handleBackdropClick(e: MouseEvent) {
    if (e.target === e.currentTarget) onClose();
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA') return;
      onClose();
    }
  }
</script>

<svelte:window onkeydown={handleKeydown} />

<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
<div class="backdrop" onclick={handleBackdropClick} role="dialog" aria-modal="true" aria-label={`Detalhes da lei ${row.lei_id}`}>
  <aside class="panel" bind:this={panelEl} onkeydown={handlePanelKeydown}>
    <div class="panel-header">
      <h2>{row.lei_id}</h2>
      <button bind:this={closeBtn} class="close-btn" onclick={onClose} aria-label="Fechar">&times;</button>
    </div>

    <div class="meta-grid">
      {#if row.ente}
        <div class="meta-item">
          <span class="meta-label">Ente</span>
          <span class="meta-value">{enteLabel[row.ente] ?? row.ente}</span>
        </div>
      {/if}
      {#if row.dispositivo_tipo}
        <div class="meta-item">
          <span class="meta-label">Tipo</span>
          <span class="meta-value">{row.dispositivo_tipo}</span>
        </div>
      {/if}
      {#if dateStr}
        <div class="meta-item">
          <span class="meta-label">Vigência</span>
          <span class="meta-value">{dateStr}</span>
        </div>
      {/if}
      {#if revokedStr}
        <div class="meta-item">
          <span class="meta-label">Revogado em</span>
          <span class="meta-value revogado">{revokedStr}</span>
        </div>
      {/if}
      {#if row.dispositivo_path && row.dispositivo_path !== 'ementa'}
        <div class="meta-item">
          <span class="meta-label">Dispositivo</span>
          <span class="meta-value">&sect; {row.dispositivo_path}</span>
        </div>
      {/if}
    </div>

    <div class="links">
      <a href={iaUrl} target="_blank" rel="noopener noreferrer" class="link-btn ia">
        Internet Archive
      </a>
    </div>

    <div class="text-section">
      <h3>
        Texto OCR
        {#if searchTerm}
          <small>— "{searchTerm}" destacado</small>
        {/if}
      </h3>
      <div class="ocr-text">
        <!-- eslint-disable-next-line svelte/no-at-html-tags -->
        {@html highlightedText}
      </div>
    </div>
  </aside>
</div>

<style>
  .backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.6);
    backdrop-filter: blur(4px);
    -webkit-backdrop-filter: blur(4px);
    z-index: 100;
    display: flex;
    justify-content: flex-end;
    animation: fade-in 0.15s ease;
  }

  @keyframes fade-in {
    from { opacity: 0; }
    to { opacity: 1; }
  }

  .panel {
    width: min(480px, 100vw);
    height: 100vh;
    overflow-y: auto;
    background: #12121f;
    border-left: 1px solid var(--glass-border, rgba(255, 255, 255, 0.1));
    padding: 1.5rem;
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
    animation: slide-in 0.2s ease;
    box-sizing: border-box;
  }

  @keyframes slide-in {
    from { transform: translateX(40px); opacity: 0; }
    to { transform: translateX(0); opacity: 1; }
  }

  .panel-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 0.75rem;
  }

  .panel-header h2 {
    margin: 0;
    font-size: 1.1rem;
    font-weight: 700;
    background: linear-gradient(135deg, #a78bfa, #60a5fa);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    word-break: break-all;
  }

  .close-btn {
    flex-shrink: 0;
    background: var(--glass-bg, rgba(255, 255, 255, 0.05));
    border: 1px solid var(--glass-border, rgba(255, 255, 255, 0.1));
    color: var(--pico-color);
    width: 2rem;
    height: 2rem;
    border-radius: 50%;
    font-size: 1.25rem;
    line-height: 1;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background 0.15s;
    padding: 0;
  }

  .close-btn:hover {
    background: rgba(255, 255, 255, 0.1);
  }

  .meta-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.75rem;
  }

  .meta-item {
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
  }

  .meta-label {
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--pico-muted-color);
    font-weight: 600;
  }

  .meta-value {
    font-size: 0.9rem;
    font-weight: 500;
  }

  .meta-value.revogado {
    color: #fca5a5;
  }

  .links {
    display: flex;
    gap: 0.5rem;
  }

  .link-btn {
    flex: 1;
    text-align: center;
    padding: 0.5rem 0.75rem;
    border-radius: 0.5rem;
    font-size: 0.8rem;
    font-weight: 600;
    text-decoration: none;
    transition: opacity 0.15s;
  }

  .link-btn:hover {
    opacity: 0.8;
    text-decoration: none;
  }

  .link-btn.ia {
    background: rgba(124, 58, 237, 0.2);
    color: #c4b5fd;
    border: 1px solid rgba(124, 58, 237, 0.3);
  }

  .text-section h3 {
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--pico-muted-color);
    margin: 0 0 0.5rem;
    font-weight: 600;
  }

  .text-section h3 small {
    font-size: 0.75rem;
    text-transform: none;
    letter-spacing: 0;
    opacity: 0.7;
  }

  .ocr-text {
    font-size: 0.875rem;
    line-height: 1.7;
    color: var(--pico-color);
    white-space: pre-wrap;
    word-break: break-word;
    background: var(--glass-bg, rgba(255, 255, 255, 0.03));
    border: 1px solid var(--glass-border, rgba(255, 255, 255, 0.07));
    border-radius: 0.5rem;
    padding: 1rem;
    max-height: 50vh;
    overflow-y: auto;
  }

  :global(.ocr-text mark) {
    background: rgba(250, 204, 21, 0.3);
    color: #fde68a;
    border-radius: 2px;
    padding: 0 1px;
  }
</style>
