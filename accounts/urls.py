from django.urls import path, re_path

from . import views

urlpatterns = [
    # ---- Страницы (аналог app.get('/register') и т.д. из server.js) ----
    path('', views.index_redirect),
    path('register', views.register_page),
    path('login', views.login_page),
    path('home', views.home_page),
    path('dictionaries', views.dictionaries_page),
    # dictionaries.html ссылается именно на /income-expense.html (как на
    # статический файл в оригинальном Express-модуле) — сохраняем путь 1:1.
    path('income-expense.html', views.income_expense_page),
    path('set-password', views.set_password_page),
    path('forgot-password', views.forgot_password_page),
    path('reset-password', views.reset_password_page),
    path('dashboard', views.dashboard_stub),

    # ---- API ----
    path('api/register', views.api_register),
    path('api/verify-token', views.api_verify_token),
    path('api/set-password', views.api_set_password),
    path('api/forgot-password', views.api_forgot_password),
    path('api/reset-password', views.api_reset_password),
    path('api/login', views.api_login),
    path('api/refresh', views.api_refresh),
    path('api/logout', views.api_logout),

    # ---- Общие статические файлы фронтенда (как express.static в оригинале) ----
    path('styles.css', views.serve_styles_css),
    re_path(r'^shared/(?P<path>.+)$', views.serve_shared_asset),
]
