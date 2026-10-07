from .models import *


def user_context(request):

    return {
        'session_user_name': request.session.get('full_name', ''),
        'session_user_role': request.session.get('role', ''),
        'session_user_email': request.session.get('email', ''),
        'is_logged_in': 'user_id' in request.session,
    }


def nav_counts(request):
    # Sidebar ke unread badges - sirf logged in admin ke liye query chalti hai
    if 'user_id' not in request.session:
        return {}
    return {
        'nav_counts': {
            'messages': ContactMessage.objects.filter(status='new').count(),
            'requirements': ProjectRequirement.objects.filter(status='new').count(),
        }
    }