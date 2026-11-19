"""Group knowledge-base articles under their category headings.

Order: DocumentCategory.order then name, with a subcategory directly after
its parent, and an "Uncategorized" group last. Within a group the incoming
order of the articles is kept (callers sort by recency / popularity first).
"""

UNCATEGORIZED = 'Uncategorized'


def _chain(cat):
    chain = []
    seen = set()
    while cat is not None and cat.pk not in seen:
        seen.add(cat.pk)
        chain.append(cat)
        cat = cat.parent
    chain.reverse()
    return chain


def group_documents_by_category(documents, full_path=True):
    """Return (ordered_documents, groups).

    Each document gets ``cat_index`` (group position) and ``cat_label``.
    ``groups`` is a list of ``{'label', 'category', 'documents'}`` dicts.
    ``full_path=False`` labels a subcategory with its own name only (use
    where the parent's name must not be disclosed).
    """
    cache = {}

    def info(cat):
        if cat is None:
            return ((1,), UNCATEGORIZED)
        if cat.pk not in cache:
            chain = _chain(cat)
            key = (0,) + tuple(
                part for c in chain for part in (c.order, (c.name or '').lower(), c.pk))
            label = ' › '.join(c.name for c in chain) if full_path else cat.name
            cache[cat.pk] = (key, label)
        return cache[cat.pk]

    docs = list(documents)
    keyed = [(info(d.category), d) for d in docs]
    keyed.sort(key=lambda kd: kd[0][0])  # stable: keeps incoming order inside a group
    groups = []
    last_key = object()
    for (key, label), d in keyed:
        if key != last_key:
            groups.append({'label': label, 'category': d.category, 'documents': []})
            last_key = key
        d.cat_index = len(groups) - 1
        d.cat_label = label
        groups[-1]['documents'].append(d)
    return [d for _, d in keyed], groups
