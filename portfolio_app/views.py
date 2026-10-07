from django.db.models import Prefetch
from django.shortcuts import render
from django.urls import reverse
from django.utils.html import escape

from dashboard_app.models import (WebsiteProject, BackendProject, Experience, Certificate,
                                  SkillCategory, Skill, Resume)


# NOTE: Websites aur Backend pages ka JS data ko innerHTML mein daalta hai,
# isliye yahan har text/URL ko escape() karke bhej rahe hain.

def _websites_data(websites):
    data = []
    for w in websites:
        data.append({
            'name': escape(w.title),
            'desc': escape(w.short_description),
            'long': escape(w.description),
            'cat': escape(w.get_category_display()),
            'tech': [escape(t) for t in w.tech_list],
            'img': escape(w.thumbnail.url) if w.thumbnail else '',
            'imgs': [escape(i.image.url) for i in w.images.all()],
            'url': escape(w.live_url),
            'gh': escape(w.public_github_url),       # sirf tab jab "GitHub link" toggle on ho
            'featured': w.is_featured,
            'feat': [escape(f) for f in w.features_list],
        })
    return data


def _has_resume():
    # Resume buttons tabhi dikhte hain jab dashboard se koi resume active ho
    return Resume.objects.filter(is_active=True).exists()


# ------------------------ Homepage --------------------------
def homepage(request):
    featured_websites = WebsiteProject.objects.filter(is_published=True, is_featured=True).prefetch_related('images')
    featured_backend = BackendProject.objects.filter(is_published=True, is_featured=True)

    context = {
        'featured_websites': _websites_data(featured_websites),
        'featured_backend': featured_backend,
        'has_resume': _has_resume(),
    }
    return render(request, 'Homepage.html', context)


# ------------------------ About --------------------------
def about(request):
    experiences = Experience.objects.filter(is_published=True)
    certificates = Certificate.objects.filter(is_published=True)

    # Technical arsenal: sirf published categories, unke andar sirf published skills
    skill_categories = SkillCategory.objects.filter(is_published=True).prefetch_related(
        Prefetch('skills', queryset=Skill.objects.filter(is_published=True), to_attr='live_skills'))
    skill_categories = [c for c in skill_categories if c.live_skills]       # khaali category nahi dikhani

    context = {
        'experiences': experiences,
        'certificates': certificates,
        'skill_categories': skill_categories,
        'has_resume': _has_resume(),
    }
    return render(request, 'About.html', context)


# ------------------------ Frontend Work (Websites) --------------------------
def frontend_work(request):
    websites = WebsiteProject.objects.filter(is_published=True).prefetch_related('images')

    context = {'websites': _websites_data(websites)}
    return render(request, 'Frontend_Work.html', context)


# ------------------------ Backend Projects --------------------------
def backend_projects(request):
    projects = BackendProject.objects.filter(is_published=True)

    backend = []
    for p in projects:
        pdf_url = reverse('backend_pdf', args=[p.slug]) if p.documentation_pdf else ''
        backend.append({
            'n': escape(p.title),
            'per': escape(p.period),
            'desc': escape(p.short_description),
            'hub': escape(p.hub_label or 'Dashboards'),
            'roles': [escape(r) for r in p.roles_list],
            'mods': [escape(m) for m in p.modules_list],
            'pts': [escape(k) for k in p.key_points_list],
            'tech': [escape(t) for t in p.tech_list],
            'cat': escape(p.get_category_display()),
            'pdf': pdf_url,                                                   # browser mein preview
            'dl': pdf_url + '?download=1' if (pdf_url and p.allow_pdf_download) else '',   # download toggle
            'gh': escape(p.public_github_url),                                # GitHub toggle
        })

    context = {
        'backend': backend,
        'has_pdf': any(b['pdf'] for b in backend),
    }
    return render(request, 'Backend_Projects.html', context)


# ------------------------ Contact --------------------------
def contact(request):
    return render(request, 'Contact.html')


# ------------------------ Start a Project --------------------------
def start_a_project(request):
    return render(request, 'Start_a_Project.html')