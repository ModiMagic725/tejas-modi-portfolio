"""
Static question/answer system. Pure Python, no network, no API key.

How matching works
------------------
1. The message is normalised: lower-cased, apostrophes dropped, punctuation turned into
   spaces, a few chat abbreviations expanded ("ur" -> "your"), and each word lightly stemmed
   (plural 's', 'ing', 'ed') so "projects" == "project" and "websites" == "website".
2. Every intent has weighted vocabulary:
       phrases  (4 or 6)    multi-word expressions, matched as a contiguous run of words
                            (6 points when the phrase has three or more words)
       strong   (4 points)  single words that almost always mean this intent
       keywords (2 points)  words that usually mean this intent
       weak     (1 point)   hints
3. The best intent wins only if it is clearly ahead of the runner-up. Long, many-part
   questions need a very strong match, otherwise they are left for the AI fallback.

Simple Hinglish (Latin script) is covered through the same vocabulary lists, e.g.
"apna resume do", "tumhare projects dikhao", "kaise contact karu", "hire karna hai".

Every answer is returned as a Reply: plain text + link buttons + suggested follow-ups.
Text is always plain text (the browser renders it with textContent), never HTML.
"""
import re
import unicodedata
from dataclasses import dataclass, field

from . import knowledge as kb


@dataclass
class Reply:
    text: str
    links: list = field(default_factory=list)          # [{'label', 'url'}]
    suggestions: list = field(default_factory=list)    # [(label, intent_id)]


# ---------------------------------------------------------------- normalisation
_ABBREV = {'u': 'you', 'ur': 'your', 'r': 'are', 'abt': 'about', 'pls': 'please', 'plz': 'please',
           'thx': 'thanks', 'tnx': 'thanks', 'wanna': 'want', 'cv': 'cv', 'dev': 'developer'}


def normalize(text):
    text = unicodedata.normalize('NFKC', text or '').lower()
    text = text.replace('\u2019', "'").replace('\u2018', "'").replace("'", '')
    text = re.sub(r'[^a-z0-9]+', ' ', text)
    return ' '.join(text.split())


def stem(word):
    if len(word) > 4 and word.endswith('s') and not word.endswith('ss'):
        word = word[:-1]
    if len(word) > 6 and word.endswith('ing'):
        word = word[:-3]
    elif len(word) > 5 and word.endswith('ed'):
        word = word[:-2]
    return word


def tokenize(text):
    return [stem(_ABBREV.get(w, w)) for w in normalize(text).split()]


def _stem_phrase(phrase):
    return tuple(tokenize(phrase))


def _contains(tokens, phrase):
    n = len(phrase)
    return any(tuple(tokens[i:i + n]) == phrase for i in range(len(tokens) - n + 1))


