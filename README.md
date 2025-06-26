# Introduction

Open Subsurface Data Universe (OSDU) Wellbore-DDMS Worker is a python backend service used internally by the [OSDU Wellbore DDMS](https://community.opengroup.org/osdu/platform/domain-data-mgmt-services/wellbore/wellbore-domain-services).
It is a single, containerized service written in Python that provides an internal API for accessing wellbore bulk data.

# Install & run

### Pre-requisites
Set `PIP_EXTRA_INDEX_URL` environment variable to add extra url and feed from OSDU gitlab:
> export PIP_EXTRA_INDEX_URL="https://community.opengroup.org/api/v4/projects/465/packages/pypi/simple https://community.opengroup.org/api/v4/projects/148/packages/pypi/simple"

Alternatively set it in `pip.conf` or `pip.ini`.

### Local installation

Install local in [“editable” mode](https://pip.pypa.io/en/stable/cli/pip_install/#cmdoption-e) (The files in the development directory are added to Python’s import path)
> pip install -e .

### Run it

Run service locally with auto reload:  
> uvicorn wdmsworker.app:app --port 8080 --reload

# Test & contribute

Install dependencies:
* `[test]` for running tests only:
> pip install -e ".[test]"

* `[dev]` for contribution, it will install required dependencies, `[test]` ones and few others like `black`
and `flake8`, so only the following is needed:
> pip install -e ".[dev]"

Update dependencies:

> pip install -U -e ".[dev]"


## Cloud provider code specific

### Code
Each provider needs to add its own implementation of:
- blob storage
- tenant resolution function from data partition id
- _(optional)_  logging message export and any other specific initialization.

Dedicated cloud provider code can be put under folder [wdmsworker/provider](./src/wdmsworker/provider).  
The code hook is done at the startup event of the FastAPI app and the switch is done inside function 
[`initialize_provider`](./src/wdmsworker/provider/__init__.py) based on the value of the environment variable
`CLOUD_PROVIDER`.  

see [implementation for Azure](./src/wdmsworker/provider/azure/__init__.py).

### Dependencies
Provider specific dependencies are expected to be listed as optional inside [pyproject.toml (line 59)](./pyproject.toml).  
Installation for a specific provider is then done this way:

````
pip install .[provider]
````

specifying extra index url directly in pip install command:

````
pip install .[provider] --extra-index-url https://community.opengroup.org/api/v4/projects/465/packages/pypi/simple
````

## Run tests


### Unit tests

> pytest ./tests/unit

### Service tests
Service tests are testing the service edge, meaning the rest APIs. There are two mode.  
* Service run locally as in its own process _(default)_. This mode provides loose coupling testing.
* Service embedded in test process using FastAPI/Starlette [TestClient](https://fastapi.tiangolo.com/tutorial/testing/#testing).
This mode allows to debug the service while running the tests.

The mode can be changed using command line flag `--no-subprocess`:

#### Default mode
_service in dedicated process_
> pytest ./tests/service

#### Embedded mode:
_service run inside test process using `TestClient`_
> pytest --no-subprocess ./tests/service


### Security tests
These security tests ensure the wdms-worker service is not reachable from outside world and only by WDMS.   

Indeed, wdms-workers APIs require authentication with a Bearer token. However, records ACL are **verified ONLY at WDMS level**. That is why, incoming requests are restricted they can come from only from WDMS.  

See dedicated readme file [here](tests/security/readme.md).


## Code cleaning

It requires `dev` dependencies.

### PEP8 formatter

see [Black](https://black.readthedocs.io/en/stable/) documentation for more details. To format code, run command:
> black .

### Static type checking

see [mypy](https://mypy.readthedocs.io/en/stable/) documentation for more details. To check static typing, run command:
> mypy ./src

_Note: [ignore_missing_imports](https://mypy.readthedocs.io/en/stable/config_file.html#confval-ignore_missing_imports)
mypy configuration parameter is set to `True`._

### Additional code checks using flake8

see [flake8](https://flake8.pycqa.org/en/latest/) documentation for more details. run command:
> flake8 ./src

### Automate above tools with Git pre-commit hook
This setup needs to be done once.
> pre-commit install

It will setup git hook (`.git/hooks/pre-commit`) to use *.precommit-config.yaml* file.  
If needed, for example after *.precommit-config.yaml* modifications run
> pre-commit autoupdate  

## Packaging
In order to build `wdms-bulk-worker` as a package `setuptools`, `wheel`, `build` are needed. Either install then manually or
run the command:
> pip install -e ".[pkg]"

Create a package:
> python -m build


# Docker image
## Build image
> tag=0.0.1  
> docker build -t wdms-worker:$tag --rm . -f ./deployment/wdms-worker.DockerFile

## Run local & expose port
> mylocaldir=/home/user  
>docker run -p 8080:8080 -e USE_LOCALFS_BLOB_STORAGE_WITH_PATH=$mylocaldir wdms-worker:$tag
