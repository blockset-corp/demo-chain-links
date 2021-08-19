from django.contrib import admin

from chainlinks.models import ChainJob, ChainBlock


class ChainBlockAdmin(admin.ModelAdmin):
    list_display = ('blockchain_id', 'service_id', 'block_height', 'status', 'scheduled', 'completed')
    ordering = ('job__service_id', 'job__blockchain_id')
    list_filter = ('job__service_id', 'job__blockchain_id', 'status')

    def blockchain_id(self, obj):
        return obj.job.blockchain_id
    blockchain_id.short_description = 'Blockchain id'

    def service_id(self, obj):
        return obj.job.service_id
    service_id.short_description = 'Service id'


admin.site.register(ChainJob)
admin.site.register(ChainBlock, ChainBlockAdmin)
