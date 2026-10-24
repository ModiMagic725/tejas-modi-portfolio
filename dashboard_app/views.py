import logging
import mimetypes
import re
from datetime import datetime

from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, FileResponse, Http404
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.mail import send_mail, EmailMessage
from django.conf import settings
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.core.validators import URLValidator, validate_email
from django.db import transaction
from django.db.models import Q, F, Count
from django.utils import timezone
from django.utils.text import get_valid_filename
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST, require_GET

from .models import *
from .decorators import login_required, role_required
from .utils import get_ip, throttled
from .validators import (validate_client_file, validate_pdf, validate_image,
                         validate_github_url, CLIENT_MAX_FILES)


logger = logging.getLogger(__name__)


def _try_email(label, send):
    """
    Email bhejne ki koshish karta hai, kabhi exception bahar nahi phenkta.
    True = bhej diya, False = fail (sirf error ka type/short message log hota hai, credentials nahi).
    """
    try:
        send()
        return True
    except Exception as exc:
        logger.error("Email '%s' failed: %s: %s", label, type(exc).__name__, str(exc)[:150])
        return False


# ================================================================
# HELPERS
# ================================================================
def _paginate(request, queryset, per_page=10):
    paginator = Paginator(queryset, per_page)
    page = request.GET.get('page')
    try:
        return paginator.page(page)
    except PageNotAnInteger:
        return paginator.page(1)
    except EmptyPage:
        return paginator.page(paginator.num_pages)


def _to_int(value, default=0):
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return default


def _tech_text(value):
    # "html, CSS,html" -> "html, CSS"   (duplicate hatata hai, max 12)
    seen, out = set(), []
    for t in (value or '').split(','):
        t = t.strip()[:30]
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return ', '.join(out[:12])


def _check_image(f):
    """Extension + size + asli image hone ki jaanch."""
    validate_image(f)
    from PIL import Image
    try:
        Image.open(f).verify()
    except Exception:
        raise ValidationError(f"{f.name}: this is not a valid image.")
    f.seek(0)


def _file_error(checker, f):
    try:
        checker(f)
    except ValidationError as e:
        return e.messages[0]
    return ''


def _project_errors(request, choices):
    """Website aur Backend dono form ki common jaanch. Errors ki list return karta hai."""
    errors = []
    for field, label in (('title', 'Title'), ('short_description', 'Short description'), ('description', 'Description')):
        if not request.POST.get(field, '').strip():
            errors.append(f"{label} is required.")
    if request.POST.get('category') not in dict(choices):
        errors.append("Please choose a valid category.")
    github = request.POST.get('github_url', '').strip()
    if github:
        try:
            URLValidator(schemes=['https'])(github)
            validate_github_url(github)
        except ValidationError:
            errors.append("GitHub link must start with https://github.com/")
    return errors


def _project_data(request):
    """Website aur Backend dono ke common fields POST se."""
    return dict(
        title=request.POST.get('title', '').strip(),
        short_description=request.POST.get('short_description', '').strip(),
        description=request.POST.get('description', '').strip(),
        category=request.POST.get('category'),
        technologies=_tech_text(request.POST.get('technologies')),
        github_url=request.POST.get('github_url', '').strip(),
        show_github='show_github' in request.POST,
        is_published='is_published' in request.POST,
        is_featured='is_featured' in request.POST,
        display_order=_to_int(request.POST.get('display_order')),
    )


def _toggle(request, model, id, field, label, redirect_name):
    obj = get_object_or_404(model, id=id)
    setattr(obj, field, not getattr(obj, field))
    obj.save()
    state = "enabled" if getattr(obj, field) else "disabled"
    messages.success(request, f"✅ {obj} - {label} {state} successfully!")
    return redirect(redirect_name)


# ================================================================
# LOGIN / LOGOUT
# ================================================================
def login_view(request):
    if 'user_id' in request.session:
        return redirect('dashboard')

    if request.method == 'POST':
        if throttled(request, 'login', 10, 900):
            messages.error(request, '❌ Too many login attempts. Please try again in 15 minutes.')
            return render(request, 'dashboard/login.html')

        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')

        try:
            admin = AdminUser.objects.get(email__iexact=email, is_active=True)
            if admin.check_password(password):
                request.session.cycle_key()
                request.session['user_id']   = admin.id
                request.session['user_type'] = 'admin'
                request.session['full_name'] = admin.full_name
                request.session['role']      = admin.role
                request.session['email']     = admin.email
                admin.last_login = timezone.now()
                admin.save(update_fields=['last_login'])
                messages.success(request, f'Welcome {admin.full_name}!')
                return redirect('dashboard')
        except AdminUser.DoesNotExist:
            pass
        # Email galat ho ya password - same message (account exist karta hai ya nahi, ye nahi batate)
        messages.error(request, '❌ Invalid email or password!')

    return render(request, 'dashboard/login.html', {'email': request.POST.get('email', '')})


def logout_view(request):
    request.session.flush()
    messages.success(request, 'Logged out successfully!')
    return redirect('login')


# ================================================================
# DASHBOARD
# ================================================================
@login_required
@role_required(['admin'])
def dashboard(request):
    context = {
        'active': 'home',
        'page_title': 'Dashboard',
        'stats': {
            'websites': WebsiteProject.objects.count(),
            'backend': BackendProject.objects.count(),
            'skills': Skill.objects.count(),
            'messages_new': ContactMessage.objects.filter(status='new').count(),
            'requirements_new': ProjectRequirement.objects.filter(status='new').count(),
        },
        'recent_messages': ContactMessage.objects.all()[:5],
        'recent_requirements': ProjectRequirement.objects.all()[:5],
        'active_resume': Resume.objects.filter(is_active=True).first(),
    }
    return render(request, 'dashboard/dashboard.html', context)


# ================================================================
# FRONTEND PROJECTS (WEBSITES)
# ================================================================
@login_required
@role_required(['admin'])
def website_list(request):
    projects_list = WebsiteProject.objects.all()
    q = request.GET.get('q', '').strip()
    category = request.GET.get('category', '')
    if q:
        projects_list = projects_list.filter(Q(title__icontains=q) | Q(short_description__icontains=q) | Q(technologies__icontains=q))
    if category:
        projects_list = projects_list.filter(category=category)
    context = {
        'active': 'websites', 'page_title': 'Website projects',
        'projects': _paginate(request, projects_list), 'q': q, 'selected': category,
        'categories': WebsiteProject.CATEGORY_CHOICES,
    }
    return render(request, 'frontend_projects/website_list.html', context)


