from django.contrib import admin

from chainlinks.models import ChainJob


admin.site.register((ChainJob,))