# ---------------------------------------------------------------- vocabulary
# Format: id -> dict(phrases=[...], strong=[...], keywords=[...], weak=[...])
_VOCAB = {
    'about_me': dict(
        phrases=['who are you', 'who is tejas', 'who is he', 'who r u', 'about you', 'about yourself',
                 'about tejas', 'about him', 'tell me about you', 'introduce yourself', 'introduce tejas',
                 'who made this', 'who built this', 'who owns this', 'tum kaun ho', 'aap kaun ho',
                 'aap kon ho', 'tum kon ho', 'tejas kaun hai', 'apne bare mein', 'aapke bare mein',
                 'tumhare bare mein', 'apne baare mein', 'about the developer', 'about this portfolio'],
        strong=['yourself', 'introduce', 'introduction', 'intro', 'bio'],
        keywords=['tejas', 'modi', 'profile'],
        weak=['kaun', 'kon', 'who', 'developer', 'person']),
    'background': dict(
        phrases=['your background', 'his background', 'professional background', 'educational background',
                 'where did you study', 'where do you study', 'where did he study', 'kahan se padhai',
                 'kahan padhe', 'career path', 'career summary', 'professional summary', 'career journey'],
        strong=['education', 'qualification', 'degree', 'btech', 'college', 'university', 'padhai',
                'academic', 'graduate', 'graduation', 'studied', 'schooling'],
        keywords=['background', 'study', 'school', 'shiksha', 'learned', 'journey'],
        weak=['learn', 'qualified']),
    'skills': dict(
        phrases=['tech stack', 'technical skills', 'what skills', 'skills do you have', 'what can you code',
                 'what do you know', 'kya aata hai', 'kya kya aata hai', 'programming languages',
                 'what languages', 'which languages', 'what technologies', 'which technologies',
                 'technologies do you use', 'technologies you use', 'tools do you use', 'what do you use',
                 'skills kya hai', 'skills batao', 'your expertise', 'areas of expertise',
                 'do you know', 'do you use', 'do you work with', 'do you code in', 'are you familiar',
                 'familiar with', 'does he know', 'does he use'],
        strong=['skill', 'techstack', 'expertise', 'proficient', 'proficiency'],
        keywords=['stack', 'language', 'technology', 'technologie', 'tool', 'framework', 'python', 'django',
                  'mysql', 'postgresql', 'postgres', 'java', 'javascript', 'html', 'css', 'bootstrap',
                  'database', 'sqlite', 'aata', 'technical'],
        weak=['know', 'code', 'coding', 'programming']),
    'experience': dict(
        phrases=['work experience', 'where have you worked', 'where did you work', 'where does he work',
                 'previous companies', 'previous jobs', 'past jobs', 'years of experience', 'how long have you',
                 'how many years', 'kitna experience', 'kitne saal', 'work history', 'employment history',
                 'current job', 'current role', 'current company', 'professional experience',
                 'kaam ka anubhav', 'kahan kaam kiya', 'kahan kaam karte'],
        strong=['experience', 'experienced', 'internship', 'intern', 'employment', 'anubhav', 'naukri',
                'employer', 'employers'],
        keywords=['worked', 'job', 'company', 'role', 'career', 'companie', 'tenure', 'position'],
        weak=['work', 'years']),
    'resume': dict(
        phrases=['download resume', 'download cv', 'see your resume', 'where can i see your resume',
                 'resume kahan', 'cv kahan', 'apna resume', 'apna cv', 'resume do', 'cv do', 'resume dikhao',
                 'curriculum vitae', 'send resume', 'send cv'],
        strong=['resume', 'cv', 'biodata', 'resumes', 'vitae'],
        keywords=['pdf'],
        weak=['download']),
    'frontend': dict(
        phrases=['frontend projects', 'front end projects', 'front end', 'website projects', 'websites you built',
                 'websites you made', 'websites built', 'websites made', 'web projects', 'live websites',
                 'live demo', 'sites you made', 'sites you built', 'website dikhao', 'websites dikhao',
                 'web design', 'landing pages', 'show me websites', 'ui projects', 'frontend work'],
        strong=['frontend', 'websites', 'website', 'landing'],
        keywords=['ui', 'ux', 'responsive', 'webpage', 'webdesign', 'site', 'design'],
        weak=['html', 'css', 'bootstrap', 'web']),
    'backend': dict(
        phrases=['backend projects', 'back end projects', 'back end', 'django projects', 'django project',
                 'management system', 'management systems', 'backend systems', 'server side', 'backend work',
                 'api projects', 'backend dikhao', 'backend projects dikhao', 'role based dashboard',
                 'role based dashboards'],
        strong=['backend', 'api', 'apis', 'payroll'],
        keywords=['django', 'server', 'dashboard', 'dashboards', 'architecture', 'automation', 'workflow'],
        weak=['database', 'system', 'systems']),
    'projects': dict(
        phrases=['show me your projects', 'your projects', 'his projects', 'what have you built',
                 'what have you made', 'what have you done', 'what has he built', 'your work', 'his work',
                 'see your work', 'previous work', 'past work', 'sample work', 'projects dikhao',
                 'project dikhao', 'kaam dikhao', 'apne projects', 'tumhare projects', 'aapke projects',
                 'portfolio dikhao', 'show projects', 'list of projects', 'all projects', 'what projects',
                 'which projects', 'projects kya hai', 'case studies', 'case study'],
        strong=['project', 'projects', 'portfolio', 'showcase'],
        keywords=['built', 'made', 'created', 'demo', 'samples', 'sample', 'dikhao'],
        weak=['work', 'show', 'kaam']),
    'services': dict(
        phrases=['what services', 'services do you offer', 'what do you offer', 'what do you do',
                 'what can you build', 'what can you make', 'what do you build', 'development services',
                 'what can you do for me', 'what can he build', 'what does he do', 'kya karte ho',
                 'kya kaam karte ho', 'kya banate ho', 'kya bana sakte ho', 'kya banaate ho',
                 'technologies and services', 'services offered', 'type of work', 'types of work',
                 'kind of work', 'kinds of projects'],
        strong=['service', 'offering', 'offer'],
        keywords=['provide', 'specialize', 'specialise', 'speciality', 'specialty', 'deliver'],
        weak=['build', 'make', 'develop', 'development']),
    'hire': dict(
        phrases=['hire you', 'hire tejas', 'hire him', 'want to hire', 'looking to hire', 'like to hire',
                 'work with you', 'work together', 'work with tejas', 'are you available', 'is he available',
                 'available for', 'open to work', 'open for work', 'for hire', 'job offer', 'job opportunity',
                 'hire karna', 'hire karni', 'hire karun', 'kaam dena', 'aapko hire', 'tumhe hire',
                 'take you on', 'join our team', 'join my team', 'need a developer', 'need developer',
                 'looking for a developer', 'looking for developer'],
        strong=['hire', 'hiring', 'hired', 'recruit', 'recruiter', 'recruitment', 'freelance', 'freelancer',
                'freelancing', 'vacancy'],
        keywords=['available', 'availability', 'opportunity', 'collaborate', 'collaboration', 'opening',
                  'engage', 'onboard'],
        weak=['team', 'join']),
    'start_project': dict(
        phrases=['start a project', 'start project', 'new project', 'have a project', 'project idea',
                 'project requirements', 'project brief', 'build me', 'build a website', 'build website',
                 'make a website', 'make website', 'create a website', 'create website', 'need a website',
                 'need website', 'want a website', 'want website', 'want to build', 'want to make',
                 'want to create', 'i need an app', 'i want an app', 'build an app', 'build a web app',
                 'build a system', 'build a software', 'website banwani', 'website banwana', 'website banana',
                 'website banani', 'app banwana', 'app banana', 'project shuru', 'project start karna',
                 'start karna hai', 'get started', 'submit requirements', 'share requirements',
                 'my requirements', 'discuss a project', 'discuss my project', 'work on my project',
                 'website banwa', 'website bana do', 'website chahiye', 'app chahiye', 'software chahiye'],
        strong=['requirement', 'requirements', 'banwani', 'banwana', 'banwa'],
        keywords=['brief', 'proposal', 'intake', 'chahiye', 'shuru', 'idea', 'startup'],
        weak=['start', 'begin', 'launch']),
    'pricing': dict(
        phrases=['how much', 'how much do you charge', 'how much does it cost', 'kitna paisa', 'kitne paise',
                 'kitna lagega', 'kitne ka', 'price list', 'your rates', 'your charges', 'your fees',
                 'what do you charge', 'cost of a website', 'cost of website', 'quote for', 'estimate for',
                 'cost of', 'cost for'],
        strong=['price', 'pricing', 'cost', 'charges', 'charge', 'fees', 'fee', 'rates', 'rate', 'quote',
                'quotation', 'estimate', 'paisa', 'paise', 'kharcha', 'afford', 'affordable', 'cheap'],
        keywords=['budget', 'payment', 'rupee', 'rupees', 'inr', 'usd', 'dollar'],
        weak=['expensive']),
    'contact': dict(
        phrases=['get in touch', 'reach you', 'reach out', 'reach tejas', 'contact you', 'contact tejas',
                 'contact details', 'contact info', 'contact information', 'how to contact', 'how can i contact',
                 'how do i contact', 'kaise contact', 'contact kaise', 'contact karu', 'contact karna',
                 'email id', 'mail id', 'email address', 'phone number', 'contact number', 'mobile number',
                 'whatsapp number', 'send a message', 'send message', 'talk to you', 'talk to tejas',
                 'baat karni', 'baat karna', 'baat karu', 'message karna', 'call you', 'call him'],
        strong=['contact', 'email', 'mail', 'linkedin', 'github', 'whatsapp', 'sampark', 'phone', 'mobile',
                'telephone'],
        keywords=['reach', 'message', 'call', 'number', 'connect', 'inbox', 'social'],
        weak=['talk', 'speak', 'baat']),
    'navigation': dict(
        phrases=['where can i find', 'where do i find', 'where is', 'how do i get to', 'take me to', 'go to',
                 'site map', 'which page', 'what pages', 'pages on', 'help me find', 'show me around',
                 'kahan milega', 'kahan hai', 'kahan dekhu', 'website tour', 'guide me', 'what can i ask',
                 'what can you help', 'how can you help', 'what can you help with', 'how do you work',
                 'what is this site', 'what is this website', 'what is on this site', 'main menu',
                 'which section', 'what sections'],
        strong=['navigate', 'navigation', 'sitemap', 'menu', 'sections', 'section'],
        keywords=['page', 'pages', 'explore', 'find', 'kahan', 'where', 'tour', 'guide'],
        weak=['help', 'link', 'links', 'open']),
}

