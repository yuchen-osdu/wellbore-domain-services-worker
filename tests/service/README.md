tests at service level i.e. test the APIs exposed by the service (~local integration tests). It's important to be as
decoupled as possible from wdmsworker module.


use custom option `--no-subprocess` to use FastAPI TestClient instead of spawning a sub process. This could ease the
debugging of the service when runing these tests.
