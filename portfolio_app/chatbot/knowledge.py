"""
What the chatbot knows about the portfolio, and the links it may hand out.

Two sources, on purpose:

1. PROFILE - facts that are written directly into the public templates (name, role, city,
   education, contact links, services). They were copied from Homepage.html / About.html /
   Contact.html. If you change that wording in the templates, update it here too.

2. snapshot() - everything managed from the dashboard (skills, experience, projects,
   certificates, resume). It reads PUBLISHED rows only, mirroring the filters that the public
   views in portfolio_app/views.py already use, so unpublished work can never leak. The result
   is cached for a few minutes so a burst of chat messages does not hit the database each time.
"""
import logging

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse

logger = logging.getLogger(__name__)

SNAPSHOT_TTL = 300  # seconds; dashboard edits show up in chatbot answers within ~5 minutes

# ---------------------------------------------------------------- verified static facts
PROFILE = {
    'name': 'Tejas Modi',
    'first_name': 'Tejas',
    'title': 'Python Full Stack Developer',
    'location': 'Ranchi, India',
    'primary_stack': 'Python, Django, MySQL',
    'focus': 'management systems, role-based dashboards and backend architecture',
    'email': 'iamtejas.dev@gmail.com',
    'linkedin': 'https://www.linkedin.com/in/tejas-modi-26563a248/',
    'education': [
        'B.Tech in Computer Science & Engineering, Institute of Technical Education and Research '
        '(ITER), Siksha \u2018O\u2019 Anusandhan University, Bhubaneswar (10/2020 \u2013 06/2024)',
        'Senior Secondary (12th), Science stream, Bokaro Public School, Bokaro (06/2019 \u2013 03/2020)',
    ],
    'first_role': 'Python Full Stack Developer Intern (started 02/2025)',
    'services': [
        'Management systems (HR, labour, salon and real-estate style operations)',
        'Role-based dashboards with separate access for each type of user',
        'Backend systems and APIs in Python and Django',
        'Database design with MySQL, PostgreSQL and SQLite',
        'Responsive websites with HTML, CSS, Bootstrap and JavaScript',
        'CMS and admin panels so content can be managed without code changes',
    ],
    'process': [
        'Understand the business process: who uses the system and what is still done by hand.',
        'Structure the data and define roles, so each team gets the dashboard and access it needs.',
        'Build the Django backend, database and interface, then automate repeat work.',
    ],
}

# ---------------------------------------------------------------- links
# key -> (url name, anchor, label). Every url name below exists in portfolio_app/urls.py or
# dashboard_app/public_urls.py. Anchors exist as ids in About.html.
_LINKS = {
    'home':        ('home', '', 'Homepage'),
    'about':       ('about', '', 'About'),
    'skills':      ('about', 'arsenal', 'Skills on About'),
    'experience':  ('about', 'journey', 'Experience on About'),
    'education':   ('about', 'edu', 'Education on About'),
    'services':    ('about', 'do', 'Services on About'),
    'certificates': ('about', 'certs', 'Certificates'),
    'websites':    ('frontend_work', '', 'Websites'),
    'backend':     ('backend_projects', '', 'Backend projects'),
    'contact':     ('contact', '', 'Contact'),
    'start':       ('start_a_project', '', 'Start a project'),
    'resume_section': ('about', 'resume', 'Resume on About'),
    'resume':      ('resume_view', '', 'View resume'),
    'resume_download': ('resume_download', '', 'Download resume'),
}

# Page keys the AI is allowed to attach as buttons (it never writes URLs itself).
AI_PAGE_KEYS = ('about', 'skills', 'experience', 'websites', 'backend', 'contact', 'start', 'resume')


def link(key, label=None):
    """A {'label', 'url'} dict with a relative URL, so it works on any domain."""
    name, anchor, default_label = _LINKS[key]
    url = reverse(name) + (f'#{anchor}' if anchor else '')
    return {'label': label or default_label, 'url': url}


def external_links():
    out = {'email': {'label': 'Email Tejas', 'url': f"mailto:{PROFILE['email']}"},
           'linkedin': {'label': 'LinkedIn', 'url': PROFILE['linkedin']}}
    github = getattr(settings, 'GITHUB_URL', '') or ''
    if github.startswith('https://'):
        out['github'] = {'label': 'GitHub', 'url': github}
    return out


# ---------------------------------------------------------------- database snapshot
def _clip(text, n):
    text = ' '.join((text or '').split())
    return text if len(text) <= n else text[: n - 1].rstrip() + '\u2026'


