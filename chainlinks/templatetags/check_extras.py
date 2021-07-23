from django import template

from chainlinks.common.constants import *
from chainlinks.models import ChainBlockFetch, ChainBlock


register = template.Library()


@register.filter
def result_status_message (result: ChainBlock):
    return {
        RESULT_STATUS_PEND: 'Pending',
        RESULT_STATUS_GOOD: 'Success',
        RESULT_STATUS_BAD: 'Comparison Failure',
        RESULT_STATUS_FAIL: 'Internal Failure',
    }[result.status]


@register.filter
def fetch_error_message (fetch: ChainBlockFetch):
    if fetch.canonical_http_status not in GOOD_STATUS_CODES:
        return 'Failed to get canonical block'

    if fetch.service_http_status not in GOOD_STATUS_CODES:
        return 'Failed to get service block'

    reasons = list()

    if fetch.canonical_block_hash != fetch.service_block_hash:
        reasons.append(f'hash mismatch')

    if fetch.canonical_prev_hash != fetch.service_prev_hash:
        reasons.append(f'previous hash mismatch')

    if fetch.canonical_txn_count > fetch.service_txn_count:
        reasons.append(f'too few transactions')

    if fetch.canonical_txn_count < fetch.service_txn_count:
        reasons.append(f'too many transactions')

    return 'Failed with ' + ','.join(reasons) if reasons else ''
