"""
RBAC and location scope helpers.

Functions:
- get_user_permission_codes(user) -> set[str]
- get_user_scope(user) -> dict with is_global, location_ids, primary_role_code
- filter_by_location_scope(queryset, user, location_field='current_location')
- get_primary_role(user) -> Role or None
"""
from access.models import Role, UserRoleAssignment
from locations.models import LocationClosure


def get_user_permission_codes(user) -> set:
    """
    Return set of permission code strings for all active role assignments of user.
    """
    if not user or not user.is_authenticated:
        return set()

    codes = set(
        UserRoleAssignment.objects.filter(
            user=user,
            is_active=True,
        )
        .select_related("role")
        .values_list(
            "role__role_permissions__permission__code",
            flat=True,
        )
    )
    codes.discard(None)
    return codes


def get_primary_role(user):
    """
    Find the user's primary active role assignment.
    Falls back to the first active assignment if no primary is set.
    Returns the Role instance or None.
    """
    if not user or not user.is_authenticated:
        return None

    assignment = (
        UserRoleAssignment.objects.filter(user=user, is_active=True, is_primary=True)
        .select_related("role")
        .first()
    )
    if assignment:
        return assignment.role

    assignment = (
        UserRoleAssignment.objects.filter(user=user, is_active=True)
        .select_related("role")
        .order_by("created_at")
        .first()
    )
    return assignment.role if assignment else None


def get_user_scope(user) -> dict:
    """
    Determine the user's location scope.

    Returns dict with:
        is_global: bool - True if any active assignment has location=None
        location_ids: set of UUID - all location IDs in scope (including descendants)
        primary_role_code: str or None
        role_codes: set of str
    """
    if not user or not user.is_authenticated:
        return {
            "is_global": False,
            "location_ids": set(),
            "primary_role_code": None,
            "role_codes": set(),
        }

    assignments = list(
        UserRoleAssignment.objects.filter(user=user, is_active=True)
        .select_related("role", "location")
    )

    if not assignments:
        return {
            "is_global": False,
            "location_ids": set(),
            "primary_role_code": None,
            "role_codes": set(),
        }

    role_codes = {a.role.code for a in assignments}

    # Find primary role
    primary = next((a for a in assignments if a.is_primary), assignments[0])
    primary_role_code = primary.role.code

    # Check for global scope
    is_global = any(a.location_id is None for a in assignments)

    if is_global:
        return {
            "is_global": True,
            "location_ids": set(),
            "primary_role_code": primary_role_code,
            "role_codes": role_codes,
        }

    # Collect location IDs including all descendants via closure table
    scoped_location_ids = {a.location_id for a in assignments if a.location_id}

    if not scoped_location_ids:
        return {
            "is_global": False,
            "location_ids": set(),
            "primary_role_code": primary_role_code,
            "role_codes": role_codes,
        }

    # Get all descendant location IDs from the closure table
    descendant_ids = set(
        LocationClosure.objects.filter(
            ancestor_id__in=scoped_location_ids,
        ).values_list("descendant_id", flat=True)
    )

    return {
        "is_global": False,
        "location_ids": descendant_ids,
        "primary_role_code": primary_role_code,
        "role_codes": role_codes,
    }


def filter_by_location_scope(queryset, user, location_field="current_location"):
    """
    Filter a queryset by the user's location scope.

    If user has global scope, returns queryset unmodified.
    Otherwise filters by location_field__in=location_ids.
    """
    scope = get_user_scope(user)
    if scope["is_global"]:
        return queryset

    if not scope["location_ids"]:
        return queryset.none()

    lookup = f"{location_field}__in"
    return queryset.filter(**{lookup: scope["location_ids"]})


def location_in_scope(location_id, user) -> bool:
    """Return True if *location_id* is within the user's allowed scope."""
    if location_id is None:
        return True
    scope = get_user_scope(user)
    if scope["is_global"]:
        return True
    if not scope["location_ids"]:
        return False
    return location_id in scope["location_ids"]