def _empty():
    return {'ok': False, 'skills': [], 'experiences': [], 'websites': [], 'backend': [],
            'certificates': [], 'has_resume': False}


def _build_snapshot():
    # Imported here so this module can be imported (e.g. by tests) before apps are ready.
    from django.db.models import Prefetch
    from dashboard_app.models import (BackendProject, Certificate, Experience, Resume, Skill,
                                      SkillCategory, WebsiteProject)

    cats = SkillCategory.objects.filter(is_published=True).prefetch_related(
        Prefetch('skills', queryset=Skill.objects.filter(is_published=True), to_attr='live_skills'))
    skills = [{'category': c.name, 'items': [s.name for s in c.live_skills]}
              for c in cats if c.live_skills]

    experiences = [{
        'role': e.role, 'company': e.company, 'location': e.location,
        'period': e.period_display, 'current': bool(e.is_current or not e.end_date),
        'tech': e.tech_list[:10], 'summary': _clip(e.description, 280),
    } for e in Experience.objects.filter(is_published=True)]

    websites = [{
        'title': w.title, 'category': w.get_category_display(),
        'summary': _clip(w.short_description, 200), 'tech': w.tech_list[:10],
    } for w in WebsiteProject.objects.filter(is_published=True)]

    backend = [{
        'title': p.title, 'category': p.get_category_display(), 'period': p.period,
        'summary': _clip(p.short_description, 200), 'tech': p.tech_list[:10],
        'modules': [_clip(m, 60) for m in p.modules_list[:8]],
    } for p in BackendProject.objects.filter(is_published=True)]

    certificates = [{'name': c.name, 'issuer': c.issuer, 'issued_on': c.issued_on}
                    for c in Certificate.objects.filter(is_published=True)]

    return {
        'ok': True, 'skills': skills, 'experiences': experiences, 'websites': websites,
        'backend': backend, 'certificates': certificates,
        # Same rule the public pages use for showing resume buttons.
        'has_resume': Resume.objects.filter(is_active=True).exists(),
    }


def snapshot():
    """Published portfolio data. Never raises: on a database problem it returns an empty,
    ok=False snapshot (not cached) and the chatbot falls back to generic, link-based answers."""
    cached = cache.get('chatbot:snapshot:v1')
    if cached is not None:
        return cached
    try:
        data = _build_snapshot()
    except Exception:  # noqa: BLE001 - the chatbot must never take a page down
        logger.exception('Chatbot: could not read portfolio data')
        return _empty()
    cache.set('chatbot:snapshot:v1', data, SNAPSHOT_TTL)
    return data


def snapshot_as_text(data, limit=6000):
    """Compact plain-text rendering of the snapshot, used as AI context."""
    lines = []
    if data['skills']:
        lines.append('SKILLS (from the About page):')
        lines += [f"- {s['category']}: {', '.join(s['items'])}" for s in data['skills']]
    if data['experiences']:
        lines.append('EXPERIENCE (newest first):')
        for e in data['experiences']:
            where = f" ({e['location']})" if e['location'] else ''
            tech = f" Tech: {', '.join(e['tech'])}." if e['tech'] else ''
            lines.append(f"- {e['role']} at {e['company']}{where}, {e['period']}. {e['summary']}{tech}")
    if data['websites']:
        lines.append('FRONTEND / WEBSITE PROJECTS (page: /websites/):')
        for w in data['websites']:
            tech = f" Tech: {', '.join(w['tech'])}." if w['tech'] else ''
            lines.append(f"- {w['title']} [{w['category']}]: {w['summary']}{tech}")
    if data['backend']:
        lines.append('BACKEND PROJECTS (page: /backend-projects/):')
        for p in data['backend']:
            tech = f" Tech: {', '.join(p['tech'])}." if p['tech'] else ''
            mods = f" Modules: {', '.join(p['modules'])}." if p['modules'] else ''
            period = f", {p['period']}" if p['period'] else ''
            lines.append(f"- {p['title']} [{p['category']}{period}]: {p['summary']}{tech}{mods}")
    if data['certificates']:
        lines.append('CERTIFICATES:')
        for c in data['certificates']:
            extra = ', '.join(x for x in (c['issuer'], c['issued_on']) if x)
            lines.append(f"- {c['name']}" + (f' ({extra})' if extra else ''))
    lines.append('RESUME: ' + ('an active resume can be previewed and downloaded on the site.'
                               if data['has_resume'] else 'no resume is currently published.'))
    return '\n'.join(lines)[:limit]
