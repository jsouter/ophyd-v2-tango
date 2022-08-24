FROM debian:11.3 as buildsardana
RUN apt update; \
    apt install -y g++ \
                # openjdk-8-jdk\
                mariadb-server libmariadb-dev \
                zlib1g-dev libomniorb4-dev \
                libcos4-dev omniidl libzmq3-dev make\
                wget tar
RUN wget https://gitlab.com/api/v4/projects/24125890/packages/generic/TangoSourceDistribution/9.3.5/tango-9.3.5.tar.gz
RUN tar xzvf tango-9.3.5.tar.gz
RUN cd tango-9.3.5; \
    ./configure --enable-java=yes --enable-mariadb=yes \
    --enable-dbserver=yes --enable-dbcreate=yes --with-mysql-admin=root \
    --with-mysql-admin-passwd='mypassword' --prefix=/usr/local/tango
RUN cd tango-9.3.5 && make && make install

# RUN DEBIAN_FRONTEND=noninteractive apt install tango-common -y
RUN service mariadb start; DEBIAN_FRONTEND=noninteractive apt install tango-db -y; service mariadb stop

RUN apt update --fix-missing; apt install python3-sardana -y --no-install-recommends
ENV TANGO_HOST=localhost:10000
COPY startsard.sh /
RUN chmod +x /startsard.sh
RUN /startsard.sh && sleep 20 && printf "y\nDoor/demo/1" | spock --profile=demo && printf "sar_demo" | spock --profile=demo;\
        /usr/local/tango/bin/tango stop; service mariadb stop
#unfortunately 20 is sort of a magic number and this is very hacky but it's the only way I've got this to work during a build.

FROM buildsardana as buildpytango
RUN apt update; apt install -y pip git

RUN apt install pkg-config libboost-all-dev -y
ENV PKG_CONFIG_PATH=/usr/local/tango/lib/pkgconfig/
RUN pip install PyTango
RUN pip install ipython jupyter matplotlib \
git+https://github.com/bluesky/bluesky git+https://github.com/dls-controls/ophyd