from . import tenancy

TENANT_APPS = {"notes", "mail"}  # live in each user's own database
SHARED_APPS = {"auth", "contenttypes", "sessions", "accounts", "admin", "migrations", "kernapps"}


class TenantRouter:
    """Notes data goes to the active user's database; accounts and sessions to the shared one."""

    def _pick(self, model):
        if model._meta.app_label in TENANT_APPS:
            return tenancy.current_alias()
        return "default"

    db_for_read = db_for_write = lambda self, model, **hints: self._pick(model)

    def allow_relation(self, a, b, **hints):
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if tenancy.testing():
            return db == "default"
        if app_label in TENANT_APPS:
            return db != "default"
        return db == "default"
