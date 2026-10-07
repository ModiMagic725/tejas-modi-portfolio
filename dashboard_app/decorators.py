from django.shortcuts import redirect
from django.contrib import messages
from functools import wraps
from .models import *


def login_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if 'user_id' not in request.session:
            messages.error(request, 'Please login first!')
            return redirect('login')
        # Admin delete / deactivate ho gaya ho to session turant band
        if not AdminUser.objects.filter(id=request.session.get('user_id'), is_active=True).exists():
            request.session.flush()
            messages.error(request, 'Your account is no longer active. Please login again.')
            return redirect('login')
        return view_func(request, *args, **kwargs)
    return wrapper


def role_required(allowed_roles=[]):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if 'user_id' not in request.session:
                messages.error(request, 'Please login first!')
                return redirect('login')

            user_role = request.session.get('role')
            if user_role not in allowed_roles:
                messages.error(request, 'You do not have permission to access this page!')
                return redirect('login')

            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator