from django.contrib import admin
from django.urls import include, path

handler403 = "jira_integration.errors.permission_denied"
handler404 = "jira_integration.errors.page_not_found"
handler500 = "jira_integration.errors.server_error"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("jira/", include("jira_integration.urls")),
]