FROM python:3.11-slim

WORKDIR /app

# Install Tailscale
RUN apt-get update && apt-get install -y curl iptables && \
    curl -fsSL https://tailscale.com/install.sh | sh && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

EXPOSE 8080

CMD ["/app/start.sh"]

