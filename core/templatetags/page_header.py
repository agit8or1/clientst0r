"""``{% page_header %}`` — the one page header (templates/core/_page_header.html).

    {% load page_header %}
    {% page_header title=_("Tickets") icon="fas fa-ticket-alt" title_suffix=view_label %}
        {% ph_subtitle %}36 tickets{% end_ph_subtitle %}
        <a class="btn btn-primary" href="...">New ticket</a>
    {% endpage_header %}

Everything between the tags is the actions area (put the primary action last;
one primary button at most). ``{% ph_subtitle %}`` fills the one-line
description under the title. Arguments: ``title`` (required), ``icon``,
``eyebrow`` (small line above the title), ``subtitle`` (plain text; use
``ph_subtitle`` for markup; ``{% ph_lead %}`` puts markup before the title block; ``{% ph_badges %}`` adds status badges inside the h1), ``title_suffix`` (muted text after the title),
``breadcrumb`` (list of (label, url) pairs; most pages leave this to the shell's
trail in base.html) and ``extra_class``. Exactly one ``<h1>`` is rendered.
"""
from django import template
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe

register = template.Library()


class _SlotNode(template.Node):
    def __init__(self, slot, nodelist):
        self.slot = slot
        self.nodelist = nodelist

    def render(self, context):
        slots = context.render_context.get('_page_header_slots')
        if slots is not None:
            slots[self.slot] = self.nodelist.render(context)
        return ''


@register.tag('ph_subtitle')
def do_subtitle(parser, token):
    nodelist = parser.parse(('end_ph_subtitle',))
    parser.delete_first_token()
    return _SlotNode('subtitle', nodelist)


@register.tag('ph_badges')
def do_badges(parser, token):
    """Status badges that belong to the title (rendered inside the h1)."""
    nodelist = parser.parse(('end_ph_badges',))
    parser.delete_first_token()
    return _SlotNode('badges', nodelist)


@register.tag('ph_lead')
def do_lead(parser, token):
    """Markup before the title block (a record's picture or logo)."""
    nodelist = parser.parse(('end_ph_lead',))
    parser.delete_first_token()
    return _SlotNode('lead', nodelist)


class _PageHeaderNode(template.Node):
    def __init__(self, kwargs, nodelist):
        self.kwargs = kwargs
        self.nodelist = nodelist

    def render(self, context):
        values = {k: v.resolve(context) for k, v in self.kwargs.items()}
        slots = {}
        context.render_context['_page_header_slots'] = slots
        try:
            actions = self.nodelist.render(context)
        finally:
            context.render_context['_page_header_slots'] = None
        values['actions'] = mark_safe(actions) if actions.strip() else ''
        if slots.get('subtitle', '').strip():
            values['subtitle_html'] = mark_safe(slots['subtitle'])
        if slots.get('badges', '').strip():
            values['badges_html'] = mark_safe(slots['badges'])
        if slots.get('lead', '').strip():
            values['lead_html'] = mark_safe(slots['lead'])
        return render_to_string('core/_page_header.html', values, request=context.get('request'))


@register.tag('page_header')
def do_page_header(parser, token):
    bits = token.split_contents()[1:]
    kwargs = {}
    for bit in bits:
        if '=' not in bit:
            raise template.TemplateSyntaxError('page_header takes keyword arguments only')
        k, v = bit.split('=', 1)
        kwargs[k] = parser.compile_filter(v)
    if 'title' not in kwargs:
        raise template.TemplateSyntaxError('page_header needs title=')
    nodelist = parser.parse(('endpage_header',))
    parser.delete_first_token()
    return _PageHeaderNode(kwargs, nodelist)