@login_required
@role_required(['admin'])
def add_website(request):
    context = {'active': 'websites', 'page_title': 'Add website', 'categories': WebsiteProject.CATEGORY_CHOICES}
    if request.method == "POST":
        try:
            errors = _project_errors(request, WebsiteProject.CATEGORY_CHOICES)
            live_url = request.POST.get('live_url', '').strip()
            if live_url:
                try:
                    URLValidator(schemes=['http', 'https'])(live_url)
                except ValidationError:
                    errors.append("Live URL must start with http:// or https://")
            thumbnail = request.FILES.get('thumbnail')
            if not thumbnail:
                errors.append("Thumbnail image is required.")
            else:
                err = _file_error(_check_image, thumbnail)
                if err:
                    errors.append(err)
            gallery = request.FILES.getlist('gallery')
            for f in gallery:
                err = _file_error(_check_image, f)
                if err:
                    errors.append(err)

            if errors:
                for e in errors:
                    messages.error(request, f"❌ {e}")
                context['form'] = request.POST
                return render(request, 'frontend_projects/add_website.html', context)

            with transaction.atomic():
                web = WebsiteProject.objects.create(
                    thumbnail=thumbnail,
                    live_url=live_url,
                    key_features=request.POST.get('key_features', '').strip(),
                    year=_to_int(request.POST.get('year'), None),
                    **_project_data(request)
                )
                for i, f in enumerate(gallery):
                    WebsiteImage.objects.create(project=web, image=f, alt_text=f"{web.title} screenshot", order=i)
            messages.success(request, f"✅ Website {web.project_id} - {web.title} added successfully!")
            return redirect("website_list")
        except Exception as e:
            messages.error(request, f"❌ Error: {str(e)}")
            context['form'] = request.POST
    return render(request, 'frontend_projects/add_website.html', context)


@login_required
@role_required(['admin'])
def edit_website(request, id):
    web = get_object_or_404(WebsiteProject, id=id)
    context = {'active': 'websites', 'page_title': 'Edit website', 'project': web,
               'categories': WebsiteProject.CATEGORY_CHOICES}
    if request.method == "POST":
        try:
            errors = _project_errors(request, WebsiteProject.CATEGORY_CHOICES)
            live_url = request.POST.get('live_url', '').strip()
            if live_url:
                try:
                    URLValidator(schemes=['http', 'https'])(live_url)
                except ValidationError:
                    errors.append("Live URL must start with http:// or https://")
            thumbnail = request.FILES.get('thumbnail')
            if thumbnail:
                err = _file_error(_check_image, thumbnail)
                if err:
                    errors.append(err)
            gallery = request.FILES.getlist('gallery')
            for f in gallery:
                err = _file_error(_check_image, f)
                if err:
                    errors.append(err)

            if errors:
                for e in errors:
                    messages.error(request, f"❌ {e}")
                context['form'] = request.POST
                return render(request, 'frontend_projects/edit_website.html', context)

            with transaction.atomic():
                for field, value in _project_data(request).items():
                    setattr(web, field, value)
                web.live_url = live_url
                web.key_features = request.POST.get('key_features', '').strip()
                web.year = _to_int(request.POST.get('year'), None)
                if thumbnail:
                    web.thumbnail = thumbnail
                web.save()
                start = web.images.count()
                for i, f in enumerate(gallery, start=start):
                    WebsiteImage.objects.create(project=web, image=f, alt_text=f"{web.title} screenshot", order=i)
            messages.success(request, f"✅ Website {web.project_id} - {web.title} updated successfully!")
            return redirect("website_list")
        except Exception as e:
            messages.error(request, f"❌ Error: {str(e)}")
            context['form'] = request.POST
    return render(request, 'frontend_projects/edit_website.html', context)


@require_POST
@login_required
@role_required(['admin'])
def delete_website(request, id):
    web = get_object_or_404(WebsiteProject, id=id)
    code, title = web.project_id, web.title
    web.delete()
    messages.success(request, f"✅ Website {code} - {title} deleted successfully!")
    return redirect("website_list")


@require_POST
@login_required
@role_required(['admin'])
def delete_website_image(request, id):
    image = get_object_or_404(WebsiteImage, id=id)
    project_id = image.project.id
    image.delete()
    messages.success(request, "✅ Screenshot deleted successfully!")
    return redirect("edit_website", id=project_id)


@require_POST
@login_required
@role_required(['admin'])
def toggle_website_published(request, id):
    return _toggle(request, WebsiteProject, id, 'is_published', 'visibility', 'website_list')


@require_POST
@login_required
@role_required(['admin'])
def toggle_website_featured(request, id):
    return _toggle(request, WebsiteProject, id, 'is_featured', 'featured status', 'website_list')


@require_POST
@login_required
@role_required(['admin'])
def toggle_website_github(request, id):
    return _toggle(request, WebsiteProject, id, 'show_github', 'GitHub link', 'website_list')


# ================================================================
# BACKEND PROJECTS
# ================================================================
@login_required
@role_required(['admin'])
def backend_list(request):
    projects_list = BackendProject.objects.all()
    q = request.GET.get('q', '').strip()
    category = request.GET.get('category', '')
    if q:
        projects_list = projects_list.filter(Q(title__icontains=q) | Q(short_description__icontains=q) | Q(technologies__icontains=q))
    if category:
        projects_list = projects_list.filter(category=category)
    context = {
        'active': 'backend', 'page_title': 'Backend projects',
        'projects': _paginate(request, projects_list), 'q': q, 'selected': category,
        'categories': BackendProject.CATEGORY_CHOICES,
    }
    return render(request, 'backend_projects/backend_list.html', context)


@login_required
@role_required(['admin'])
def add_backend(request):
    context = {'active': 'backend', 'page_title': 'Add backend project', 'categories': BackendProject.CATEGORY_CHOICES}
    if request.method == "POST":
        try:
            errors = _project_errors(request, BackendProject.CATEGORY_CHOICES)
            thumbnail = request.FILES.get('thumbnail')
            pdf = request.FILES.get('documentation_pdf')
            showcase = request.FILES.get('showcase_pdf')
            if thumbnail:
                err = _file_error(_check_image, thumbnail)
                if err:
                    errors.append(err)
            if pdf:
                err = _file_error(validate_pdf, pdf)
                if err:
                    errors.append(err)
            if showcase:
                err = _file_error(validate_pdf, showcase)
                if err:
                    errors.append(err)

            if errors:
                for e in errors:
                    messages.error(request, f"❌ {e}")
                context['form'] = request.POST
                return render(request, 'backend_projects/add_backend.html', context)

            proj = BackendProject.objects.create(
                thumbnail=thumbnail,
                documentation_pdf=pdf,
                allow_pdf_download='allow_pdf_download' in request.POST,
                showcase_pdf=showcase,
                allow_showcase_download='allow_showcase_download' in request.POST,
                period=request.POST.get('period', '').strip(),
                hub_label=request.POST.get('hub_label', '').strip(),
                roles=request.POST.get('roles', '').strip(),
                modules=request.POST.get('modules', '').strip(),
                key_points=request.POST.get('key_points', '').strip(),
                **_project_data(request)
            )
            messages.success(request, f"✅ Backend project {proj.project_id} - {proj.title} added successfully!")
            return redirect("backend_list")
        except Exception as e:
            messages.error(request, f"❌ Error: {str(e)}")
            context['form'] = request.POST
    return render(request, 'backend_projects/add_backend.html', context)


