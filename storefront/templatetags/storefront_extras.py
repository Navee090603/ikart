from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def dict_get(mapping, key):
    return mapping.get(key)


# IKart design-system icons: 24px outline set, 2px round stroke, drawn in currentColor.
ICON_PATHS = {
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
    "cart": '<path d="M3 4h2.5l2.2 10.2a2 2 0 0 0 2 1.6h7.6a2 2 0 0 0 2-1.5L21 8H6.4"/><circle cx="10" cy="20" r="1.5"/><circle cx="17" cy="20" r="1.5"/>',
    "bag": '<path d="M8 8V7a4 4 0 0 1 8 0v1"/><rect x="4" y="8" width="16" height="13" rx="4"/>',
    "heart": '<path d="M12 20s-7.5-4.6-7.5-10A4.3 4.3 0 0 1 12 7.4 4.3 4.3 0 0 1 19.5 10c0 5.4-7.5 10-7.5 10z"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4.5 20a7.5 7.5 0 0 1 15 0"/>',
    "home": '<path d="M4 10.5 12 4l8 6.5V19a1 1 0 0 1-1 1h-4.5v-6h-5v6H5a1 1 0 0 1-1-1z"/>',
    "menu": '<path d="M4 7h16M4 12h16M4 17h16"/>',
    "close": '<path d="M6 6l12 12M18 6 6 18"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "check": '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    "chevron-right": '<path d="m9 5 7 7-7 7"/>',
    "chevron-left": '<path d="m15 5-7 7 7 7"/>',
    "chevron-down": '<path d="m5 9 7 7 7-7"/>',
    "star": '<path d="m12 3.8 2.5 5.1 5.6.8-4 4 .9 5.6-5-2.7-5 2.7.9-5.6-4-4 5.6-.8z"/>',
    "filter": '<path d="M4 6h16M7 12h10M10 18h4"/>',
    "truck": '<path d="M3 6h11v10H3zM14 10h4l3 3v3h-7"/><circle cx="7" cy="18" r="1.8"/><circle cx="17.5" cy="18" r="1.8"/>',
    "tag": '<path d="M3.5 12.5V4.5a1 1 0 0 1 1-1h8l8 8a1.5 1.5 0 0 1 0 2.1l-7 7a1.5 1.5 0 0 1-2.1 0z"/><circle cx="8.5" cy="8.5" r="1.3"/>',
    "sparkle": '<path d="M12 3c.9 4.9 3.1 7.1 8 8-4.9.9-7.1 3.1-8 8-.9-4.9-3.1-7.1-8-8 4.9-.9 7.1-3.1 8-8z"/>',
    "trash": '<path d="M4 7h16M10 7V4.5h4V7M6.5 7l1 12.5a1 1 0 0 0 1 .9h7a1 1 0 0 0 1-.9l1-12.5"/>',
    "bell": '<path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15zM10 20.5a2 2 0 0 0 4 0"/>',
    "info": '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5M12 8h.01"/>',
    "alert": '<path d="M12 4 2.8 19.5h18.4z"/><path d="M12 10v4.5M12 17h.01"/>',
    "check-circle": '<circle cx="12" cy="12" r="8.5"/><path d="m8.5 12.3 2.4 2.4 4.8-5"/>',
    "lock": '<rect x="5" y="11" width="14" height="10" rx="2.5"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    "mail": '<rect x="3" y="5" width="18" height="14" rx="3"/><path d="m4 7.5 8 6 8-6"/>',
}


@register.simple_tag
def icon(name, size=20, label="", css=""):
    """Render an IKart icon as inline SVG: {% icon "cart" %}, {% icon "heart" 18 css="fill-current" %}.
    Pass label="…" when the icon alone carries meaning; otherwise it is hidden from screen readers."""
    body = ICON_PATHS.get(name, "")
    a11y = format_html('role="img" aria-label="{}"', label) if label else mark_safe('aria-hidden="true"')
    return format_html(
        '<svg class="ik-icon{}" width="{}" height="{}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" {}>{}</svg>',
        f" {css}" if css else "", int(size), int(size), a11y, mark_safe(body),
    )


@register.simple_tag
def ikart_logo(size=32, wordmark=True):
    """The IKart bag mark (+ wordmark). Uses theme tokens, so it adapts to light and dark."""
    mark = format_html(
        '<svg width="{0}" height="{0}" viewBox="0 0 48 48" aria-hidden="true">'
        '<path d="M17 18v-3a7 7 0 0 1 14 0v3" fill="none" stroke="var(--brand)" stroke-width="3.5" stroke-linecap="round"/>'
        '<rect x="6" y="16" width="36" height="28" rx="9" fill="var(--brand)"/>'
        '<path d="M24 22.5c.8 4.4 2.9 6.5 7.3 7.5-4.4 1-6.5 3.1-7.3 7.5-.8-4.4-2.9-6.5-7.3-7.5 4.4-1 6.5-3.1 7.3-7.5z" fill="var(--surface)"/>'
        "</svg>",
        int(size),
    )
    if not wordmark:
        return mark
    return format_html('{}<span class="ik-logo-word"><span class="ik-logo-i">I</span>Kart</span>', mark)
