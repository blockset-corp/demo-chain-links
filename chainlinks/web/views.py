import collections
import math
from itertools import groupby
from typing import Iterable

from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models.functions import Collate
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import cache_page

from chainlinks.common.constants import RESULT_STATUS_PEND, RESULT_STATUS_GOOD, RESULT_STATUS_BAD, RESULT_STATUS_FAIL
from chainlinks.common.constants import SERVICE_ID_CANONICAL
from chainlinks.domain.chainsources import get_chainsource
from chainlinks.models import ChainJob, ChainBlock


class ServiceChainView:

    def view_get(self, request, service_id, blockchain_id):
        job = ChainJob.objects.filter(service_id=service_id, blockchain_id=blockchain_id).first()
        if job is None:
            raise Http404('No %s matches the given query.' % ChainJob._meta.object_name)

        errors_paginator = Paginator(ChainBlock.objects.filter(
            job = job,
            status__in=(RESULT_STATUS_BAD, RESULT_STATUS_FAIL)
        ).select_related('fetch').order_by('-block_height'), 15)

        jobs = (job,)
        return render(
            request,
            'chainlinks.html',
            {
                'detail_view': True,
                'include_all_blocks': True,
                'errors_page': errors_paginator.get_page(request.GET.get('error_page', None))
            } | self._to_service_chains_context(jobs)
        )

    def view_get_all(self, request):
        jobs = [job for job in ChainJob.objects.find_all_visible().order_by('service_id', Collate('blockchain_id', 'C'))]
        return render(
            request,
            'chainlinks.html',
            {
                'detail_view': False,
                'include_all_blocks': 'include_all_blocks' not in request.GET or request.GET['include_all_blocks'].lower() not in ('false, no'),
            } | self._to_service_chains_context(jobs)
        )

    def _to_service_chains_context(self, jobs: Iterable[ChainJob]):
        return {
            'services': [
                {
                    'service_id': service_id,
                    'service_name': service_id.title(),
                    'chains': [
                        {
                            'job_id': service_job.pk,
                            'blockchain_id': service_job.blockchain_id,
                            'blockchain_name': service_job.blockchain_id.split('-')[0].title(),
                            'network_name': service_job.blockchain_id.split('-')[1],
                            'testnet': service_job.blockchain_id.split('-')[1].lower() not in ('mainnet',)
                        } for service_job in service_jobs
                    ]
                } for service_id, service_jobs in groupby(jobs, lambda x: x.service_id)
            ]
        }


