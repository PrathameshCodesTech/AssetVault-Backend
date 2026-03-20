from django.urls import path

from access.views_admin import (
    AdminApplyTemplateView,
    AdminPermissionDetailView,
    AdminPermissionListView,
    AdminPermissionTemplateDetailView,
    AdminPermissionTemplateListView,
    AdminRoleDetailView,
    AdminRoleListCreateView,
    AdminRolePermissionRemoveView,
    AdminRolePermissionsView,
    AdminUserRoleAssignmentDetailView,
    AdminUserRoleAssignmentListCreateView,
)

urlpatterns = [
    path("roles/", AdminRoleListCreateView.as_view()),
    path("roles/<uuid:pk>/", AdminRoleDetailView.as_view()),
    path("roles/<uuid:pk>/permissions/", AdminRolePermissionsView.as_view()),
    path("roles/<uuid:pk>/permissions/<uuid:perm_id>/", AdminRolePermissionRemoveView.as_view()),
    path("roles/<uuid:pk>/apply-template/", AdminApplyTemplateView.as_view()),
    path("permissions/", AdminPermissionListView.as_view()),
    path("permissions/<uuid:pk>/", AdminPermissionDetailView.as_view()),
    path("permission-templates/", AdminPermissionTemplateListView.as_view()),
    path("permission-templates/<uuid:pk>/", AdminPermissionTemplateDetailView.as_view()),
    path("assignments/", AdminUserRoleAssignmentListCreateView.as_view()),
    path("assignments/<uuid:pk>/", AdminUserRoleAssignmentDetailView.as_view()),
]
