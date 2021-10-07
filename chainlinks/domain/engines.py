import logging
from datetime import datetime, timedelta
from typing import Any, List

from django.utils import timezone
from gevent import spawn
from sentry_sdk import push_scope, capture_message

from chainlinks.common.constants import RESULT_STATUS_FAIL
from chainlinks.common.constants import GOOD_STATUS_CODES, UNKNOWN_HASH_VALUE, UNKNOWN_TXN_COUNT
from chainlinks.common.constants import SERVICE_ID_CANONICAL
from chainlinks.domain.chainsources import Block, get_chainsource
from chainlinks.models import ChainJob, ChainBlockFetch, ChainBlock
from chainlinks.models import RESULT_STATUS_PEND, RESULT_STATUS_GOOD, RESULT_STATUS_BAD



logger = logging.getLogger('chainlinks.domain.engines')


# Engines


class ChainCheckAllEngine:

    def __init__(self, check_scheduler: Any, retention_timedelta: timedelta) -> None:
        self.check_scheduler = check_scheduler
        self.retention_timedelta = retention_timedelta

    def check_all_chains(self):
        for job in ChainJob.objects.find_all_active():
            self.check_scheduler(args=(job.pk,))

    def clean_all_chains(self):
        now = timezone.now()
        ChainBlockFetch.objects.delete_superceded_fetches(now - self.retention_timedelta)


