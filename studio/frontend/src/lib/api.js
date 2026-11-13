export async function api(path, body) {
  let response;
  try {
    response = await fetch('/api' + path, body === undefined ? {} : {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
    });
  } catch {
    throw new Error('Нет связи с локальным сервером Studio. Проверьте, что он запущен. Черновик остаётся в редакторе.');
  }
  const text = await response.text();
  let data;
  try {data=JSON.parse(text);} catch {throw new Error('Сервер вернул некорректный ответ (HTTP '+response.status+'). '+text.slice(0,200));}
  if (!response.ok) {
    const error = new Error(data.message || data.detail?.[0]?.msg || 'Ошибка локального сервиса');
    error.diagnostics = data.diagnostics || [];
    error.status = response.status;
    throw error;
  }
  return data;
}
export const get = (object, path) => path.split('.').reduce((value, key) => value?.[key], object);
export function put(object, path, value, remove = false) {
  const keys = path.split('.'); const last = keys.pop(); let target = object;
  for (const key of keys) target = target[key] ??= {};
  if (remove) delete target[last]; else target[last] = value;
}
export const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export function highlight(line) {
  const safe = esc(line);
  if (/^#{1,6}\s/.test(line)) return `<span class="syntax-heading">${safe}</span>`;
  if (/^>/.test(line)) return `<span class="syntax-quote">${safe}</span>`;
  if (/^<!--/.test(line)) return `<span class="syntax-comment">${safe}</span>`;
  return safe.replace(/(\*\*[^*]+\*\*)/g, '<span class="syntax-bold">$1</span>').replace(/(`[^`]+`)/g, '<span class="syntax-code">$1</span>').replace(/^(\s*(?:- |\d+\. ))/, '<span class="syntax-marker">$1</span>');
}
export function filesToTree(files) {
  const root = { children: [] };
  for (const file of files) {
    const parts = file.path.split('/'); let parent = root; let path = '';
    for (let i = 0; i < parts.length; i++) {
      path += (path ? '/' : '') + parts[i];
      let child = parent.children.find(n => n.path === path);
      if (!child) {
        child = { path, label: parts[i], children: [], directory: i < parts.length - 1, exists: true };
        parent.children.push(child);
      }
      parent = child;
    }
  }
  function sort(node) { node.children.sort((a,b) => Number(b.directory)-Number(a.directory) || a.label.localeCompare(b.label)); node.children.forEach(sort); }
  sort(root); return root.children;
}
export function nodeCount(nodes) { return nodes.reduce((n, node) => n + (node.active ? 1 : 0) + nodeCount(node.children || []), 0); }
