<script>
  export let field;
  export let value;
  export let fallback;
  export let onchange;
  export let disabled = false;
  const units = { mm:1, cm:10, pt:25.4/72, in:25.4 };
  $: id = 'f-' + field.path.replaceAll('.', '-');
  $: display = value === undefined ? (fallback ?? '') : value;
  $: dimension = String(display).match(/^(-?(?:\d+(?:\.\d+)?|\.\d+))(mm|cm|pt|in)$/);
  function input(event) { onchange(field.path, field.type === 'checkbox' ? event.target.checked : field.type === 'number' ? event.target.value === '' ? '' : Number(event.target.value) : field.type === 'color' ? event.target.value.toUpperCase() : event.target.value); }
  function setUnit(event) { if (dimension) onchange(field.path, (Math.round(Number(dimension[1])*units[dimension[2]]/units[event.target.value]*1000000)/1000000)+event.target.value); }
</script>
{#if field.type === 'checkbox'}
  <div class="check-row"><label><input type="checkbox" checked={Boolean(display)} {disabled} onchange={input} /><span>{field.label}{#if value === undefined && fallback !== undefined}<small>Наследуется: {fallback ? 'да' : 'нет'}</small>{/if}{#if field.hint}<small>{field.hint}</small>{/if}</span></label>{#if field.optional && value !== undefined}<button class="inherit-button" type="button" {disabled} onclick={() => onchange(field.path, undefined, true)}>Наследовать</button>{/if}</div>
{:else}
  <div class="field" class:full={field.full}>
    <label for={id}>{field.label}</label>
    {#if field.type === 'dimension'}
      <div class="measurement"><input {id} type="number" step="any" min={field.signed ? undefined : 0} value={dimension?.[1] ?? ''} {disabled} oninput={e => onchange(field.path, e.target.value + (dimension?.[2] || 'mm'))} /><select aria-label={'Единицы: '+field.label} value={dimension?.[2] || 'mm'} {disabled} onchange={setUnit}>{#each Object.keys(units) as unit}<option value={unit}>{unit}</option>{/each}</select></div>
    {:else if field.type === 'select'}
      <select {id} value={display} {disabled} onchange={input}>{#if display !== '' && !field.options.some(o => (Array.isArray(o) ? o[0] : o) === display)}<option value={display}>{display}</option>{/if}{#each field.options as option}<option value={Array.isArray(option)?option[0]:option}>{Array.isArray(option)?option[1]:option}</option>{/each}</select>
    {:else if field.type === 'textarea'}
      <textarea {id} rows="3" value={display} {disabled} oninput={input}></textarea>
    {:else}
      <div class:measurement={Boolean(field.unit)}><input {id} type={field.type || 'text'} value={display} min={field.min} max={field.max} step={field.integer ? 1 : 'any'} list={field.path.endsWith('family') ? 'fonts' : undefined} {disabled} oninput={input} />{#if field.unit}<span class="unit">{field.unit}</span>{/if}</div>
    {/if}
    {#if value === undefined && fallback !== undefined}<small>Наследуется: {String(fallback)}</small>{/if}
    {#if field.hint}<small>{field.hint}</small>{/if}
    {#if field.optional && value !== undefined}<button class="inherit-button" type="button" {disabled} onclick={() => onchange(field.path, undefined, true)}>Наследовать</button>{/if}
  </div>
{/if}