class ServiceChainMatrixJsonView:

    CHART_ROWS_COUNT_MAX = 50
    CHART_COLUMN_COUNT = 10
    CHAIN_HEIGHT_CACHE_TIMEOUT_S = 10

    def view_get(self, request, job_id: int):
        job = get_object_or_404(ChainJob, pk=job_id)
        job_id = job.pk
        service_id = job.service_id
        blockchain_id = job.blockchain_id
        finality_depth = job.finality_depth
        start_height = job.start_height
        end_height = job.end_height

        # determine how many blocks are covered by this job (if not all blocks are requested, use the last 10%)
        final_height = self._determine_final_height(blockchain_id, end_height, finality_depth)
        if 'include_all_blocks' in request.GET and not request.GET['include_all_blocks'].lower() in ('true, yes'):
            start_height = max(start_height, math.floor(final_height * 9 / 10))
        height_delta = final_height - start_height + 1

        # compute the step per x tick
        range_cols = ServiceChainMatrixJsonView.CHART_COLUMN_COUNT
        range_step = self._compute_chainlinks_step(height_delta, range_cols)
        range_stride = range_cols * range_step

        # use 0-based coordinates; implies conversion to actual heights must be done later on
        range_start = math.floor(start_height / range_stride) * range_stride
        range_end = math.ceil(final_height / range_stride) * range_stride
        range_rows = int((range_end - range_start) / range_stride)
        range_coords = [(x, y) for y in range(range_rows) for x in range(range_cols)]

        # compute the count of blocks in each step
        range_data = collections.defaultdict(dict)
        self._initialize_range_data(range_coords, start_height, final_height, range_start, range_stride, range_step, range_data)
        self._populate_range_data(job, range_coords, start_height, final_height, range_start, range_stride, range_step, range_data)

        # prepare chartjs labels and data
        return JsonResponse({
            'job_id': job_id,
            'service_id': service_id,
            'blockchain_id': blockchain_id,
            'y_labels': [self._to_y_label(i * range_stride + range_start, range_stride) for i in reversed(range(range_rows))],
            'x_labels': [self._to_x_label(i * range_step, range_step) for i in range(range_cols)],
            'dataset': [{'x': self._to_x_label(x * range_step, range_step), 'y': self._to_y_label(y * range_stride + range_start, range_stride), 'v': v}
                        for (y, yv) in range_data.items() for (x, v) in yv.items()],
        })

    def _determine_final_height(self, blockchain_id: str, end_height: int, finality_depth: int):
        cache_key = f'ServiceChainMatrixJsonView._determine_final_height.{blockchain_id}'
        current_chain_height = cache.get_or_set(
            cache_key,
            lambda: get_chainsource(SERVICE_ID_CANONICAL, blockchain_id).get_chain().chain_height,
            ServiceChainMatrixJsonView.CHAIN_HEIGHT_CACHE_TIMEOUT_S
        )
        return min(end_height, current_chain_height - finality_depth + 1)

    def _compute_chainlinks_step(self, height_delta: int, columns: int):
        step = 1
        heights = math.ceil(height_delta / columns)
        while True:
            if (math.ceil(heights / step) < ServiceChainMatrixJsonView.CHART_ROWS_COUNT_MAX):
                return step
            step = step * 10

    def _initialize_range_data(self, range_coords, start_height, end_height, range_start, range_stride, range_step, range_data):
        status_dict = {f'status_{RESULT_STATUS_PEND}': 0, f'status_{RESULT_STATUS_GOOD}': 0, f'status_{RESULT_STATUS_BAD}': 0, f'status_{RESULT_STATUS_FAIL}': 0}
        for x, y in range_coords:
            start = max(start_height, range_start + (y * range_stride) + (x * range_step))
            end = min(end_height, range_start + (y * range_stride) + (x * range_step) + range_step - 1)
            if end >= start:
                range_data[y][x] = {'total': end - start + 1 , 'start': start, 'end': end} | status_dict
            else:
                range_data[y][x] = {'total': 0, 'start': 0, 'end': 0} | status_dict

    def _populate_range_data(self, job, range_coords, start_height, end_height, range_start, range_stride, range_step, range_data):
        if ChainBlock.objects.has_holes(job.pk, start_height, end_height):
            self._populate_with_status_ranges(job, range_coords, start_height, end_height, range_start, range_stride, range_step, range_data)
        else:
            self._populate_with_status_islands(job, range_coords, start_height, end_height, range_start, range_stride, range_step, range_data)

    def _populate_with_status_ranges(self, job, range_coords, start_height, end_height, range_start, range_stride, range_step, range_data):
        status_ranges = ChainBlock.objects.find_status_counts_in_ranges(job.pk, start_height, end_height, range_step)
        for status, height, count in status_ranges:
            y = math.floor((height - range_start) / range_stride)
            x = math.floor((height - range_start) % range_stride / range_step)
            range_data[y][x][f'status_{status}'] += count

        for x, y in range_coords:
            total = range_data[y][x]['total']
            pend = range_data[y][x][f'status_{RESULT_STATUS_PEND}']
            good = range_data[y][x][f'status_{RESULT_STATUS_GOOD}']
            bad = range_data[y][x][f'status_{RESULT_STATUS_BAD}']
            fail = range_data[y][x][f'status_{RESULT_STATUS_FAIL}']
            range_data[y][x]['missing'] = total - (pend + good + bad + fail)

    def _populate_with_status_islands(self, job, range_coords, start_height, end_height, range_start, range_stride, range_step, range_data):
        islands = ChainBlock.objects.find_all_islands(job.pk, start_height, end_height, [RESULT_STATUS_PEND, RESULT_STATUS_BAD, RESULT_STATUS_FAIL])
        for status, island_start, island_end in islands:
            for height in range(island_start, island_end + 1, range_step):
                height = math.floor(height  / range_step) * range_step
                count = min(height + range_step, island_end) - max(height, island_start) + 1
                y = math.floor((height - range_start) / range_stride)
                x = math.floor((height - range_start) % range_stride / range_step)
                range_data[y][x][f'status_{status}'] += count

        for x, y in range_coords:
            total = range_data[y][x]['total']
            pend = range_data[y][x][f'status_{RESULT_STATUS_PEND}']
            bad = range_data[y][x][f'status_{RESULT_STATUS_BAD}']
            fail = range_data[y][x][f'status_{RESULT_STATUS_FAIL}']
            range_data[y][x][f'status_{RESULT_STATUS_GOOD}'] = total - (pend + bad + fail)

    def _to_x_label(self, value, step):
        return f'+{value:,} to {(value + step - 1):,}'

    def _to_y_label(self, value, step):
        return f'{value:,} to {(value + step - 1):,}'


class ServiceChainSummaryJsonView:

    def view_get(self, request, job_id: int):
        job = get_object_or_404(ChainJob, pk=job_id)
        return JsonResponse({
            'bad_ranges': [
                {
                    'blockchain_id': job.blockchain_id,
                    'block_start': result_start,
                    'block_end': result_end,
                } for _, result_start, result_end in ChainBlock.objects.find_all_islands(
                    job.id, job.start_height, job.end_height, [RESULT_STATUS_BAD]
                )
            ],
            'fail_ranges': [
                {
                    'blockchain_id': job.blockchain_id,
                    'block_start': result_start,
                    'block_end': result_end,
                } for _, result_start, result_end in ChainBlock.objects.find_all_islands(
                    job.id, job.start_height, job.end_height, [RESULT_STATUS_FAIL]
                )
            ]
        })


@cache_page(15)
def service_chain_view(request, service_id, blockchain_id):
    return ServiceChainView().view_get(request, service_id, blockchain_id)


@cache_page(15)
def service_chains_view(request):
    return ServiceChainView().view_get_all(request)


def service_chain_matrix_json(request, job_id: int):
    return ServiceChainMatrixJsonView().view_get(request, job_id)


def service_chain_summary_json(request, job_id: int):
    return ServiceChainSummaryJsonView().view_get(request, job_id)
