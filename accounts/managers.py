from django.contrib.auth.base_user import BaseUserManager


class UserManager(BaseUserManager):
    """
    Менеджер пользователя «Учёт». USERNAME_FIELD = email (регистр не важен —
    email всегда нормализуется в нижний регистр, аналог CITEXT из schema.sql).
    """
    use_in_migrations = True

    def _create_user(self, email, name, phone, password=None, **extra_fields):
        if not email:
            raise ValueError('Email обязателен')
        email = self.normalize_email(email).strip().lower()
        user = self.model(email=email, name=name, phone=phone, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, email, name='', phone='', password=None, **extra_fields):
        extra_fields.setdefault('status', 'pending')
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        return self._create_user(email, name, phone, password, **extra_fields)

    def create_superuser(self, email, name='', phone='', password=None, **extra_fields):
        extra_fields.setdefault('status', 'active')
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        if extra_fields.get('status') != 'active':
            raise ValueError('Суперпользователь должен иметь status=active')
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Суперпользователь должен иметь is_staff=True')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Суперпользователь должен иметь is_superuser=True')
        from django.utils import timezone
        user = self._create_user(email, name, phone, password, **extra_fields)
        user.activated_at = timezone.now()
        user.save(using=self._db)
        return user
