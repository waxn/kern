from . import tenancy

SHARED_APPS = {"auth", "contenttypes", "sessions", "accounts", "admin", "migrations"}


class TenantRouter:
    """Notes data goes to the active user's database; accounts and sessions to the shared one."""

    def _pick(self, model):
        if model._meta.app_label == "notes":
            return tenancy.current_alias()
        return "default"

    db_for_read = db_for_write = lambda self, model, **hints: self._pick(model)

    def allow_relation(self, a, b, **hints):
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if tenancy.testing():
            return db == "default"
        if app_label == "notes":
            return db != "default"
        return db == "default"
