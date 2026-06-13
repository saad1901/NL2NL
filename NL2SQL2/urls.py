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
    path('settings/', views.settings_view, name='settings'),
    path('settings/providers/save/', views.save_provider_view, name='save_provider'),
    path('settings/providers/<int:provider_id>/delete/', views.delete_provider_view, name='delete_provider'),
    path('settings/models/save/', views.save_model_view, name='save_model'),
    path('settings/models/<int:model_id>/delete/', views.delete_model_view, name='delete_model'),
    path('api/models/', views.models_for_chat_view, name='models_for_chat'),
    path('chat/<int:db_id>/dashboard/', views.dashboard_chart_view, name='dashboard_chart'),
    path('chat/<int:db_id>/dashboard/list/', views.dashboard_charts_list, name='dashboard_charts_list'),
    path('chat/<int:db_id>/dashboard/save/', views.dashboard_chart_save, name='dashboard_chart_save'),
    path('chat/<int:db_id>/dashboard/<int:chart_id>/delete/', views.dashboard_chart_delete, name='dashboard_chart_delete'),
    path('docs/', views.docs_view, name='docs'),
]
