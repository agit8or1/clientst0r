"""Client St0r Docs: the guide index, a guide, its images, and search."""
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import render

from . import guides


@login_required
def guides_index(request):
    q = request.GET.get('q', '').strip()[:200]
    by_cat = {c: [] for c in guides.CATEGORIES}
    for g, data in guides.available():
        by_cat.setdefault(g.category, []).append({'guide': g, 'title': data['title'],
                                                  'images': data['images']})
    return render(request, 'core/guides/index.html', {
        'q': q,
        'results': guides.search(q) if q else None,
        'categories': [(c, items) for c, items in by_cat.items() if items],
    })


@login_required
def guide_detail(request, slug):
    g = guides.GUIDES_BY_SLUG.get(slug)
    if g is None or not (guides._root() / g.path).is_file():
        raise Http404('No such guide')
    data = guides.load(g)
    return render(request, 'core/guides/detail.html', {
        'guide': g,
        'data': data,
        'github_url': guides.GITHUB_BLOB + g.path,
        'q': request.GET.get('q', '').strip()[:200],
        'siblings': [(s, d['title']) for s, d in guides.available() if s.category == g.category],
    })


@login_required
def guide_asset(request, path):
    f = guides.asset_path(path)
    if f is None:
        raise Http404('No such image')
    resp = FileResponse(open(f, 'rb'), content_type=guides.ASSET_TYPES[f.suffix.lower()])
    resp['Cache-Control'] = 'private, max-age=86400'
    # An SVG opened on its own must not run anything.
    resp['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox"
    resp['X-Content-Type-Options'] = 'nosniff'
    return resp
