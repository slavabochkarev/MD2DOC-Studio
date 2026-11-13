<script>
  import Icon from './Icon.svelte';
  export let nodes = [];
  export let mode = 'document';
  export let selected = '';
  export let onselect;
  export let depth = 0;
  let closed = {};
  const names = { title_page:'Титульный лист', frontmatter:'Вводная часть', chapter:'Глава', section:'Раздел', content:'Текст', appendix:'Приложение' };
</script>
{#each nodes as node}
  <div class="tree-item">
    <div class="tree-line" style:padding-left={8 + depth * 15 + 'px'}>
      {#if node.children?.length}
        <button class="tree-expander" aria-label={closed[node.path || node.id] ? 'Раскрыть' : 'Свернуть'} onclick={() => closed = { ...closed, [node.path || node.id]: !closed[node.path || node.id] }}><span class:expanded={!closed[node.path || node.id]}><Icon name="chevron" /></span></button>
      {:else}<span class="tree-expander empty"></span>{/if}
      <button class="tree-select" class:selected={selected === (node.source || node.path)} class:missing={node.exists === false} class:excluded={mode === 'document' && !node.active} onclick={() => node.directory ? closed = { ...closed, [node.path]: !closed[node.path] } : onselect(node.source || node.path)}>
        {#if mode === 'files'}<Icon name={node.directory ? 'folder' : /\.(png|jpe?g|svg|gif)$/i.test(node.path) ? 'image' : 'file'} />{/if}
        <span class="node-content"><span class="node-title">{node.label || node.id}</span>{#if mode === 'document'}<span class="node-kind">{names[node.type] || node.type}{!node.active ? ' · исключён' : ''}</span><span class="node-source">{node.exists === false ? '⚠ ' : ''}{node.source}{node.exists === false ? ' · отсутствует' : ''}</span>{/if}</span>
      </button>
    </div>
    {#if node.children?.length && !closed[node.path || node.id]}<svelte:self nodes={node.children} {mode} {selected} {onselect} depth={depth+1} />{/if}
  </div>
{/each}
