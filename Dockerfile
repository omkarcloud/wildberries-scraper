FROM chetan1111/botasaurus:chrome-151

ENV PYTHONUNBUFFERED=1
# Never open debug prompts/devtools on crash.
ENV ENV=production

COPY requirements.txt .

RUN python -m pip install -r requirements.txt

RUN mkdir app
WORKDIR /app
COPY . /app

EXPOSE 8000

# The image ships real Google Chrome + Xvfb. Chrome opens Wildberries once to
# earn its x_wbaas_token cookie (the site's own anti-bot wants a real, visible
# browser) and closes again; every request after that is plain HTTP.
CMD ["python", "run.py"]
