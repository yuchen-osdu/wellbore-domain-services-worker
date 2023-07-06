#!/usr/bin/env bash

#Future: Support for using Amazon Cert Manager
# if [ "$1" == "webserver" ] && [ -n $ACM_CERTIFICATE_ARN ];
# then

#   if [ -z $SSL_CERT_PATH ] || [ -z $SSL_KEY_PATH ];
#   then
#     echo "SSL_CERT_PATH and SSL_KEY_PATH must be set as environment variables when using ACM_CERTIFICATE_ARN"
#     exit 1
#   fi

#   aws acm export-certificate --certificate-arn $ACM_CERTIFICATE_ARN --passphrase $(echo -n 'aws123' | openssl base64 -e) | jq -r '"\(.PrivateKey)"' > ${SSL_KEY_PATH}.enc
#   openssl rsa -in ${SSL_KEY_PATH}.enc -out $SSL_KEY_PATH -passin pass:aws123
#   aws acm get-certificate --certificate-arn $ACM_CERTIFICATE_ARN | jq -r '"\(.CertificateChain)"' > $SSL_CERT_PATH
#   aws acm get-certificate --certificate-arn $ACM_CERTIFICATE_ARN | jq -r '"\(.Certificate)"' >> $SSL_CERT_PATH

# fi

if [ "$APPLICATION_PORT" -eq 443 ]
then
    if [ -z $SSL_CERT_PATH ] || [ -z $SSL_KEY_PATH ]
    then
      echo "SSL_CERT_PATH and SSL_KEY_PATH must be set as environment variables when using USE_SELF_SIGNED_SSL_CERT"
      exit 1
    fi

    mkdir -p $(dirname "$SSL_CERT_PATH")
    mkdir -p $(dirname "$SSL_KEY_PATH")

    hostname="localhost"
    subject="/CN=${hostname}"

    #new versions of openssl support this:
    # openssl req \
    #     -newkey rsa:2048  -nodes  -keyout ${SSL_KEY_PATH} \
    #     -new -x509 -sha256 -days 365 -out ${SSL_CERT_PATH} \
    #     -subj "${subject}" \
    #     -addext "subjectAltName = DNS:${hostname}" \
    #     -addext "extendedKeyUsage = serverAuth"

    #old version of openssl use this:
    confdir=$(openssl version -d | awk -F'"' '{print $2}')
    
    openssl req \
        -newkey rsa:2048  -nodes  -keyout ${SSL_KEY_PATH} \
        -new -x509 -sha256 -days 365 -out ${SSL_CERT_PATH} \
        -subj "${subject}" \
        -extensions SAN -reqexts SAN \
        -config <(cat ${confdir}/openssl.cnf;printf "[SAN]\nsubjectAltName=DNS:${hostname}\nextendedKeyUsage=serverAuth")
fi
