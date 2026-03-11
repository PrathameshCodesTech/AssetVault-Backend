"""
Fix FieldSubmissionPhoto.image upload_to callable.

The 0001_initial migration serialized upload_to="" because the callable
was not properly referenced at migration-write time.  This AlterField
corrects the migration state so it matches the model definition.
"""
import submissions.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("submissions", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="fieldsubmissionphoto",
            name="image",
            field=models.ImageField(
                upload_to=submissions.models._submission_photo_upload_path
            ),
        ),
    ]