@login_required
@role_required(['admin'])
def edit_backend(request, id):
    proj = get_object_or_404(BackendProject, id=id)
    context = {'active': 'backend', 'page_title': 'Edit backend project', 'project': proj,
               'categories': BackendProject.CATEGORY_CHOICES}
    if request.method == "POST":
        try:
            errors = _project_errors(request, BackendProject.CATEGORY_CHOICES)
            thumbnail = request.FILES.get('thumbnail')
            pdf = request.FILES.get('documentation_pdf')
            showcase = request.FILES.get('showcase_pdf')
            if thumbnail:
                err = _file_error(_check_image, thumbnail)
                if err:
                    errors.append(err)
            if pdf:
                err = _file_error(validate_pdf, pdf)
                if err:
                    errors.append(err)
            if showcase:
                err = _file_error(validate_pdf, showcase)
                if err:
                    errors.append(err)

            if errors:
                for e in errors:
                    messages.error(request, f"❌ {e}")
                context['form'] = request.POST
                return render(request, 'backend_projects/edit_backend.html', context)

            for field, value in _project_data(request).items():
                setattr(proj, field, value)
            proj.allow_pdf_download = 'allow_pdf_download' in request.POST
            proj.allow_showcase_download = 'allow_showcase_download' in request.POST
            proj.period = request.POST.get('period', '').strip()
            proj.hub_label = request.POST.get('hub_label', '').strip()
            proj.roles = request.POST.get('roles', '').strip()
            proj.modules = request.POST.get('modules', '').strip()
            proj.key_points = request.POST.get('key_points', '').strip()
            if thumbnail:
                proj.thumbnail = thumbnail
            if pdf:
                proj.documentation_pdf = pdf
            elif 'remove_pdf' in request.POST:
                proj.documentation_pdf = None
            if showcase:
                proj.showcase_pdf = showcase
            elif 'remove_showcase' in request.POST:
                proj.showcase_pdf = None
            proj.save()
            messages.success(request, f"✅ Backend project {proj.project_id} - {proj.title} updated successfully!")
            return redirect("backend_list")
        except Exception as e:
            messages.error(request, f"❌ Error: {str(e)}")
            context['form'] = request.POST
    return render(request, 'backend_projects/edit_backend.html', context)


@require_POST
@login_required
@role_required(['admin'])
def delete_backend(request, id):
    proj = get_object_or_404(BackendProject, id=id)
    code, title = proj.project_id, proj.title
    proj.delete()
    messages.success(request, f"✅ Backend project {code} - {title} deleted successfully!")
    return redirect("backend_list")


@require_POST
@login_required
@role_required(['admin'])
def toggle_backend_published(request, id):
    return _toggle(request, BackendProject, id, 'is_published', 'visibility', 'backend_list')


@require_POST
@login_required
@role_required(['admin'])
def toggle_backend_featured(request, id):
    return _toggle(request, BackendProject, id, 'is_featured', 'featured status', 'backend_list')


@require_POST
@login_required
@role_required(['admin'])
def toggle_backend_github(request, id):
    return _toggle(request, BackendProject, id, 'show_github', 'GitHub link', 'backend_list')


@require_POST
@login_required
@role_required(['admin'])
def toggle_backend_pdf_download(request, id):
    return _toggle(request, BackendProject, id, 'allow_pdf_download', 'PDF download', 'backend_list')


@require_POST
@login_required
@role_required(['admin'])
def toggle_backend_showcase_download(request, id):
    return _toggle(request, BackendProject, id, 'allow_showcase_download', 'Showcase PDF download', 'backend_list')


# ================================================================
# CONTACT MESSAGES
# ================================================================
@login_required
@role_required(['admin'])
def message_list(request):
    items_list = ContactMessage.objects.all()
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    if q:
        items_list = items_list.filter(Q(name__icontains=q) | Q(email__icontains=q) | Q(subject__icontains=q) | Q(message__icontains=q))
    if status:
        items_list = items_list.filter(status=status)
    context = {
        'active': 'messages', 'page_title': 'Contact messages',
        'items': _paginate(request, items_list), 'q': q, 'selected': status,
        'statuses': ContactMessage.STATUS_CHOICES,
    }
    return render(request, 'contact/message_list.html', context)


@login_required
@role_required(['admin'])
def view_message(request, id):
    item = get_object_or_404(ContactMessage, id=id)
    if request.method == "POST":
        status = request.POST.get('status')
        if status in dict(ContactMessage.STATUS_CHOICES):
            item.status = status
            item.save()
            messages.success(request, f"✅ Message from {item.name} marked as {item.get_status_display()}!")
        return redirect("view_message", id=item.id)
    if item.status == 'new':
        item.status, item.read_at = 'read', timezone.now()
        item.save()
    context = {'active': 'messages', 'page_title': 'Message', 'item': item,
               'statuses': ContactMessage.STATUS_CHOICES}
    return render(request, 'contact/view_message.html', context)


@require_POST
@login_required
@role_required(['admin'])
def delete_message(request, id):
    item = get_object_or_404(ContactMessage, id=id)
    name = item.name
    item.delete()
    messages.success(request, f"✅ Message from {name} deleted successfully!")
    return redirect("message_list")


# ================================================================
# PROJECT REQUIREMENTS (Start a Project)
# ================================================================
@login_required
@role_required(['admin'])
def requirement_list(request):
    items_list = ProjectRequirement.objects.all()
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    if q:
        items_list = items_list.filter(Q(client_name__icontains=q) | Q(email__icontains=q) |
                                       Q(project_name__icontains=q) | Q(company__icontains=q))
    if status:
        items_list = items_list.filter(status=status)
    context = {
        'active': 'requirements', 'page_title': 'Project requirements',
        'items': _paginate(request, items_list), 'q': q, 'selected': status,
        'statuses': ProjectRequirement.STATUS_CHOICES,
    }
    return render(request, 'requirements/requirement_list.html', context)


@login_required
@role_required(['admin'])
def view_requirement(request, id):
    item = get_object_or_404(ProjectRequirement, id=id)
    if request.method == "POST":
        status = request.POST.get('status')
        if status in dict(ProjectRequirement.STATUS_CHOICES):
            item.status = status
        item.internal_notes = request.POST.get('internal_notes', '').strip()
        item.save()
        messages.success(request, f"✅ Requirement {item.requirement_id} updated successfully!")
        return redirect("view_requirement", id=item.id)
    if item.status == 'new':
        item.status = 'reviewing'
        item.save()
    context = {'active': 'requirements', 'page_title': 'Project requirement', 'item': item,
               'statuses': ProjectRequirement.STATUS_CHOICES}
    return render(request, 'requirements/view_requirement.html', context)


@require_POST
@login_required
@role_required(['admin'])
def delete_requirement(request, id):
    item = get_object_or_404(ProjectRequirement, id=id)
    code = item.requirement_id
    item.delete()
    messages.success(request, f"✅ Requirement {code} deleted successfully!")
    return redirect("requirement_list")


@login_required
@role_required(['admin'])
def download_requirement_file(request, id):
    # Client ki files public nahi hoti - sirf logged in admin download kar sakta hai
    f = get_object_or_404(RequirementFile, id=id)
    try:
        handle = f.file.open('rb')
    except FileNotFoundError:
        raise Http404("File is missing from storage.")
    response = FileResponse(handle, as_attachment=True, filename=f.original_name,
                            content_type=mimetypes.guess_type(f.original_name)[0] or 'application/octet-stream')
    response['X-Content-Type-Options'] = 'nosniff'
    return response


