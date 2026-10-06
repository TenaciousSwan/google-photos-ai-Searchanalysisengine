FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY . .

# Set default port
ENV PORT=8000
EXPOSE 8000

# Start the FastAPI server
CMD ["python", "-m", "backend.main"]
