./ssl.sh;

if [ ${APPLICATION_PORT} -ne 443 ]
then
    uvicorn wdmsworker.app:base --host 0.0.0.0 --port ${APPLICATION_PORT}
else
    uvicorn wdmsworker.app:base --host 0.0.0.0 --port ${APPLICATION_PORT} --ssl-certfile ${SSL_CERT_PATH} --ssl-keyfile ${SSL_KEY_PATH}
fi