# ================================================================
# PROFILE: EXPERIENCE (About page timeline)
# ================================================================
def _parse_date(value):
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def _experience_errors(request):
    """Add / Edit dono ki jaanch. Returns (errors, start_date, end_date)."""
    errors = []
    for field, label in (('role', 'Role'), ('company', 'Company'), ('description', 'Description')):
        if not request.POST.get(field, '').strip():
            errors.append(f"{label} is required.")
    start = _parse_date(request.POST.get('start_date'))
    end = _parse_date(request.POST.get('end_date'))
    is_current = 'is_current' in request.POST
    if not start:
        errors.append("Start date is required.")
    if is_current:
        end = None
    elif request.POST.get('end_date') and not end:
        errors.append("End date is not valid.")
    elif start and end and end < start:
        errors.append("End date cannot be before the start date.")
    return errors, start, end


@login_required
@role_required(['admin'])
def experience_list(request):
    experiences_list = Experience.objects.all()
    q = request.GET.get('q', '').strip()
    if q:
        experiences_list = experiences_list.filter(Q(role__icontains=q) | Q(company__icontains=q) | Q(technologies__icontains=q))
    context = {
        'active': 'experience', 'page_title': 'Experience',
        'experiences': _paginate(request, experiences_list), 'q': q,
    }
    return render(request, 'experience/experience_list.html', context)


@login_required
@role_required(['admin'])
def add_experience(request):
    context = {'active': 'experience', 'page_title': 'Add experience'}
    if request.method == "POST":
        try:
            errors, start, end = _experience_errors(request)
            if errors:
                for e in errors:
                    messages.error(request, f"❌ {e}")
                context['form'] = request.POST
                return render(request, 'experience/add_experience.html', context)

            exp = Experience.objects.create(
                role=request.POST.get('role', '').strip(),
                company=request.POST.get('company', '').strip(),
                location=request.POST.get('location', '').strip(),
                start_date=start,
                end_date=end,
                is_current='is_current' in request.POST,
                description=request.POST.get('description', '').strip(),
                technologies=_tech_text(request.POST.get('technologies')),
                is_published='is_published' in request.POST,
                display_order=_to_int(request.POST.get('display_order')),
            )
            messages.success(request, f"✅ Experience {exp.experience_id} - {exp.role} at {exp.company} added successfully!")
            return redirect("experience_list")
        except Exception as e:
            messages.error(request, f"❌ Error: {str(e)}")
            context['form'] = request.POST
    return render(request, 'experience/add_experience.html', context)


@login_required
@role_required(['admin'])
def edit_experience(request, id):
    exp = get_object_or_404(Experience, id=id)
    context = {'active': 'experience', 'page_title': 'Edit experience', 'experience': exp}
    if request.method == "POST":
        try:
            errors, start, end = _experience_errors(request)
            if errors:
                for e in errors:
                    messages.error(request, f"❌ {e}")
                context['form'] = request.POST
                return render(request, 'experience/edit_experience.html', context)

            exp.role = request.POST.get('role', '').strip()
            exp.company = request.POST.get('company', '').strip()
            exp.location = request.POST.get('location', '').strip()
            exp.start_date = start
            exp.end_date = end
            exp.is_current = 'is_current' in request.POST
            exp.description = request.POST.get('description', '').strip()
            exp.technologies = _tech_text(request.POST.get('technologies'))
            exp.is_published = 'is_published' in request.POST
            exp.display_order = _to_int(request.POST.get('display_order'))
            exp.save()
            messages.success(request, f"✅ Experience {exp.experience_id} - {exp.role} at {exp.company} updated successfully!")
            return redirect("experience_list")
        except Exception as e:
            messages.error(request, f"❌ Error: {str(e)}")
            context['form'] = request.POST
    return render(request, 'experience/edit_experience.html', context)


@require_POST
@login_required
@role_required(['admin'])
def delete_experience(request, id):
    exp = get_object_or_404(Experience, id=id)
    label = f"{exp.experience_id} - {exp.role} at {exp.company}"
    exp.delete()
    messages.success(request, f"✅ Experience {label} deleted successfully!")
    return redirect("experience_list")


@require_POST
@login_required
@role_required(['admin'])
def toggle_experience_published(request, id):
    return _toggle(request, Experience, id, 'is_published', 'visibility', 'experience_list')


# ================================================================
# PROFILE: CERTIFICATES
# ================================================================
@login_required
@role_required(['admin'])
def certificate_list(request):
    certificates_list = Certificate.objects.all()
    q = request.GET.get('q', '').strip()
    if q:
        certificates_list = certificates_list.filter(Q(name__icontains=q) | Q(description__icontains=q))
    context = {
        'active': 'certificates', 'page_title': 'Certificates',
        'certificates': _paginate(request, certificates_list), 'q': q,
    }
    return render(request, 'certificates/certificate_list.html', context)


@login_required
@role_required(['admin'])
def add_certificate(request):
    context = {'active': 'certificates', 'page_title': 'Add certificate'}
    if request.method == "POST":
        try:
            name = request.POST.get('name', '').strip()
            description = request.POST.get('description', '').strip()
            issuer = request.POST.get('issuer', '').strip()
            issued_on = request.POST.get('issued_on', '').strip()
            thumb = request.FILES.get('thumbnail')
            pdf = request.FILES.get('pdf_file')

            errors = []
            if not name:
                errors.append("Certificate name is required.")
            if len(description) > 300:
                errors.append("Description must be 300 characters or less.")
            if len(issuer) > 120:
                errors.append("Issuing organisation must be 120 characters or less.")
            if len(issued_on) > 30:
                errors.append("Issue date must be 30 characters or less.")
            if thumb:
                err = _file_error(_check_image, thumb)
                if err:
                    errors.append(err)
            if pdf:
                err = _file_error(validate_pdf, pdf)
                if err:
                    errors.append(err)
            if errors:
                for e in errors:
                    messages.error(request, f"❌ {e}")
                context['form'] = request.POST
                return render(request, 'certificates/add_certificate.html', context)

            cert = Certificate.objects.create(
                name=name,
                description=description,
                issuer=issuer,
                issued_on=issued_on,
                thumbnail=thumb,
                pdf_file=pdf,
                is_published='is_published' in request.POST,
                display_order=_to_int(request.POST.get('display_order')),
            )
            messages.success(request, f"✅ Certificate {cert.certificate_id} - {cert.name} added successfully!")
            return redirect("certificate_list")
        except Exception as e:
            messages.error(request, f"❌ Error: {str(e)}")
            context['form'] = request.POST
    return render(request, 'certificates/add_certificate.html', context)


