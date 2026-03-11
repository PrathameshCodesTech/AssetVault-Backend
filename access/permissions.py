"""
DRF permission classes for RBAC.
"""
from rest_framework.permissions import BasePermission

from access.helpers import get_user_permission_codes


class HasPermission(BasePermission):
    """
    Usage: permission_classes = [HasPermission('asset.view')]
    Grants access if the user has ANY of the specified permission codes.
    """

    def __init__(self, *required_codes):
        self.required_codes = set(required_codes)

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        user_codes = get_user_permission_codes(request.user)
        return bool(self.required_codes & user_codes)


def permission_required(*codes):
    """
    Factory function that returns a HasPermission instance.
    Usage in views: permission_classes = [permission_required('asset.view', 'asset.create')]
    """

    class _Perm(HasPermission):
        def __init__(self):
            super().__init__(*codes)

    _Perm.__name__ = f"HasPermission({'|'.join(codes)})"
    _Perm.__qualname__ = _Perm.__name__
    return _Perm
