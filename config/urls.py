from django.urls import include, path

from apps.core.admin import clinic_admin_site

urlpatterns = [
    path("django-admin/", clinic_admin_site.urls),
    path("", include("apps.core.urls")),
]
