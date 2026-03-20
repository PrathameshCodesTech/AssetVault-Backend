from django.urls import path

from locations.views_admin import (
    AdminLocationNodeDetailView,
    AdminLocationNodeListCreateView,
    AdminLocationTypeListView,
)

urlpatterns = [
    path("location-types/", AdminLocationTypeListView.as_view()),
    path("locations/", AdminLocationNodeListCreateView.as_view()),
    path("locations/<uuid:pk>/", AdminLocationNodeDetailView.as_view()),
]
