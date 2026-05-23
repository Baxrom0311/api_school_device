from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0005_alter_user_avatar_alter_user_role"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="password_reset_token",
            field=models.CharField(
                blank=True,
                help_text="Token for password reset",
                max_length=100,
                null=True,
                verbose_name="Password Reset Token",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="password_reset_token_expires",
            field=models.DateTimeField(
                blank=True,
                help_text="When the password reset token expires",
                null=True,
                verbose_name="Reset Token Expires",
            ),
        ),
    ]
