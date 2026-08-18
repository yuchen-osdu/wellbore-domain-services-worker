# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
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

from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def isolate_global_tracer_provider(monkeypatch):
    # initialize_provider() calls opentelemetry.trace.set_tracer_provider(), which mutates a
    # process-global set-once singleton. Under pytest-randomly whichever provider test runs first
    # would otherwise leak its TracerProvider into every later test that reads the global. No-op the
    # setter so each test's provider stays local to it.
    monkeypatch.setattr("opentelemetry.trace.set_tracer_provider", MagicMock())
