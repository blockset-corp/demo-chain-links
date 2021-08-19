import sys
from datetime import datetime

from django.db import models
from django.core.validators import MinValueValidator
from django.utils import timezone

from chainlinks.common.constants import *
from chainlinks.data.querysets import ChainJobQuerySet, ChainBlockQuerySet


MAX_LEN_SERVICE_ID = 32
MAX_LEN_BLOCKCHAIN_ID = 32
MAX_LEN_BLOCK_HASH = 1024


BLOCKCHAIN_IDS = (
    (BLOCKCHAIN_ID_BITCOIN_MAINNET, 'Bitcoin Mainnet'),
    (BLOCKCHAIN_ID_BITCOIN_TESTNET, 'Bitcoin Testnet'),
    (BLOCKCHAIN_ID_BITCOINCASH_MAINNET, 'Bitcoin Cash Mainnet'),
    (BLOCKCHAIN_ID_BITCOINCASH_TESTNET, 'Bitcoin Cash Testnet'),
    (BLOCKCHAIN_ID_BITCOINSV_MAINNET, 'Bitcoin SV Mainnet'),
    (BLOCKCHAIN_ID_DOGECOIN_MAINNET, 'Dogecon Mainnet'),
    (BLOCKCHAIN_ID_LITECOIN_MAINNET, 'Litecoin Mainnet'),
    (BLOCKCHAIN_ID_HEDERA_MAINNET, 'Hedera Mainnet'),
    (BLOCKCHAIN_ID_RIPPLE_MAINNET, 'Ripple Mainnet'),
    (BLOCKCHAIN_ID_TEZOS_MAINNET, 'Tezos Mainnet'),
    (BLOCKCHAIN_ID_ETHEREUM_MAINNET, 'Ethereum Mainnet'),
    (BLOCKCHAIN_ID_ETHEREUM_ROPSTEN, 'Ethereum Testnet'),
)


SERVICE_IDS = (
    (SERVICE_ID_BLOCKSET, 'Blockset'),
    (SERVICE_ID_INFURA, 'Infura'),
)


RESULT_STATUSES = (
    (RESULT_STATUS_PEND, 'Pending'),
    (RESULT_STATUS_GOOD, 'Good'),
    (RESULT_STATUS_BAD, 'Bad'),
    (RESULT_STATUS_FAIL, 'Failure'),
)


class ChainJob(models.Model):
    name = models.CharField(max_length=64)

    # metadata
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    # job parameters
    enabled = models.BooleanField()
    service_id = models.CharField(max_length=MAX_LEN_SERVICE_ID, choices=SERVICE_IDS)
    blockchain_id = models.CharField(choices=BLOCKCHAIN_IDS, max_length=MAX_LEN_BLOCKCHAIN_ID)

    start_height = models.BigIntegerField(validators=[MinValueValidator(0)])
    end_height = models.BigIntegerField(validators=[MinValueValidator(0)], default=sys.maxsize)
    inflight_max = models.IntegerField(validators=[MinValueValidator(1)])
    finality_depth = models.IntegerField(validators=[MinValueValidator(1)])

    objects = ChainJobQuerySet.as_manager()

    def __str__(self):
        return self.name


class ChainBlock(models.Model):
    job = models.ForeignKey(ChainJob, on_delete=models.CASCADE)

    # metadata
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    # immutable; set when block is detected in the chain
    scheduled = models.DateTimeField()
    block_height = models.BigIntegerField()

    # mutable; set once a fetch has been performed
    completed = models.DateTimeField(default=datetime.utcfromtimestamp(0).replace(tzinfo=timezone.utc))
    status = models.CharField(max_length=2, choices=RESULT_STATUSES)
    fetch = models.ForeignKey('ChainBlockFetch', null=True, on_delete=models.SET_NULL)

    objects = ChainBlockQuerySet.as_manager()

    class Meta:
        unique_together = [
            ('job', 'block_height')
        ]
        indexes = [
            models.Index(fields=('status',), name='cb_status'),
            models.Index(fields=('-block_height',), name='cb_block_height'),
        ]

    def status_message(self):
        return {
            RESULT_STATUS_PEND: 'Pending',
            RESULT_STATUS_GOOD: 'Success',
            RESULT_STATUS_BAD: 'Comparison Failure',
            RESULT_STATUS_FAIL: 'Internal Failure',
        }[self.status]

    def __str__(self):
        return f'{self.job} - {self.block_height}'


class ChainBlockFetch(models.Model):
    job = models.ForeignKey(ChainJob, on_delete=models.CASCADE)

    # metadata
    created = models.DateTimeField(auto_now_add=True)

    # target block
    block = models.ForeignKey(ChainBlock, null=True, on_delete=models.CASCADE)

    # canonical service fetch details
    canonical_http_status = models.IntegerField()
    canonical_block_hash = models.CharField(max_length=MAX_LEN_BLOCK_HASH)
    canonical_prev_hash = models.CharField(max_length=MAX_LEN_BLOCK_HASH)
    canonical_txn_count = models.IntegerField()

    # target service fetch details
    service_http_status = models.IntegerField()
    service_block_hash = models.CharField(max_length=MAX_LEN_BLOCK_HASH)
    service_prev_hash = models.CharField(max_length=MAX_LEN_BLOCK_HASH)
    service_txn_count = models.IntegerField()

    @property
    def error_message(self):
        if self.canonical_http_status not in GOOD_STATUS_CODES:
            return f'canonical block retrieval failure ({self.canonical_http_status})'

        if self.service_http_status not in GOOD_STATUS_CODES:
            return f'service block retrieval failure ({self.service_http_status})'

        reasons = list()

        if self.canonical_block_hash != self.service_block_hash:
            reasons.append(f'block hash mismatch ({self.service_block_hash})')

        if self.canonical_prev_hash != self.service_prev_hash:
            reasons.append(f'previous hash mismatch ({self.service_prev_hash})')

        if self.canonical_txn_count != self.service_txn_count:
            reasons.append(f'transaction count mismatch ({self.service_txn_count} vs {self.canonical_txn_count})')

        return ', '.join(reasons) if reasons else ''


    def __str__(self):
        return f'{self.block}'
