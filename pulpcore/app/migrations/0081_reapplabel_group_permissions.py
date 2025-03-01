# Generated by Django 3.2.9 on 2021-12-08 11:33

from django.conf import settings
from django.db import migrations


def reapplabel_group_permissions_up(apps, schema_editor, up=True):
    User = apps.get_model(settings.AUTH_USER_MODEL)

    PERMISSION_CLASSES = [
        (User.user_permissions.through._meta.app_label, User.user_permissions.through._meta.model_name),
        ("auth", "Group_permissions"),
        ("guardian", "UserObjectPermission"),
        ("guardian", "GroupObjectPermission"),
    ]

    PERMISSION_NAMES = ["add", "change", "delete", "view"]

    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    AuthGroup = apps.get_model("auth", "Group")
    CoreGroup = apps.get_model("core", "Group")
    auth_ctype = ContentType.objects.get_for_model(AuthGroup, for_concrete_model=False)
    core_ctype = ContentType.objects.get_for_model(CoreGroup, for_concrete_model=False)

    perm_classes = [apps.get_model(class_app, class_name) for class_app, class_name in PERMISSION_CLASSES]

    for perm_name in PERMISSION_NAMES:
        auth_perm, _ = Permission.objects.get_or_create(content_type=auth_ctype, codename=f"{perm_name}_group", defaults={"name": f"Can {perm_name} group"})
        core_perm, _ = Permission.objects.get_or_create(content_type=core_ctype, codename=f"{perm_name}_group", defaults={"name": f"Can {perm_name} group"})
        for perm_class in perm_classes:
            if up:
                perm_class.objects.filter(permission=auth_perm).update(permission=core_perm)
            else:
                perm_class.objects.filter(permission=core_perm).update(permission=auth_perm)


def reapplabel_group_permissions_down(apps, schema_editor):
    reapplabel_group_permissions_up(apps, schema_editor, up=False)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0080_proxy_group_model'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
        ('guardian', '0002_generic_permissions_index'),
    ]

    operations = [
        migrations.RunPython(reapplabel_group_permissions_up, reverse_code=reapplabel_group_permissions_down),
    ]
