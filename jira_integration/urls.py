from django.contrib.auth import views as auth_views
from django.urls import path

from . import api, views

app_name = "jira_integration"

urlpatterns = [
    path("", views.index, name="index"),
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="jira_integration/login.html",
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("api/backlog/", api.backlog, name="api_backlog"),
    path("api/board/", api.board, name="api_board"),
    path("api/status/", api.sync_status, name="api_status"),
    path("api/issues/<str:key>/", api.issue_detail, name="api_issue"),
]