# Order breaks ties and drives the "best guess" when the AI is unavailable.
_PRIORITY = ['resume', 'hire', 'start_project', 'pricing', 'contact', 'projects', 'frontend', 'backend',
             'skills', 'experience', 'background', 'services', 'about_me', 'navigation']

_COMPILED = {}
for _id, _v in _VOCAB.items():
    _COMPILED[_id] = {
        'phrases': [p for p in (_stem_phrase(x) for x in _v['phrases']) if p],
        'strong': {stem(w) for w in _v['strong']},
        'keywords': {stem(w) for w in _v['keywords']},
        'weak': {stem(w) for w in _v['weak']},
    }

# Whole-message intents (only when the message is *only* this kind of words).
_GREETING_WORDS = {stem(w) for w in (
    'hi hii hiii hello helo hey heyy hlo hola yo sup namaste namaskar pranam good morning afternoon evening '
    'there bot assistant everyone all tejas how are you kaise ho kya haal hai whats up wassup greetings').split()}
_THANKS_WORDS = {stem(w) for w in (
    'thanks thank you thankyou ty thx shukriya dhanyavad dhanyawad ok okay k great nice cool awesome perfect '
    'got it bye goodbye see later cya take care alright fine good wow amazing helpful').split()}
_BYE_WORDS = {'bye', 'goodbye', 'cya', 'later'}
_HELP_ONLY = {'help', 'help me', 'please help', 'options', 'menu', 'commands', 'start', 'what can i do'}

