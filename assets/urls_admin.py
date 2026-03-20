from django.urls import path

from assets.views_admin import (
    AdminBusinessEntityDetailView,
    AdminBusinessEntityListCreateView,
    AdminCategoryDetailView,
    AdminCategoryListCreateView,
    AdminCostCenterDetailView,
    AdminCostCenterListCreateView,
    AdminSubTypeDetailView,
    AdminSubTypeListCreateView,
    AdminSupplierDetailView,
    AdminSupplierListCreateView,
)

urlpatterns = [
    path("lookups/categories/", AdminCategoryListCreateView.as_view()),
    path("lookups/categories/<uuid:pk>/", AdminCategoryDetailView.as_view()),
    path("lookups/subtypes/", AdminSubTypeListCreateView.as_view()),
    path("lookups/subtypes/<uuid:pk>/", AdminSubTypeDetailView.as_view()),
    path("lookups/entities/", AdminBusinessEntityListCreateView.as_view()),
    path("lookups/entities/<uuid:pk>/", AdminBusinessEntityDetailView.as_view()),
    path("lookups/cost-centers/", AdminCostCenterListCreateView.as_view()),
    path("lookups/cost-centers/<uuid:pk>/", AdminCostCenterDetailView.as_view()),
    path("lookups/suppliers/", AdminSupplierListCreateView.as_view()),
    path("lookups/suppliers/<uuid:pk>/", AdminSupplierDetailView.as_view()),
]
