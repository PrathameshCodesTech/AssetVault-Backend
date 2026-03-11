"""
Fix AssetImage.image upload_to callable.

The 0001_initial migration serialized upload_to="" because the callable
was not properly referenced at migration-write time.  This AlterField
corrects the migration state so it matches the model definition.
"""
import assets.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="assetimage",
            name="image",
            field=models.ImageField(upload_to=assets.models.asset_image_upload_path),
        ),
    ]
