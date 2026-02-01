FROM eclipse-temurin:17-jre-jammy 

ENV ZOO_CONF_DIR=/conf \
    ZOO_DATA_DIR=/data \
    ZOO_DATA_LOG_DIR=/datalog \
    ZOO_LOG_DIR=/logs \
    DISTRO_NAME=apache-zookeeper-3.8.5-bin

RUN set -eux; \
    groupadd -r zookeeper --gid=1000; \
    useradd -r -g zookeeper --uid=1000 zookeeper; \
    mkdir -p "$ZOO_DATA_LOG_DIR" "$ZOO_DATA_DIR" "$ZOO_CONF_DIR" "$ZOO_LOG_DIR"

RUN set -eux; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        dirmngr \
        gosu \
        gnupg \
        netcat; \
    rm -rf /var/lib/apt/lists/*; \
    gosu nobody true


ADD apache-zookeeper-3.8.5-bin.tar.gz /
COPY zoo.cfg ${ZOO_CONF_DIR}/zoo.cfg
COPY entrypoint.sh /entrypoint.sh
COPY healthcheck.sh /healthcheck.sh

RUN set -eux; \
    chmod +x /entrypoint.sh /healthcheck.sh; \
    chown zookeeper:zookeeper /entrypoint.sh /healthcheck.sh; \
    mv "/$DISTRO_NAME/conf/"* "$ZOO_CONF_DIR"; \
    chown -R zookeeper:zookeeper \
          "/$DISTRO_NAME" \
          "$ZOO_DATA_LOG_DIR" \
          "$ZOO_DATA_DIR" \
          "$ZOO_CONF_DIR" \
          "$ZOO_LOG_DIR"

WORKDIR $DISTRO_NAME
USER zookeeper
VOLUME ["$ZOO_DATA_DIR", "$ZOO_DATA_LOG_DIR", "$ZOO_LOG_DIR"]

EXPOSE 2181 2888 3888 8080 7000

ENV PATH=$PATH:/$DISTRO_NAME/bin \
    ZOOCFGDIR=$ZOO_CONF_DIR
ENTRYPOINT ["/entrypoint.sh"]
CMD ["start-foreground"]
