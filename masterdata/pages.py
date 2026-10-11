"""Страницы интерфейса «Мастер-данные» (собственный UI, §7) и документация API."""
import os

from django.http import HttpResponse
from django.shortcuts import render

from accounts.views import _serve_asset_file

ASSETS = os.path.join(os.path.dirname(__file__), 'assets')


def app_page(request):
    return render(request, 'masterdata/app.html')


def asset(request, path):
    return _serve_asset_file(ASSETS, path)


def api_docs(request):
    return HttpResponse('''<!doctype html><html lang="ru"><head><meta charset="utf-8">
<title>API «Мастер-данные»</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui.css"></head>
<body><div id="ui"></div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui-bundle.js"></script>
<script>SwaggerUIBundle({url:'/api/md/schema/', dom_id:'#ui'});</script></body></html>''')
