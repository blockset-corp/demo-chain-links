from django.contrib import admin

from admin_numeric_filter.admin import NumericFilterModelAdmin, RangeNumericFilter
from advanced_filters.admin import AdminAdvancedFiltersMixin
from advanced_filters.forms import AdvancedFilterForm

from chainlinks.models import ChainJob, ChainBlock
from chainlinks.tasks import run_check_height


SCHEDULE_BLOCK_LIMIT = 100

# Hack until https://github.com/modlinltd/django-advanced-filters/issues/141
class MyAdvancedFilterForm(AdvancedFilterForm):
    def clean(self):
        for form in self.fields_formset:
            if not form.is_valid():
                form.cleaned_data = {'field':'id', 'DELETE': True}
        return super().clean()

# Hack until https://github.com/modlinltd/django-advanced-filters/issues/141
class MyAdminAdvancedFiltersMixin(AdminAdvancedFiltersMixin):
    advanced_filter_form = MyAdvancedFilterForm


@admin.action(description=f'Schedule selected chain blocks (max {SCHEDULE_BLOCK_LIMIT})')
def schedule_block(modeladmin, request, queryset):
    try:
        for block in queryset[:SCHEDULE_BLOCK_LIMIT]:
            job = block.job
            run_check_height.delay(job.pk, block.pk, job.blockchain_id, block.block_height, job.service_id)
        modeladmin.message_user(request, 'Scheduled blocks successfully')
    except Exception as e:
        modeladmin.message_user(request, f'Error scheduling blocks error={e}')


class ChainBlockAdmin(MyAdminAdvancedFiltersMixin, NumericFilterModelAdmin):
    list_display = ('blockchain_id', 'service_id', 'block_height', 'status', 'scheduled', 'completed')
    ordering = ('job__service_id', 'job__blockchain_id', '-block_height')
    list_filter = ('job__service_id', 'job__blockchain_id', ('block_height', RangeNumericFilter), 'status')
    advanced_filter_fields = ('block_height', 'status', 'scheduled', 'completed',)
    actions = [schedule_block]

    def blockchain_id(self, obj):
        return obj.job.blockchain_id
    blockchain_id.short_description = 'Blockchain id'

    def service_id(self, obj):
        return obj.job.service_id
    service_id.short_description = 'Service id'


admin.site.register(ChainJob)
admin.site.register(ChainBlock, ChainBlockAdmin)
