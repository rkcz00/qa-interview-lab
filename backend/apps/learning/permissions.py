from django.apps import apps as global_apps
from django.contrib.auth.management import create_permissions
from django.db import router, transaction
from django.db.models import Q


CONTENT_ADMIN_GROUP = "Content Admin"
CONTENT_MODELS = {
    "learning": ("topic", "topictranslation", "term", "termtranslation"),
    "assessments": ("question", "questiontranslation", "choice", "choicetranslation"),
}


def sync_content_admin(sender, *, using, apps=global_apps, **kwargs):
    try:
        group_model = apps.get_model("auth", "Group")
        permission_model = apps.get_model("auth", "Permission")
        for app_label, models in CONTENT_MODELS.items():
            for model in models:
                apps.get_model(app_label, model)
    except LookupError:
        return  # The migration target may precede the content tables.

    if not all(router.allow_migrate_model(using, model) for model in (group_model, permission_model)):
        return

    allowed = Q()
    for app_label, models in CONTENT_MODELS.items():
        create_permissions(global_apps.get_app_config(app_label), apps=apps, using=using, verbosity=0)
        for model in models:
            allowed |= Q(
                content_type__app_label=app_label,
                content_type__model=model,
                codename__in=[f"{action}_{model}" for action in ("view", "add", "change", "delete")],
            )

    with transaction.atomic(using=using):
        group, _ = group_model.objects.using(using).get_or_create(name=CONTENT_ADMIN_GROUP)
        group.permissions.set(permission_model.objects.using(using).filter(allowed))
