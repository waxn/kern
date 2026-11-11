from django.urls import path

from . import views as v

urlpatterns = [
    path("site", v.site_info),
    path("setup", v.setup),
    path("setup/restore", v.setup_restore),
    path("auth/login", v.login_view),
    path("auth/logout", v.logout_view),
    path("auth/signup", v.signup),
    path("auth/password", v.change_password),
    path("auth/profile", v.update_profile),
    path("admin/users", v.admin_users),
    path("admin/users/<int:user_id>", v.admin_user_detail),
    path("admin/site", v.admin_site),
]
