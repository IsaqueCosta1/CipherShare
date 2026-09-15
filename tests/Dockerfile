# A imagem oficial do Playwright já traz os navegadores e as bibliotecas de
# sistema que eles exigem — instalar isso à mão é a parte chata deste teste.
FROM mcr.microsoft.com/playwright/python:v1.62.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/work:/work/api

WORKDIR /work

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

CMD ["pytest", "-v", "tests/"]