@login_required
@role_required(['admin'])
def edit_certificate(request, id):
    cert = get_object_or_404(Certificate, id=id)
    context = {'active': 'certificates', 'page_title': 'Edit certificate', 'cert': cert}
    if request.method == "POST":
        try:
            name = request.POST.get('name', '').strip()
            description = request.POST.get('description', '').strip()
            issuer = request.POST.get('issuer', '').strip()
            issued_on = request.POST.get('issued_on', '').strip()
            thumb = request.FILES.get('thumbnail')
            pdf = request.FILES.get('pdf_file')

            errors = []
            if not name:
                errors.append("Certificate name is required.")
            if len(description) > 300:
                errors.append("Description must be 300 characters or less.")
            if len(issuer) > 120:
                errors.append("Issuing organisation must be 120 characters or less.")
            if len(issued_on) > 30:
                errors.append("Issue date must be 30 characters or less.")
            if thumb:
                err = _file_error(_check_image, thumb)
                if err:
                    errors.append(err)
            if pdf:
                err = _file_error(validate_pdf, pdf)
                if err:
                    errors.append(err)
            if errors:
                for e in errors:
                    messages.error(request, f"❌ {e}")
                context['form'] = request.POST
                return render(request, 'certificates/edit_certificate.html', context)

            cert.name = name
            cert.description = description
            cert.issuer = issuer
            cert.issued_on = issued_on
            if thumb:
                cert.thumbnail = thumb
            elif 'remove_thumbnail' in request.POST:
                cert.thumbnail = None
            cert.is_published = 'is_published' in request.POST
            cert.display_order = _to_int(request.POST.get('display_order'))
            if pdf:
                cert.pdf_file = pdf
            elif 'remove_pdf' in request.POST:
                cert.pdf_file = None
            cert.save()
            messages.success(request, f"✅ Certificate {cert.certificate_id} - {cert.name} updated successfully!")
            return redirect("certificate_list")
        except Exception as e:
            messages.error(request, f"❌ Error: {str(e)}")
            context['form'] = request.POST
    return render(request, 'certificates/edit_certificate.html', context)


@require_POST
@login_required
@role_required(['admin'])
def delete_certificate(request, id):
    cert = get_object_or_404(Certificate, id=id)
    label = f"{cert.certificate_id} - {cert.name}"
    cert.delete()
    messages.success(request, f"✅ Certificate {label} deleted successfully!")
    return redirect("certificate_list")


@require_POST
@login_required
@role_required(['admin'])
def toggle_certificate_published(request, id):
    return _toggle(request, Certificate, id, 'is_published', 'visibility', 'certificate_list')


# ================================================================
# SKILLS (Technical arsenal): Category -> Skills
# ================================================================
@login_required
@role_required(['admin'])
def skill_list(request):
    context = {
        'active': 'skills', 'page_title': 'Skills',
        'categories': SkillCategory.objects.prefetch_related('skills'),
        'skill_total': Skill.objects.count(),
    }
    return render(request, 'skills/skill_list.html', context)


@login_required
@role_required(['admin'])
def skill_category_list(request):
    context = {
        'active': 'skill_categories', 'page_title': 'Skill categories',
        'categories': SkillCategory.objects.annotate(skill_count=Count('skills')),
    }
    return render(request, 'skills/category_list.html', context)


@login_required
@role_required(['admin'])
def add_skill_category(request):
    context = {'active': 'skill_categories', 'page_title': 'Add skill category'}
    if request.method == "POST":
        try:
            name = request.POST.get('name', '').strip()
            errors = []
            if not name:
                errors.append("Category name is required.")
            elif len(name) > 60:
                errors.append("Category name must be 60 characters or less.")
            elif SkillCategory.objects.filter(name__iexact=name).exists():
                errors.append(f"A category named “{name}” already exists.")
            if errors:
                for e in errors:
                    messages.error(request, f"❌ {e}")
                context['form'] = request.POST
                return render(request, 'skills/add_skill_category.html', context)

            cat = SkillCategory.objects.create(
                name=name,
                display_order=_to_int(request.POST.get('display_order')),
                is_published='is_published' in request.POST,
            )
            messages.success(request, f"✅ Category “{cat.name}” added. Now add skills to it.")
            return redirect("add_skill")
        except Exception as e:
            messages.error(request, f"❌ Error: {str(e)}")
            context['form'] = request.POST
    return render(request, 'skills/add_skill_category.html', context)


@login_required
@role_required(['admin'])
def edit_skill_category(request, id):
    cat = get_object_or_404(SkillCategory, id=id)
    context = {'active': 'skill_categories', 'page_title': 'Edit skill category', 'category': cat}
    if request.method == "POST":
        try:
            name = request.POST.get('name', '').strip()
            errors = []
            if not name:
                errors.append("Category name is required.")
            elif len(name) > 60:
                errors.append("Category name must be 60 characters or less.")
            elif SkillCategory.objects.filter(name__iexact=name).exclude(id=cat.id).exists():
                errors.append(f"A category named “{name}” already exists.")
            if errors:
                for e in errors:
                    messages.error(request, f"❌ {e}")
                context['form'] = request.POST
                return render(request, 'skills/edit_skill_category.html', context)

            cat.name = name
            cat.display_order = _to_int(request.POST.get('display_order'))
            cat.is_published = 'is_published' in request.POST
            cat.save()
            messages.success(request, f"✅ Category “{cat.name}” updated successfully!")
            return redirect("skill_category_list")
        except Exception as e:
            messages.error(request, f"❌ Error: {str(e)}")
            context['form'] = request.POST
    return render(request, 'skills/edit_skill_category.html', context)


@require_POST
@login_required
@role_required(['admin'])
def delete_skill_category(request, id):
    cat = get_object_or_404(SkillCategory, id=id)
    name, count = cat.name, cat.skills.count()
    cat.delete()                                   # uske saare skills bhi delete ho jaate hain
    messages.success(request, f"✅ Category “{name}” and its {count} skill(s) deleted successfully!")
    return redirect("skill_category_list")


@require_POST
@login_required
@role_required(['admin'])
def toggle_skill_category_published(request, id):
    return _toggle(request, SkillCategory, id, 'is_published', 'visibility', 'skill_category_list')


@login_required
@role_required(['admin'])
def add_skill(request):
    categories = SkillCategory.objects.all()
    context = {'active': 'skills', 'page_title': 'Add skills', 'categories': categories,
               'selected_category': _to_int(request.GET.get('category'), None)}
    if not categories.exists():
        messages.error(request, "❌ Please add a skill category first.")
        return redirect("add_skill_category")

    if request.method == "POST":
        try:
            cat = categories.filter(id=_to_int(request.POST.get('category'), 0)).first()
            # Ek saath kai skills: comma ya nayi line se alag karo
            names = []
            for n in re.split(r'[,\n]+', request.POST.get('names', '')):
                n = n.strip()
                if n and n.lower() not in [x.lower() for x in names]:
                    names.append(n)

            errors = []
            if not cat:
                errors.append("Please choose a category.")
            if not names:
                errors.append("Enter at least one skill name.")
            if len(names) > 30:
                errors.append("Add up to 30 skills at a time.")
            if any(len(n) > 60 for n in names):
                errors.append("Each skill name must be 60 characters or less.")
            if errors:
                for e in errors:
                    messages.error(request, f"❌ {e}")
                context['form'] = request.POST
                context['selected_category'] = _to_int(request.POST.get('category'), None)
                return render(request, 'skills/add_skill.html', context)

            existing = [s.lower() for s in cat.skills.values_list('name', flat=True)]
            added = 0
            for n in names:
                if n.lower() not in existing:
                    Skill.objects.create(category=cat, name=n, is_published='is_published' in request.POST)
                    added += 1
            skipped = len(names) - added
            messages.success(request, f"✅ {added} skill(s) added to {cat.name}." + (f" {skipped} already existed." if skipped else ""))
            return redirect("skill_list")
        except Exception as e:
            messages.error(request, f"❌ Error: {str(e)}")
            context['form'] = request.POST
    return render(request, 'skills/add_skill.html', context)


