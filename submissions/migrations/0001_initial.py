import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("accounts", "0001_initial"),
        ("assets", "0001_initial"),
        ("locations", "0001_initial"),
    ]

    operations = [
        # ---------------------------------------------------------------
        # FieldSubmission
        # ---------------------------------------------------------------
        migrations.CreateModel(
            name="FieldSubmission",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "submitted_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="field_submissions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "submission_type",
                    models.CharField(
                        choices=[
                            (
                                "verification_existing",
                                "Verification \u2014 Existing Asset",
                            ),
                            ("new_asset_candidate", "New Asset Candidate"),
                        ],
                        db_index=True,
                        max_length=30,
                    ),
                ),
                (
                    "asset",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="field_submissions",
                        to="assets.asset",
                    ),
                ),
                (
                    "asset_name",
                    models.CharField(blank=True, max_length=300, null=True),
                ),
                (
                    "serial_number",
                    models.CharField(blank=True, max_length=200, null=True),
                ),
                (
                    "asset_type_name",
                    models.CharField(blank=True, max_length=200, null=True),
                ),
                (
                    "location",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="field_submissions",
                        to="locations.locationnode",
                    ),
                ),
                ("location_snapshot", models.JSONField(blank=True, default=dict)),
                ("remarks", models.TextField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("approved", "Approved"),
                            ("rejected", "Rejected"),
                            ("correction_requested", "Correction Requested"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=25,
                    ),
                ),
                ("submitted_at", models.DateTimeField()),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "submissions_field_submission",
            },
        ),
        migrations.AddIndex(
            model_name="fieldsubmission",
            index=models.Index(
                fields=["submitted_by"], name="sub_fs_submitted_by_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="fieldsubmission",
            index=models.Index(
                fields=["submission_type"], name="sub_fs_sub_type_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="fieldsubmission",
            index=models.Index(fields=["status"], name="sub_fs_status_idx"),
        ),
        migrations.AddIndex(
            model_name="fieldsubmission",
            index=models.Index(
                fields=["submitted_at"], name="sub_fs_submitted_at_idx"
            ),
        ),
        # ---------------------------------------------------------------
        # FieldSubmissionPhoto
        # ---------------------------------------------------------------
        migrations.CreateModel(
            name="FieldSubmissionPhoto",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "submission",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="photos",
                        to="submissions.fieldsubmission",
                    ),
                ),
                ("image", models.ImageField(upload_to="")),
                (
                    "image_type",
                    models.CharField(
                        choices=[
                            ("asset_photo", "Asset Photo"),
                            ("supporting_photo", "Supporting Photo"),
                            ("other", "Other"),
                        ],
                        default="other",
                        max_length=20,
                    ),
                ),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "submissions_field_submission_photo",
            },
        ),
        # ---------------------------------------------------------------
        # SubmissionReview
        # ---------------------------------------------------------------
        migrations.CreateModel(
            name="SubmissionReview",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "submission",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="reviews",
                        to="submissions.fieldsubmission",
                    ),
                ),
                (
                    "reviewed_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="submission_reviews",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "decision",
                    models.CharField(
                        choices=[
                            ("approved", "Approved"),
                            ("rejected", "Rejected"),
                            ("correction_requested", "Correction Requested"),
                        ],
                        max_length=25,
                    ),
                ),
                ("review_notes", models.TextField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "submissions_submission_review",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddIndex(
            model_name="submissionreview",
            index=models.Index(
                fields=["submission"], name="sub_sr_submission_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="submissionreview",
            index=models.Index(
                fields=["reviewed_by"], name="sub_sr_reviewed_by_idx"
            ),
        ),
    ]
