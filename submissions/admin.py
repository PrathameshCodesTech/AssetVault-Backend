from django.contrib import admin

from .models import FieldSubmission, FieldSubmissionPhoto, SubmissionReview

admin.site.register(FieldSubmission)
admin.site.register(FieldSubmissionPhoto)
admin.site.register(SubmissionReview)