@login_required
@role_required(['admin'])
def edit_skill(request, id):
    skill = get_object_or_404(Skill, id=id)
    categories = SkillCategory.objects.all()
    context = {'active': 'skills', 'page_title': 'Edit skill', 'skill': skill, 'categories': categories}
    if request.method == "POST":
        try:
            name = request.POST.get('name', '').strip()
            cat = categories.filter(id=_to_int(request.POST.get('category'), 0)).first()
            errors = []
            if not name:
                errors.append("Skill name is required.")
            elif len(name) > 60:
                errors.append("Skill name must be 60 characters or less.")
            if not cat:
                errors.append("Please choose a category.")
            elif name and Skill.objects.filter(category=cat, name__iexact=name).exclude(id=skill.id).exists():
                errors.append(f"“{name}” already exists in {cat.name}.")
            if errors:
                for e in errors:
                    messages.error(request, f"❌ {e}")
                context['form'] = request.POST
                return render(request, 'skills/edit_skill.html', context)

            skill.name = name
            skill.category = cat
            skill.display_order = _to_int(request.POST.get('display_order'))
            skill.is_published = 'is_published' in request.POST
            skill.save()
            messages.success(request, f"✅ Skill “{skill.name}” updated successfully!")
            return redirect("skill_list")
        except Exception as e:
            messages.error(request, f"❌ Error: {str(e)}")
            context['form'] = request.POST
    return render(request, 'skills/edit_skill.html', context)


@require_POST
@login_required
@role_required(['admin'])
def delete_skill(request, id):
    skill = get_object_or_404(Skill, id=id)
    name = skill.name
    skill.delete()
    messages.success(request, f"✅ Skill “{name}” deleted successfully!")
    return redirect("skill_list")


# ================================================================
# PUBLIC SITE ENDPOINTS (login ki zaroorat nahi)
# Contact form, Start a Project form, Backend PDF
# ================================================================
def _too_many():
    return JsonResponse({'ok': False, 'errors': {'__all__': 'Too many submissions. Please try again later.'}}, status=429)


def _bad_email(value):
    try:
        validate_email(value)
        return False
    except ValidationError:
        return True


# @require_POST
# def contact_submit(request):
#     if request.POST.get('website'):                       # honeypot - asli user ye field nahi bharta
#         return JsonResponse({'ok': True})
#     if throttled(request, 'contact', 5, 3600):
#         return _too_many()

#     name = request.POST.get('name', '').strip()
#     email = request.POST.get('email', '').strip()
#     subject = request.POST.get('subject', '').strip()
#     project_type = request.POST.get('project_type', '').strip()
#     message = request.POST.get('message', '').strip()

#     errors = {}
#     if not name or len(name) > 100:
#         errors['name'] = 'Please tell me your name.'
#     if _bad_email(email):
#         errors['email'] = 'Please enter a valid email address.'
#     if len(subject) > 150:
#         errors['subject'] = 'Subject is too long.'
#     if not message or len(message) > 3000:
#         errors['message'] = 'Please tell me a little about your project (max 3000 characters).'
#     if errors:
#         return JsonResponse({'ok': False, 'errors': errors}, status=400)

#     ContactMessage.objects.create(name=name, email=email, subject=subject, project_type=project_type[:30],
#                                   message=message, ip_address=get_ip(request))
#     return JsonResponse({'ok': True})


@require_POST
def contact_submit(request):
    if request.POST.get('website'):                       # honeypot - asli user ye field nahi bharta
        return JsonResponse({'ok': True})
    if not settings.DEBUG and throttled(request, 'contact', 5, 3600):   # local testing (DEBUG=True) par limit nahi
        return _too_many()

    name = request.POST.get('name', '').strip()
    email = request.POST.get('email', '').strip()
    subject = request.POST.get('subject', '').strip()
    project_type = request.POST.get('project_type', '').strip()
    message = request.POST.get('message', '').strip()

    errors = {}
    if not name or len(name) > 100:
        errors['name'] = 'Please tell me your name.'
    if _bad_email(email):
        errors['email'] = 'Please enter a valid email address.'
    if len(subject) > 150:
        errors['subject'] = 'Subject is too long.'
    if not message or len(message) > 3000:
        errors['message'] = 'Please tell me a little about your project (max 3000 characters).'

    if errors:
        return JsonResponse({'ok': False, 'errors': errors}, status=400)

    # ---- Stage 1: database save (sirf yahi 'save nahi hua' wala error de sakta hai) ----
    try:
        ContactMessage.objects.create(
            name=name,
            email=email,
            subject=subject,
            project_type=project_type[:30],
            message=message,
            ip_address=get_ip(request)
        )
    except Exception:
        logger.exception("Contact form: database save failed")
        return JsonResponse(
            {'ok': False, 'errors': {'__all__': 'Could not save your message. Please try again.'}},
            status=500,
        )

    # ---- Stage 2: email (message DB mein save ho chuka hai, email fail hone se response fail nahi hoga) ----
    def _send_admin():
        send_mail(
            subject=f"New Portfolio Inquiry — {subject}",
            message=f"""
Hi Tejas,

You’ve received a new message through your portfolio website.

A new person has reached out regarding a potential project. Here are the details:

Name: {name}
Email: {email}
Project Type: {project_type}
Subject: {subject}

Message:
{message}

You can reply directly to the visitor using their email address above.

Best,
Portfolio Contact System
""",
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[settings.EMAIL_HOST_USER],
        )

    def _send_visitor():
        send_mail(
            subject="Thanks for reaching out — Tejas Modi",
            message=f"""
Hi {name},

Thank you for taking the time to reach out through my portfolio.

I’ve received your message successfully and really appreciate your interest in working together. I’ll review your requirements and get back to you as soon as possible.

Here’s a quick summary of what you submitted:

Project Type: {project_type}
Subject: {subject}

Your Message:
{message}

If you need to add anything else, you can simply reply to this email.

Looking forward to connecting with you.

Warm regards,
Tejas Modi
Python Full Stack Developer

Portfolio
Python • Django • Full Stack Development
""",
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[email],
        )

    notified = _try_email('contact-admin', _send_admin)
    if notified:
        # Visitor ko confirmation tabhi try karte hain jab SMTP chal raha ho (warna dobara timeout wait hoga)
        _try_email('contact-visitor', _send_visitor)
        return JsonResponse({'ok': True, 'email_sent': True})

    return JsonResponse({
        'ok': True,
        'email_sent': False,
        'message': 'Your message has been received successfully. Email notification is temporarily unavailable.',
    })




# @require_POST
# def requirement_submit(request):
#     if request.POST.get('website'):
#         return JsonResponse({'ok': True})
#     if throttled(request, 'requirement', 5, 3600):
#         return _too_many()

#     p = request.POST
#     data = {k: p.get(k, '').strip() for k in (
#         'client_name', 'email', 'phone', 'company', 'project_name', 'project_type', 'project_description',
#         'features', 'additional_requirements', 'budget_range', 'desired_timeline')}

