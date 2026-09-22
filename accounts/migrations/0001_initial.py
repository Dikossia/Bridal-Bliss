import django.contrib.auth.models
import django.contrib.auth.validators
import django.utils.timezone
from django.db import migrations, models
import django.db.models.deletion

import accounts.managers


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='User',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('password', models.CharField(max_length=128, verbose_name='password')),
                ('last_login', models.DateTimeField(blank=True, null=True, verbose_name='last login')),
                ('is_superuser', models.BooleanField(default=False, help_text='Designates that this user has all permissions without explicitly assigning them.', verbose_name='superuser status')),
                ('email', models.EmailField(max_length=254, unique=True)),
                ('name', models.CharField(max_length=100)),
                ('phone', models.CharField(max_length=20)),
                ('status', models.CharField(choices=[('pending', 'pending'), ('active', 'active'), ('disabled', 'disabled')], default='pending', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('activated_at', models.DateTimeField(blank=True, null=True)),
                ('is_staff', models.BooleanField(default=False)),
                ('is_active', models.BooleanField(default=False)),
                ('groups', models.ManyToManyField(blank=True, help_text='The groups this user belongs to. A user will get all permissions granted to each of their groups.', related_name='user_set', related_query_name='user', to='auth.group', verbose_name='groups')),
                ('user_permissions', models.ManyToManyField(blank=True, help_text='Specific permissions for this user.', related_name='user_set', related_query_name='user', to='auth.permission', verbose_name='user permissions')),
            ],
            options={
                'db_table': 'users',
            },
            managers=[
                ('objects', accounts.managers.UserManager()),
            ],
        ),
        migrations.CreateModel(
            name='RateLimitHit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(db_index=True, max_length=200)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                'db_table': 'rate_limit_hits',
            },
        ),
        migrations.CreateModel(
            name='RefreshToken',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token_hash', models.CharField(max_length=64, unique=True)),
                ('expires_at', models.DateTimeField()),
                ('session_started_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='refresh_tokens', to='accounts.user')),
            ],
            options={
                'db_table': 'refresh_tokens',
            },
        ),
        migrations.AddIndex(
            model_name='refreshtoken',
            index=models.Index(fields=['user'], name='refresh_tok_user_id_5f1c2a_idx'),
        ),
        migrations.AddIndex(
            model_name='refreshtoken',
            index=models.Index(fields=['expires_at'], name='refresh_tok_expires_8b6f3d_idx'),
        ),
        migrations.CreateModel(
            name='PasswordSetupToken',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token_hash', models.CharField(max_length=64, unique=True)),
                ('expires_at', models.DateTimeField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('used_at', models.DateTimeField(blank=True, null=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='setup_tokens', to='accounts.user')),
            ],
            options={
                'db_table': 'password_setup_tokens',
            },
        ),
        migrations.AddIndex(
            model_name='passwordsetuptoken',
            index=models.Index(fields=['user'], name='password_se_user_id_1a2b3c_idx'),
        ),
        migrations.AddIndex(
            model_name='passwordsetuptoken',
            index=models.Index(fields=['expires_at'], name='password_se_expires_4d5e6f_idx'),
        ),
    ]
