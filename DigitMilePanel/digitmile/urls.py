"""
URL configuration for digitmile project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from django.urls import path, include # Make sure include is imported
from digitmileapi import views as api_views

# Your existing URL patterns
panel_patterns = [
    path('', api_views.home_view, name='home'),
    path('health/', api_views.health_check),
    path('api/', include('digitmileapi.urls')),
    path('register/school/', api_views.register_school_view, name='register_school'),
    path('register/teacher/', api_views.register_teacher_view, name='register_teacher'),
    path('registration-success/', api_views.registration_success, name='registration_success'),
    path('teacher/statistics/', api_views.teacher_statistics_dashboard, name='teacher_statistics'),
    path('captcha/', include('captcha.urls')),
]

urlpatterns = [
    path('admin/', admin.site.urls),
    path('panel/', include(panel_patterns)),
]