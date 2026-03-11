from django.urls import path

from submissions.views import (
    AdminSubmissionApproveView,
    AdminSubmissionCorrectionView,
    AdminSubmissionConvertView,
    AdminSubmissionDetailView,
    AdminSubmissionListView,
    AdminSubmissionRejectView,
    AdminSubmissionReviewView,
    SubmissionDetailView,
    SubmissionListCreateView,
)

app_name = "submissions"

urlpatterns = [
    path("", SubmissionListCreateView.as_view(), name="list-create"),
    path("<uuid:pk>/", SubmissionDetailView.as_view(), name="detail"),
    path("admin/", AdminSubmissionListView.as_view(), name="admin-list"),
    path("<uuid:pk>/review/", AdminSubmissionReviewView.as_view(), name="admin-review"),
    path("admin/<uuid:pk>/", AdminSubmissionDetailView.as_view(), name="admin-detail"),
    path("admin/<uuid:pk>/approve/", AdminSubmissionApproveView.as_view(), name="admin-approve"),
    path("admin/<uuid:pk>/reject/", AdminSubmissionRejectView.as_view(), name="admin-reject"),
    path("admin/<uuid:pk>/correction/", AdminSubmissionCorrectionView.as_view(), name="admin-correction"),
    path("admin/<uuid:pk>/convert-to-asset/", AdminSubmissionConvertView.as_view(), name="admin-convert"),
]
