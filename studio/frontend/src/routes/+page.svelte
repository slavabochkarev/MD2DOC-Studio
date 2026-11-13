<script>
  import { onMount } from 'svelte';
  import '../app.css';
  import Icon from '../lib/Icon.svelte';
  import Tree from '../lib/Tree.svelte';
  import Field from '../lib/Field.svelte';
  import Sample from '../lib/Sample.svelte';
  import CodeEditor from '../lib/CodeEditor.svelte';
  import fields from '../lib/fields.json';
  import { api, get, put, highlight, filesToTree, nodeCount } from '../lib/api.js';

  const categories = [ ['page','page','Страница','Формат и поля документа'], ['body','edit','Основной текст','Шрифт и абзац'], ['headings','list','Заголовки','Оформление уровней H1–H6'], ['numbering','list','Нумерация','Многоуровневые заголовки'], ['lists','list','Списки','Отступы и интервалы'], ['tables','table','Таблицы','Границы и ячейки'], ['images','image','Изображения','Размеры и подписи'], ['headers','page','Колонтитулы','Текст и номера страниц'], ['breaks','page','Переносы','Разбиение документа'], ['advanced','settings','Дополнительно','Другие параметры текста'] ];
  const labels = {footer_center:'Внизу по центру',footer_left:'Внизу слева',footer_right:'Внизу справа',header_center:'Вверху по центру',header_left:'Вверху слева',header_right:'Вверху справа',portrait:'Книжная',landscape:'Альбомная',left:'Слева',center:'По центру',right:'Справа',justify:'По ширине',multiple:'Множитель',exact:'Точно (пт)',at_least:'Минимум (пт)',space:'Пробел',tab:'Табуляция',none:'Нет',parent:'С нового родителя',continue:'Продолжать',above:'Над изображением',below:'Под изображением',document:'Документ',chapter:'Глава',between_rows:'Между строками',keep_table:'Таблица целиком',wrap:'Переносить',overflow:'Выход за границы',error:'Ошибка',line:'Перевод строки',single:'Одинарная',double:'Двойная',normal:'Обычный',uppercase:'ПРОПИСНЫЕ',lowercase:'строчные',small_caps:'Капитель'};
  const stages = {queued:'В очереди',snapshot:'Чтение проекта',input:'Проверка проекта',build:'Формирование DOCX',delivery:'Проверка DOCX',publishing:'Сохранение DOCX',success:'DOCX готов',warning:'DOCX готов · есть предупреждения',failed:'Документ не сформирован',cancelled:'Формирование отменено'};
  let project = null, draft = {}, patches = {}, view = 'editor', mode = 'document', selected = '', markdown = null, category = 'page', level = 'h1';
  let modal = '', projectPath = '', output = '', strict = false, opening = false, choosingProject = false, saving = false, busyAction = false, job = null, drawer = false, error = '', notices = [], toast = '', theme = 'light', previewVisible = true, compactPreview = false;
  let outline = [], previewPending = false, previewTimer, previewGeneration = 0, selectionGeneration = 0, width = 1440, treeWidth = 260, centerRatio = 1.05;
  let mdDraft='', mdBase='', mdRevision='', mdTimer, mdGeneration=0;
  let settingsMode='visual', yamlKind='styles', yamlFile=null, yamlText='', yamlStatus='', yamlLoading=false;
  let pendingAction=null, guardScope='all', guardReason='';
  let yamlPreviewStyles=null, resultOpening='', yamlGeneration=0, resultNotice='';
  const headerGroups=[['upper','Верхний колонтитул'],['lower','Нижний колонтитул'],['first','Первая страница'],['number','Нумерация страниц']];
  $: sampleStyles=settingsMode==='yaml'&&yamlPreviewStyles?yamlPreviewStyles:effectiveStyles;
  $: dirty = Object.keys(patches).length > 0;
  $: mdDirty = Boolean(markdown && mdDraft !== mdBase);
  $: yamlDirty = Boolean(yamlFile && yamlText !== yamlFile.text);
  $: anyDirty = dirty || mdDirty || yamlDirty;
  $: dirtyLabel = [mdDirty?'Markdown':'',yamlDirty?'YAML':'',dirty?'оформление':''].filter(Boolean).join(', ');
  $: busy = Boolean(job && ['queued','snapshot','input','build','delivery','publishing'].includes(job.status));
  $: activeCategory = categories.find(c => c[0] === category);
  $: categoryFields = fields.filter(f => f.category === category && (!['headings','numbering'].includes(category) || !/\.h[1-6]\./.test(f.path) || f.path.includes('.'+level+'.'))).map(f => ({...f, options:f.options.map(v => [v,labels[v] || v])}));
  $: effectiveStyles = {...(draft.styles || {}), headings: Object.fromEntries(Array.from({length:6},(_,i) => { const h='h'+(i+1); return [h,{font:{...draft.styles?.font,...draft.styles?.headings?.[h]?.font},paragraph:{...draft.styles?.paragraph,...draft.styles?.headings?.[h]?.paragraph}}]; }))};
  $: allDiagnostics = [...notices, ...(job?.diagnostics || [])];
  $: status = busy ? `${stages[job.status]} · ${Math.floor(job.elapsed || 0)} с` : job ? stages[job.status] : 'Документ ещё не сформирован';

  function notify(message) { toast=message; setTimeout(() => { if(toast===message) toast=''; },6500); }
  function failed(e) { error=e.message; notices=e.diagnostics || []; if(notices.length) drawer=true; }
  function defaultOutput(data) {return data.root.replace(/[\\/]$/, '')+'\\'+(data.configs.document.build?.output_dir || 'output').replaceAll('/','\\')+'\\'+(data.configs.document.build?.output_name || 'document.docx');}
  function setProject(data, keepFile = false, preserveVisual = false) {
    clearTimeout(previewTimer); previewGeneration++; previewPending=false;
    if(!keepFile){clearTimeout(mdTimer);mdGeneration++;selectionGeneration++;yamlGeneration++;yamlLoading=false;resultNotice='';}
    const oldDefault=project?defaultOutput(project):null;
    if(!keepFile){mode='document';view='editor';settingsMode='visual';yamlFile=null;yamlText='';yamlStatus='';yamlPreviewStyles=null;}
    project=data; if(!preserveVisual){draft=structuredClone(data.configs);patches={};} outline=data.outline; notices=data.diagnostics; error=''; job=null;
    if(!keepFile||output===oldDefault)output=defaultOutput(data);
    if(keepFile && markdown && data.files.some(f=>f.path===selected)){scheduleMdPreview();return;}
    const first = data.files.find(f => f.path === selected && keepFile) || data.files.find(f => f.path === data.nodes.find(n=>n.active)?.source) || data.files.find(f=>f.kind==='.md');
    markdown=null; selected='';mdDraft='';mdBase='';mdRevision=''; if(first) loadMarkdown(first.path);
  }
  async function openProject() {
    opening=true; error='';
    try { setProject(await api('/project/open',{path:projectPath.trim()})); localStorage.setItem('md2doc-path',projectPath.trim()); modal=''; }
    catch(e) { failed(e); } finally { opening=false; }
  }
  async function chooseProject() {
    if(choosingProject||opening)return;
    choosingProject=true;error='';
    try{const selected=await api('/project/choose',{path:projectPath.trim()});if(selected.path)projectPath=selected.path;}
    catch(e){failed(e);}finally{choosingProject=false;}
  }
  function selectFile(path) {
    if(!/\.md$/i.test(path)){notify('Конфигурации доступны в «Настройки → Редактор YAML».');return;}
    if(path===selected)return;
    guard(()=>loadMarkdown(path),'file','Перед переключением Markdown-файла');
  }
  async function loadMarkdown(path) {
    clearTimeout(mdTimer);mdGeneration++;
    const generation=++selectionGeneration; selected=path; markdown=null;mdDraft='';mdBase='';mdRevision='';
    try { const data=await api('/markdown?project='+project.id+'&path='+encodeURIComponent(path)); if(generation===selectionGeneration){markdown=data;mdDraft=data.text;mdBase=data.text;mdRevision=data.file_revision;} }
    catch(e) { if(generation===selectionGeneration) failed(e); }
  }
  function mdPayload(){return {project:project.id,path:selected,text:mdDraft,revision:project.revision,file_revision:mdRevision};}
  function scheduleMdPreview() {
    clearTimeout(mdTimer);const generation=++mdGeneration;
    if(!markdown)return;
    mdTimer=setTimeout(async()=>{try{const data=await api('/text/markdown/preview',mdPayload());if(generation===mdGeneration)markdown={...markdown,html:data.html,included:data.included,lines:data.lines};}catch(e){if(generation===mdGeneration)failed(e);}},350);
  }
  function editMarkdown(text){mdDraft=text;scheduleMdPreview();}
  function discardMarkdown(){mdDraft=mdBase;error='';scheduleMdPreview();}
  async function saveMarkdown(){
    if(!mdDirty||busy||saving||modal==='open')return !mdDirty;
    saving=true;error='';
    try{const data=await api('/text/markdown/save',mdPayload());mdRevision=data.file_revision;mdBase=mdDraft;const previousJob=job;setProject(data.project,true,true);job=previousJob;notify('Markdown сохранён. Резервная копия: '+(data.backup||'изменений нет'));return true;}
    catch(e){failed(e);return false;}finally{saving=false;}
  }
  function yamlPayload(){return {project:project.id,kind:yamlKind,text:yamlText,revision:project.revision,file_revision:yamlFile.file_revision};}
  async function loadYaml(kind){
    const generation=++yamlGeneration,id=project.id;
    yamlLoading=true;error='';
    try{const data=await api('/text/config?project='+id+'&kind='+kind);if(generation===yamlGeneration&&project.id===id){yamlKind=kind;yamlFile=data;yamlText=data.text;yamlStatus='';yamlPreviewStyles=null;settingsMode='yaml';}}
    catch(e){if(generation===yamlGeneration)failed(e);}finally{if(generation===yamlGeneration)yamlLoading=false;}
  }
  function editYaml(text){yamlText=text;yamlStatus='';yamlPreviewStyles=null;}
  function discardYaml(){if(yamlFile)yamlText=yamlFile.text;yamlStatus='';yamlPreviewStyles=null;error='';notices=project.diagnostics;outline=project.outline;}
  async function validateYaml(){
    if(!yamlFile||busy||saving)return;
    saving=true;error='';
    try{const data=await api('/text/yaml/validate',yamlPayload());outline=data.outline;notices=data.diagnostics;yamlPreviewStyles=data.styles;yamlStatus='Синтаксис и схема проверены';notify(yamlStatus);}
    catch(e){yamlStatus='Проверка не пройдена';failed(e);drawer=true;}finally{saving=false;}
  }
  async function saveYaml(){
    if(!yamlDirty||busy||saving)return !yamlDirty;
    saving=true;error='';
    try{const data=await api('/text/yaml/save',yamlPayload());const previousJob=job;setProject(data.project,true);job=previousJob;yamlFile=data.file;yamlText=data.file.text;yamlStatus='YAML сохранён и проверен';notify(yamlStatus+'. Резервная копия: '+(data.backup||'изменений нет'));return true;}
    catch(e){yamlStatus='YAML не сохранён';failed(e);return false;}finally{saving=false;}
  }
  function needsSave(scope){return (scope!=='settings'&&mdDirty)||(scope!=='file'&&(dirty||yamlDirty));}
  function guard(action,scope='all',reason='Перед продолжением'){
    if(needsSave(scope)){pendingAction=action;guardScope=scope;guardReason=reason;modal='unsaved';error='';}else action();
  }
  function settingsModeChange(next){if(next===settingsMode)return;guard(()=>next==='yaml'?loadYaml(yamlKind):settingsMode='visual','settings','Перед сменой режима настроек');}
  function selectYaml(kind){if(kind!==yamlKind||!yamlFile)guard(()=>loadYaml(kind),'settings','Перед переключением YAML-файла');}
  function chooseCategory(next){const go=()=>{category=next;settingsMode='visual';};if(settingsMode==='yaml')guard(go,'settings','Перед переходом к визуальным настройкам');else go();}
  function previewLinks(node) { node.addEventListener('click',previewClick); return {destroy(){node.removeEventListener('click',previewClick);}}; }
  function resetScroll(node, key) {return {update(next){if(next!==key){node.scrollTop=0;key=next;}}};}
  function previewClick(event) {
    const link=event.target.closest('a[data-project-file]');
    if(link && link.dataset.projectFile !== selected) { event.preventDefault(); selectFile(link.dataset.projectFile); }
  }
  function edit(path,value,remove=false) {
    put(draft,path,value,remove); draft=structuredClone(draft);
    const next={...patches};
    if(JSON.stringify(get(project.configs,path))===JSON.stringify(get(draft,path))) delete next[path];
    else next[path]={path,op:remove?'remove':'set',...(remove?{}:{value})};
    patches=next; schedulePreview();
  }
  function schedulePreview() {
    clearTimeout(previewTimer); const generation=++previewGeneration; previewPending=true;
    previewTimer=setTimeout(async()=>{
      try { const data=await api('/settings/preview',{project:project.id,revision:project.revision,patches:Object.values(patches)}); if(generation===previewGeneration){outline=data.outline; notices=data.diagnostics;} }
      catch(e) { if(generation===previewGeneration){outline=[]; notices=e.diagnostics || [{severity:'error',message:e.message,code:'SETTINGS'}];} }
      finally {if(generation===previewGeneration) previewPending=false;}
    },650);
  }
  function discard() { clearTimeout(previewTimer); previewGeneration++; previewPending=false; draft=structuredClone(project.configs); patches={}; outline=project.outline; notices=project.diagnostics; error=''; }
  async function save() {
    if(!dirty||busy||saving)return !dirty;
    saving=true; error=''; clearTimeout(previewTimer); previewGeneration++; previewPending=false;
    try { const data=await api('/settings/save',{project:project.id,revision:project.revision,patches:Object.values(patches)}); const previousJob=job; setProject(data.project,true); job=previousJob; notify('Настройки сохранены. Резервная копия: '+(data.backup || 'изменений нет')); return true; }
    catch(e) {failed(e);return false;} finally {saving=false;}
  }
  function refresh(){guard(reopen,'all','Перед перечитыванием проекта');}
  async function reopen() { try {setProject(await api('/project/open',{path:project.root})); modal='';} catch(e){failed(e);} }
  function requestOpen() {guard(()=>{modal='open';error='';},'all','Перед переключением проекта');}
  async function continueAction(action) {
    if(action==='save'){
      if(guardScope!=='settings'&&mdDirty&&!await saveMarkdown())return;
      if(guardScope!=='file'&&yamlDirty&&!await saveYaml())return;
      if(guardScope!=='file'&&dirty&&!await save())return;
    }else if(action==='discard'){
      if(guardScope!=='settings')discardMarkdown();
      if(guardScope!=='file'){discard();discardYaml();}
    }
    const next=pendingAction;pendingAction=null;modal='';if(next)await next();
  }
  function convert(){guard(buildDocument,'all','Перед конвертацией');}
  async function buildDocument() {
    busyAction=true; error='';resultNotice='';
    try { notices=[]; job=await api('/build',{project:project.id,revision:project.revision,output,strict}); drawer=true; }
    catch(e){failed(e);}finally{busyAction=false;}
  }
  async function result(action) {if(resultOpening)return;resultOpening=action;resultNotice='Передаю команду Windows…';drawer=true;try{await api('/result/'+action,{});resultNotice=action==='reveal'?'Команда открытия папки передана Проводнику Windows.':'DOCX передан приложению по умолчанию в Windows.';notify(resultNotice);}catch(e){toast='';resultNotice='Открытие не выполнено. Причина указана в диагностике.';failed(e);}finally{resultOpening='';}}
  function toggleTheme() {theme=theme==='light'?'dark':'light';document.documentElement.dataset.theme=theme;localStorage.setItem('md2doc-theme',theme);}
  function resize(event,side) {
    if(event.button!==0)return;
    const start=event.clientX,initial=treeWidth,ratio=centerRatio;
    const move=e=>{ if(side==='left') treeWidth=Math.min(410,Math.max(190,initial+e.clientX-start)); else centerRatio=Math.min(2.3,Math.max(.6,ratio+(e.clientX-start)/350)); };
    const stop=()=>{window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',stop);};
    window.addEventListener('pointermove',move);window.addEventListener('pointerup',stop);
  }
  function resizeKey(event,side) {if(['ArrowLeft','ArrowRight'].includes(event.key)){event.preventDefault(); const step=event.key==='ArrowLeft'?-1:1; if(side==='left')treeWidth=Math.max(190,Math.min(410,treeWidth+step*15));else centerRatio=Math.max(.6,Math.min(2.3,centerRatio+step*.1));}}
  function preset(template) {edit('styles.heading_numbering.levels.'+level+'.template',template);edit('styles.heading_numbering.levels.'+level+'.format','decimal');}
  function fallback(path) {
    if(path.startsWith('styles.headings.')) { const suffix=path.split('.').slice(3).join('.'); return get(draft,'styles.'+suffix) ?? get(project.effective,path); }
    return get(project?.effective,path);
  }
  onMount(()=>{
    theme=localStorage.getItem('md2doc-theme') || (matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');document.documentElement.dataset.theme=theme;
    projectPath=localStorage.getItem('md2doc-path') || '';
    api('/session').then(data=>{if(data.project&&!project&&!opening){setProject(data.project);job=data.job;}}).catch(failed);
    let polling=false;
    const timer=setInterval(async()=>{if(busy&&!polling){polling=true;try{job=await api('/job');}catch(e){failed(e);}finally{polling=false;}}},500);
    const leave=e=>{if(anyDirty){e.preventDefault();e.returnValue='';}};
    const shortcut=e=>{if(project&&!modal&&!e.defaultPrevented&&(e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();if(view==='editor')saveMarkdown();else if(settingsMode==='yaml')saveYaml();else save();}};
    window.addEventListener('beforeunload',leave);
    window.addEventListener('keydown',shortcut);
    return()=>{clearInterval(timer);clearTimeout(previewTimer);clearTimeout(mdTimer);window.removeEventListener('beforeunload',leave);window.removeEventListener('keydown',shortcut);};
  });
</script>

<svelte:head><title>MD → DOC — MD2DOC Studio</title><meta name="description" content="Локальная настройка и конвертация Markdown-проектов в Word" /></svelte:head>
<svelte:window bind:innerWidth={width} />
<div class="studio-shell">
  <header class="app-header"><div class="brand-icon" aria-hidden="true"><span>M↓</span><span>↥W</span></div><div class="brand"><h1>MD → DOC</h1><p>Конвертация Markdown-проекта в документ Word</p></div><div class="header-meta">{#if project}<button class="icon-button" aria-label="Перечитать проект" disabled={busy||saving} onclick={refresh}><Icon name="refresh" /></button>{/if}<span class="prototype-label">MD2DOC Studio · локально</span><button class="button" onclick={requestOpen} disabled={busy||saving}><Icon name="folder" />Открыть проект</button><button class="icon-button" aria-label="Переключить тему" onclick={toggleTheme}><Icon name={theme==='light'?'moon':'sun'} /></button></div></header>
  <div class="command-bar"><nav class="main-tabs" aria-label="Основные разделы"><button class="main-tab" class:active={view==='editor'} aria-pressed={view==='editor'} onclick={()=>view='editor'}><Icon name="edit" />Редактор{#if mdDirty}<span class="dirty-dot"></span>{/if}</button><button class="main-tab" class:active={view==='settings'} aria-pressed={view==='settings'} onclick={()=>view='settings'}><Icon name="settings" />Настройки{#if dirty||yamlDirty}<span class="dirty-dot"></span>{/if}</button></nav><div class="convert-group"><span class="conversion-scope">Весь документ{project?' · '+nodeCount(project.nodes)+' источников':''}</span><button class="icon-button" aria-label={width<1100?'Переключить просмотр':previewVisible?'Скрыть предпросмотр':'Показать предпросмотр'} onclick={()=>{if(width<1100)compactPreview=!compactPreview;else previewVisible=!previewVisible;}}><Icon name="eye" /></button><button class="icon-button" aria-label="Параметры конвертации" disabled={!project||busy} onclick={()=>modal='output'}><Icon name="settings" /></button><button class="convert-button" disabled={!project||busy||saving||busyAction} onclick={convert}><span class="word-mark" aria-hidden="true">W</span>{busy?'Формирование…':'Конвертировать в DOCX'}</button></div></div>
  {#if error && !modal}<div class="error-banner" role="alert"><Icon name="alert" /><span>{error}</span><button class="icon-button" aria-label="Скрыть сообщение" onclick={()=>error=''}><Icon name="close" /></button></div>{/if}
  {#if !project}
    <main class="welcome"><div class="welcome-icon"><Icon name="folder" /></div><h2>Ваш Markdown-проект — в готовый Word</h2><p>Откройте папку с document.yaml. Структура документа, исходный текст и его просмотр будут рядом.</p><button class="convert-button" onclick={requestOpen}><Icon name="folder" />Открыть проект</button><small>Настройте оформление во вкладке «Настройки», затем конвертируйте весь документ в DOCX.</small></main>
  {:else}
    <main class="workspace" class:settings-layout={view==='settings'} class:preview-hidden={!previewVisible} class:compact-preview={compactPreview} style:--tree={treeWidth+'px'} style:--center-width={centerRatio+'fr'}>
      {#if view==='editor'}
        <aside class="panel project-panel"><div class="panel-head"><Icon name="folder" /><span>Проект</span><div class="head-actions"><button class="icon-button" aria-label="Перечитать проект с диска" onclick={refresh} disabled={busy||saving}><Icon name="refresh" /></button></div></div><div class="project-root" title={project.root}>{project.root.split(/[\\/]/).pop()}</div><div class="project-view-tabs"><button class:active={mode==='document'} onclick={()=>mode='document'}>Документ</button><button class:active={mode==='files'} onclick={()=>mode='files'}>Файлы</button></div><div class="tree"><Tree nodes={mode==='document'?project.nodes:filesToTree(project.files)} {mode} {selected} onselect={selectFile} /></div><div class="tree-meta"><span>Схема {project.schema} · {nodeCount(project.nodes)} источников</span><span>Конвертируется весь документ</span></div></aside>
        <div class="panel-resizer left-resizer" role="slider" aria-valuemin="0" aria-valuemax="500" aria-label="Ширина дерева" aria-orientation="horizontal" aria-valuenow={treeWidth} tabindex="0" onpointerdown={e=>resize(e,'left')} onkeydown={e=>resizeKey(e,'left')}></div>
        <section class="panel source-panel" aria-label="Исходный Markdown"><div class="file-tab-bar"><div class="file-tab active"><Icon name="file" />{selected||'Выберите Markdown-файл'}{#if mdDirty}<span class="dirty-dot"></span>{/if}</div></div><div class="source-toolbar"><span class="markdown-badge">Markdown</span><span>Редактирование · Ctrl+S</span><span class="toolbar-right">{markdown?.included?'В документе':'Вне документа'}</span></div>
          {#if markdown}{#key selected}<CodeEditor value={mdDraft} {theme} label="Редактор Markdown" readonly={busy||saving||Boolean(modal)} onchange={editMarkdown} onsave={saveMarkdown} />{/key}{:else}<div class="source-content"><p class="empty-panel">{selected?'Чтение файла…':'Выберите источник слева'}</p></div>{/if}
          <div class="editor-save-bar"><span class:unsaved={mdDirty}>{mdDirty?'Файл не сохранён':markdown?'Файл сохранён':'Нет файла'}</span><button class="button" disabled={!mdDirty||busy||saving} onclick={discardMarkdown}>Отменить</button><button class="button primary" disabled={!mdDirty||busy||saving} onclick={saveMarkdown}><Icon name="save" />Сохранить</button></div>
        </section>
      {:else}
        <aside class="panel settings-sidebar"><div class="panel-head"><Icon name="settings" />Оформление DOCX</div><div class="settings-context" title={project.root}>{project.title}</div><nav class="settings-categories" aria-label="Категории настроек">{#each categories as c}<button class="category-button" class:active={category===c[0]} onclick={()=>chooseCategory(c[0])}><Icon name={c[1]} />{c[2]}</button>{/each}</nav><div class="category-foot">Схема {project.schema}<br />Настройки применяются ко всему документу</div></aside>
        <div class="panel-resizer left-resizer" role="slider" aria-valuemin="0" aria-valuemax="500" aria-label="Ширина категорий" aria-orientation="horizontal" aria-valuenow={treeWidth} tabindex="0" onpointerdown={e=>resize(e,'left')} onkeydown={e=>resizeKey(e,'left')}></div>
        <section class="panel settings-main"><div class="settings-main-head"><h2>{settingsMode==='yaml'?'Редактор YAML':activeCategory[2]}</h2><p>{settingsMode==='yaml'?(yamlFile?.path||'Конфигурации проекта'):category==='headers'?'Верхний и нижний колонтитулы, первая страница и номера страниц':activeCategory[3]}</p><div class="settings-mode-tabs"><button class:active={settingsMode==='visual'} onclick={()=>settingsModeChange('visual')}>Визуальные настройки</button><button class:active={settingsMode==='yaml'} onclick={()=>settingsModeChange('yaml')}>Редактор YAML{#if yamlDirty}<span class="dirty-dot"></span>{/if}</button></div></div>{#if settingsMode==='visual'}<div class="settings-fields" use:resetScroll={category+level}><datalist id="fonts"><option>Times New Roman</option><option>Arial</option><option>Calibri</option><option>Aptos</option><option>Georgia</option></datalist>
          {#if ['headings','numbering'].includes(category)}<div class="level-tabs" aria-label="Уровень заголовка">{#each [1,2,3,4,5,6] as i}<button class:active={level==='h'+i} onclick={()=>level='h'+i}>H{i}</button>{/each}</div>{/if}
          {#if category==='numbering'&&project.schema==='0.1'}<div class="settings-note">Проект использует схему 0.1. Нумерация сохраняется по существующим правилам проекта. Настройка H1–H6 доступна в схеме 0.2; Studio не меняет версию схемы.</div><Field field={{path:'document.defaults.numbering.enabled',label:'Структурная нумерация по умолчанию',type:'checkbox'}} value={get(draft,'document.defaults.numbering.enabled')} onchange={edit} disabled={busy||saving} />
          {:else}
            {#if category==='numbering'}<p class="settings-note">Шаблон <code>{'{n}'}</code> — номер уровня, <code>{'{path}'}</code> — путь из номеров. Параметры отдельных элементов и Markdown могут переопределять эти настройки. Результат виден справа.</p><div class="template-choices">{#each [['1','{n}'],['1.','{n}.'],['1)','{n})'],['(1)','({n})'],['1.1','{path}'],['1.1.1','{path}']] as p}<button disabled={busy||saving} onclick={()=>preset(p[1])}>{p[0]}</button>{/each}</div>{/if}
            {#if category==='headers'}{#each headerGroups as group}<h3 class="header-group-title">{group[1]}</h3><div class="form-grid">{#each categoryFields.filter(f=>f.group===group[0]&&(!f.requiresFirstPage||draft.styles.headers_footers.different_first_page)) as field}<Field {field} value={get(draft,field.path)} fallback={fallback(field.path)} onchange={edit} disabled={busy||saving} />{/each}</div>{/each}{:else}<div class="form-grid">{#each categoryFields as field}<Field {field} value={get(draft,field.path)} fallback={fallback(field.path)} onchange={edit} disabled={busy||saving} />{/each}
              {#if category==='numbering'}<Field field={{path:'styles.heading_numbering.levels.'+level+'.format',label:'Вид цифр',type:'select',optional:true,options:[['decimal','1, 2, 3'],['lower_alpha','a, b, c'],['upper_alpha','A, B, C'],['lower_roman','i, ii, iii'],['upper_roman','I, II, III']]}} value={get(draft,'styles.heading_numbering.levels.'+level+'.format')} fallback={fallback('styles.heading_numbering.levels.'+level+'.format')} onchange={edit} disabled={busy||saving} />{/if}
            </div>{/if}
            {#if category==='headers'}<p class="settings-note">Текст выводится буквально и выравнивается слева. Шрифт берётся из основного текста. Подстановки metadata, отдельный шрифт и изображения в колонтитуле ядром не поддерживаются.</p>{/if}
            {#if category==='lists'}<p class="settings-note">Начальное значение применяется там, где Markdown не задаёт собственный номер. Массивы маркеров и форматов сохраняются без изменений.</p>{/if}
          {/if}
        </div>{:else}
          <div class="yaml-file-tabs" aria-label="Конфигурационные файлы">{#each ['document','styles','metadata'] as kind}<button class:active={yamlKind===kind} title={project.config_paths[kind]} disabled={yamlLoading||saving} onclick={()=>selectYaml(kind)}>{project.config_paths[kind]}</button>{/each}</div>
          <div class="yaml-note">Текст сохраняется с вашими комментариями и расширениями. Проверка синтаксиса и схемы выполняется перед записью.</div>
          {#if yamlFile&&!yamlLoading}{#key yamlFile.path}<CodeEditor value={yamlText} language="yaml" {theme} label={'Редактор YAML: '+yamlFile.path} readonly={busy||saving||Boolean(modal)} onchange={editYaml} onsave={saveYaml} />{/key}{:else}<div class="source-content"><p class="empty-panel">Чтение YAML…</p></div>{/if}
          <div class="yaml-validation" role="status">{yamlStatus||'Ctrl+S — сохранить YAML'}{#if yamlDirty&&!yamlPreviewStyles}<small>Для обновления образца проверьте или сохраните YAML.</small>{/if}</div>
        {/if}<div class="settings-save-bar">{#if settingsMode==='yaml'}<span class="save-caption" class:unsaved={yamlDirty}>{yamlDirty?'YAML не сохранён':'YAML сохранён'}</span><div class="save-actions"><button class="button" disabled={busy||saving||yamlLoading} onclick={validateYaml}>Проверить YAML</button><button class="button" disabled={!yamlDirty||busy||saving} onclick={discardYaml}>Отменить</button><button class="button primary" disabled={!yamlDirty||busy||saving} onclick={saveYaml}><Icon name="save" />{saving?'Проверка…':'Сохранить YAML'}</button></div>{:else}<span class="save-caption" class:unsaved={dirty}>{dirty?'Есть несохранённые изменения':'Настройки сохранены'}</span><div class="save-actions"><button class="button" disabled={!dirty||busy||saving} onclick={discard}>Отменить изменения</button><button class="button primary" disabled={!dirty||busy||saving} onclick={save}><Icon name="save" />{saving?'Сохранение…':'Сохранить настройки'}</button></div>{/if}</div></section>
      {/if}
      <div class="panel-resizer right-resizer" role="slider" aria-valuemin="0" aria-valuemax="500" aria-label="Ширина просмотра" aria-orientation="horizontal" aria-valuenow={Math.round(centerRatio*100)} tabindex="0" onpointerdown={e=>resize(e,'right')} onkeydown={e=>resizeKey(e,'right')}></div>
      {#if view==='editor'}<section class="panel preview-panel"><div class="panel-head"><Icon name="eye" />Просмотр Markdown<div class="head-actions"><button class="icon-button" aria-label="Перечитать Markdown" disabled={!selected} onclick={()=>guard(()=>loadMarkdown(selected),'file','Перед перечитыванием Markdown')}><Icon name="refresh" /></button></div></div><div class="preview-content rendered" use:previewLinks role="region" aria-label="Содержимое Markdown">{#if markdown}{@html markdown.html}{:else}<p class="empty-panel">Здесь появится выбранный Markdown-файл</p>{/if}</div></section>
      {:else}<aside class="panel settings-preview"><div class="panel-head"><Icon name="eye" />Образец оформления DOCX</div>{#key category}<Sample styles={sampleStyles} {outline} pending={previewPending} numbering={category==='numbering'} />{/key}</aside>{/if}
    </main>
  {/if}
  {#if drawer}<section class="build-drawer actual-drawer" aria-label="Результат и диагностика"><div class="drawer-heading"><strong>{status}</strong><span>{busy?'Можно продолжать просматривать Markdown':''}</span>{#if busy}<button class="button" onclick={async()=>{try{job=await api('/job/cancel',{});}catch(e){failed(e);}}}>Отменить формирование</button>{/if}<button class="icon-button" aria-label="Свернуть диагностику" onclick={()=>drawer=false}><Icon name="close" /></button></div>{#if job?.target}<div class="result-path">{job.target}</div>{/if}{#if job?.artifact}<div class="artifact-actions">{#if !['success','warning'].includes(job.status)}<span class="settings-note">Предыдущий успешный результат</span>{/if}<button class="button" disabled={Boolean(resultOpening)} onclick={()=>result('open')}>Открыть DOCX ↗</button><button class="button" disabled={Boolean(resultOpening)} onclick={()=>result('reveal')}>Открыть папку</button><a class="button" href="/api/result/download">Скачать DOCX</a></div>{/if}{#if resultNotice}<p class="result-action-status" role="status">{resultNotice}</p>{/if}<div class="diagnostic-list">{#each allDiagnostics as d}<div class="diagnostic" class:is-error={d.severity==='error'}><Icon name={d.severity==='error'?'alert':'eye'} /><div><strong>{d.code}</strong> {d.message}{#if d.source||d.context}<small>{d.source||''}{d.context?' · '+d.context:''}</small>{/if}</div></div>{/each}{#if !allDiagnostics.length}<p class="settings-note">{busy?'Выполняется проверка и формирование документа…':'Ошибок и предупреждений нет'}</p>{/if}</div></section>{/if}
  <footer class="status-bar"><div class="status-left"><span class="status-dot" class:error={job?.status==='failed'}></span><span role="status" aria-live="polite">{status}</span><span class="status-separator"></span><span id="settings-state">{anyDirty?'Не сохранено: '+dirtyLabel:project?'Изменения сохранены':'Откройте проект'}</span></div><div class="status-right">{#if job?.artifact}<button class="status-link" disabled={Boolean(resultOpening)} onclick={()=>result('open')}>Открыть DOCX ↗</button>{/if}<button class="diagnostics-toggle" aria-expanded={drawer} onclick={()=>drawer=!drawer}>Результат и диагностика <span class="count">{allDiagnostics.length}</span>⌃</button></div></footer>
</div>
{#if modal}<div class="modal-backdrop"><dialog open aria-labelledby="modal-title"><div class="modal-heading"><h2 id="modal-title">{modal==='open'?'Открыть Markdown-проект':modal==='output'?'Параметры конвертации':'Есть несохранённые изменения'}</h2><button class="icon-button" aria-label="Закрыть" disabled={opening||choosingProject||saving} onclick={()=>modal=''}><Icon name="close" /></button></div>
  {#if modal==='open'}<p>Укажите папку существующего проекта с document.yaml.</p><form onsubmit={e=>{e.preventDefault();openProject();}}><label for="project-path">Папка проекта</label><div class="project-path-picker"><input id="project-path" class="path-input" bind:value={projectPath} placeholder="C:\Project\MyProject" disabled={opening||choosingProject} /><button class="button" type="button" disabled={opening||choosingProject} onclick={chooseProject}><Icon name="folder" />{choosingProject?'Выбор папки…':'Выбрать папку…'}</button></div><small>Studio читает структуру и настройки из файлов вашего проекта.</small>{#if error}<p class="error-note" role="alert">{error}</p>{/if}<div class="dialog-actions"><button class="button" type="button" disabled={opening||choosingProject} onclick={()=>modal=''}>Отмена</button><button class="button primary" disabled={opening||choosingProject||!projectPath.trim()}>{opening?'Открытие…':'Открыть проект'}</button></div></form>
  {:else if modal==='output'}<p>Будет сформирован весь документ в порядке document.yaml.</p><label for="output-path">Полный путь к DOCX</label><input id="output-path" class="path-input" bind:value={output} /><label class="check-row"><input type="checkbox" bind:checked={strict} /><span>Строгий режим<small>Предупреждения считаются ошибками</small></span></label><p class="settings-note">Существующий DOCX по этому пути будет заменён после успешной проверки результата. Microsoft Word автоматически не запускается.</p><div class="dialog-actions"><button class="button primary" onclick={()=>modal=''}>Готово</button></div>
  {:else}<p>{guardReason} сохраните изменения или откажитесь от них. Несохранённые данные: {dirtyLabel}.</p>{#if error}<p class="error-note" role="alert">{error}</p>{/if}<div class="dialog-actions"><button class="button" disabled={saving} onclick={()=>modal=''}>Остаться</button><button class="button" disabled={saving} onclick={()=>continueAction('discard')}>Не сохранять</button><button class="button primary" disabled={saving} onclick={()=>continueAction('save')}>{saving?'Сохранение…':'Сохранить и продолжить'}</button></div>{/if}
</dialog></div>{/if}
{#if toast}<div class="actual-toast" role="status">{toast}</div>{/if}