# Requests that should never reach the AI or reveal anything.
_BLOCKED = re.compile(
    r'ignore (all |any |the |your |previous |prior |above |earlier )*(instruction|prompt|rule|direction)'
    r'|disregard (all |any |the |your |previous |prior |above )*(instruction|prompt|rule)'
    r'|system prompt|developer message|hidden prompt|initial prompt|your (instruction|prompt|rule)s?\b'
    r'|reveal .{0,25}(prompt|instruction|secret|key|password)'
    r'|api ?key|secret key|access token|environment variable|env file|dotenv|\benv\b'
    r'|admin ?panel|admin login|dashboard login|admin password|\bpassword\b|\bcredentials?\b'
    r'|jailbreak|\bdan mode\b|developer mode|pretend (to be|you are|youre)|you are now|act as if'
)


# ---------------------------------------------------------------- matching
@dataclass
class Match:
    intent: str            # intent id, or 'unknown'
    score: int
    confident: bool


def match(text):
    """Decide which static intent (if any) a message is about."""
    tokens = tokenize(text)
    if not tokens:
        return Match('unknown', 0, False)

    # Pure greeting / thanks messages
    tset = set(tokens)
    if tset <= _GREETING_WORDS and len(tokens) <= 6:
        return Match('greeting', 10, True)
    if tset <= (_THANKS_WORDS | _GREETING_WORDS) and len(tokens) <= 5:
        return Match('bye' if tset & _BYE_WORDS else 'thanks', 10, True)

    if ' '.join(tokens) in _HELP_ONLY:
        return Match('navigation', 10, True)

    scores = {}
    for iid, v in _COMPILED.items():
        s = 0
        for ph in v['phrases']:
            if _contains(tokens, ph):
                s += 6 if len(ph) >= 3 else 4      # longer phrases are more specific
        for t in tset:
            if t in v['strong']:
                s += 4
            elif t in v['keywords']:
                s += 2
            elif t in v['weak']:
                s += 1
        if s:
            scores[iid] = s
    if not scores:
        return Match('unknown', 0, False)

    # "where can I find your projects" is about *projects*; the generic navigation wrapper
    # only wins when nothing more specific is mentioned.
    if 'navigation' in scores and any(k != 'navigation' and v >= 2 for k, v in scores.items()):
        scores['navigation'] //= 2

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], _PRIORITY.index(kv[0])))
    best_id, best = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0
    confident = best >= 4 and (best - second) >= 2
    if len(tokens) > 14 and best < 8:           # long multi-part question: let the AI have a go
        confident = False
    return Match(best_id, best, confident)


