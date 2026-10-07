import os
import uuid

from django.conf import settings
from django.contrib.auth import hashers
from django.core.files.storage import FileSystemStorage
from django.db import models, transaction
from django.utils import timezone

from .utils import unique_slug


# =========================== HELPERS ========================

def get_protected_storage():
    # Client uploads yahan jaati hain (MEDIA_ROOT ke bahar) - inka koi public URL nahi hota
    root = getattr(settings, 'PROTECTED_MEDIA_ROOT', settings.BASE_DIR / 'protected_media')
    return FileSystemStorage(location=root)


def _random_name(folder, filename):
    return f"{folder}/{uuid.uuid4().hex}{os.path.splitext(filename)[1].lower()}"


def website_thumb_path(instance, filename):     return _random_name('websites/thumbs', filename)
def website_image_path(instance, filename):     return _random_name('websites/gallery', filename)
def backend_thumb_path(instance, filename):     return _random_name('backend/thumbs', filename)
def backend_pdf_path(instance, filename):       return _random_name('backend/docs', filename)
def requirement_file_path(instance, filename):  return _random_name('requirements', filename)


def _lines(text):
    return [ln.strip() for ln in (text or '').splitlines() if ln.strip()]


def _next_code(model, field, prefix):
    last = model.objects.all().order_by('id').last()
    if last:
        return f'{prefix}{str(int(getattr(last, field)[len(prefix):]) + 1).zfill(3)}'
    return f'{prefix}001'


# =========================== ADMIN USER (Login) ========================

class AdminUser(models.Model):
    ADMIN_ROLE_CHOICES = (
        ('admin', 'Admin'),
    )

    admin_id = models.CharField(max_length=10, unique=True, editable=False)
    full_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=255)          # hashed - plain text kabhi save nahi hota
    role = models.CharField(max_length=20, choices=ADMIN_ROLE_CHOICES, default='admin')
    is_active = models.BooleanField(default=True)
    last_login = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    def set_password(self, raw_password):
        self.password = hashers.make_password(raw_password)

    def check_password(self, raw_password):
        return hashers.check_password(raw_password, self.password)

    def save(self, *args, **kwargs):
        if not self.admin_id:
            self.admin_id = _next_code(AdminUser, 'admin_id', 'ADM')
        if self.email:
            self.email = self.email.strip().lower()
        super(AdminUser, self).save(*args, **kwargs)

    def __str__(self):
        return f"{self.admin_id} - {self.full_name} ({self.role})"


# =========================== FRONTEND PROJECTS (Websites) ========================

class WebsiteProject(models.Model):
    CATEGORY_CHOICES = (
        ('business', 'Business website'),
        ('landing', 'Landing page'),
        ('dashboard', 'Dashboard'),
        ('ecommerce', 'E-commerce'),
        ('webapp', 'Web application'),
        ('other', 'Other'),
    )

    project_id = models.CharField(max_length=10, unique=True, editable=False)
    title = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, editable=False)
    short_description = models.CharField(max_length=220)
    description = models.TextField()
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='business')
    technologies = models.CharField(max_length=300, blank=True)      # comma separated: "HTML, CSS, JavaScript"
    thumbnail = models.ImageField(upload_to=website_thumb_path)
    live_url = models.URLField(blank=True)
    github_url = models.URLField(blank=True)
    show_github = models.BooleanField(default=True)                  # toggle: public site par GitHub link dikhana ya nahi
    key_features = models.TextField(blank=True)                      # ek line = ek feature
    year = models.PositiveSmallIntegerField(null=True, blank=True)
    is_published = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    display_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', '-created_at']

    def save(self, *args, **kwargs):
        if not self.project_id:
            self.project_id = _next_code(WebsiteProject, 'project_id', 'WEB')
        if not self.slug:
            self.slug = unique_slug(self, self.title)
        super(WebsiteProject, self).save(*args, **kwargs)

    @property
    def tech_list(self):
        return [t.strip() for t in self.technologies.split(',') if t.strip()]

    @property
    def features_list(self):
        return _lines(self.key_features)

    @property
    def public_github_url(self):
        return self.github_url if (self.show_github and self.github_url) else ''

    def __str__(self):
        return f"{self.project_id} - {self.title}"


