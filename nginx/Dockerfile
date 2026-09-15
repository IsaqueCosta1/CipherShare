FROM nginx:1.27-alpine

# openssl é necessário apenas para gerar o certificado de desenvolvimento.
RUN apk add --no-cache openssl

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY proxy.inc /etc/nginx/conf.d/proxy.inc
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 80 443

CMD ["/entrypoint.sh"]
