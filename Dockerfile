# Reproducible build environment for both editions.
#   docker build -t ceph-scalable-storage .
#   docker run --rm -v "$PWD":/book ceph-scalable-storage make all
FROM debian:trixie-slim

ARG PANDOC_VERSION=3.6.4
ENV DEBIAN_FRONTEND=noninteractive LC_ALL=C.UTF-8 PIP_BREAK_SYSTEM_PACKAGES=1 \
    CHROME=/usr/bin/chromium PUPPETEER_SKIP_DOWNLOAD=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      make git curl ca-certificates unzip zip fontconfig \
      python3 python3-pip python3-venv \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
      nodejs npm chromium \
      fonts-vazirmatn fonts-inter fonts-jetbrains-mono fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

RUN arch="$(dpkg --print-architecture)" \
 && curl -fsSL -o /tmp/pandoc.deb \
      "https://github.com/jgm/pandoc/releases/download/${PANDOC_VERSION}/pandoc-${PANDOC_VERSION}-1-${arch}.deb" \
 && dpkg -i /tmp/pandoc.deb && rm /tmp/pandoc.deb

WORKDIR /opt/book-tools
COPY requirements.txt package.json ./
RUN pip3 install --no-cache-dir -r requirements.txt \
 && npm install --no-audit --no-fund \
 && ln -s /opt/book-tools/node_modules/.bin/* /usr/local/bin/
COPY tools/install_fonts.sh /usr/local/bin/install-book-fonts
RUN install-book-fonts

WORKDIR /book
CMD ["make", "help"]
