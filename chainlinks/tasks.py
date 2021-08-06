from typing import Any

from celery import shared_task, signature
from celery.utils.log import get_task_logger
from celery_singleton import Singleton

from chainlinks.common.constants import CHAIN_CHECK_EXPIRY
from chainlinks.domain.engines import ChainCheckAllEngine, ChainCheckEngine


logger = get_task_logger('app.tasks')
check_all_engine = ChainCheckAllEngine(signature('chainlinks.tasks.run_check_job').apply_async)
check_single_engine = ChainCheckEngine(signature('chainlinks.tasks.run_check_height').apply_async)


# Tasks


CHAIN_CHECK_ALL_EXPIRY=60


@shared_task(base=Singleton, ignore_result=True, expiry=CHAIN_CHECK_ALL_EXPIRY, lock_expiry=CHAIN_CHECK_ALL_EXPIRY)
def run_all_check_jobs():
    check_all_engine.check_all_chains()


@shared_task(base=Singleton, ignore_result=True, expiry=CHAIN_CHECK_EXPIRY, lock_expiry=CHAIN_CHECK_EXPIRY)
def run_check_job(job_pk: Any):
    check_single_engine.check_chain(job_pk)


@shared_task(queue='consumer', ignore_result=True, expiry=CHAIN_CHECK_EXPIRY)
def run_check_height(job_pk: Any, result_pk: Any, blockchain_id: str, block_height: int, service_id: str):
    check_single_engine.check_block(job_pk, result_pk, blockchain_id, block_height, service_id)
