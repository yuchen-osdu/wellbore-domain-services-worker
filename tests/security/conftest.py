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


def pytest_addoption(parser):
    parser.addoption("--base_url", action="store")
    parser.addoption("--check_cert", action="store", default=True)
    parser.addoption("--token", action="store")


def pytest_generate_tests(metafunc):
    base_url = metafunc.config.getoption("base_url")
    verify_cert = bool(metafunc.config.getoption("check_cert"))
    token = metafunc.config.getoption("token")
    metafunc.parametrize("base_url, check_cert, token", [(base_url, verify_cert, token)])