class ChainCheckEngine:

    def __init__(self, block_scheduler, requeue_timedelta: timedelta, retry_timedelta: timedelta) -> None:
        self.block_scheduler = block_scheduler
        self.requeue_timedelta = requeue_timedelta
        self.retry_timedelta = retry_timedelta

    def check_chain(self, job_pk: Any):
        now = timezone.now()
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
        inflight_blocks = ChainBlock.objects.count_pending_blocks(job_pk, start_height, final_height)
        inflight_capacity = max(0, inflight_max - inflight_blocks)
        logger.info(f'Inflight inflights={inflight_blocks}, capacity={inflight_capacity} for job_id={job_pk} and blockchain_id={blockchain_id}')

        # Find heights that have not completed and are candidates for requeueing

        expired_blocks = [x for x in ChainBlock.objects.find_all_pending_blocks(job_pk, start_height, final_height, inflight_capacity, now - self.requeue_timedelta)]
        logger.info(f'Found requeue_count={len(expired_blocks)} for job_id={job_pk} and blockchain_id={blockchain_id}')
        self._reschedule_blocks(now, job_pk, blockchain_id, service_id, 'expiry', expired_blocks)

        # Check if there is room to continue on

        inflight_capacity = max(0, inflight_capacity - len(expired_blocks))
        if inflight_capacity == 0:
            return

        # Find heights that for some reason are missing

        missing_heights = [x for x in ChainBlock.objects.find_all_gap_heights(job_pk, start_height, final_height, inflight_capacity)]
        logger.info(f'Found gap_count={len(missing_heights)} for job_id={job_pk} and blockchain_id={blockchain_id}')
        self._schedule_blocks(now, job_pk, blockchain_id, service_id, 'gap', missing_heights)

        # Check if there is room to continue on

        inflight_capacity = max(0, inflight_capacity - len(missing_heights))
        if inflight_capacity == 0:
            return

        # Find heights that were unsuccessful and should be retried

        unsuccessful_blocks = [x for x in ChainBlock.objects.find_all_unsuccessful_blocks(job_pk, start_height, final_height, inflight_capacity, now - self.retry_timedelta)]
        logger.info(f'Found retry_count={len(unsuccessful_blocks)} for job_id={job_pk} and blockchain_id={blockchain_id}')
        self._reschedule_blocks(now, job_pk, blockchain_id, service_id, 'retry', unsuccessful_blocks)

    def check_block(self, job_pk: Any, block_pk: Any, blockchain_id: str, block_height: int, service_id: str):
        canonical_chainsource = get_chainsource(SERVICE_ID_CANONICAL, blockchain_id)
        service_chainsource = get_chainsource(service_id, blockchain_id)

        # fetch block from canonical and service block (in parallel using greenlets)
        service_block_greenlet = spawn(service_chainsource.get_block, block_height)
        canonical_block_greenlet = spawn(canonical_chainsource.get_block, block_height)
        service_block = service_block_greenlet.get()
        canonical_block = canonical_block_greenlet.get()

        # compare the blocks
        status = self._compare_blocks(canonical_block, service_block)
        completed = timezone.now()

        # create a record of our fetch
        fetch = ChainBlockFetch.objects.create(
            job_id=job_pk,
            block_id = block_pk,

            canonical_http_status=canonical_block.status,
            canonical_block_hash=canonical_block.hash or UNKNOWN_HASH_VALUE,
            canonical_prev_hash=canonical_block.prev_hash or UNKNOWN_HASH_VALUE,
            canonical_txn_count=canonical_block.txn_count or UNKNOWN_TXN_COUNT,

            service_http_status=service_block.status,
            service_block_hash=service_block.hash or UNKNOWN_HASH_VALUE,
            service_prev_hash=service_block.prev_hash or UNKNOWN_HASH_VALUE,
            service_txn_count=service_block.txn_count or UNKNOWN_TXN_COUNT,
        )

        # update the block to point to our blocks as the latest fetch
        ChainBlock.objects.filter(pk=block_pk).update(
            completed=completed,
            status=status,
            fetch=fetch
        )

        # report to Sentry on failure
        if RESULT_STATUS_GOOD != status:
            self._report_error(blockchain_id, block_height, service_id, status, fetch)

        return block_pk

    def _schedule_blocks(self, now: datetime, job_pk: int, blockchain_id: str, service_id: str, reason: str, heights: List[int]):
        blocks = ChainBlock.objects.bulk_create([self._create_chain_check_block(
            now, job_pk, height
        ) for height in heights])

        for block in blocks:
            logger.info(f'Queueing height={block.block_height} for job_id={job_pk} and blockchain_id={blockchain_id} due to {reason}')
            self.block_scheduler(args=(job_pk, block.pk, blockchain_id, block.block_height, service_id))

    def _reschedule_blocks(self, now: datetime, job_pk: int, blockchain_id: str, service_id: str, reason: str, blocks: List[ChainBlock]):
        ChainBlock.objects.bulk_update([self._reset_chain_check_block(
            now, height
        ) for height in blocks], fields=('status', 'scheduled', 'completed', 'fetch'))

        for block in blocks:
            logger.info(f'Queueing height={block.block_height} for job_id={job_pk} and blockchain_id={blockchain_id} due to {reason}')
            self.block_scheduler(args=(job_pk, block.pk, blockchain_id, block.block_height, service_id))

    def _create_chain_check_block(self, now: datetime, job_pk: int, block_height: int):
        return ChainBlock(
            job_id=job_pk,
            scheduled=now,
            block_height=block_height,
            status = RESULT_STATUS_PEND,
            completed = datetime.utcfromtimestamp(0).replace(tzinfo=timezone.utc),
            fetch = None
        )

    def _reset_chain_check_block(self, now: datetime, block: ChainBlock):
        block.scheduled = now
        block.status = RESULT_STATUS_PEND
        block.completed = datetime.utcfromtimestamp(0).replace(tzinfo=timezone.utc)
        block.fetch = None
        return block

    def _compare_blocks(self, canonical_block: Block, service_block: Block):
        return RESULT_STATUS_FAIL if (
            canonical_block.status not in GOOD_STATUS_CODES
        ) else RESULT_STATUS_BAD if (
            canonical_block.status != service_block.status or
            canonical_block.hash != service_block.hash or
            canonical_block.prev_hash != service_block.prev_hash or
            canonical_block.height != service_block.height or
            canonical_block.txn_count != service_block.txn_count
        ) else RESULT_STATUS_GOOD

    def _report_error(self, blockchain_id: str, block_height: int, service_id: str, status: str, fetch: ChainBlockFetch):
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
