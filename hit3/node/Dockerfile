FROM python:3.11-slim
WORKDIR /app
RUN pip install flask requests
COPY node.py .
CMD ["python", "node.py"]
