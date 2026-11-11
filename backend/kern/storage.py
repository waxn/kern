import os

from django.core.files.storage import FileSystemStorage

from . import tenancy


class TenantStorage(FileSystemStorage):
    """Uploaded files go to the folder of the user making the request."""

    @property
    def base_location(self):
        return str(tenancy.media_root())

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    @property
    def base_url(self):
        return "/media/"
