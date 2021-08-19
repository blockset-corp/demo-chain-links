from dataclasses import dataclass
from urllib3.util.retry import Retry

import requests

from chainlinks.common.constants import GOOD_STATUS_CODES, SERVICE_ID_CANONICAL, SERVICE_ID_BLOCKSET, SERVICE_ID_INFURA
from chainlinks.common.constants import BLOCKCHAIN_ID_ETHEREUM_MAINNET, BLOCKCHAIN_ID_ETHEREUM_ROPSTEN


RETRY_STATUS_CODES = (404, 429, 500, 503, 504)

CONNECTION_POOL_COUNT=20
CONNECTION_POOL_SIZE=1000

REQUESTS_ADAPTER_OPTIONS = dict(pool_connections=CONNECTION_POOL_COUNT, pool_maxsize=CONNECTION_POOL_SIZE, max_retries=Retry(3, backoff_factor=0.1, raise_on_status=False, status_forcelist=RETRY_STATUS_CODES))
REQUESTS_TIMEOUTS = (3, 30)


@dataclass
class Chain:
    status: int
    chain_height: int


@dataclass
class Block:
    '''Block holder'''

    status: int
    hash: str
    prev_hash: str
    height: str
    txn_count: int


class Infura:
    """Infura API"""

    CHAIN_TO_URL = {
        'ethereum-mainnet': 'https://mainnet.infura.io/v3',
        'ethereum-ropsten': 'https://ropsten.infura.io/v3',
    }

    def __init__(self, project_id, blockchain_id) -> None:
        assert blockchain_id in Infura.CHAIN_TO_URL.keys()
        self.base_url = Infura.CHAIN_TO_URL[blockchain_id]
        self.project_id = project_id

        adapter = requests.adapters.HTTPAdapter(**REQUESTS_ADAPTER_OPTIONS)
        self.session = requests.session()
        self.session.mount('https://', adapter)
        self.session.mount('http://', adapter)

    def get_chain(self) -> Chain:
        resp = self.session.request('post', f'{self.base_url}/{self.project_id}', json={
            'jsonrpc': '2.0', 'id': 1, 'method': 'eth_blockNumber', 'params': []
        })
        if (resp.status_code not in GOOD_STATUS_CODES):
            return Chain(resp.status_code, None)

        body = resp.json()
        chain_height = int(body['result'], 16)
        return Chain(resp.status_code, chain_height)

    def get_block(self, block_height: str) -> Block:
        resp = self.session.request('post', f'{self.base_url}/{self.project_id}', json={
            'jsonrpc': '2.0', 'id': 1, 'method': 'eth_getBlockByNumber', 'params': [f'{hex(int(block_height))}', False]
        })
        if (resp.status_code not in GOOD_STATUS_CODES):
            return Block(resp.status_code, None, None, None, None)

        body = resp.json()
        hash = body['result'].get('hash', None)
        prev_hash = body['result'].get('parentHash', None)
        height = body['result'].get('number', None)
        height = int(height, 16) if height is not None else None
        txn_count = len(body['result'].get('transactions', []))
        return Block(resp.status_code, hash, prev_hash, height, txn_count)


class Blockset:
    '''Blockset API'''

    def __init__(self, base_url, token, blockchain_id) -> None:
        self.token = token
        self.blockchain_id = blockchain_id
        self.base_url = base_url

        adapter = requests.adapters.HTTPAdapter(**REQUESTS_ADAPTER_OPTIONS)
        self.session = requests.session()
        self.session.mount('https://', adapter)
        self.session.mount('http://', adapter)

    def get_block(self, block_height: str) -> Block:
        hdrs = {"Authorization": f"Bearer {self.token}"}
        resp = self.session.get(f'{self.base_url}/blocks/{self.blockchain_id}:{block_height}', headers=hdrs, timeout=REQUESTS_TIMEOUTS, params={'include_tx_reverted': False, 'include_tx_rejected': False})
        if (resp.status_code not in GOOD_STATUS_CODES):
            return Block(resp.status_code, None, None, None, None)

        body = resp.json()
        hash = body.get('hash', None)
        prev_hash = body.get('prev_hash', None)
        height = body.get('height', None)
        txn_count = len(body['transaction_ids']) if 'transaction_ids' in body else 0
        return Block(resp.status_code, hash, prev_hash, height, txn_count)

    def get_chain(self) -> Chain:
        hdrs = {"Authorization": f"Bearer {self.token}"}
        resp = self.session.get(f'{self.base_url}/blockchain/{self.blockchain_id}', headers=hdrs, timeout=REQUESTS_TIMEOUTS)
        if (resp.status_code not in GOOD_STATUS_CODES):
            return Chain(resp.status_code, None)

        body = resp.json()
        chain_height = body.get('block_height', None)
        return Chain(resp.status_code, chain_height)


