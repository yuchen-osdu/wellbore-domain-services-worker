# Copyright 2023 Schlumberger
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from typing import Final
from logging import INFO, DEBUG
from functools import wraps, partial
import asyncio
from time import perf_counter, process_time
from contextlib import contextmanager

from .logger import get_logger

LOG_TIMING_THRESHOLD: Final[float] = 1  # threshold for switching log level


def log_timings(tag, wall, cpu, threshold=LOG_TIMING_THRESHOLD):
    level = INFO if cpu > threshold or wall > threshold else DEBUG
    get_logger().log(level, f"Timings of {tag}, wall={wall:.5f}s, cpu={cpu:.5f}s")


default_capture_timing_handlers = [partial(log_timings)]


def capture_timings(tag, handlers=None):
    """basic timing decorator, get both wall and cpu"""

    handlers = handlers or default_capture_timing_handlers

    def decorate(target):
        if asyncio.iscoroutinefunction(target):

            @wraps(target)
            async def async_inner(*args, **kwargs):
                start_perf = perf_counter()
                start_process = process_time()
                try:
                    return await target(*args, **kwargs)
                finally:
                    perf_elapsed = perf_counter() - start_perf
                    process_elapsed = process_time() - start_process
                    for handler in handlers:
                        handler(tag=tag, wall=perf_elapsed, cpu=process_elapsed)

            return async_inner

        @wraps(target)
        def sync_inner(*args, **kwargs):
            start_perf = perf_counter()
            start_process = process_time()
            try:
                return target(*args, **kwargs)
            finally:
                perf_elapsed = perf_counter() - start_perf
                process_elapsed = process_time() - start_process
                for handler in handlers:
                    handler(tag=tag, wall=perf_elapsed, cpu=process_elapsed)

        return sync_inner

    return decorate


@contextmanager
def timeit(tag: str, threshold=LOG_TIMING_THRESHOLD):
    """
    log timings of a block. Must used with context manager:

    with timeit("operation label"):
        ...
    """
    start_perf = perf_counter()
    start_process = process_time()

    yield

    wall = perf_counter() - start_perf
    cpu = process_time() - start_process
    log_timings(tag, wall, cpu, threshold)
