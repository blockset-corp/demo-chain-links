import logging
from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone
from sentry_sdk import push_scope, capture_message

from chainlinks.common.constants import CHAIN_CHECK_EXPIRY, RESULT_STATUS_FAIL
from chainlinks.common.constants import GOOD_STATUS_CODES, UNKNOWN_HASH_VALUE, UNKNOWN_TXN_COUNT
from chainlinks.common.constants import SERVICE_ID_CANONICAL
from chainlinks.domain.chainsources import Block, get_chainsource
from chainlinks.models import ChainJob, ChainBlockFetch, ChainBlock
from chainlinks.models import RESULT_STATUS_PEND, RESULT_STATUS_GOOD, RESULT_STATUS_BAD



logger = logging.getLogger('chainlinks.domain.engines')


# Engines


class ChainCheckAllEngine:

    def __init__(self, check_scheduler: Any) -> None:
        self.check_scheduler = check_scheduler

    def check_all_chains(self):
        for job in ChainJob.objects.find_all_active():
            self.check_scheduler(args=(job.pk,))


class ChainCheckEngine:

    def __init__(self, block_scheduler, requeue_timedelta: timedelta = CHAIN_CHECK_EXPIRY) -> None:
        self.block_scheduler = block_scheduler
        self.requeue_timedelta = requeue_timedelta

    def check_chain(self, job_pk: Any):
        job = ChainJob.objects.get(pk=job_pk)

        # Get the job details
        blockchain_id = job.blockchain_id
        finality_depth = job.finality_depth
        start_height = job.start_height
        end_height = job.end_height
        inflight_max = job.inflight_max
        service_id = job.service_id

        logger.info(
            f"Running with finality_depth={finality_depth}, start_height={start_height}, end_height={end_height}, and inflight_max={inflight_max} " +
            f"for job_id={job_pk} and blockchain_id={blockchain_id}")

        # Get the current state of the chain
        current_chain = get_chainsource(SERVICE_ID_CANONICAL, blockchain_id).get_chain()
        final_height = current_chain.chain_height - finality_depth + 1

        logger.info(
            f"State is final_height={final_height} " +
            f"for job_id={job_pk} and blockchain_id={blockchain_id}")

        # Get the current inflight requests
        inflight_blocks = ChainBlock.objects.find_all_inflight_blocks(job_pk, start_height, final_height, inflight_max)
        inflight_capacity = max(0, inflight_max - len(inflight_blocks))
        logger.info(f'Inflight inflights={len(inflight_blocks)}, capacity={inflight_capacity} for job_id={job_pk} and blockchain_id={blockchain_id}')

        # Find heights that have not completed and are candidates for requeueing

        requeue_results = [x for x in inflight_blocks if (x.scheduled + self.requeue_timedelta) < timezone.now()][:inflight_max]
        logger.info(f'Found req_count={len(requeue_results)} for job_id={job_pk} and blockchain_id={blockchain_id}')

        ChainBlock.objects.bulk_update([self.reset_chain_check_block_result(
            result
        ) for result in requeue_results], fields=('status', 'scheduled', 'completed', 'fetch'))

        for result in requeue_results:
            logger.info(f'Queueing height={result.block_height} for job_id={job_pk} and blockchain_id={blockchain_id} due to expiry')
            self.block_scheduler(args=(job.pk, result.pk, blockchain_id, result.block_height, service_id))

        # Check if there is room to continue on
        inflight_capacity = max(0, inflight_capacity - len(requeue_results))
        if inflight_capacity == 0:
            return

        # Find heights that for some reason are missing

        missing_heights = [x for x in ChainBlock.objects.find_all_gap_heights(job_pk, start_height, final_height, inflight_capacity)]
        logger.info(f'Found gap_count={len(missing_heights)} for job_id={job_pk} and blockchain_id={blockchain_id}')

        missing_results = ChainBlock.objects.bulk_create([self.create_chain_check_block_result(
                job, height
        ) for height in missing_heights])

        for result in missing_results:
            logger.info(f'Queueing height={result.block_height} for job_id={job_pk} and blockchain_id={blockchain_id} due to gap')
            self.block_scheduler(args=(job.pk, result.pk, blockchain_id, result.block_height, service_id))

    def check_block(self, job_pk: Any, result_pk: Any, blockchain_id: str, block_height: int, service_id: str):
        canonical_chainsource = get_chainsource(SERVICE_ID_CANONICAL, blockchain_id)
        service_chainsource = get_chainsource(service_id, blockchain_id)

        # fetch block from canonical and service block and compare
        service_block = service_chainsource.get_block(block_height)
        canonical_block = canonical_chainsource.get_block(block_height)
        status = self.compare_blocks(canonical_block, service_block)
        completed = timezone.now()

        # create a record of our fetch
        fetch = ChainBlockFetch.objects.create(
            job_id=job_pk,
            block_id = result_pk,

            canonical_http_status=canonical_block.status,
            canonical_block_hash=canonical_block.hash or UNKNOWN_HASH_VALUE,
            canonical_prev_hash=canonical_block.prev_hash or UNKNOWN_HASH_VALUE,
            canonical_txn_count=canonical_block.txn_count or UNKNOWN_TXN_COUNT,

            service_http_status=service_block.status,
            service_block_hash=service_block.hash or UNKNOWN_HASH_VALUE,
            service_prev_hash=service_block.prev_hash or UNKNOWN_HASH_VALUE,
            service_txn_count=service_block.txn_count or UNKNOWN_TXN_COUNT,
        )

        # update the block to point to our result as the latest fetch
        ChainBlock.objects.filter(pk=result_pk).update(
            completed=completed,
            status=status,
            fetch=fetch
        )

        # report to Sentry on failure
        if RESULT_STATUS_GOOD != status:
            self.report_error(blockchain_id, block_height, service_id, status, fetch)

        return result_pk

    def create_chain_check_block_result(self, job: int, block_height: int):
        return ChainBlock(
            job=job,
            scheduled=timezone.now(),
            block_height=block_height,
            status = RESULT_STATUS_PEND,
            completed = datetime.utcfromtimestamp(0).replace(tzinfo=timezone.utc),
            fetch = None
        )

    def reset_chain_check_block_result(self, result: ChainBlock):
        result.scheduled = timezone.now()
        result.status = RESULT_STATUS_PEND
        result.completed = datetime.utcfromtimestamp(0).replace(tzinfo=timezone.utc)
        result.fetch = None
        return result

    def compare_blocks(self, canonical_block: Block, service_block: Block):
        return RESULT_STATUS_FAIL if (
            canonical_block.status not in GOOD_STATUS_CODES
        ) else RESULT_STATUS_BAD if (
            canonical_block.status != service_block.status or
            canonical_block.hash != service_block.hash or
            canonical_block.prev_hash != service_block.prev_hash or
            canonical_block.height != service_block.height or
            canonical_block.txn_count != service_block.txn_count
        ) else RESULT_STATUS_GOOD

    def report_error(self, blockchain_id: str, block_height: int, service_id: str, status: str, fetch: ChainBlockFetch):
        with push_scope() as sentry_scope:
            sentry_scope.set_tag('job_id', fetch.job_id)
            sentry_scope.set_tag('block_id', fetch.block_id)
            sentry_scope.set_tag('block_outcome', status)
            sentry_scope.set_tag('service_id', service_id)
            sentry_scope.set_tag('blockchain_id', blockchain_id)
            sentry_scope.set_context('block_info', {
                'block_height': block_height,
            })
            sentry_scope.set_context('canonical_block', {
                'http_status': fetch.canonical_http_status,
                'block_hash': fetch.canonical_block_hash,
                'prev_hash': fetch.canonical_prev_hash,
                'txn_count': fetch.canonical_txn_count,
            })
            sentry_scope.set_context('service_block', {
                'http_status': fetch.service_http_status,
                'block_hash': fetch.service_block_hash,
                'prev_hash': fetch.service_prev_hash,
                'txn_count': fetch.service_txn_count,
            })
            capture_message(f'Block error for {blockchain_id} at {block_height} for {service_id}: {fetch.error_message}', level='error')
