from django.urls import path

from verification.views_admin import (
    AdminCycleActivateView,
    AdminCycleCloseView,
    AdminCycleDetailView,
    AdminCycleListCreateView,
)

urlpatterns = [
    path("verification-cycles/", AdminCycleListCreateView.as_view()),
    path("verification-cycles/<uuid:pk>/", AdminCycleDetailView.as_view()),
    path("verification-cycles/<uuid:pk>/activate/", AdminCycleActivateView.as_view()),
    path("verification-cycles/<uuid:pk>/close/", AdminCycleCloseView.as_view()),
]
