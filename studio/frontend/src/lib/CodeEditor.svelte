<script>
  import { onMount } from 'svelte';
  import { basicSetup } from 'codemirror';
  import { EditorState, Compartment, Prec } from '@codemirror/state';
  import { EditorView, keymap } from '@codemirror/view';
  import { markdown } from '@codemirror/lang-markdown';
  import { yaml } from '@codemirror/lang-yaml';
  import { oneDark } from '@codemirror/theme-one-dark';

  export let value = '';
  export let language = 'markdown';
  export let theme = 'light';
  export let readonly = false;
  export let label = 'Редактор';
  export let onchange;
  export let onsave;
  let host, editor;
  const access = new Compartment(), colors = new Compartment();
  const accessMode = () => [EditorState.readOnly.of(readonly),EditorView.editable.of(!readonly)];
  $: if(editor && value !== editor.state.doc.toString()) editor.dispatch({changes:{from:0,to:editor.state.doc.length,insert:value}});
  $: if(editor) editor.dispatch({effects:access.reconfigure(accessMode(readonly))});
  $: if(editor) editor.dispatch({effects:colors.reconfigure(theme === 'dark' ? oneDark : [])});
  onMount(()=>{
    editor = new EditorView({parent:host,state:EditorState.create({doc:value,extensions:[
      basicSetup, language === 'yaml' ? yaml() : markdown(), EditorView.lineWrapping,
      access.of(accessMode()),colors.of(theme === 'dark' ? oneDark : []),
      EditorView.contentAttributes.of({'aria-label':label,'spellcheck':'false'}),
      Prec.highest(keymap.of([{key:'Mod-s',preventDefault:true,run:()=>{onsave?.();return true;}}])),
      EditorView.updateListener.of(update=>{if(update.docChanged)onchange?.(update.state.doc.toString());}),
      EditorView.theme({'&':{height:'100%',fontSize:'var(--editor-size)',backgroundColor:'var(--panel)',color:'var(--code)'},
        '.cm-scroller':{overflow:'auto',fontFamily:'"Cascadia Code",Consolas,monospace'},'.cm-content':{padding:'14px 0'},
        '.cm-gutters':{backgroundColor:'var(--soft)',color:'var(--muted)',borderRight:'1px solid var(--line-soft)'},
        '.cm-line':{padding:'0 15px 0 9px'},'&.cm-focused':{outline:'none'}})
    ]})});
    return()=>{editor.destroy();editor=null;};
  });
</script>
<div class="code-editor" bind:this={host}></div>