class WebsiteImage(models.Model):
    project = models.ForeignKey(WebsiteProject, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to=website_image_path)
    alt_text = models.CharField(max_length=160, blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f"{self.project.title} - image {self.id}"


# =========================== BACKEND PROJECTS ========================

class BackendProject(models.Model):
    CATEGORY_CHOICES = (
        ('management', 'Management system'),
        ('api', 'API / backend service'),
        ('cms', 'CMS / admin system'),
        ('other', 'Other'),
    )

    project_id = models.CharField(max_length=10, unique=True, editable=False)
    title = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, editable=False)
    short_description = models.CharField(max_length=220)
    description = models.TextField()
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='management')
    technologies = models.CharField(max_length=300, blank=True)
    thumbnail = models.ImageField(upload_to=backend_thumb_path, blank=True, null=True)
    period = models.CharField(max_length=40, blank=True)             # e.g. 01/2026 - 04/2026
    hub_label = models.CharField(max_length=40, blank=True)          # architecture diagram ka center node
    roles = models.TextField(blank=True)                             # ek line = ek role
    modules = models.TextField(blank=True)                           # ek line = ek module
    key_points = models.TextField(blank=True)                        # ek line = ek point
    documentation_pdf = models.FileField(upload_to=backend_pdf_path, blank=True, null=True)
    allow_pdf_download = models.BooleanField(default=True)           # toggle: visitor PDF download kar sake ya nahi
    download_count = models.PositiveIntegerField(default=0)
    github_url = models.URLField(blank=True)
    show_github = models.BooleanField(default=True)                  # toggle: GitHub link dikhana ya nahi
    is_published = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    display_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', '-created_at']

    def save(self, *args, **kwargs):
        if not self.project_id:
            self.project_id = _next_code(BackendProject, 'project_id', 'BCK')
        if not self.slug:
            self.slug = unique_slug(self, self.title)
        super(BackendProject, self).save(*args, **kwargs)

    @property
    def tech_list(self):
        return [t.strip() for t in self.technologies.split(',') if t.strip()]

    @property
    def roles_list(self):
        return _lines(self.roles)

    @property
    def modules_list(self):
        return _lines(self.modules)

    @property
    def key_points_list(self):
        return _lines(self.key_points)

    @property
    def public_github_url(self):
        return self.github_url if (self.show_github and self.github_url) else ''

    def __str__(self):
        return f"{self.project_id} - {self.title}"


# =========================== CONTACT MESSAGES ========================

class ContactMessage(models.Model):
    STATUS_CHOICES = (
        ('new', 'New'),
        ('read', 'Read'),
        ('replied', 'Replied'),
        ('archived', 'Archived'),
    )

    name = models.CharField(max_length=100)
    email = models.EmailField()
    subject = models.CharField(max_length=150, blank=True)
    project_type = models.CharField(max_length=30, blank=True)
    message = models.TextField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='new')
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} - {self.subject or 'No subject'}"


# =========================== START A PROJECT (Requirements) ========================

class ProjectRequirement(models.Model):
    STATUS_CHOICES = (
        ('new', 'New'),
        ('reviewing', 'Reviewing'),
        ('discussing', 'Discussing'),
        ('approved', 'Approved'),
        ('in_progress', 'In progress'),
        ('completed', 'Completed'),
        ('archived', 'Archived'),
    )

    requirement_id = models.CharField(max_length=10, unique=True, editable=False)
    client_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=25, blank=True)
    company = models.CharField(max_length=120, blank=True)
    project_name = models.CharField(max_length=120)
    project_type = models.CharField(max_length=50)
    project_description = models.TextField()
    features = models.TextField()
    preferred_technologies = models.CharField(max_length=300, blank=True)
    additional_requirements = models.TextField(blank=True)
    budget_range = models.CharField(max_length=80, blank=True)
    desired_timeline = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='new')
    internal_notes = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.requirement_id:
            self.requirement_id = _next_code(ProjectRequirement, 'requirement_id', 'REQ')
        super(ProjectRequirement, self).save(*args, **kwargs)

    def __str__(self):
        return f"{self.requirement_id} - {self.project_name} ({self.client_name})"


class RequirementLink(models.Model):
    requirement = models.ForeignKey(ProjectRequirement, on_delete=models.CASCADE, related_name='links')
    url = models.URLField(max_length=300)

    def __str__(self):
        return self.url