#     errors = {}
#     limits = {'client_name': 100, 'phone': 25, 'company': 120, 'project_name': 120, 'project_type': 50,
#               'project_description': 4000, 'features': 4000, 'additional_requirements': 3000,
#               'budget_range': 80, 'desired_timeline': 80}
#     for field in ('client_name', 'project_name', 'project_type', 'project_description', 'features'):
#         if not data[field]:
#             errors[field] = 'This field is required.'
#     for field, limit in limits.items():
#         if len(data[field]) > limit:
#             errors[field] = f'Please keep this under {limit} characters.'
#     if _bad_email(data['email']):
#         errors['email'] = 'Please enter a valid email address.'

#     files = request.FILES.getlist('files')
#     if len(files) > CLIENT_MAX_FILES:
#         errors['files'] = f'You can attach up to {CLIENT_MAX_FILES} files.'
#     else:
#         for f in files:
#             err = _file_error(validate_client_file, f)
#             if err:
#                 errors['files'] = err
#                 break

#     links = []
#     for url in request.POST.getlist('links')[:5]:
#         url = url.strip()
#         if url:
#             try:
#                 URLValidator(schemes=['http', 'https'])(url)
#                 links.append(url)
#             except ValidationError:
#                 errors['links'] = 'Please enter full links starting with https://'

#     if errors:
#         return JsonResponse({'ok': False, 'errors': errors}, status=400)

#     technologies = _tech_text(', '.join(request.POST.getlist('preferred_technologies')))
#     with transaction.atomic():
#         req = ProjectRequirement.objects.create(preferred_technologies=technologies, ip_address=get_ip(request), **data)
#         for url in links:
#             RequirementLink.objects.create(requirement=req, url=url)
#         for f in files:
#             RequirementFile.objects.create(requirement=req, file=f, file_size=f.size,
#                                            original_name=get_valid_filename(f.name)[:255])
#     return JsonResponse({'ok': True, 'message': 'Your project brief has been received.'})

@require_POST
def requirement_submit(request):
    if request.POST.get('website'):
        return JsonResponse({'ok': True})

    if throttled(request, 'requirement', 5, 3600):
        return _too_many()

    p = request.POST

    data = {
        k: p.get(k, '').strip()
        for k in (
            'client_name',
            'email',
            'phone',
            'company',
            'project_name',
            'project_type',
            'project_description',
            'features',
            'additional_requirements',
            'budget_range',
            'desired_timeline'
        )
    }

    errors = {}

    limits = {
        'client_name': 100,
        'phone': 25,
        'company': 120,
        'project_name': 120,
        'project_type': 50,
        'project_description': 4000,
        'features': 4000,
        'additional_requirements': 3000,
        'budget_range': 80,
        'desired_timeline': 80
    }

    for field in (
        'client_name',
        'project_name',
        'project_type',
        'project_description',
        'features'
    ):
        if not data[field]:
            errors[field] = 'This field is required.'

    for field, limit in limits.items():
        if len(data[field]) > limit:
            errors[field] = f'Please keep this under {limit} characters.'

    if _bad_email(data['email']):
        errors['email'] = 'Please enter a valid email address.'

    files = request.FILES.getlist('files')

    if len(files) > CLIENT_MAX_FILES:
        errors['files'] = f'You can attach up to {CLIENT_MAX_FILES} files.'
    else:
        for f in files:
            err = _file_error(validate_client_file, f)
            if err:
                errors['files'] = err
                break

    links = []

    for url in request.POST.getlist('links')[:5]:
        url = url.strip()

        if url:
            try:
                URLValidator(schemes=['http', 'https'])(url)
                links.append(url)
            except ValidationError:
                errors['links'] = 'Please enter full links starting with https://'

    if errors:
        return JsonResponse({'ok': False, 'errors': errors}, status=400)

    technologies = _tech_text(
        ', '.join(request.POST.getlist('preferred_technologies'))
    )

    with transaction.atomic():
        req = ProjectRequirement.objects.create(
            preferred_technologies=technologies,
            ip_address=get_ip(request),
            **data
        )

        for url in links:
            RequirementLink.objects.create(
                requirement=req,
                url=url
            )

        for f in files:
            RequirementFile.objects.create(
                requirement=req,
                file=f,
                file_size=f.size,
                original_name=get_valid_filename(f.name)[:255]
            )

    admin_message = f"""
Hi Tejas,

You’ve received a new project inquiry through your portfolio website.

A potential client has submitted a detailed project brief. Here are the requirements:

CLIENT DETAILS
-------------------------
Name: {data['client_name']}
Email: {data['email']}
Phone: {data['phone']}
Company: {data['company'] or 'Not provided'}

PROJECT DETAILS
-------------------------
Project Name: {data['project_name']}
Project Type: {data['project_type']}

Project Description:
{data['project_description']}

Required Features:
{data['features']}

Additional Requirements:
{data['additional_requirements'] or 'Not provided'}

Budget Range:
{data['budget_range'] or 'Not provided'}

Desired Timeline:
{data['desired_timeline'] or 'Not provided'}

Preferred Technologies:
{technologies or 'Not specified'}

Project Links:
{chr(10).join(links) if links else 'No links provided'}

The submitted files, if any, are attached to this email.

Project Requirement ID: {req.id}

Please review the requirement from your portfolio dashboard.

Best,
Portfolio Project System
"""

    admin_email = EmailMessage(
        subject=f"New Project Inquiry — {data['project_name']}",
        body=admin_message,
        from_email=settings.EMAIL_HOST_USER,
        to=[settings.EMAIL_HOST_USER],
    )

    for f in files:
        f.seek(0)
        file_content = f.read()

        content_type = (
            getattr(f, 'content_type', None)
            or mimetypes.guess_type(f.name)[0]
            or 'application/octet-stream'
        )

        admin_email.attach(
            f.name,
            file_content,
            content_type
        )

    admin_sent = _try_email('requirement-admin', admin_email.send)

    visitor_message = f"""
Hi {data['client_name']},

Thank you for taking the time to share your project requirements with me.

I’ve successfully received your project brief and all the information you provided. I really appreciate your interest in working together.

Here’s a quick summary of your submission:

Project Name: {data['project_name']}
Project Type: {data['project_type']}

Project Description:
{data['project_description']}

Budget Range:
{data['budget_range'] or 'Not provided'}

Desired Timeline:
{data['desired_timeline'] or 'Not provided'}

I’ll go through your requirements carefully and get back to you soon to discuss the next steps.

If you remember anything else you would like to add, you can simply send another message through the portfolio website.

Looking forward to connecting with you and hopefully bringing your idea to life.

Warm regards,
Tejas Modi
Python Full Stack Developer

Portfolio
Python • Django • Full Stack Development
"""

    def _send_visitor_brief():
        send_mail(
            subject=f"Project Brief Received — {data['project_name']}",
            message=visitor_message,
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[data['email']],
        )

    if admin_sent:
        _try_email('requirement-visitor', _send_visitor_brief)

    if admin_sent:
        return JsonResponse({'ok': True, 'email_sent': True, 'message': 'Your project brief has been received.'})
    return JsonResponse({
        'ok': True,
        'email_sent': False,
        'message': 'Your project brief has been received successfully. Email notification is temporarily unavailable.',
    })