def is_blocked(text):
    return bool(_BLOCKED.search(normalize(text)))


# ---------------------------------------------------------------- answers
def _bullets(items, limit=6):
    return '\n'.join(f'\u2022 {i}' for i in items[:limit])


def _names(items, key='title', limit=3):
    return [i[key] for i in items[:limit]]


def _sugg(*ids):
    return [(LABELS[i], i) for i in ids]


# Short labels used for quick replies and follow-up suggestions.
LABELS = {
    'projects': 'Show me your projects',
    'frontend': 'Website projects',
    'backend': 'Backend projects',
    'skills': 'What are your skills?',
    'experience': 'Work experience',
    'background': 'Education and background',
    'resume': 'Where is your resume?',
    'hire': 'How can I hire you?',
    'start_project': 'Start a project',
    'contact': 'Contact details',
    'services': 'What services do you offer?',
    'about_me': 'Who is Tejas?',
    'navigation': 'Help me find a page',
    'pricing': 'What about pricing?',
}
QUICK_REPLIES = ['projects', 'skills', 'experience', 'resume', 'hire', 'contact']
ALLOWED_INTENTS = set(LABELS) | {'greeting', 'thanks', 'unknown'}


def _greeting(d):
    return Reply(
        "Hi! I'm the portfolio assistant. I can walk you through Tejas's projects, skills and "
        "experience, or point you to the right page. What would you like to see?",
        suggestions=_sugg('projects', 'skills', 'hire'))


def _thanks(d):
    return Reply("Happy to help! If you'd like to go further, these are good next steps.",
                 suggestions=_sugg('projects', 'contact', 'start_project'))


def _about_me(d):
    P = kb.PROFILE
    return Reply(
        f"{P['name']} is a {P['title']} based in {P['location']}. He builds Django management "
        f"platforms with role-based dashboards, workflow automation and clean backend architecture. "
        f"His primary stack is {P['primary_stack']}, with a focus on {P['focus']}.",
        links=[kb.link('about'), kb.link('contact')],
        suggestions=_sugg('skills', 'experience', 'projects'))


