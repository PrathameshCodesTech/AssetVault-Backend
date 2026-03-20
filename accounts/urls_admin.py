from django.urls import path

from accounts.views_admin import (
    AdminUserAssignmentsView,
    AdminUserDetailView,
    AdminUserListCreateView,
)

urlpatterns = [
    path("users/", AdminUserListCreateView.as_view()),
    path("users/<uuid:pk>/", AdminUserDetailView.as_view()),
    path("users/<uuid:pk>/assignments/", AdminUserAssignmentsView.as_view()),
]
