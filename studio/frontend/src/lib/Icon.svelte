<script>
  export let name = 'file';
  const paths = {
    folder: 'M3 7V5h6l2 3h10v12H3V7Z', file: 'M14 3H5v18h14V8l-5-5ZM14 3v6h5M8 13h8M8 17h6',
    edit: 'm15 4 5 5M4 20l5-1L20 8a2 2 0 0 0-5-5L4 14l-1 7Z',
    settings: 'm10 3-1 3-2 1-3-1-1 3 2 2v2l-2 2 1 3 3-1 2 1 1 3h4l1-3 2-1 3 1 1-3-2-2v-2l2-2-1-3-3 1-2-1-1-3Z',
    eye: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z',
    refresh: 'M20 9a8 8 0 1 0 0 7M20 3v6h-6', external: 'M14 3h7v7M21 3l-9 9M10 5H4v15h15v-6',
    chevron: 'm8 5 7 7-7 7', image: 'M3 3h18v18H3V3Zm0 14 6-6 4 4 3-3 5 5',
    sun: 'M12 2v2m0 16v2M2 12h2m16 0h2M5 5l2 2m10 10 2 2M5 19l2-2M17 7l2-2',
    moon: 'M20.5 14A8.5 8.5 0 0 1 10 4 8.5 8.5 0 1 0 20.5 14Z', lock: 'M5 10h14v11H5V10ZM8 10V7a4 4 0 0 1 8 0v3',
    check: 'm5 12 4 4L20 5', alert: 'm12 3 10 18H2L12 3Zm0 6v5m0 3v1', close: 'm6 6 12 12M6 18 18 6',
    page: 'M5 2h14v20H5V2ZM8 6h8M8 10h8M8 14h8M8 18h5',
    list: 'M9 5h12M9 12h12M9 19h12M3 5h1M3 12h1M3 19h1', table: 'M3 3h18v18H3V3ZM3 9h18M3 15h18M10 3v18',
    save: 'M3 3h14l4 4v14H3V3ZM7 3v6h10V3M7 21v-8h10v8', code: 'm7 7-5 5 5 5m10-10 5 5-5 5M14 3l-4 18'
  };
</script>
<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d={paths[name] || paths.file} />{#if name === 'eye'}<circle cx="12" cy="12" r="3" />{:else if name === 'settings'}<circle cx="12" cy="12" r="3" />{:else if name === 'sun'}<circle cx="12" cy="12" r="4" />{/if}</svg>