def _background(d):
    P = kb.PROFILE
    roles = len(d['experiences'])
    lines = [f"Tejas studied {P['education'][0]}.", f"Before that: {P['education'][1]}."]
    lines.append(f"His first developer role was as a {P['first_role']}.")
    if roles:
        lines.append(f"Since then he has held {roles} role{'s' if roles != 1 else ''} "
                     f"in Python and Django development; the full timeline is on the About page.")
    return Reply('\n'.join(lines),
                 links=[kb.link('education'), kb.link('experience')],
                 suggestions=_sugg('experience', 'skills', 'resume'))


def _skills(d):
    P = kb.PROFILE
    if d['skills']:
        rows = [f"{s['category']}: {', '.join(s['items'])}" for s in d['skills']]
        text = (f"Tejas works mainly with {P['primary_stack']}. Here is the technical arsenal "
                f"from his About page:\n{_bullets(rows, 8)}")
    else:
        text = (f"Tejas works mainly with {P['primary_stack']}, building backends, databases "
                f"(MySQL, PostgreSQL, SQLite) and responsive interfaces. The full list is on the About page.")
    return Reply(text, links=[kb.link('skills')], suggestions=_sugg('projects', 'experience', 'hire'))


def _experience(d):
    if d['experiences']:
        rows = []
        for e in d['experiences'][:5]:
            rows.append(f"{e['role']} at {e['company']} ({e['period']})")
        text = f"Here are Tejas's roles, newest first:\n{_bullets(rows, 5)}"
    else:
        text = "Tejas's work history is laid out as a timeline on the About page."
    return Reply(text, links=[kb.link('experience')], suggestions=_sugg('skills', 'projects', 'resume'))


def _resume(d):
    if d['has_resume']:
        return Reply("Tejas's resume is available to preview in your browser or download as a PDF.",
                     links=[kb.link('resume'), kb.link('resume_download'), kb.link('resume_section')],
                     suggestions=_sugg('experience', 'hire', 'contact'))
    return Reply("A resume isn't published on the site right now. You can ask Tejas for one by "
                 "message, or read his background and experience on the About page.",
                 links=[kb.link('contact'), kb.link('about')],
                 suggestions=_sugg('experience', 'background', 'contact'))


def _frontend(d):
    items = d['websites']
    if items:
        t = ', '.join(_names(items))
        text = (f"The Websites page shows Tejas's frontend work, including {t}. Each project has "
                f"screenshots, the technologies used and a live link where available.")
    else:
        text = "The Websites page shows Tejas's frontend projects, with screenshots and the technologies used."
    return Reply(text, links=[kb.link('websites')], suggestions=_sugg('backend', 'skills', 'start_project'))


def _backend(d):
    items = d['backend']
    if items:
        t = ', '.join(_names(items))
        text = (f"The Backend Projects page covers Tejas's Django systems, including {t}. "
                f"Each one lists its roles, modules and key points, with a PDF write-up where available.")
    else:
        text = ("The Backend Projects page covers Tejas's Django systems, with their roles, modules and "
                "key points.")
    return Reply(text, links=[kb.link('backend')], suggestions=_sugg('frontend', 'skills', 'start_project'))


def _projects(d):
    parts = []
    if d['websites']:
        parts.append(f"{len(d['websites'])} website project{'s' if len(d['websites']) != 1 else ''}")
    if d['backend']:
        parts.append(f"{len(d['backend'])} backend project{'s' if len(d['backend']) != 1 else ''}")
    lead = f"Tejas's published work includes {' and '.join(parts)}. " if parts else ''
    return Reply(lead + "Websites are his frontend work; Backend Projects are his Django systems "
                        "with dashboards and automation.",
                 links=[kb.link('websites'), kb.link('backend')],
                 suggestions=_sugg('skills', 'hire', 'start_project'))


