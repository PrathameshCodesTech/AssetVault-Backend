from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("verification", "0004_employeeassetreport_verificationrequest_review_notes_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="assetverificationresponse",
            name="admin_review_status",
            field=models.CharField(
                choices=[
                    ("pending_review", "Pending Review"),
                    ("approved", "Approved"),
                    ("correction_required", "Correction Required"),
                ],
                default="pending_review",
                db_index=True,
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="assetverificationresponse",
            name="admin_review_note",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="assetverificationresponse",
            name="admin_reviewed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="assetverificationresponse",
            name="admin_reviewed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="reviewed_asset_responses",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
