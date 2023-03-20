## Authorization tests

Run integration tests for authorization which checks for common misconfigurations for Istio misconfiguration:

- service visibility outside cluster

## Setup Pre-Requisities

```bash
pip install -e ".[test]"
```

## Run Security Tests Locally

### Run Tests

Run the python script with arguments: 

```bash
# set options 
export base_url="<appurl>"
export check_cert="<boolean to skip the cert validation>"
export token="<valid token>"

# navigate to the security integration tests directory
cd tests/security

# run the tests
pytest test_authorization.py --base_url $base_url --check_cert $check_cert --token $token
```