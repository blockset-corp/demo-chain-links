from django.urls import path


from chainlinks.web.views import service_chains_view, service_chain_view
from chainlinks.web.views import service_chain_matrix_json, service_chain_summary_json


urlpatterns = [
    path('', service_chains_view, name='service-chains'),
    path('_matrix/<int:job_id>', service_chain_matrix_json, name='service-chain-matrix-json'),
    path('_summary/<int:job_id>', service_chain_summary_json, name='service-chain-summary-json'),
    path('<str:service_id>/<str:blockchain_id>', service_chain_view, name='service-chain'),
]