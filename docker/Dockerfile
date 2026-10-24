# Ubuntu 24.04 with everything render.sh needs, for Windows/macOS/Linux with Docker.
# Build:  docker build -t lorimaps-render docker
# Run:    see README.md ("Variante B: Docker")
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update -q && apt-get install -y -q --no-install-recommends \
      sudo git curl ca-certificates bc unzip sqlite3 build-essential \
      postgresql-16-postgis-3 postgresql-contrib osm2pgsql osmium-tool \
      gdal-bin python3-gdal libgdal-dev python3-mapnik mapnik-utils python3-pil \
      fonts-dejavu-core fonts-dejavu-extra fonts-unifont fonts-noto-core libdbd-pg-perl \
      fonts-roboto-unhinted fonts-open-sans fonts-wine fonts-urw-base35 fonts-texgyre \
 && echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" | debconf-set-selections \
 && apt-get install -y -q --no-install-recommends ttf-mscorefonts-installer \
 && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /work /out && useradd -m -s /bin/bash render && chown render /work /out
# normal user with sudo (render.sh calls sudo for PostgreSQL)
RUN echo "render ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/render
USER render
ENV USER=render SKIP_APT=1 WORK=/work OUT=/out
WORKDIR /home/render/lorimaps-render
CMD ["bash", "render.sh"]
