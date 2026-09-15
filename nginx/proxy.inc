# Parâmetros comuns do encaminhamento para a API.
proxy_pass http://api:8000;

proxy_set_header Host $host;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;

# Uploads e downloads são transmitidos em streaming: o Nginx não deve acumular
# o arquivo inteiro em disco antes de repassá-lo.
proxy_request_buffering off;
proxy_buffering off;

# Arquivos grandes em conexões lentas precisam de mais que os 60s padrão.
proxy_read_timeout 300s;
proxy_send_timeout 300s;
