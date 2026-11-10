from django.shortcuts import render

from .decorators import intern_required


@intern_required
def index(request):
    return render(request, "jira_integration/index.html")