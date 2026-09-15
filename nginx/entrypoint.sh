#!/bin/sh
# Gera um certificado autoassinado na primeira subida e entrega o controle ao
# Nginx. O certificado fica em um volume, então sobrevive a recriações do
# contêiner — e o navegador só precisa aceitar a exceção de segurança uma vez.
set -e

CERT_DIR=/etc/nginx/certs
CERT="$CERT_DIR/servidor.crt"
KEY="$CERT_DIR/servidor.key"

mkdir -p "$CERT_DIR"

if [ ! -f "$CERT" ] || [ ! -f "$KEY" ]; then
    echo "Gerando certificado autoassinado para desenvolvimento..."
    openssl req -x509 -newkey rsa:2048 -nodes \
        -keyout "$KEY" -out "$CERT" -days 365 \
        -subj "/C=BR/O=Troca Confidencial (desenvolvimento)/CN=localhost" \
        -addext "subjectAltName=DNS:localhost,DNS:nginx,IP:127.0.0.1" \
        2>/dev/null
    chmod 600 "$KEY"
    echo "Certificado criado em $CERT"
fi

exec nginx -g 'daemon off;'
