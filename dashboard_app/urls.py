from django.urls import path
from dashboard_app.views import *

urlpatterns = [

    path('',   dashboard, name='dashboard'),
    path('login/',   login_view, name='login'),
    path('logout/',   logout_view, name='logout'),

    # ------------------------ Frontend Projects (Websites) --------------------------

    path('websites/', website_list, name='website_list'),
    path('websites/add/', add_website, name='add_website'),
    path('websites/edit/<int:id>/', edit_website, name='edit_website'),
    path('websites/delete/<int:id>/', delete_website, name='delete_website'),
    path('websites/image/delete/<int:id>/', delete_website_image, name='delete_website_image'),
    path('websites/toggle-published/<int:id>/', toggle_website_published, name='toggle_website_published'),
    path('websites/toggle-featured/<int:id>/', toggle_website_featured, name='toggle_website_featured'),
    path('websites/toggle-github/<int:id>/', toggle_website_github, name='toggle_website_github'),

    # ------------------------ Backend Projects --------------------------

    path('backend/', backend_list, name='backend_list'),
    path('backend/add/', add_backend, name='add_backend'),
    path('backend/edit/<int:id>/', edit_backend, name='edit_backend'),
    path('backend/delete/<int:id>/', delete_backend, name='delete_backend'),
    path('backend/toggle-published/<int:id>/', toggle_backend_published, name='toggle_backend_published'),
    path('backend/toggle-featured/<int:id>/', toggle_backend_featured, name='toggle_backend_featured'),
    path('backend/toggle-github/<int:id>/', toggle_backend_github, name='toggle_backend_github'),
    path('backend/toggle-pdf-download/<int:id>/', toggle_backend_pdf_download, name='toggle_backend_pdf_download'),
    path('backend/toggle-showcase-download/<int:id>/', toggle_backend_showcase_download, name='toggle_backend_showcase_download'),

    # ------------------------ Contact Messages --------------------------

    path('messages/', message_list, name='message_list'),
    path('messages/view/<int:id>/', view_message, name='view_message'),
    path('messages/delete/<int:id>/', delete_message, name='delete_message'),

    # ------------------------ Project Requirements --------------------------

    path('requirements/', requirement_list, name='requirement_list'),
    path('requirements/view/<int:id>/', view_requirement, name='view_requirement'),
    path('requirements/delete/<int:id>/', delete_requirement, name='delete_requirement'),
    path('requirements/file/<int:id>/', download_requirement_file, name='download_requirement_file'),

    # ------------------------ Profile: Experience --------------------------

    path('experience/', experience_list, name='experience_list'),
    path('experience/add/', add_experience, name='add_experience'),
    path('experience/edit/<int:id>/', edit_experience, name='edit_experience'),
    path('experience/delete/<int:id>/', delete_experience, name='delete_experience'),
    path('experience/toggle-published/<int:id>/', toggle_experience_published, name='toggle_experience_published'),

    # ------------------------ Profile: Certificates --------------------------

    path('certificates/', certificate_list, name='certificate_list'),
    path('certificates/add/', add_certificate, name='add_certificate'),
    path('certificates/edit/<int:id>/', edit_certificate, name='edit_certificate'),
    path('certificates/delete/<int:id>/', delete_certificate, name='delete_certificate'),
    path('certificates/toggle-published/<int:id>/', toggle_certificate_published, name='toggle_certificate_published'),

    # ------------------------ Resume --------------------------

    path('resume/', resume_list, name='resume'),
    path('resume/add/', add_resume, name='add_resume'),
    path('resume/edit/<int:id>/', edit_resume, name='edit_resume'),
    path('resume/delete/<int:id>/', delete_resume, name='delete_resume'),
    path('resume/toggle-active/<int:id>/', toggle_resume_active, name='toggle_resume_active'),
    path('resume/preview/<int:id>/', resume_preview, name='resume_preview'),

    # ------------------------ Skills (Technical arsenal) --------------------------

    path('skills/', skill_list, name='skill_list'),
    path('skills/categories/', skill_category_list, name='skill_category_list'),
    path('skills/category/add/', add_skill_category, name='add_skill_category'),
    path('skills/category/edit/<int:id>/', edit_skill_category, name='edit_skill_category'),
    path('skills/category/delete/<int:id>/', delete_skill_category, name='delete_skill_category'),
    path('skills/category/toggle-published/<int:id>/', toggle_skill_category_published, name='toggle_skill_category_published'),
    path('skills/add/', add_skill, name='add_skill'),
    path('skills/edit/<int:id>/', edit_skill, name='edit_skill'),
    path('skills/delete/<int:id>/', delete_skill, name='delete_skill'),
]