@require_GET
@xframe_options_sameorigin
def backend_pdf(request, slug):
    # Default: browser mein preview.  ?download=1 -> download (agar project allow kare)
    project = get_object_or_404(BackendProject, slug=slug, is_published=True)
    if not project.documentation_pdf:
        raise Http404
    download = request.GET.get('download') == '1'
    if download:
        if not project.allow_pdf_download:
            raise Http404
        BackendProject.objects.filter(id=project.id).update(download_count=F('download_count') + 1)
    response = FileResponse(project.documentation_pdf.open('rb'), as_attachment=download,
                            filename=f"{project.slug}-documentation.pdf", content_type='application/pdf')
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@require_GET
@xframe_options_sameorigin
def backend_showcase_pdf(request, slug):
    # Project ka poora look (screens / flow). Default: browser mein preview.  ?download=1 -> download (agar allow ho)
    project = get_object_or_404(BackendProject, slug=slug, is_published=True)
    if not project.showcase_pdf:
        raise Http404
    download = request.GET.get('download') == '1'
    if download and not project.allow_showcase_download:
        raise Http404
    response = FileResponse(project.showcase_pdf.open('rb'), as_attachment=download,
                            filename=f"{project.slug}-showcase.pdf", content_type='application/pdf')
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@require_GET
@xframe_options_sameorigin
def certificate_pdf(request, id):
    # Public: certificate PDF browser mein preview. ?download=1 -> download
    cert = get_object_or_404(Certificate, id=id, is_published=True)
    if not cert.pdf_file:
        raise Http404
    download = request.GET.get('download') == '1'
    response = FileResponse(cert.pdf_file.open('rb'), as_attachment=download,
                            filename=f"{get_valid_filename(cert.name)}.pdf", content_type='application/pdf')
    response['X-Content-Type-Options'] = 'nosniff'
    return response


# ================================================================
# RESUME
# ================================================================
def _resume_response(resume, download):
    # Resume protected storage mein hai, isliye hamesha view ke through hi milta hai
    if not resume.pdf_file:
        raise Http404
    try:
        handle = resume.pdf_file.open('rb')
    except FileNotFoundError:
        raise Http404
    name = get_valid_filename(resume.title) or 'resume'
    response = FileResponse(handle, as_attachment=download, filename=f"{name}.pdf",
                            content_type='application/pdf')
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'no-cache'      # naya resume active ho to purani copy cache se na dikhe
    return response


def _resume_errors(title, note, pdf, pdf_required):
    errors = []
    if not title:
        errors.append("Title is required.")
    elif len(title) > 120:
        errors.append("Title must be 120 characters or less.")
    if len(note) > 200:
        errors.append("Note must be 200 characters or less.")
    if pdf:
        err = _file_error(validate_pdf, pdf)
        if err:
            errors.append(err)
    elif pdf_required:
        errors.append("Please choose a PDF file.")
    return errors


@login_required
@role_required(['admin'])
def resume_list(request):
    context = {
        'active': 'resume', 'page_title': 'Resume',
        'resumes': _paginate(request, Resume.objects.all()),
        'active_resume': Resume.objects.filter(is_active=True).first(),
    }
    return render(request, 'resume/resume_list.html', context)


@login_required
@role_required(['admin'])
def add_resume(request):
    context = {'active': 'resume', 'page_title': 'Upload resume',
               'has_active': Resume.objects.filter(is_active=True).exists()}
    if request.method == "POST":
        try:
            title = request.POST.get('title', '').strip()
            note = request.POST.get('note', '').strip()
            pdf = request.FILES.get('pdf_file')

            errors = _resume_errors(title, note, pdf, pdf_required=True)
            if errors:
                for e in errors:
                    messages.error(request, f"❌ {e}")
                context['form'] = request.POST
                return render(request, 'resume/add_resume.html', context)

            resume = Resume.objects.create(
                title=title, note=note, pdf_file=pdf,
                original_name=get_valid_filename(pdf.name)[:255], file_size=pdf.size,
                is_active='is_active' in request.POST,
            )
            messages.success(request, f"✅ Resume {resume.resume_id} - {resume.title} uploaded successfully!")
            return redirect("resume")
        except Exception as e:
            messages.error(request, f"❌ Error: {str(e)}")
            context['form'] = request.POST
    return render(request, 'resume/add_resume.html', context)


@login_required
@role_required(['admin'])
def edit_resume(request, id):
    resume = get_object_or_404(Resume, id=id)
    context = {'active': 'resume', 'page_title': 'Edit resume', 'resume': resume}
    if request.method == "POST":
        try:
            title = request.POST.get('title', '').strip()
            note = request.POST.get('note', '').strip()
            pdf = request.FILES.get('pdf_file')

            errors = _resume_errors(title, note, pdf, pdf_required=False)
            if errors:
                for e in errors:
                    messages.error(request, f"❌ {e}")
                context['form'] = request.POST
                return render(request, 'resume/edit_resume.html', context)

            old_name = resume.pdf_file.name
            resume.title = title
            resume.note = note
            resume.is_active = 'is_active' in request.POST
            if pdf:
                resume.pdf_file = pdf
                resume.original_name = get_valid_filename(pdf.name)[:255]
                resume.file_size = pdf.size
            resume.save()
            if pdf and old_name:                        # purani file disk se hata do
                try:
                    resume.pdf_file.storage.delete(old_name)
                except Exception:
                    pass
            messages.success(request, f"✅ Resume {resume.resume_id} - {resume.title} updated successfully!")
            return redirect("resume")
        except Exception as e:
            messages.error(request, f"❌ Error: {str(e)}")
            context['form'] = request.POST
    return render(request, 'resume/edit_resume.html', context)


@require_POST
@login_required
@role_required(['admin'])
def delete_resume(request, id):
    resume = get_object_or_404(Resume, id=id)
    label = f"{resume.resume_id} - {resume.title}"
    storage, name = resume.pdf_file.storage, resume.pdf_file.name
    resume.delete()
    if name:
        try:
            storage.delete(name)
        except Exception:
            pass
    messages.success(request, f"✅ Resume {label} deleted successfully!")
    return redirect("resume")


@require_POST
@login_required
@role_required(['admin'])
def toggle_resume_active(request, id):
    resume = get_object_or_404(Resume, id=id)
    resume.is_active = not resume.is_active          # model save() baaki sab ko inactive kar deta hai
    resume.save()
    if resume.is_active:
        messages.success(request, f"✅ {resume.resume_id} - {resume.title} is now the active resume.")
    else:
        messages.success(request, f"✅ {resume.resume_id} - {resume.title} deactivated. The resume buttons are hidden on your website.")
    return redirect("resume")


@require_GET
@xframe_options_sameorigin
@login_required
@role_required(['admin'])
def resume_preview(request, id):
    # Dashboard preview: koi bhi resume (active ho ya na ho) dekh sakte ho
    return _resume_response(get_object_or_404(Resume, id=id), download=False)


@require_GET
@xframe_options_sameorigin
def resume_view(request):
    # Public: active resume browser mein preview (Homepage / About ke "Preview" buttons)
    resume = Resume.objects.filter(is_active=True).first()
    if not resume:
        raise Http404
    return _resume_response(resume, download=False)


@require_GET
def resume_download(request):
    # Public: active resume download (Homepage / About ke "Download" buttons)
    resume = Resume.objects.filter(is_active=True).first()
    if not resume:
        raise Http404
    return _resume_response(resume, download=True)
