from django.urls import path
from dashboard_app.views import *

# Public site ke liye - ye project ke root par include hota hai (login ki zaroorat nahi)
urlpatterns = [

# ye links saamne se jo data aaega mere cms ke liye means clients use karenge
    path('api/contact/', contact_submit, name='contact_submit'), # mujhse contact karne ke liye
    path('api/start-project/', requirement_submit, name='requirement_submit'), # project details submit karne ke liye
    path('docs/backend/<slug:slug>/', backend_pdf, name='backend_pdf'), # project file ki safety check karne ke liye
    path('docs/backend/<slug:slug>/showcase/', backend_showcase_pdf, name='backend_showcase_pdf'),   # project ka poora look (PDF)
    path('docs/certificate/<int:id>/', certificate_pdf, name='certificate_pdf'),
    path('docs/resume/', resume_view, name='resume_view'),                    # active resume - browser mein preview
    path('docs/resume/download/', resume_download, name='resume_download'),   # active resume - download
]