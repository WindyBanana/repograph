FROM python:3.11
WORKDIR /srv
COPY . .
RUN pip install -e .
ENV DEBUG=1
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