class RequirementFile(models.Model):
    requirement = models.ForeignKey(ProjectRequirement, on_delete=models.CASCADE, related_name='files')
    file = models.FileField(upload_to=requirement_file_path, storage=get_protected_storage)
    original_name = models.CharField(max_length=255)
    file_size = models.PositiveIntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.requirement.requirement_id} - {self.original_name}"

# =========================== PROFILE: EXPERIENCE (About page timeline) ========================

class Experience(models.Model):
    experience_id = models.CharField(max_length=10, unique=True, editable=False)
    role = models.CharField(max_length=120)
    company = models.CharField(max_length=120)
    location = models.CharField(max_length=100, blank=True)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=False)                  # True = "Present"
    description = models.TextField()
    technologies = models.CharField(max_length=300, blank=True)      # comma separated
    is_published = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', '-start_date']                  # same order ho to naya pehle

    def save(self, *args, **kwargs):
        if not self.experience_id:
            self.experience_id = _next_code(Experience, 'experience_id', 'EXP')
        if self.is_current:
            self.end_date = None
        super(Experience, self).save(*args, **kwargs)

    @property
    def tech_list(self):
        return [t.strip() for t in self.technologies.split(',') if t.strip()]

    @property
    def period_display(self):
        start = self.start_date.strftime('%m/%Y')
        end = 'Present' if (self.is_current or not self.end_date) else self.end_date.strftime('%m/%Y')
        return f"{start} – {end}"

    def __str__(self):
        return f"{self.experience_id} - {self.role} at {self.company}"


# =========================== PROFILE: CERTIFICATES ========================

def certificate_pdf_path(instance, filename):
    return _random_name('certificates', filename)


class Certificate(models.Model):
    certificate_id = models.CharField(max_length=10, unique=True, editable=False)
    name = models.CharField(max_length=150)
    description = models.CharField(max_length=300, blank=True)
    pdf_file = models.FileField(upload_to=certificate_pdf_path, blank=True, null=True)
    is_published = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', '-created_at']

    def save(self, *args, **kwargs):
        if not self.certificate_id:
            self.certificate_id = _next_code(Certificate, 'certificate_id', 'CRT')
        super(Certificate, self).save(*args, **kwargs)

    def __str__(self):
        return f"{self.certificate_id} - {self.name}"


# =========================== RESUME ========================
# Sirf ek resume "active" hota hai - wahi Homepage / About par preview + download hota hai.
# File protected storage mein rehti hai (public URL nahi), isliye purane / inactive resumes bahar leak nahi hote.

def resume_pdf_path(instance, filename):
    return _random_name('resumes', filename)


class Resume(models.Model):
    resume_id = models.CharField(max_length=10, unique=True, editable=False)
    title = models.CharField(max_length=120)                  # download file name bhi yahi banta hai
    note = models.CharField(max_length=200, blank=True)       # sirf admin ke liye
    pdf_file = models.FileField(upload_to=resume_pdf_path, storage=get_protected_storage)
    original_name = models.CharField(max_length=255, blank=True)   # upload karte waqt file ka naam
    file_size = models.PositiveIntegerField(default=0)             # bytes
    is_active = models.BooleanField(default=False)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_active', '-uploaded_at']

    def save(self, *args, **kwargs):
        if not self.resume_id:
            self.resume_id = _next_code(Resume, 'resume_id', 'RES')
        with transaction.atomic():
            super(Resume, self).save(*args, **kwargs)
            if self.is_active:      # ek time par sirf ek active
                Resume.objects.exclude(pk=self.pk).filter(is_active=True).update(is_active=False)

    def __str__(self):
        return f"{self.resume_id} - {self.title}"


# =========================== SKILLS (Technical arsenal) ========================
# Category (Languages, Backend, Databases ...)  ->  Skills (Python, Django, MySQL ...)

class SkillCategory(models.Model):
    name = models.CharField(max_length=60, unique=True)
    display_order = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['display_order', 'name']
        verbose_name_plural = 'skill categories'

    def __str__(self):
        return self.name


class Skill(models.Model):
    category = models.ForeignKey(SkillCategory, on_delete=models.CASCADE, related_name='skills')
    name = models.CharField(max_length=60)
    display_order = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['display_order', 'id']
        unique_together = ('category', 'name')

    def __str__(self):
        return f"{self.category.name} - {self.name}"