class Canonical:
    '''Canonical API'''

    def __init__(self, base_url, token, blockchain_id) -> None:
        self.token = token
        self.blockchain_id = blockchain_id
        self.base_url = base_url

        adapter = requests.adapters.HTTPAdapter(**REQUESTS_ADAPTER_OPTIONS)
        self.session = requests.session()
        self.session.mount('https://', adapter)
        self.session.mount('http://', adapter)

    def get_block(self, block_height: str) -> Block:
        hdrs = {"Authorization": f"Bearer {self.token}"}

        resp = self.session.get(f'{self.base_url}/_coinnode/{self.blockchain_id}/heights/{block_height}', headers=hdrs, timeout=REQUESTS_TIMEOUTS)
        if (resp.status_code not in GOOD_STATUS_CODES):
            return Block(resp.status_code, None, None, None, None)

        body = resp.json()
        block_hash = body.get('blockHash', None)

        resp = self.session.get(f'{self.base_url}/_coinnode/{self.blockchain_id}/blocks/{block_hash}', headers=hdrs, params=dict(txidsonly=True), timeout=REQUESTS_TIMEOUTS)
        if (resp.status_code not in GOOD_STATUS_CODES):
            return Block(resp.status_code, None, None, None, None)

        body = resp.json()
        hash = body.get('hash', None)
        prev_hash = body.get('prevHash', None)
        height = body.get('height', None)
        txn_count = len(body['transactions']) if 'transactions' in body else 0
        return Block(resp.status_code, hash, prev_hash, height, txn_count)

    def get_chain(self) -> Chain:
        hdrs = {"Authorization": f"Bearer {self.token}"}
        resp = self.session.get(f'{self.base_url}/_coinnode/{self.blockchain_id}/blockchain/', headers=hdrs, timeout=REQUESTS_TIMEOUTS)
        if (resp.status_code not in GOOD_STATUS_CODES):
            return Chain(resp.status_code, None)

        body = resp.json()
        chain_height = body.get('num_consensus_rounds', None)
        return Chain(resp.status_code, chain_height)


_chainsources = dict()

def get_chainsource(service_id: str, blockchain_id: str):
    def _get_chainsource(service_id: str, blockchain_id: str):
        from django.conf import settings

        # re-write specific chains that aren't available via the canonical source
        service_id = {
            (SERVICE_ID_CANONICAL, BLOCKCHAIN_ID_ETHEREUM_MAINNET): SERVICE_ID_INFURA,
            (SERVICE_ID_CANONICAL, BLOCKCHAIN_ID_ETHEREUM_ROPSTEN): SERVICE_ID_INFURA,
        }.get((service_id, blockchain_id), service_id)

        if service_id == SERVICE_ID_CANONICAL:
            return Canonical(settings.CANONICAL_URL, settings.CANONICAL_TOKEN, blockchain_id)
        elif service_id == SERVICE_ID_BLOCKSET:
            return Blockset(settings.BLOCKSET_URL, settings.BLOCKSET_TOKEN, blockchain_id)
        elif service_id == SERVICE_ID_INFURA:
            return Infura(settings.INFURA_PROJECT_ID, blockchain_id)
        raise ValueError(f'unknown service_id={service_id}')

    global _chainsources
    if (service_id, blockchain_id) not in _chainsources:
        _chainsources[(service_id, blockchain_id)] = _get_chainsource(service_id, blockchain_id)
    return _chainsources[(service_id, blockchain_id)]

