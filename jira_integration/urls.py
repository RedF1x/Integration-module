from django.urls import path

from . import views

app_name = "jira_integration"

urlpatterns = [
    path("", views.index, name="index"),
]