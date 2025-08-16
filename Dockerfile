FROM python:3.10-slim
  
WORKDIR /app
  
COPY requirements.txt .
RUN pip install -r requirements.txt
  
EXPOSE 5000
  
# Point to the mounted source directory
CMD ["gunicorn", "-b", "0.0.0.0:5000", "-w", "1", "--chdir", "/app/src", "app:app"]