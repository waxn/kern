from django.urls import path

from . import api as v

urlpatterns = [
    path("", v.apps),
    path("templates", v.templates),
    path("check-slug", v.check_slug),
    path("<str:slug>", v.app_detail),
    path("<str:slug>/logs", v.app_logs),
    path("<str:slug>/env", v.app_env),
    path("<str:slug>/ai/models", v.app_ai_models),
    path("<str:slug>/ai", v.app_ai),
    path("<str:slug>/files", v.app_files),
    path("<str:slug>/data", v.app_data),
    path("<str:slug>/deploys", v.deploys),
    path("<str:slug>/deploys/<int:number>/log", v.deploy_log),
    path("<str:slug>/deploys/<int:number>/<str:action>", v.deploy_action),
    path("<str:slug>/tasks", v.app_tasks),
    path("<str:slug>/db", v.app_db),
    path("<str:slug>/db/rows", v.app_db_rows),
    path("<str:slug>/db/query", v.app_db_query),
    path("<str:slug>/builder", v.builder),
    path("<str:slug>/builder/stop", v.builder_stop),
    path("<str:slug>/<str:action>", v.app_action),
]