def _services(d):
    return Reply("Tejas can help with:\n" + _bullets(kb.PROFILE['services']),
                 links=[kb.link('services'), kb.link('start')],
                 suggestions=_sugg('start_project', 'projects', 'skills'))


def _hire(d):
    return Reply("There are two good routes. For a quick question or a conversation, send a message "
                 "from the Contact page. For a defined project, the Start a Project form lets you share "
                 f"scope, references and files as a brief. You can also email {kb.PROFILE['email']}.",
                 links=[kb.link('contact'), kb.link('start'), kb.external_links()['linkedin']],
                 suggestions=_sugg('start_project', 'projects', 'resume'))


def _start_project(d):
    return Reply("Starting is simple. The Start a Project form walks you through it in steps:\n"
                 "\u2022 your details\n\u2022 project name, type and description\n"
                 "\u2022 core features and scope (budget and timeline are optional)\n"
                 "\u2022 reference links and files\n\u2022 a final review before you submit\n"
                 "It's collected only to review your project request. For a quick question instead, "
                 "use the Contact page.",
                 links=[kb.link('start'), kb.link('contact')],
                 suggestions=_sugg('services', 'projects', 'pricing'))


def _pricing(d):
    return Reply("No fixed prices are published on this site, since cost depends on scope. "
                 "The Start a Project form has an optional budget range and timeline, which is the best "
                 "way to get the conversation going.",
                 links=[kb.link('start'), kb.link('contact')],
                 suggestions=_sugg('services', 'projects', 'contact'))


def _contact(d):
    ext = kb.external_links()
    links = [kb.link('contact'), ext['email'], ext['linkedin']]
    if 'github' in ext:
        links.append(ext['github'])
    return Reply(f"You can email Tejas at {kb.PROFILE['email']}, find him on LinkedIn, or send a message "
                 "from the Contact page. For a detailed project brief, use Start a Project instead.",
                 links=links + [kb.link('start')],
                 suggestions=_sugg('hire', 'projects', 'resume'))


def _navigation(d):
    return Reply("Here is what's on the site:\n"
                 "\u2022 About: background, skills, experience, certificates\n"
                 "\u2022 Websites: frontend projects\n"
                 "\u2022 Backend Projects: Django systems\n"
                 "\u2022 Contact: send a message\n"
                 "\u2022 Start a Project: share a project brief\n"
                 "You can also ask me things like \"What are your skills?\" or \"How can I hire you?\"",
                 links=[kb.link('about'), kb.link('websites'), kb.link('backend'), kb.link('contact'),
                        kb.link('start')],
                 suggestions=_sugg('projects', 'skills', 'hire'))


def _unknown(d):
    return Reply("I don't have a good answer for that one, but I can help with Tejas's projects, skills, "
                 "experience and resume, or with how to hire him or start a project. Try one of these:",
                 links=[kb.link('websites'), kb.link('backend'), kb.link('contact')],
                 suggestions=_sugg('projects', 'skills', 'resume', 'hire'))


def blocked_reply():
    return Reply("I can only share what's public on this portfolio, so I can't help with that. "
                 "I'm glad to talk about Tejas's work, though.",
                 suggestions=_sugg('projects', 'skills', 'contact'))


_HANDLERS = {
    'greeting': _greeting, 'thanks': _thanks, 'bye': _thanks, 'about_me': _about_me, 'background': _background,
    'skills': _skills, 'experience': _experience, 'resume': _resume, 'frontend': _frontend, 'backend': _backend,
    'projects': _projects, 'services': _services, 'hire': _hire, 'start_project': _start_project,
    'pricing': _pricing, 'contact': _contact, 'navigation': _navigation, 'unknown': _unknown,
}


def answer(intent_id, data=None):
    """Build the static reply for an intent id. `data` is the knowledge snapshot."""
    if data is None:
        data = kb.snapshot()
    return _HANDLERS.get(intent_id, _unknown)(data)
