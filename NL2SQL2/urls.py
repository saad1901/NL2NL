"""
URL configuration for NL2SQL2 project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
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
from app import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.login_view),
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('chat/<int:db_id>/', views.chat_view, name='chat'),
    path('chat/<int:db_id>/ask/', views.ask_view, name='ask'),
    path('chat/<int:db_id>/clear/', views.clear_history_view, name='clear_history'),
    path('databases/', views.databases_view, name='databases'),
    path('databases/add/', views.add_database_view, name='add_database'),
    path('databases/upload/', views.upload_file_db_view, name='upload_file_db'),
    path('databases/<int:db_id>/delete/', views.delete_database_view, name='delete_database'),
]
