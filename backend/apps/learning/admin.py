from django.contrib import admin

from .models import Term, TermTranslation, Topic, TopicTranslation


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    readonly_fields = ("status",)


admin.site.register([TopicTranslation, Term, TermTranslation])
