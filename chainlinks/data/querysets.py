from datetime import datetime
import itertools
from typing import Any, List

from django.db import connection, models

from chainlinks.common.constants import RESULT_STATUS_PEND, RESULT_STATUS_BAD, RESULT_STATUS_FAIL



class ChainJobQuerySet(models.QuerySet):

    def find_all_active(self):
        return self.filter(enabled=True)


class ChainBlockQuerySet(models.QuerySet):

    @property
    def table_name(self):
        return self.model._meta.db_table

    def find_status_counts_in_ranges(self, job_pk, start_inclusive, end_inclusive, step):
        with connection.cursor() as cursor:
            cursor.execute(f'''
                SELECT status, range_start, COUNT(range_start) AS range_count FROM(
                    SELECT status, floor(block_height / %s) * %s AS range_start FROM {self.table_name} WHERE job_id = %s AND block_height >= %s AND block_height <= %s
                ) ig GROUP BY status, range_start ORDER BY range_start;
            ''', [step, step, job_pk, start_inclusive, end_inclusive])
            for status, range_start, range_count in cursor:
                yield (status, range_start, range_count)

    def find_all_islands(self, job_pk: Any, start_inclusive: int, end_inclusive: int, status_list: List[str]):
        with connection.cursor() as cursor:
            cursor.execute(f'''
                SELECT status, MIN(block_height) AS island_start, MAX(block_height) AS island_end
                FROM (
                    SELECT status, block_height, block_height - ROW_NUMBER() OVER (PARTITION BY status ORDER BY block_height ASC) AS island_quantity
                    FROM {self.table_name}
                    WHERE job_id = %s AND block_height >= %s AND block_height <= %s AND status IN %s
                ) nh
                GROUP BY status, island_quantity ORDER BY island_start
            ''', [job_pk, start_inclusive, end_inclusive, tuple(status_list)])
            for (status, island_start, island_end) in cursor:
                yield (status, island_start, island_end)

    def find_all_gaps(self, job_pk: Any, start_inclusive: int, end_inclusive: int):
        # get the min and max block we have tracked
        min_block_height = self.find_min_block_height(job_pk, start_inclusive, end_inclusive)
        max_block_height = self.find_max_block_height(job_pk, start_inclusive, end_inclusive)

        # special case for the whole thing being a gap
        if min_block_height is None or max_block_height is None:
            yield (start_inclusive, end_inclusive)

        else:
            # iterate through leading gap
            if start_inclusive != min_block_height:
                yield (start_inclusive, min_block_height - 1)

            # iterate through trailing gap
            if end_inclusive != max_block_height:
                yield (max_block_height + 1, end_inclusive)

            # find actual gaps
            with connection.cursor() as cursor:
                cursor.execute(f'''
                    SELECT block_height + 1 AS gap_start, next_block_height - 1 AS gap_end
                    FROM (
                        SELECT block_height, LEAD(block_height) over (order by block_height asc) AS next_block_height
                        FROM {self.table_name} WHERE job_id = %s AND block_height >= %s AND block_height < %s
                    ) nh
                    WHERE block_height + 1 <> next_block_height;
                ''', [job_pk, start_inclusive, end_inclusive])
                for gap_start, gap_end in cursor:
                    yield (gap_start, gap_end)

    def find_all_gap_heights(self, job_pk: Any, start_inclusive: int, end_inclusive: int, limit: int):
        def _find_all_gap_heights():
            for gap_start, gap_end in self.find_all_gaps(job_pk, start_inclusive, end_inclusive):
                for gap_index in range(gap_start, gap_end + 1):
                    yield gap_index
        yield from itertools.islice(_find_all_gap_heights(), limit)

    def count_pending_blocks(self, job_pk: Any, start_inclusive: int, end_inclusive: int):
        return self.filter(
            job=job_pk,
            status=RESULT_STATUS_PEND,
            block_height__gte=start_inclusive,
            block_height__lte=end_inclusive,
        ).count()

    def find_all_unsuccessful_blocks(self, job_pk: Any, start_inclusive: int, end_inclusive: int, limit: int, completed_before: datetime):
        return self.filter(
            job=job_pk,
            status__in=(RESULT_STATUS_BAD, RESULT_STATUS_FAIL),
            block_height__gte=start_inclusive,
            block_height__lte=end_inclusive,
            completed__lte=completed_before,
        ).order_by('block_height')[:limit]

    def find_all_pending_blocks(self, job_pk: Any, start_inclusive: int, end_inclusive: int, limit: int, scheduled_before: datetime):
        return self.filter(
            job=job_pk,
            status=RESULT_STATUS_PEND,
            block_height__gte=start_inclusive,
            block_height__lte=end_inclusive,
            scheduled__lte=scheduled_before,
        ).order_by('block_height')[:limit]

    def find_min_block_height(self, job_pk: Any, start_inclusive: int, end_inclusive: int):
        res = self.filter(
            job=job_pk,
            block_height__gte=start_inclusive,
            block_height__lte=end_inclusive,
        ).order_by('block_height').only('block_height').first()
        return res.block_height if res else None

    def find_max_block_height(self, job_pk: Any, start_inclusive: int, end_inclusive: int):
        res = self.filter(
            job=job_pk,
            block_height__gte=start_inclusive,
            block_height__lte=end_inclusive,
        ).order_by('-block_height').only('block_height').first()
        return res.block_height if res else None
