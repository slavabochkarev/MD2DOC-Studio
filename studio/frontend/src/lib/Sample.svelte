<script>
  export let styles;
  export let outline = [];
  export let pending = false;
  export let numbering = false;
  const length = (v, fallback) => typeof v === 'string' && /^[\d.]+(mm|cm|pt|in)$/.test(v) ? v : fallback;
  const color = v => /^#[\da-f]{6}$/i.test(v) ? v : '#e8edf5';
  function font(f = {}) { return `font-family:${JSON.stringify(f.family || 'Times New Roman')};font-size:${Math.min(22, Math.max(8, Number(f.size) || 14))}px;color:${/^#[\da-f]{6}$/i.test(f.color) ? f.color : '#202838'};font-weight:${f.bold ? 700 : 400};font-style:${f.italic ? 'italic' : 'normal'}`; }
</script>
<div class="paper-surround">
  {#if !numbering}
  <div class="sample-paper" style={font(styles.font)}>
    <div class="paper-header">{styles.headers_footers?.different_first_page ? styles.headers_footers.first_page?.header_text : styles.headers_footers?.header_text}</div>
    <h1 style={font({...styles.font,...styles.headings?.h1?.font})}>Документация проекта</h1>
    <p style:text-align={styles.paragraph?.alignment || 'left'} style:line-height={styles.paragraph?.line_spacing?.mode === 'multiple' ? styles.paragraph.line_spacing.value : 1.5} style:text-indent={length(styles.paragraph?.first_line, '0mm')}>Этот образец помогает выбрать шрифт и оформление документа. Содержимое вашего проекта остаётся в Markdown.</p>
    <h2 style={font({...styles.font,...styles.headings?.h2?.font})}>Оформление разделов</h2>
    <p>Заголовки, абзацы и списки получают стили при формировании документа Word.</p>
    <table><thead><tr><th style:background={color(styles.tables?.header_fill)}>Параметр</th><th style:background={color(styles.tables?.header_fill)}>Значение</th></tr></thead><tbody><tr><td>Формат</td><td>{styles.page?.paper}</td></tr><tr><td>Шрифт</td><td>{styles.font?.family}</td></tr></tbody></table>
    <div class="paper-footer">{styles.headers_footers?.different_first_page ? styles.headers_footers.first_page?.footer_text : styles.headers_footers?.footer_text}</div>
  </div>
  <p class="sample-note">Приблизительный образец. Итоговое оформление и переносы страниц могут отличаться в Microsoft Word.</p>
  {/if}
  <div class="live-outline"><strong>Заголовки вашего документа</strong><small>{pending ? 'Пересчитывает MD2DOC…' : 'Номера рассчитаны ядром MD2DOC'}</small>
    {#each outline.slice(0, 24) as item}<p style:padding-left={(item.level-1)*10+'px'}><span>{item.number}</span> {item.text}</p>{/each}
    {#if !outline.length}<p>Нет доступных заголовков</p>{/if}
  </div>
</div>
