#!/usr/bin/env python3
"""Text-contrast sweep of the rendered application (WCAG 2.x, AA).

Opens each page of the screenshot manifests on the demo instance in the light
and the dark theme, and lists every visible text element whose colour against
its effective background is under 4.5:1 (3:1 for large text). Disabled
controls are reported too; WCAG exempts them, so judge those by eye.

    DEMO_DIR=/var/tmp/clientst0r-demo DJANGO_SETTINGS_MODULE=demo_settings \
    PYTHONPATH=scripts/demo:. python scripts/contrast_check.py [--route /reports/ ...] [--json out.json]

Needs the demo server (scripts/demo/README.md) and Playwright, like
scripts/capture_screenshots.py. Exit status 1 when anything fails.
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import capture_screenshots as cs  # noqa: E402

MANIFESTS = ('screenshot_manifest.json', 'guide_screenshots.json')

JS = r"""() => {
 const parse = c => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return [p[0],p[1],p[2],p.length>3?p[3]:1]; };
 const lum = ([r,g,b]) => { const f = v => { v/=255; return v<=.03928? v/12.92 : Math.pow((v+.055)/1.055,2.4); }; return .2126*f(r)+.7152*f(g)+.0722*f(b); };
 const over = (top, bot) => { const a = top[3]; return [top[0]*a+bot[0]*(1-a), top[1]*a+bot[1]*(1-a), top[2]*a+bot[2]*(1-a), 1]; };
 function bgOf(el) { const stack=[]; let e=el; while (e && e.nodeType===1) { const cs=getComputedStyle(e); if (cs.backgroundImage && cs.backgroundImage!=='none' && !cs.backgroundImage.startsWith('url')) return null; const c=parse(cs.backgroundColor); if (c && c[3]>0) { stack.push(c); if (c[3]>=1) break; } e=e.parentElement; } let base = [255,255,255,1]; if (!e) { const bc=parse(getComputedStyle(document.body).backgroundColor); } for (let i=stack.length-1;i>=0;i--) base = over(stack[i], base); return base; }
 function opac(el){ let o=1, e=el; while(e && e.nodeType===1){ o*=parseFloat(getComputedStyle(e).opacity); e=e.parentElement;} return o; }
 const out=[]; const seen=new Set(); const isSvg = el => el instanceof SVGElement;
 const walker=document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
 while (walker.nextNode()) { const t=walker.currentNode; const txt=t.textContent.trim(); if (txt.length<2) continue; if (t.parentElement && t.parentElement.closest(".skip-to-main,.visually-hidden-focusable")) continue; const el=t.parentElement; if (!el || seen.has(el) || isSvg(el)) continue; seen.add(el);
  const r=el.getBoundingClientRect(); if (r.width<1||r.height<1) continue; const cs=getComputedStyle(el); if (cs.visibility==='hidden' || el.closest('[aria-hidden=true],script,style,noscript,.visually-hidden,.sr-only,canvas,.modal:not(.show),.dropdown-menu:not(.show),.collapse:not(.show),[hidden]')) continue;
  let fg=parse(cs.color); if(!fg) continue; const bg=bgOf(el); if(!bg) continue; const o=opac(el); fg=[fg[0],fg[1],fg[2],fg[3]*o]; fg=over(fg,bg);
  const L1=lum(fg), L2=lum(bg); const ratio=(Math.max(L1,L2)+.05)/(Math.min(L1,L2)+.05);
  const size=parseFloat(cs.fontSize), bold=parseInt(cs.fontWeight)>=700; const large= size>=24 || (bold && size>=18.66);
  const need= large?3:4.5; if (ratio<need) { let sel=el.tagName.toLowerCase()+(el.id?'#'+el.id:'')+(el.className&&typeof el.className==='string'?'.'+el.className.trim().split(/\s+/).slice(0,3).join('.'):''); out.push({sel, text: txt.slice(0,50), ratio: Math.round(ratio*100)/100, need, fg: fg.slice(0,3).map(Math.round), bg: bg.slice(0,3).map(Math.round), y: Math.round(r.top+scrollY), html: el.outerHTML.slice(0,160)}); }
 }
 return out; }"""


def manifest_routes():
    routes = set()
    for name in MANIFESTS:
        data = json.loads((pathlib.Path(__file__).resolve().parent / name).read_text())
        entries = data.get('screenshots', data) if isinstance(data, dict) else data
        for e in entries:
            r = isinstance(e, dict) and (e.get('route') or e.get('url'))
            if r and r.startswith('/') and '{' not in r:
                routes.add(r)
    return sorted(routes)


def main():
    from playwright.sync_api import sync_playwright
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--base', default='http://127.0.0.1:8099')
    ap.add_argument('--route', action='append', help='check only these paths (repeatable)')
    ap.add_argument('--user', default='demo.tech')
    ap.add_argument('--organization', default='Northwind Logistics')
    ap.add_argument('--json', type=pathlib.Path, help='write every finding here')
    args = ap.parse_args()
    routes = args.route or manifest_routes()
    session = cs.make_session(args.user, args.organization)
    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for theme in ('light', 'dark'):
            ctx = browser.new_context(viewport={'width': 1440, 'height': 1000})
            ctx.add_cookies([{'name': cs.settings.SESSION_COOKIE_NAME, 'value': session,
                              'domain': args.base.split('//')[1].split(':')[0], 'path': '/'}])
            page = ctx.new_page()
            themed = False
            for route in routes:
                try:
                    page.goto(args.base + route, wait_until='networkidle', timeout=30000)
                    if not themed:
                        cs.ensure_theme(page, args.base, theme)
                        themed = True
                        page.goto(args.base + route, wait_until='networkidle', timeout=30000)
                    page.wait_for_timeout(300)
                    results[f'{theme} {route}'] = page.evaluate(JS)
                except Exception as exc:  # report and carry on with the next page
                    results[f'{theme} {route}'] = [{'error': str(exc)[:200]}]
            ctx.close()
        browser.close()
    failures = 0
    for key, found in results.items():
        for f in found:
            failures += 1
            if 'error' in f:
                print(f'{key}: ERROR {f["error"]}')
            else:
                print(f'{key}: {f["ratio"]}:1 (needs {f["need"]}) {f["text"]!r} {f["sel"]}')
    if args.json:
        args.json.write_text(json.dumps(results, indent=1))
    print(f'{failures} finding(s) on {len(routes)} page(s) x 2 themes')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
