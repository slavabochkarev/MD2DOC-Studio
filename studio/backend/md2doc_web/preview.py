import html
from urllib.parse import quote, unquote, urlsplit

from md2doc.core.markdown_parser import parser, substitute
from md2doc.config.validation import slug
from .repository import safe_path, StudioError, digest


def markdown_preview(project, relative, text=None):
    path = safe_path(project.root, relative)
    if path.suffix.lower() != '.md':
        raise StudioError('Просмотр содержимого доступен для Markdown-файлов.', 422)
    if not path.is_file():
        raise StudioError('Markdown-файл отсутствует.', 404)
    data = path.read_bytes()
    if text is None:
        text = data.decode('utf-8-sig').replace('\r\n','\n')
    md = parser()  # The existing core's Markdown profile and special blocks.
    md.renderer.rules['heading_options'] = lambda *args: ''
    md.renderer.rules['pagebreak'] = lambda *args: '<div class="markdown-pagebreak">Разрыв страницы</div>'
    for name in ('note', 'warning', 'subtitle'):
        md.renderer.rules[name + '_open'] = lambda *args, name=name: '<aside class="markdown-' + name + '">'
        md.renderer.rules[name + '_close'] = lambda *args: '</aside>'

    def render_text(tokens, idx, options, env):
        value = tokens[idx].content
        try:
            value = substitute(value, project.configs['metadata'])
        except KeyError:
            pass
        return html.escape(value)
    md.renderer.rules['text'] = render_text

    def image(tokens, idx, options, env):
        token = tokens[idx]
        parsed = urlsplit(token.attrGet('src') or '')
        if parsed.scheme or parsed.netloc:
            return '<span>[Внешнее изображение не загружается]</span>'
        try:
            resource = (path.parent / unquote(parsed.path)).resolve()
            relative_asset = resource.relative_to(project.root).as_posix()
        except ValueError:
            return '<span>[Изображение вне проекта]</span>'
        src = '/api/asset?project=' + project.id + '&path=' + quote(relative_asset, safe='')
        return '<img src="' + html.escape(src, quote=True) + '" alt="' + html.escape(token.content, quote=True) + '">'
    md.renderer.rules['image'] = image

    def link_open(tokens, idx, options, env):
        token = tokens[idx]
        href = token.attrGet('href') or ''
        parsed = urlsplit(href)
        if parsed.scheme in ('https', 'http', 'mailto'):
            return '<a href="' + html.escape(href, quote=True) + '" target="_blank" rel="noreferrer noopener">'
        if href.startswith('md2doc:'):
            node = next((n for n in project._walk() if n.get('id') == href[7:]), None)
            target = node.get('source') if node else None
        elif not parsed.scheme and not parsed.netloc:
            try:
                target = (path.parent / unquote(parsed.path)).resolve().relative_to(project.root).as_posix() if parsed.path else relative
            except ValueError:
                target = None
        else:
            target = None
        if target:
            return '<a href="#md-' + html.escape(unquote(parsed.fragment), quote=True) + '" data-project-file="' + html.escape(target, quote=True) + '">'
        return '<a aria-disabled="true">'
    md.renderer.rules['link_open'] = link_open

    used = {}
    def heading(tokens, idx, options, env):
        content = tokens[idx + 1].content if idx + 1 < len(tokens) else ''
        base = slug(content)
        used[base] = used.get(base, 0) + 1
        identifier = base if used[base] == 1 else base + '-' + str(used[base])
        return '<' + tokens[idx].tag + ' id="md-' + html.escape(identifier, quote=True) + '">'
    md.renderer.rules['heading_open'] = heading
    def included(nodes, active=True):
        return any((active and n.get('enabled', True) and n.get('source') == relative) or included(n.get('children', []), active and n.get('enabled', True)) for n in nodes)
    return {'path': relative, 'text': text, 'html': md.render(text), 'file_revision':digest(data), 'bytes':len(data), 'lines':len(text.splitlines()), 'included':included(project.configs['document'].get('elements', []))}
