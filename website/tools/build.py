#!/usr/bin/env python3
"""Build the Heirloom Unbound marketing site: website/src -> website/public.

  python3 website/tools/build.py               # preview build (noindex, preview banner + notes for C L)
  python3 website/tools/build.py --production  # strips preview-only blocks, allows indexing
  SITE_URL=https://example.com python3 ...      # canonical origin (placeholder until C L picks the domain)
  DEMO_DIR=/path/to/mp4s                       # demo videos to wire into the video slots (copied to assets/video)

Pages use {{name}} includes from src/partials and these tokens: {{SITE}}, {{PATH}}, {{TITLE}}, {{DESC}}.
Blocks between <!--PREVIEW--> and <!--/PREVIEW--> only appear in preview builds.
"""
import os, re, sys, json, shutil, datetime, html
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC, OUT = os.path.join(ROOT, 'src'), os.path.join(ROOT, 'public')
PROD = '--production' in sys.argv
SITE = os.environ.get('SITE_URL', 'https://heirloom.unboundinfotech.com').rstrip('/')  # TODO(C L): final domain
DEMO_DIR = os.environ.get('DEMO_DIR', '/workspace/heirloom-demo/final')

# Video slots: id -> filename keywords (first matching mp4 in DEMO_DIR wins)
SLOTS = {
    'interview': ['lifestory', 'life-story', 'interview', 'onboard'],
    'phone': ['lookphone', 'phone', 'mobile', 'qr'],
    'recall': ['twin', 'recall', 'cite', 'ask'],
    'skills': ['skills', 'skill', 'assistant', 'remind', 'calendar'],
    'heir': ['heir', 'family', 'portal'],
    'look': ['look', 'tour', 'overview', 'install'],
}

def find_videos():
    found = {}
    vdir = os.path.join(OUT, 'assets', 'video')
    os.makedirs(vdir, exist_ok=True)
    pool = []
    for d in (DEMO_DIR, vdir):
        if os.path.isdir(d):
            pool += [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.lower().endswith(('.mp4', '.webm'))]
    for slot, keys in SLOTS.items():
        for p in pool:
            n = os.path.basename(p).lower()
            if any(k in n for k in keys) and p not in found.values():
                found[slot] = p; break
    out = {}
    for slot, p in found.items():
        dst = os.path.join(vdir, os.path.basename(p))
        if os.path.abspath(p) != os.path.abspath(dst): shutil.copy2(p, dst)
        poster = os.path.splitext(dst)[0] + '.jpg'
        if not os.path.exists(poster):
            os.system(f'ffmpeg -loglevel error -y -ss 2 -i "{dst}" -frames:v 1 -vf scale=960:-2 -q:v 4 "{poster}"')
        out[slot] = 'assets/video/' + os.path.basename(dst)
    return out

def wire_video(m, videos):
    slot, label = m.group(1), m.group(2)
    src = videos.get(slot)
    if not src:
        return (f'<div class="video" id="video-{slot}" role="img" aria-label="Demo video coming soon: {html.escape(label)}">'
                f'<div><span class="tag ghost">Video coming soon</span><br>{html.escape(label)}</div></div>')
    poster = os.path.splitext(src)[0] + '.jpg'
    p = f' poster="{poster}"' if os.path.exists(os.path.join(OUT, poster)) else ''
    return (f'<div class="video has" id="video-{slot}"><video controls preload="none" playsinline{p} '
            f'aria-label="{html.escape(label)}"><source src="{src}" type="video/{src.rsplit(".",1)[1]}"></video></div>')

def render(page, partials, videos):
    raw = open(os.path.join(SRC, page), encoding='utf-8').read()
    meta = dict(re.findall(r'^<!--\s*(\w+):\s*(.*?)\s*-->$', raw, re.M))
    body = re.sub(r'^<!--\s*\w+:.*?-->\n', '', raw, flags=re.M)
    for _ in range(3):
        body = re.sub(r'{{>(\w+)}}', lambda m: partials[m.group(1)], body)
    body = re.sub(r'{{video:(\w+)\|([^}]*)}}', lambda m: wire_video(m, videos), body)
    if PROD:
        body = re.sub(r'<!--PREVIEW-->.*?<!--/PREVIEW-->', '', body, flags=re.S)
    else:
        body = body.replace('<!--PREVIEW-->', '').replace('<!--/PREVIEW-->', '')
    path = '/' if page == 'index.html' else '/' + page
    toks = {'SITE': SITE, 'PATH': path, 'TITLE': meta.get('title', ''), 'DESC': meta.get('desc', ''),
            'ROBOTS': 'index,follow' if PROD else 'noindex,nofollow', 'YEAR': str(datetime.date.today().year)}
    for k, v in toks.items():
        body = body.replace('{{' + k + '}}', v)
    body = re.sub(r'{{nav:(\w+)}}', lambda m: ' aria-current="page"' if m.group(1) == meta.get('nav') else '', body)
    body = re.sub(r'\n\s*\n+', '\n', body)
    return body, meta

def main():
    partials = {os.path.splitext(f)[0]: open(os.path.join(SRC, 'partials', f), encoding='utf-8').read().strip()
                for f in os.listdir(os.path.join(SRC, 'partials'))}
    videos = find_videos()
    pages = sorted(f for f in os.listdir(SRC) if f.endswith('.html'))
    urls = []
    for p in pages:
        out, meta = render(p, partials, videos)
        open(os.path.join(OUT, p), 'w', encoding='utf-8').write(out)
        if meta.get('sitemap', 'yes') != 'no':
            urls.append(('/' if p == 'index.html' else '/' + p, meta.get('priority', '0.7')))
    today = datetime.date.today().isoformat()
    sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    sm += [f'  <url><loc>{SITE}{u}</loc><lastmod>{today}</lastmod><priority>{pr}</priority></url>' for u, pr in urls]
    sm.append('</urlset>')
    open(os.path.join(OUT, 'sitemap.xml'), 'w').write('\n'.join(sm) + '\n')
    robots = f'User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n' if PROD else 'User-agent: *\nDisallow: /\n'
    open(os.path.join(OUT, 'robots.txt'), 'w').write(robots)
    print(f'built {len(pages)} pages ({"production" if PROD else "preview"}), site={SITE}, videos={json.dumps(videos)}')

if __name__ == '__main__':
    main()
